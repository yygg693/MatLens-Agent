"""双端共享：核心访问封装（TUI 与 Web 复用，不重复实现业务逻辑）。"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

# 确保 MATLENS_HOME 指向 ~/.matlens（双端数据互通的前提）
if "MATLENS_HOME" not in os.environ:
    os.environ["MATLENS_HOME"] = os.path.join(os.path.expanduser("~"), ".matlens")

# 统一加载 ~/.matlens/.env（TUI/Web 进程都能读到 API Key 等）
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.environ["MATLENS_HOME"], ".env"))
except Exception:
    pass

_AGENT = None
_AGENT_LOCK = threading.Lock()

# ── MatLens 回答风格指令（ephemeral：仅随 API 请求注入，不进缓存/不覆盖 Hermes 核心）──
# 解决「答案太简洁死板、只罗列引用不归纳、格式过度统一」的问题。
_MATLENS_STYLE_PROMPT = """【MatLens 材料科研助手 · 回答风格要求】
你是材料研究领域的资深工程师兼导师，用中文与用户交流。请遵守：
1. 先理解意图再作答：判断用户是要查资料、算数据、写综述、做对比还是解决具体问题，据此选择组织方式，不要套用固定模板。
2. 检索/调用工具后必须"综合归纳"：把搜索结果或工具输出消化成有观点、有重点的总结，说明"这说明了什么/该怎么用"，而不是把引用原文罗列出来就算完。引用可作为依据附在后面，但答案主体是你自己的分析与归纳。
3. 行文自然，像师兄讲解而不是流水账：避免每段都"首先/其次/最后"、避免机械的等长 bullet。该讲清楚的讲清楚，该给数据的给数据（带单位），该对比的做对比。
4. 按需结构化：查数据给表格、多方案给对比、步骤类给流程、概念类给直白解释（先结论后原理）。不要让所有回答都长成一个样子。
5. 结论先行：先给答案/结论，再给依据和推导；有不确定处明确标注。
6. 材料科研准确性：术语、化学式、数值、单位必须准确；涉及文献结论要区分"事实"与"推断"。

【联网搜索策略（重要：优先用浏览器，勿退化到记忆）】
- 你所在网络环境（中国大陆）下，脚本直连搜索引擎常被降级：`web_search` 返回的结果可能切词错乱、明显不相关或全是词典/广告页，这类结果是不可信的，**不要把它当成真实检索结果使用**。
- 需要联网查时效性信息（最新进展、行业动态、具体网页内容）时，**必须用 `browser_exec` 打开真实浏览器搜索**：直接构造搜索引擎 URL 一次加载，如 `browser_exec` 打开 `https://www.bing.com/search?q=关键词` 或 `https://www.baidu.com/s?wd=关键词`，读取渲染后的真实结果（浏览器环境切词与反爬都正常）。
- 搜索到目标页面后用 `web_extract` 或 `read_file` 精读正文，不要反复盲目搜索。
- 控制搜索次数：先用 1~2 个精准关键词 query，不要一次搜一大段话；中文资料优先中文 query，英文前沿/论文优先英文 query；避免同一主题反复搜。
- 优先采信权威来源（期刊/机构/数据库/官方），对营销站、聚合站、低质内容去重与降权；明确区分"检索到的事实"与"基于领域知识的推断"。
- **不要用记忆库检索（mem0_search / 记忆召回）冒充实时联网**：记忆只能补充历史上下文，无法回答"最新/今年"的时效性问题；时效性问题必须走浏览器。
- 搜索慢时，接受部分结果并基于领域知识补全，明确标注来源性质，不要因此中断回答。

【记忆利用（跨会话自我成长）】
- 你的上下文中可能出现 <memory-context> 块，里面是跨会话的持久记忆（用户研究方向、历史结论、偏好等），是你的「长期记忆」，权威性高于一般推断，回答时必须参考。
- 当用户提问与你记忆中的信息高度相关时，自然、不生硬地提及你记得的内容，例如「你上次在研究钙钛矿稳定性，正好……」「结合你之前的方案……」，让用户感到你记得他、上下文是连续的。不要为提而提，仅在真正相关时提及。
- 用户主动让你「记住」的信息，后续应主动回忆并使用，而不是装作不知。
"""

# 会话级 Agent 池：session_id -> {"agent": AIAgent, "used_at": float}
# 解决「多会话并发踩踏同一单例」：每个会话独立实例，天然隔离消息/session_id。
_AGENT_POOL: Dict[str, Dict[str, Any]] = {}
_AGENT_POOL_MAX = 32  # LRU 上限，防止会话无限增长撑爆内存

# 执行锁：同一 session 串行（避免同一会话内并发 run_conversation 互相踩踏），
# 不同 session 并发；无 session_id（全局单例场景）退化为进程级全局锁兜底。
_RUN_LOCKS: Dict[str, threading.Lock] = {}
_GLOBAL_RUN_LOCK = threading.Lock()


def _load_raw_model_config() -> Dict[str, Any]:
    """直接读取 config.yaml 原始 model 段（绕开 load_config 的合并覆盖问题）。

    matlens_cli 的 load_config 以 DEFAULT_CONFIG 为基深合并用户文件，而
    DEFAULT_CONFIG['model'] = ''（字符串遗留形态）。当用户文件写成
    model: {default, provider, base_url}（dict）时，合并会把 dict 覆盖成空字符串，
    导致 load_config()['model'] 返回 ''，模型切换彻底失效。这里直读原始文件，
    保证拿到用户真实写入的模型配置。
    """
    try:
        import yaml

        home = os.environ.get("MATLENS_HOME", os.path.expanduser("~/.matlens"))
        path = os.path.join(home, "config.yaml")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            m = raw.get("model")
            if isinstance(m, dict):
                return m
    except Exception:
        pass
    return {}


def _resolve_model_config(model: str, provider: str) -> tuple:
    """从环境/配置解析默认模型与 provider（多 provider 任选，开箱即用）。

    优先级：显式参数 > 用户 config.yaml（直读原始 model 段） > 环境变量推断。
    """
    if not model or not provider:
        try:
            m_cfg = _load_raw_model_config()
            if not m_cfg:
                cfg = get_config()
                m_cfg = cfg.get("model") or {}
            if isinstance(m_cfg, dict):  # Hermes: model 配置为 dict 结构
                if not model:
                    model = m_cfg.get("default") or ""
                if not provider or provider == "auto":
                    provider = m_cfg.get("provider") or ""
            else:
                if not model:
                    model = m_cfg or ""
            if not provider and m_cfg.get("provider"):
                provider = m_cfg.get("provider")
        except Exception:
            pass
    # 环境推断（DeepSeek 原生支持 / OpenAI 兼容自定义端点）
    if not provider or provider == "auto":
        if os.environ.get("DEEPSEEK_API_KEY"):
            provider = "deepseek"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "custom"
    if not model:
        if provider == "deepseek":
            model = "deepseek-chat"
        elif provider == "custom":
            model = os.environ.get("MATLENS_MODEL") or ""
        else:
            model = ""
    # 兜底：config 模板默认 qwen2.5:7b 等本地模型名与云端 provider 不匹配时，用 provider 默认模型
    if model and ":" in model and provider in ("deepseek", "openai", "anthropic"):
        if provider == "deepseek":
            model = "deepseek-chat"
        elif provider == "openai":
            model = "gpt-4o"
        elif provider == "anthropic":
            model = "claude-sonnet-4-20250514"
    return model, provider


def _runtime_setting_overrides() -> Dict[str, Any]:
    """从 settings_store 实时读取 general/memory 设置，转成 AIAgent 构造 kwargs。

    这是「设置页 → 运行时」生效的唯一接线点（见 design/settings-backend-contract.md）：
      - general.max_turns      -> max_iterations（单轮工具调用迭代上限）
      - general.reasoning_effort -> reasoning_config（走 matlens_constants 的
        resolve_reasoning_config 真实约定；不支持 effort 的模型由下游 adapter 安全降级）
      - memory.enabled         -> skip_memory（False 时不建 mem0 provider、不召回、不写入）

    每次动作都实时读 config.yaml（settings_store.get_section 不做进程内缓存），
    反映最新设置；任何读取/解析失败都静默回退（不阻断 agent 构造）。
    """
    out: Dict[str, Any] = {}
    try:
        from matlens_kit import settings_store
    except Exception:
        return out
    try:
        general = settings_store.get_section("general")
    except Exception:
        general = {}
    try:
        memory = settings_store.get_section("memory")
    except Exception:
        memory = {}

    # max_turns -> max_iterations（整型，>0 才生效）
    max_turns = general.get("max_turns")
    if isinstance(max_turns, int) and not isinstance(max_turns, bool) and max_turns > 0:
        out["max_iterations"] = max_turns

    # reasoning_effort -> reasoning_config（沿用 CLI/switch_model 的同一解析函数）
    effort = general.get("reasoning_effort")
    if effort:
        try:
            from matlens_constants import resolve_reasoning_config

            rc = resolve_reasoning_config(
                {"agent": {"reasoning_effort": effort}}, ""
            )
            if rc:
                out["reasoning_config"] = rc
        except Exception:
            pass

    # memory.enabled -> skip_memory（总开关关闭时整体禁用外部记忆）
    out["skip_memory"] = not bool(memory.get("enabled", True))
    return out


def get_agent(model: str = "", provider: str = "", session_id: str = "", **kwargs: Any):
    """创建核心 AIAgent 实例。

    - session_id 为空 → 返回全局单例（TUI / gradio / mem 等无会话上下文场景，行为不变）
    - session_id 非空 → 返回「会话级独立实例」（Web 对话/论文工坊），
      多会话并发各自持独立 messages/session_id，互不踩踏。

    每次调用都重新解析 config 中期望的模型/provider；若与当前实例不一致，
    则释放并重建——前端「切换模型」保存后无需重启即生效（实时真实）。
    池内实例带 LRU 上限（_AGENT_POOL_MAX），防止会话无限增长。
    """
    want_model, want_provider = _resolve_model_config(model, provider)
    # MatLens 风格指令随实例注入（ephemeral：不进缓存、不覆盖 Hermes 默认 system prompt）
    kwargs.setdefault("ephemeral_system_prompt", _MATLENS_STYLE_PROMPT)
    # 设置页运行时生效：max_turns / reasoning_effort / memory.enabled 实时注入。
    # 显式传入的 kwargs 优先（setdefault），这里只补默认值，不覆盖调用方意图。
    for _k, _v in _runtime_setting_overrides().items():
        kwargs.setdefault(_k, _v)
    if not session_id:
        return _get_global_agent(want_model, want_provider, kwargs)
    return _get_session_agent(session_id, want_model, want_provider, kwargs)


def _get_global_agent(want_model: str, want_provider: str, kwargs: Dict[str, Any]):
    """全局单例（兼容原有无会话上下文调用方）。锁只保护创建，执行由 run_conversation 全局锁兜底。"""
    global _AGENT
    with _AGENT_LOCK:
        if _AGENT is not None:
            cur_model = getattr(_AGENT, "model", None)
            cur_provider = getattr(_AGENT, "provider", None)
            if cur_model == (want_model or None) and cur_provider == (want_provider or None):
                return _AGENT
            _AGENT = None  # 不一致 → 释放旧实例，下面重建
        from run_agent import AIAgent

        _AGENT = AIAgent(model=want_model or None, provider=want_provider or None, **kwargs)
        return _AGENT


def _get_session_agent(session_id: str, want_model: str, want_provider: str, kwargs: Dict[str, Any]):
    """会话级 agent 池：每个 session 独立实例 + 独立执行锁。"""
    now = time.time()
    with _AGENT_LOCK:
        entry = _AGENT_POOL.get(session_id)
        if entry is not None:
            agent = entry["agent"]
            if (getattr(agent, "model", None) == (want_model or None)
                    and getattr(agent, "provider", None) == (want_provider or None)):
                entry["used_at"] = now
                return agent
            # 模型/provider 变更 → 释放旧实例，重建
            _AGENT_POOL.pop(session_id, None)
        # LRU 上限淘汰最久未使用的会话实例
        while len(_AGENT_POOL) >= _AGENT_POOL_MAX and _AGENT_POOL:
            oldest = min(_AGENT_POOL, key=lambda k: _AGENT_POOL[k]["used_at"])
            _AGENT_POOL.pop(oldest, None)
        from run_agent import AIAgent

        agent = AIAgent(
            model=want_model or None,
            provider=want_provider or None,
            session_id=session_id,
            **kwargs,
        )
        _AGENT_POOL[session_id] = {"agent": agent, "used_at": now}
        return agent


def get_agent_timed(session_id: str = "", timeout: float = 45, **kwargs: Any):
    """带超时守卫的 agent 构造。

    AIAgent 构造可能因记忆后端（mem0/qdrant 等）初始化而长时间挂起，若在 HTTP
    请求线程里直接构造，会把请求永久卡死。本函数把构造放到独立线程并 join 限时：
    超时抛 TimeoutError（调用方降级为友好错误），线程本身 daemon 化、不阻塞退出。
    """
    box: Dict[str, Any] = {}

    def _t() -> None:
        try:
            box["a"] = get_agent(session_id=session_id, **kwargs)
        except Exception as e:  # noqa: BLE001
            box["e"] = e

    th = threading.Thread(target=_t, daemon=True, name="agent-fetch-timed")
    th.start()
    th.join(timeout)
    if "a" in box:
        return box["a"]
    if "e" in box:
        raise box["e"]
    raise TimeoutError(f"agent 初始化超时（session={session_id!r}，可能记忆后端导入阻塞）")


def reset_agent() -> None:
    """释放 Agent 实例（模型切换等场景）：清空全局单例与会话池。"""
    global _AGENT
    with _AGENT_LOCK:
        _AGENT = None
        _AGENT_POOL.clear()


def get_kb_manager():
    """知识库管理器（与 matlens kb 命令共用同一实现）。"""
    from matlens_kit.plugins.local_rag import get_manager

    return get_manager()


def get_kb_command_handler():
    """知识库命令处理器（/kb 系列）。"""
    from matlens_kit.plugins.local_rag import handle_kb_command

    return handle_kb_command


def get_config() -> Dict[str, Any]:
    """读取用户配置（~/.matlens/config.yaml 合并默认）。"""
    from matlens_cli.config import load_config

    return load_config()


def get_version() -> str:
    """MatLens 垂直层版本。"""
    from matlens_kit import __version__

    return __version__


def run_conversation(agent, message: str, session_id: str = "", stream_callback=None,
                     setup=None) -> Dict[str, Any]:
    """单轮对话（流式可选）。核心转发，UI 层不做业务逻辑。

    同一 session_id 的并发调用由 per-session 锁串行（防止同一会话内
    连点/断线重连导致的并发踩踏）；不同 session 之间互不阻塞。
    session_id 为空时退化为进程级全局锁（保护全局单例场景）。

    setup: 可选回调，在锁内、run_conversation 之前调用。用于对共享 agent
        实例做副作用初始化（注入 _session_db / 重挂工具钩子 / 会话兜底），
        避免并发请求在锁外同时修改同一 agent 造成竞争（会导致运行中的
        run_conversation 卡死、per-session 锁被死线程永久持有）。
    """
    if session_id:
        lock = _RUN_LOCKS.setdefault(session_id, threading.Lock())
    else:
        lock = _GLOBAL_RUN_LOCK
    with lock:
        if setup is not None:
            setup()
        return agent.run_conversation(message, stream_callback=stream_callback)

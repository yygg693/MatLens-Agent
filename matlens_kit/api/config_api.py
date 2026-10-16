"""配置 API —— 对齐 matlens 统一后端的真实配置（config.yaml + .env + mem0.json）。

前端设置页全部直连：
- GET  /api/settings        读取（api_key 脱敏）
- PUT  /api/settings        写入（config.yaml 深合并 + .env 写密钥）
- POST /api/settings/test   连接测试（向 DeepSeek 发一次最小请求）

审批策略（tool_loop_guardrails）一并读写，作为 M5 审批层的配置基座。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

_router = APIRouter(prefix="/api/settings", tags=["settings"])

# 注意：生产环境（未设 MATLENS_HOME）下 get_matlens_home() == ~/.matlens，
# 与旧硬编码值一致；测试/自定义部署下则跟随 MATLENS_HOME，保证设置页读写与
# matlens_cli.config / settings_store 落到同一个 home。
_HOME = Path(os.path.expanduser("~/.matlens"))
_CONFIG_PATH = _HOME / "config.yaml"

# ---------------------------------------------------------------------------
# 审批开箱配置（2026-10-15）
#
# 问题背景：approval.allowlist / denylist 此前默认空列表，且前端只给了
# 「开关 + 三档策略」没有清单入口。结果是：
#   - strategy=auto        → request() 恒返回 None，开关打开也没任何效果
#   - strategy=confirm_list→ allowlist 空 = **所有工具都要审批**，连read_file
#     这类纯只读操作都会被拦，用户只能放弃
# 于是审批功能事实上不可用。
#
# 现在的默认：confirm_list 策略下白名单覆盖只读工具，其余（写文件、跑命令、
# 删改）必须逐次确认——这是科研场景合理的默认。
# ---------------------------------------------------------------------------
DEFAULT_APPROVAL_ALLOWLIST = [
    # 纯只读 / 信息查询
    "read_file", "list_dir", "search_files", "grep", "glob",
    "read_terminal", "read_window_below", "read_preview", "open_preview",
    "web_search", "web_fetch", "web_extract", "browser_exec",
    "session_search", "skills_list", "skill_view",
    # 科研计算（无副作用）
    "molar_mass", "xrd_dspacing", "xrd_preprocess", "tauc_bandgap",
    "thermo_gibbs", "unit_convert", "lever_rule", "balance_equation",
    "data_normalize", "data_fit", "citation_format",
    "matlens_kb", "rag_search", "mem0_search", "memory",
]

DEFAULT_APPROVAL_DENYLIST = [
    # 高危：默认直接拒绝，不给「确认一次」的机会
    "shell", "eval", "exec",
]


def _env_path() -> Path:
    """.env 路径：动态解析（跟随 MATLENS_HOME / get_matlens_home）。

    密钥的读写（_read_env / _write_env_key / 下面的 reset）都必须用这个，
    不能用模块级硬编码常量，否则在 MATLENS_HOME 隔离（测试）下会读写到真实
    用户的 ~/.matlens/.env。
    """
    from matlens_constants import get_matlens_home

    return get_matlens_home() / ".env"


# 向后兼容别名（旧代码若引用过模块级 _ENV_PATH 仍可工作）。
def _HOME_DIR() -> Path:
    from matlens_constants import get_matlens_home

    return get_matlens_home()

# 前端可选 provider（与后端 provider 体系一致）
PROVIDER_OPTIONS = ["deepseek", "ollama", "openrouter", "openai"]

# 各 provider 的真实 API key 环境变量名（与 matlens_cli 终端完全一致）
_PROVIDER_KEY_ENV = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
}

# Ollama 本地常见模型（实时拉取 localhost 标签失败时回退）
_OLLAMA_COMMON = [
    "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b",
    "llama3.1:8b", "llama3.1:70b",
    "deepseek-r1:7b", "deepseek-r1:32b",
    "mistral:7b", "gemma2:9b",
]

# 实时目录缓存：与终端 /model picker 同源于 cached_provider_model_ids（其自身
# 已有 1h 磁盘缓存）。这里再加一层进程内短 TTL，避免设置页每次打开都打网络。
_CATALOG_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_CATALOG_TTL = 600.0  # 10 分钟（终端侧是 1h 磁盘缓存，进程内再短一点更灵敏）
_CATALOG_LOCK = threading.Lock()


def _ensure_env_loaded() -> None:
    """把 .env 里的 provider key 注入 os.environ（不覆盖已存在的），
    以便 matlens_cli 的 live 拉取能读到密钥。"""
    env_path = _env_path()
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except Exception:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
            os.environ.setdefault(k, v)


def _live_catalog_for(provider: str) -> Optional[Dict[str, str]]:
    """实时拉取某 provider 的真实模型列表，返回 {model_id: friendly_name}。"""
    key_env = _PROVIDER_KEY_ENV.get(provider)
    if key_env is None:
        try:
            import json as _json
            import urllib.request as _urlreq
            req = _urlreq.Request("http://localhost:11434/api/tags")
            with _urlreq.urlopen(req, timeout=2) as resp:
                payload = _json.loads(resp.read().decode("utf-8"))
            return {m.get("name", ""): m.get("name", "") for m in payload.get("models", []) if m.get("name")}
        except Exception:
            return None
    key = os.environ.get(key_env, "").strip()
    if not key:
        return None
    base_urls = {
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }
    base = base_urls.get(provider)
    if not base:
        return None
    try:
        import json as _json
        import urllib.request as _urlreq
        req = _urlreq.Request(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        with _urlreq.urlopen(req, timeout=5) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
        return {m.get("id", ""): m.get("name", "") or m.get("id", "") for m in payload.get("data", []) if m.get("id")}
    except Exception:
        return None


def _build_model_catalog(force: bool = False) -> Dict[str, list]:
    """Hermes 终端权威模型目录（provider -> 真实模型名列表），实时优先。

    优先调用终端同源的 cached_provider_model_ids（真实 /v1/models 拉取），
    失败/无密钥时回退到 matlens_cli.models 的静态 _PROVIDER_MODELS /
    OPENROUTER_MODELS。保证前端模型选项与终端 100% 一致——例如 deepseek 会
    出现 deepseek-v4-pro / deepseek-v4-flash / deepseek-v4-flash-vision-exp。
    """
    global _CATALOG_CACHE
    now = time.time()
    if not force and _CATALOG_CACHE["data"] is not None and now - _CATALOG_CACHE["at"] < _CATALOG_TTL:
        return _CATALOG_CACHE["data"]
    with _CATALOG_LOCK:
        # 双重检查，避免并发重复拉取
        if not force and _CATALOG_CACHE["data"] is not None and now - _CATALOG_CACHE["at"] < _CATALOG_TTL:
            return _CATALOG_CACHE["data"]
        _ensure_env_loaded()
        catalog: Dict[str, list] = {}
        # 实时优先（与终端 picker 同源）
        for prov in ("deepseek", "openai", "openrouter", "ollama"):
            live = _live_catalog_for(prov)
            if live:
                catalog[prov] = live
        # 兜底静态清单（网络/密钥缺失时仍给真实可选名，绝不私设）
        try:
            from matlens_cli.models import OPENROUTER_MODELS, _PROVIDER_MODELS

            if "deepseek" not in catalog and isinstance(_PROVIDER_MODELS, dict):
                catalog["deepseek"] = list(_PROVIDER_MODELS.get("deepseek", []))
            if "openai" not in catalog and isinstance(_PROVIDER_MODELS, dict):
                catalog["openai"] = list(_PROVIDER_MODELS.get("openai", []))
            if "openrouter" not in catalog and OPENROUTER_MODELS:
                catalog["openrouter"] = [m for m, _ in OPENROUTER_MODELS]
        except Exception:
            pass
        catalog.setdefault("deepseek", ["deepseek-v4-pro", "deepseek-flash"])
        catalog.setdefault("openai", ["gpt-4o", "gpt-4o-mini", "gpt-4.1"])
        catalog.setdefault("openrouter", [])
        catalog["ollama"] = list(_OLLAMA_COMMON)
        _CATALOG_CACHE = {"at": now, "data": catalog}
        return catalog


def _model_options_for(provider: str, default: Optional[str]) -> list:
    """某 provider 的候选模型（含当前默认，置于首位）。"""
    opts = list((_build_model_catalog().get(provider) or []))
    if default and default not in opts:
        opts.insert(0, default)
    return opts


def _refresh_catalog_async() -> None:
    """后台预热实时目录（首次可能 1-3s 网络延迟），不阻塞设置页。"""
    def _warm():
        try:
            _build_model_catalog(force=True)
        except Exception:
            pass
    t = threading.Thread(target=_warm, daemon=True, name="catalog-warm")
    t.start()


def _load_cfg() -> Dict[str, Any]:
    """读取配置，但 model 段直读原始 config.yaml，绕开 load_config 合并把
    model dict 覆盖成空字符串的 bug（保证前端看到/保存的是真实模型配置）。"""
    from matlens_cli.config import load_config

    cfg = load_config()
    try:
        from matlens_kit.ui.common import _load_raw_model_config

        raw_model = _load_raw_model_config()
        if raw_model:
            cfg["model"] = raw_model
    except Exception:
        pass
    # load_config() 以 DEFAULT_CONFIG（model 为 '' 字符串遗留形态）为基深合并；
    # 当用户 config.yaml 没有 model 段时，合并结果会把 model 变成空字符串，
    # 下游 model.get(...) 会炸。这里兜底保证 model 永远是 dict。
    if not isinstance(cfg.get("model"), dict):
        cfg["model"] = {}
    return cfg


def _save_cfg(cfg: Dict[str, Any]) -> None:
    from matlens_cli.config import save_config

    save_config(cfg, merge_existing=True)


def _read_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    env_path = _env_path()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _write_env_key(key: str, value: str) -> None:
    env = _read_env()
    env[key] = value
    lines = [f"{k}={v}" for k, v in env.items()]
    _env_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mask_key(key: str) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "***"
    return key[:4] + "…" + key[-4:]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SettingsPut(BaseModel):
    # 允许新的嵌套部分更新段（papers/kb/experiment/memory/general）透传，
    # 旧的扁平字段仍由下面的显式字段校验；未登记的额外字段进 model_extra。
    model_config = ConfigDict(extra="allow")

    model_default: Optional[str] = None
    model_provider: Optional[str] = None
    model_base_url: Optional[str] = None
    memory_enabled: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    max_turns: Optional[int] = None
    api_key: Optional[str] = None  # 仅写入 .env；留空不改
    approval_enabled: Optional[bool] = None
    approval_strategy: Optional[str] = None  # auto / confirm_list / deny_list
    approval_allowlist: Optional[list] = None
    approval_denylist: Optional[list] = None


def _key_env_for_provider(provider: Optional[str]) -> str:
    """按 provider 决定写入哪个 env 变量（与终端一致）；未知/缺省走 deepseek。"""
    return _PROVIDER_KEY_ENV.get((provider or "").strip().lower(), "DEEPSEEK_API_KEY")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@_router.get("")
def get_settings() -> Dict[str, Any]:
    cfg = _load_cfg()
    model = cfg.get("model", {})
    memory = cfg.get("memory", {})
    guard = cfg.get("tool_loop_guardrails", {}) or {}

    env = _read_env()
    raw_key = env.get("DEEPSEEK_API_KEY", "")

    # ── 统一设置基座（general/memory/papers/kb/experiment/about）──────────
    # 数据全部来自 settings_store：以 DEFAULTS 为底叠加 config.yaml 原始值。
    from matlens_kit import settings_store

    ss = settings_store.load_settings()
    general = ss["general"]
    # memory 别名保留且与基座一致：enabled 继续映射 memory.memory_enabled
    mem_section = {
        "enabled": ss["memory"]["enabled"],
        "auto_write": ss["memory"]["auto_write"],
        "graph_auto_build": ss["memory"]["graph_auto_build"],
        "provider": ss["memory"]["provider"],
    }
    # agent 别名保留，数值与 general 一致
    agent_section = {
        "reasoning_effort": general["reasoning_effort"],
        "max_turns": general["max_turns"],
    }

    return {
        "ok": True,
        "model": {
            "default": model.get("default"),
            "provider": model.get("provider"),
            "base_url": model.get("base_url"),
            "options": _model_options_for(model.get("provider") or "", model.get("default")),
        },
        "providers": PROVIDER_OPTIONS,
        "model_catalog": _build_model_catalog(),
        # memory 别名（新形状：含 auto_write/graph_auto_build）
        "memory": mem_section,
        # agent 别名（数值与 general 一致）
        "agent": agent_section,
        # ── 新规范段 ──
        "general": general,
        "papers": ss["papers"],
        "kb": ss["kb"],
        "experiment": ss["experiment"],
        "about": ss["about"],
        "api_key_set": bool(raw_key),
        "api_key_masked": _mask_key(raw_key),
        "provider_keys": _provider_key_status(),
        "approval": {
            # 2026-10-15：把 allowlist / denylist 的默认值补成「真实可用的一套」。
            # 此前两者默认空列表，前端审批面板也只有开关没有清单入口 →
            # 用户开了 confirm_list 后**每个工具都要审批**（含read_file 这类
            # 只读工具），实际只能回退到 auto（=永不审批），开关形同虚设。
            # 现在前端把这两份清单暴露出来，且默认给出合理的开箱配置。
            "enabled": bool(guard.get("enabled", False)),
            "strategy": guard.get("strategy", "auto"),
            "allowlist": guard.get("allowlist") or list(DEFAULT_APPROVAL_ALLOWLIST),
            "denylist": guard.get("denylist") or list(DEFAULT_APPROVAL_DENYLIST),
        },
    }


def _provider_key_status() -> Dict[str, Any]:
    """每个 provider 的 API key 配置状态（供设置页 provider 卡片展示状态点）。

    从 ~/.matlens/.env 真实读取，脱敏展示；ollama 等本地服务标记无需密钥。
    """
    env = _read_env()
    out: Dict[str, Any] = {}
    for prov, env_name in _PROVIDER_KEY_ENV.items():
        if env_name is None:
            out[prov] = {"set": False, "masked": None, "env": None, "label": "本地服务 · 无需密钥"}
        else:
            v = env.get(env_name, "").strip()
            out[prov] = {"set": bool(v), "masked": _mask_key(v), "env": env_name, "label": env_name}
    return out


@_router.get("/catalog")
def get_catalog(refresh: bool = False, provider: Optional[str] = None) -> Dict[str, Any]:
    """实时模型目录。传 provider 参数则只拉该 provider（快，~400ms），返回 {models: {id: name}}。"""
    _ensure_env_loaded()
    if provider:
        live = _live_catalog_for(provider)
        if live:
            return {"ok": True, "provider": provider, "models": live}
        return {"ok": False, "provider": provider, "error": "无法拉取模型列表（检查 API Key 或网络）", "models": {}}
    cat = _build_model_catalog(force=refresh)
    return {"ok": True, "catalog": cat, "sources": {
        "deepseek": "live /v1/models",
        "openai": "live /v1/models",
        "openrouter": "live /v1/models",
        "ollama": "live localhost tags",
    }}


@_router.put("")
def put_settings(req: SettingsPut) -> Dict[str, Any]:
    from matlens_kit import settings_store

    # 记录切换前的统一设置值，用于判断 effort / max_turns / memory_enabled 是否变化。
    old_ss = settings_store.load_settings()
    old_effort = old_ss["general"]["reasoning_effort"]
    old_turns = old_ss["general"]["max_turns"]
    old_mem_enabled = old_ss["memory"]["enabled"]

    cfg = _load_cfg()

    # 记录切换前的模型配置，用于判断是否需要让运行中的 agent 失效重建。
    # 注意：必须拷出标量，不能保留对 cfg["model"] 的引用——下面会原地改它，
    # 若用引用比较，old 会被新值覆盖，导致 model_changed 永远为 False（agent_reset 谎报）。
    _msec = cfg.get("model", {}) or {}
    old_default = _msec.get("default")
    old_provider = _msec.get("provider")
    old_base_url = _msec.get("base_url")

    if req.model_default is not None:
        cfg.setdefault("model", {})["default"] = req.model_default
    if req.model_provider is not None:
        cfg.setdefault("model", {})["provider"] = req.model_provider
    if req.model_base_url is not None:
        cfg.setdefault("model", {})["base_url"] = req.model_base_url
    if req.memory_enabled is not None:
        cfg.setdefault("memory", {})["memory_enabled"] = req.memory_enabled
    if req.reasoning_effort is not None:
        cfg.setdefault("agent", {})["reasoning_effort"] = req.reasoning_effort
    if req.max_turns is not None:
        cfg.setdefault("agent", {})["max_turns"] = int(req.max_turns)

    # 审批策略写入 tool_loop_guardrails
    guard = cfg.setdefault("tool_loop_guardrails", {})
    if req.approval_enabled is not None:
        guard["enabled"] = req.approval_enabled
    if req.approval_strategy is not None:
        guard["strategy"] = req.approval_strategy
    if req.approval_allowlist is not None:
        guard["allowlist"] = req.approval_allowlist
    if req.approval_denylist is not None:
        guard["denylist"] = req.approval_denylist

    # api_key 按 provider 写入对应 env 变量（与终端一致：deepseek/openai/openrouter）
    if req.api_key:
        target_env = _key_env_for_provider(req.model_provider)
        _write_env_key(target_env, req.api_key.strip())

    _save_cfg(cfg)

    # ── 嵌套部分更新（新规范段）：papers/kb/experiment/memory/general ──
    # 只更新传入的叶子；未提及的段保持不变。经 settings_store 翻译成磁盘落点后落盘。
    NESTED_SECTIONS = ("papers", "kb", "experiment", "memory", "general")
    nested = {
        k: v for k, v in (req.model_extra or {}).items()
        if k in NESTED_SECTIONS and isinstance(v, dict)
    }
    if nested:
        settings_store.update_settings(nested)

    # 关键修复：模型/provider/base_url 变更后，前端「切换模型」无需重启即生效。
    # 机制：get_agent() 每次重读配置并对模型/provider 不一致的单例自动重建，
    # 所以即使不显式 reset，下次对话请求也会用上新模型（实时真实）。
    model_changed = (
        (req.model_default is not None and req.model_default != old_default)
        or (req.model_provider is not None and req.model_provider != old_provider)
        or (req.model_base_url is not None and req.model_base_url != old_base_url)
    )

    # 契约：reasoning_effort / max_turns / memory.memory_enabled 变化时也要让
    # 运行中的 agent 失效重建（扁平旧字段与嵌套新段都算）。
    new_ss = settings_store.load_settings()
    ss_changed = (
        new_ss["general"]["reasoning_effort"] != old_effort
        or int(new_ss["general"]["max_turns"]) != int(old_turns)
        or (not new_ss["memory"]["enabled"]) != (not old_mem_enabled)
    )

    # 最佳努力：立即让当前单例失效，缩短切换生效延迟（失败不影响，get_agent 会自动重建）
    need_reset = model_changed or ss_changed
    if need_reset:
        try:
            from matlens_kit.ui.common import reset_agent

            reset_agent()
        except Exception:
            pass

    # 异步预热新 provider 的实时目录（例如刚切到 openrouter 想立刻看到模型列表）
    _refresh_catalog_async()

    # agent_reset 如实反映「是否发起了需要重建 agent 的变更」（模型切换 / effort /
    # max_turns / memory_enabled；下次 get_agent 即生效）
    return {"ok": True, "saved": True, "agent_reset": bool(need_reset)}


# 各 provider 的默认 base_url 和测试模型
_PROVIDER_DEFAULTS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    # OpenRouter 用免费模型测试，避免付费模型 402/403
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "nvidia/nemotron-3-super-120b-a12b:free"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b"},
}


class TestReq(BaseModel):
    provider: Optional[str] = None  # 不填则用当前配置的 provider


@_router.post("/test")
def test_connection(req: TestReq = TestReq()) -> Dict[str, Any]:
    """向真实推理端点发一次最小请求验证 key / 连通性。

    provider 参数可指定测试某个供应商（用于设置页每个 provider 卡片单独测试）；
    不填则用当前 config.yaml 配置的 provider。
    """
    env = _read_env()
    cfg = _load_cfg()
    model_cfg = cfg.get("model", {}) or {}
    provider = (req.provider or model_cfg.get("provider") or "deepseek").strip().lower()

    # 按 provider 选 key 和 base_url
    key_env = _PROVIDER_KEY_ENV.get(provider)
    if key_env is None:
        # ollama 本地服务，无需 key
        key = "ollama"
    else:
        key = env.get(key_env, "").strip()
        if not key:
            return {"ok": False, "provider": provider, "error": f"未配置 {key_env}"}

    defaults = _PROVIDER_DEFAULTS.get(provider, {})
    base_url = (model_cfg.get("base_url") or defaults.get("base_url") or "").strip() or None
    # 测试时用该 provider 的默认小模型，避免用户配置的大模型超时
    model_name = defaults.get("model") or (model_cfg.get("default") or "gpt-4o-mini")

    try:
        from openai import OpenAI

        t0 = time.time()
        client = OpenAI(api_key=key, base_url=base_url, timeout=15, max_retries=0)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
        )
        latency = round((time.time() - t0) * 1000)
        text = resp.choices[0].message.content if resp.choices else ""
        return {"ok": True, "provider": provider, "latency_ms": latency, "model": model_name, "echo": (text or "")[:20]}
    except Exception as e:
        return {"ok": False, "provider": provider, "error": str(e)[:300]}


@_router.get("/openrouter-free")
def openrouter_free_models() -> Dict[str, Any]:
    """查询 OpenRouter 真实免费模型（prompt/completion 价格均为 "0"）。

    直接打 OpenRouter 官方 /api/v1/models（带 OPENROUTER_API_KEY），返回所有
    免费模型的真实 id / 名称 / 上下文长度。这是「实时真实」的免费模型清单，
    与 openrouter 官网一致，不私设。
    """
    env = _read_env()
    key = env.get("OPENROUTER_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise HTTPException(status_code=400, detail="未配置 OPENROUTER_API_KEY（先到设置页填入 OpenRouter 密钥）")

    import json
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"OpenRouter 请求失败：{str(e)[:200]}"}

    free: list = []
    for m in payload.get("data", []):
        p = m.get("pricing") or {}
        prompt_p = str(p.get("prompt", "x"))
        comp_p = str(p.get("completion", "x"))
        if prompt_p == "0" and comp_p == "0":
            free.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "context_length": m.get("context_length"),
                "prompt_price": prompt_p,
                "completion_price": comp_p,
                "description": (m.get("description") or "")[:160],
            })
    free.sort(key=lambda x: (x.get("name") or x.get("id") or "").lower())
    return {"ok": True, "count": len(free), "models": free}


@_router.get("/agent-model")
def agent_model_status() -> Dict[str, Any]:
    """实时反映「服务进程内」get_agent() 当前真正使用的模型/provider。

    用于验证「前端切换模型无需重启即生效」：get_agent() 在每次调用时会重读
    config.yaml 并对模型/provider 不一致的单例自动重建，所以这里返回的就是
    下一次对话请求实际会用的模型（实时真实，不私设）。
    """
    try:
        from matlens_kit.ui.common import get_agent

        agent = get_agent()
        return {
            "ok": True,
            "model": getattr(agent, "model", None),
            "provider": getattr(agent, "provider", None),
            "base_url": getattr(agent, "base_url", None),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# 「关于」tab：恢复出厂设置 / 备份下载
# ---------------------------------------------------------------------------
# 需要从 .env 中清除的 LLM provider 密钥环境变量（与 _PROVIDER_KEY_ENV 一致）。
_PROVIDER_KEYS_TO_CLEAR = {v for v in _PROVIDER_KEY_ENV.values() if v}


@_router.post("/reset")
def reset_settings() -> Dict[str, Any]:
    """恢复出厂设置（前端「关于 → 重置」按钮）。

    步骤（契约第 3 节）：
    1. 时间戳备份 config.yaml / .env（存在才备份）到 config.yaml.bak-<ts>、.env.bak-<ts>；
    2. 把 config.yaml 重写为最小空配置——settings_store 以 DEFAULTS 为底叠加，
       因此 GET 立即回到 general.max_turns=25、papers.export_format=docx、模型段清空；
    3. 从 .env 移除所有 LLM provider 密钥（DEEPSEEK/OPENAI/OPENROUTER_API_KEY），
       保留非密钥行，并从 os.environ 弹出对应键——随后 GET 的 api_key_set=false；
    4. best-effort 让运行中的 agent 失效重建。

    不删除 state.db / papers.db / experiments.db / knowledge（那是「清空历史」与
    备份下载的职责，重置只动设置与密钥）。
    """
    from matlens_constants import get_matlens_home

    home = get_matlens_home()
    ts = time.strftime("%Y%m%d%H%M%S")
    backed_up: list = []

    config_path = home / "config.yaml"
    env_path = _env_path()

    # 1) 时间戳备份（存在才备份）
    try:
        if config_path.exists():
            dst = config_path.with_name(f"config.yaml.bak-{ts}")
            shutil.copy2(config_path, dst)
            backed_up.append(dst.name)
    except Exception:
        pass
    try:
        if env_path.exists():
            dst = env_path.with_name(f".env.bak-{ts}")
            shutil.copy2(env_path, dst)
            backed_up.append(dst.name)
    except Exception:
        pass

    # 2) 恢复设置默认：把 config.yaml 重写为空 dict。settings_store.load_settings()
    #    以 DEFAULTS 为底叠加磁盘原始值，空配置 = 全量默认。
    try:
        home.mkdir(parents=True, exist_ok=True)
        import yaml as _yaml

        config_path.write_text(_yaml.safe_dump({}) + "\n", encoding="utf-8")
    except Exception:
        pass

    # 3) 清除 provider 密钥（重写 .env，保留非密钥行/注释），并弹出进程内环境变量。
    try:
        kept_lines: list = []
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    kept_lines.append(line)
                    continue
                k, _, _v = stripped.partition("=")
                if k.strip() in _PROVIDER_KEYS_TO_CLEAR:
                    continue  # 丢弃密钥行
                kept_lines.append(line)
        env_path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""),
                            encoding="utf-8")
    except Exception:
        pass
    for k in _PROVIDER_KEYS_TO_CLEAR:
        os.environ.pop(k, None)

    # 4) best-effort 让运行中的 agent 失效重建（失败不影响重置结果）
    try:
        from matlens_kit.ui.common import reset_agent

        reset_agent()
    except Exception:
        pass

    return {"ok": True, "reset": True, "backed_up": backed_up}


def _backup_state_db(zf: "zipfile.ZipFile", home: Path) -> None:
    """把 state.db 安全地写入 zip（WAL 安全）。

    WAL 模式下直接 shutil.copy state.db 可能漏掉 -wal 中尚未 checkpoint 的内容。
    优先用 SQLite backup API 生成一个一致性快照再入 zip；失败回退到 shutil.copy2；
    再失败则跳过（best-effort，不抛 500）。
    """
    src = home / "state.db"
    if not src.exists():
        return
    tmp_path: Optional[str] = None
    try:
        import sqlite3
        import tempfile

        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        sconn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        dconn = sqlite3.connect(tmp_path)
        try:
            sconn.backup(dconn)
        finally:
            dconn.close()
            sconn.close()
        zf.write(tmp_path, arcname="state.db")
        return
    except Exception:
        pass
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    try:
        zf.write(src, arcname="state.db")
    except Exception:
        pass


def _build_knowledge_manifest(home: Path) -> str:
    """生成 knowledge/ 元数据清单（不打包向量二进制）。

    列出各子目录名、文件清单与大小。knowledge/ 体量大（向量库），按契约只入清单。
    """
    kdir = home / "knowledge"
    lines = ["MatLens knowledge/ 备份清单（仅元数据，未打包向量二进制）", ""]
    if not kdir.exists():
        lines.append("(knowledge/ 目录不存在)")
        return "\n".join(lines)

    def _walk(d: Path, prefix: str) -> None:
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        except Exception:
            return
        for e in entries:
            if e.is_dir():
                lines.append(f"{prefix}{e.name}/")
                _walk(e, prefix + "    ")
            else:
                try:
                    size = e.stat().st_size
                except Exception:
                    size = -1
                lines.append(f"{prefix}{e.name}  ({size} bytes)")

    _walk(kdir, "")
    return "\n".join(lines)


@_router.get("/backup")
def download_backup() -> Response:
    """打包 MATLENS_HOME 关键配置/数据为 zip 下载（前端「关于 → 备份」按钮）。

    内存打包（io.BytesIO + zipfile）；缺失文件跳过（不 404）；state.db 走
    SQLite backup API 防半写；knowledge/ 体量只入一份 MANIFEST.txt。
    arcname 一律相对 home，不写本机绝对路径。整个端点 best-effort、不抛 500。
    """
    from matlens_constants import get_matlens_home

    home = get_matlens_home()
    ts = time.strftime("%Y%m%d%H%M%S")
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in ("config.yaml", ".env", "papers.db", "experiments.db", "graph.json"):
                p = home / name
                try:
                    if p.exists():
                        zf.write(p, arcname=name)
                except Exception:
                    pass
            # state.db：WAL 安全快照
            try:
                _backup_state_db(zf, home)
            except Exception:
                pass
            # knowledge/：仅清单
            try:
                manifest = _build_knowledge_manifest(home)
                zf.writestr("knowledge/MANIFEST.txt", manifest)
            except Exception:
                pass
    except Exception:
        # 兜底：哪怕打包失败也返回一个空 zip，绝不让设置页 500。
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("error.txt", "backup failed")

    filename = f"matlens-backup-{ts}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

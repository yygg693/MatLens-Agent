# -*- coding: utf-8 -*-
"""工具目录 API —— 前端「工具中心」页的真实数据源。

设计原则（2026-10-15 重写）
--------------------------
此前版本有两个结构性问题，导致前端「工具展示不全」：

1. **通用工具只给聚合摘要**——``count`` + ``examples[:4]``，前端只能画6 张
   分类卡，81 个工具里只有 18 个被归类，其余 63 个（``read_file`` /
   ``search_files`` / ``patch`` …）因前缀不匹配任何分类而**整类丢失**。
2. **材料工具与通用工具重复计数**——``_MATLENS_CORE_TOOLS`` 里已包含 16 个
   材料工具（molar_mass / xrd_preprocess …），与 registry 的
   ``matlens_material`` toolset 重叠，23 + 81 = 104 是虚高数字。

现在改为：
- 逐条返回**所有**工具（材料 + 通用），每条含 name / cn / cat / desc /
  params / emoji，��端可直接渲染完整清单；
- 分类用「前缀表+ 兜底 Other」双层，未归类的**仍然展示**（只是归到 Other）；
- 材料工具去重：registry 命中的不再重复计入通用；
- 补``skill_*`` 分类，让 agent 的skill 能力在工具中心可见。

诚实性要求（沿用项目 AGENTS.md「不编造」原则）：分类标签是**本地维护的映射**，
匹配不上的一律进「其他能力」而非悄悄丢弃；``cn`` 缺失时回落到工具名本身。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

_router = APIRouter(prefix="/api/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# 材料工具中文元数据
# ---------------------------------------------------------------------------
#: 已知材料工具的中文名 / 分类 / 可读描述。
#: ⚠️ 必须保持 **key 唯一** —— Python dict 重复 key 会被后者静默覆盖，
#:    旧版本曾有 9 组重复（energy_convert / battery_capacity / thermo_gibbs /
#:    lever_rule / xrd_dspacing / experiment_plot 等各写两遍），已清理。
_MATERIAL_META: Dict[str, Dict[str, str]] = {
    # 材料计算
    "molar_mass": {"cn": "摩尔质量计算", "cat": "材料计算", "desc": "化学式摩尔质量 / 元素占比 / 组成公式，支持括号与结晶水"},
    "solution_prep": {"cn": "溶液配制", "cat": "材料计算", "desc": "摩尔浓度 / 质量浓度 / 质量分数三种模式，输出溶质用量与步骤"},
    "tauc_bandgap": {"cn": "Tauc 带隙", "cat": "材料计算", "desc": "Tauc plot 直接 / 间接带隙，支持 TXT/CSV 吸收或透射数据"},
    "energy_convert": {"cn": "能量单位换算", "cat": "材料计算", "desc": "光谱能量单位互转：eV↔nm↔cm⁻¹↔THz↔kJ/mol"},
    "battery_capacity": {"cn": "电池理论比容量", "cat": "材料计算", "desc": "C=nF/(3.6M)，支持化学式或直接给摩尔质量（含固溶体 NCM811）"},
    "thermo_gibbs": {"cn": "热力学判据", "cat": "材料计算", "desc": "Gibbs 自由能 ΔG=ΔH−T·ΔS，判断自发方向与平衡温度"},
    "lever_rule": {"cn": "相图杠杆定律", "cat": "材料计算", "desc": "二元相图两平衡相相对质量分数 Wα/Wβ"},
    "unit_convert": {"cn": "通用单位换算", "cat": "材料计算", "desc": "温度/压力/长度/质量/体积单位换算，支持 K↔°C、atm↔kPa、Å↔nm 等"},
    "balance_equation": {"cn": "化学方程式配平", "cat": "材料计算", "desc": "输入未配平方程式，输出配平系数与元素守恒验证"},
    "crystal_structure": {"cn": "晶体结构解析", "cat": "材料计算", "desc": "输入化学式+结构类型，计算晶格参数/密度/空间群/配位数/原子位置"},
    # 实验辅助
    "experiment_protocol": {"cn": "实验方案", "cat": "实验辅助", "desc": "水热 / 溶胶凝胶 / 煅烧 / 电化学 4 种实验方案模板"},
    "lab_notebook_template": {"cn": "记录模板", "cat": "实验辅助", "desc": "标准实验记录模板生成（目的 / 材料 / 步骤 / 结果）"},
    "chemical_safety": {"cn": "化学品安全", "cat": "实验辅助", "desc": "危险化学品安全信息查询（危险性 / 防护 / 应急）"},
    # 数据处理
    "xrd_preprocess": {"cn": "XRD 预处理", "cat": "数据处理", "desc": "XRD 图谱背景扣除 / SG 平滑 / 峰识别"},
    "xrd_dspacing": {"cn": "XRD 晶面间距", "cat": "数据处理", "desc": "Bragg 2θ↔d 互转，支持 Cu/Co/Fe/Mo/Cr 常用靶"},
    "data_normalize": {"cn": "数据归一化", "cat": "数据处理", "desc": "多种归一化方式，适配不同实验数据尺度"},
    "experiment_plot": {"cn": "实验数据可视化", "cat": "数据处理", "desc": "XRD/Tauc/CV/充放电曲线渲染 PNG 图表"},
    "data_fit": {"cn": "数据自动拟合", "cat": "数据处理", "desc": "线性拟合/高斯峰拟合（峰位/FWHM）/Tauc带隙拟合，自动找吸收边"},
    # 写作
    "citation_format": {"cn": "文献格式", "cat": "写作", "desc": "参考文献格式：GB/T 7714 / IEEE / APA"},
    "experiment_writing": {"cn": "实验写作", "cat": "写作", "desc": "实验方法 / 结果讨论章节写作辅助"},
    # 知识库
    "rag_search": {"cn": "知识库检索", "cat": "知识库", "desc": "对话中检索当前知识库文献片段，带来源标注"},
    "matlens_kb": {"cn": "知识库管理", "cat": "知识库", "desc": "知识库创建 / 切换 / 导入 / 问答操作"},
}

#: 通用工具分类表：前缀 → (中文名, 提示)
#: ⚠️ 只做**前缀**匹配是 2026-10-15 修复的核心：旧版只有 6 个分类，
#:    81 个工具中 63 个（read_file / search_files / patch / todo / cronjob …）
#:    因不匹配任何前缀而丢失。现在扩展到 16 类 + 兜底「其他能力」。
_GENERAL_PREFIXES: List[tuple] = [
    ("web_", "Web 检索", "网页搜索 / 正文抽取"),
    ("browser_", "浏览器", "导航 / 点击 / 截图 / CDP"),
    ("terminal", "终端", "命令执行"),
    ("process", "进程管理", "后台任务 / 生命周期"),
    ("read_file", "文件读取", "读取本地文件"),
    ("write_file", "文件写入", "写入 / 新建文件"),
    ("patch", "文件编辑", "补丁式精准修改"),
    ("search_files", "文件检索", "内容 / 路径搜索"),
    ("execute_code", "代码执行", "沙箱运行代码片段"),
    ("vision_", "视觉理解", "图像内容分析"),
    ("image_", "图像生成", "文生图/ 图生图"),
    ("bfl_", "视频生成", "Black Forest Labs 视频接口"),
    ("text_to_speech", "语音合成", "文本转语音"),
    ("skill_", "技能管理", "查看 / 加载 / 新增技能"),
    ("skills_", "技能管理", "技能列表"),
    ("todo", "任务管理", "待办清单"),
    ("memory", "记忆", "长期记忆读写"),
    ("session_", "会话检索", "历史会话搜索"),
    ("cronjob", "定时任务", "cron 调度"),
    ("delegate_task", "子任务委派", "派发独立子任务"),
    ("clarify", "澄清提问", "向用户确认歧义"),
    ("computer_use", "计算机控制", "键鼠 / 桌面操作"),
    ("kanban_", "看板协作", "任务看板操作（14 个）"),
    ("ha_", "智能家居", "Home Assistant 设备控制"),
]


def _load_registry():
    """触发并返回工具 registry（幂等）。"""
    import matlens_kit.tools.material_kit  # noqa: F401
    # 网页抓取工具（2026-10-15）：web_fetch / web_fetch_batch / web_capabilities
    # 让 Agent 能主动抓取公开文献正文，补齐「搜到 → 读到 → 引用」闭环。
    try:
        import matlens_kit.tools.web_tools  # noqa: F401
    except Exception as _e:  # 抓取模块缺失不应让工具中心整体挂掉
        logger.warning("web_tools 加载失败，抓取工具不可用: %s", _e)
    import matlens_kit.plugins.local_rag  # noqa: F401
    import tools.matlens_kit_bridge  # noqa: F401
    from tools.registry import registry

    return registry


def _core_tool_defs() -> Dict[str, Dict[str, Any]]:
    """从 model_tools.get_tool_definitions() 取核心工具的真实 schema。

    ⚠️ **数据源选择很关键**（2026-10-15 实测）：

    - ``tools.registry`` 只有**材料插件**的条目，``registry.get_entry('web_search')``
      返回 ``None`` —— 核心工具不走这个registry。
    - ``toolsets._MATLENS_CORE_TOOLS`` 只是**名字清单**（81 个），没有 schema。
    - ``model_tools.get_tool_definitions()`` 才是权威：它返回 OpenAI 风格的
      function 定义（description / properties / required / examples），
      而且已经过 ``check_fn`` 过滤 —— 拿不到 key 的工具不会出现在结果里。

    副作用是**这里的清单是"当前可实际调用"的**，比静态清单短（典型 42 vs 81）。
    这恰恰是用户最需要看到的信息：不能调的工具列出来没有意义。
    """
    try:
        from model_tools import get_tool_definitions

        defs = get_tool_definitions()
    except Exception as e:
        return {"__error__": f"{type(e).__name__}: {e}"}
    out: Dict[str, Dict[str, Any]] = {}
    for d in defs or []:
        fn = (d or {}).get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        props = fn.get("properties") or fn.get("parameters", {}).get("properties") or {}
        required = set(fn.get("required") or [])
        out[name] = {
            "desc": fn.get("description", ""),
            "examples": fn.get("examples") or [],
            "params_detail": [
                {
                    "name": k,
                    "type": str((v or {}).get("type", "?")),
                    "required": k in required,
                    "desc": str((v or {}).get("description", ""))[:160],
                }
                for k, v in props.items()
            ],
            "params": list(props.keys()),
        }
    return out


def _entry_info(registry, name: str) -> Dict[str, Any]:
    """从 registry 取单条工具的schema / 描述 / emoji。"""
    try:
        e = registry.get_entry(name)
    except Exception:
        e = None
    schema = (e.schema if e is not None else None) or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return {
        "desc": (e.description if e is not None else "") or "",
        "emoji": (e.emoji if e is not None else "") or "",
        # 参数明细：名/ 类型 / 必填 / 说明 —— 供前端详情抽屉展示
        "params_detail": [
            {
                "name": k,
                "type": str((v or {}).get("type", "?")),
                "required": k in required,
                "desc": str((v or {}).get("description", ""))[:120],
            }
            for k, v in props.items()
        ],
        "params": list(props.keys()),
    }


def _classify_general(name: str) -> Dict[str, str]:
    """按前缀给通用工具归类。**未匹配 → 「其他能力」**（不丢弃）。"""
    for prefix, cn, hint in _GENERAL_PREFIXES:
        if name == prefix.rstrip("_") or name.startswith(prefix):
            return {"cat": cn, "hint": hint}
    return {"cat": "其他能力", "hint": "未归类的基础工具"}


def _material_tools() -> Dict[str, Any]:
    """材料科研工具（registry 真实注册信息）。"""
    try:
        registry = _load_registry()
        names = registry.get_tool_names_for_toolset("matlens_material")
    except Exception as e:
        return {"items": [], "names": set(), "error": str(e)}

    out: List[Dict[str, Any]] = []
    for n in names:
        info = _entry_info(registry, n)
        meta = _MATERIAL_META.get(n, {})
        out.append({
            "name": n,
            "cn": meta.get("cn", n),
            "cat": meta.get("cat", "材料工具"),
            "desc": meta.get("desc") or info["desc"],
            "params": info["params"],
            "params_detail": info["params_detail"],
            "emoji": info["emoji"] or "⚗",
            "source": "材料插件",
        })
    order = {"材料计算": 0, "实验辅助": 1, "数据处理": 2, "写作": 3, "知识库": 4}
    out.sort(key=lambda t: (order.get(t["cat"], 9), t["name"]))
    return {"items": out, "names": set(names)}


def _general_tools(material_names: set) -> Dict[str, Any]:
    """通用能力：逐条返回（schema 来自 model_tools，已过滤不可用工具）。"""
    try:
        from toolsets import _MATLENS_CORE_TOOLS

        static_names = list(_MATLENS_CORE_TOOLS)
    except Exception as e:
        return {"items": [], "categories": [], "count": 0, "error": str(e)}

    defs = _core_tool_defs()
    core_error = defs.pop("__error__", None) if isinstance(defs, dict) else None
    # schema 清单是权威；静态清单做补充（万一某工具只在静态清单里）
    names = list(defs.keys()) if defs else static_names
    for n in static_names:
        if n not in names and n not in material_names:
            names.append(n)

    items: List[Dict[str, Any]] = []
    # 补充：registry 里注册、但不在静态清单 / schema 清单里的 toolset
    # （2026-10-15：matlens_web 抓取工具走 registry 注册，原来这条路径
    #  只认 _MATLENS_CORE_TOOLS + model_tools，导致工具明明注册成功、
    #  Agent 也能调用，却**在工具中心里完全不可见** —— 用户无从发现。
    #  这里把所有非 material 的 registry toolset 一并纳入目录。）
    try:
        reg = _load_registry()
        try:
            all_names = list(reg.get_all_tool_names())
        except Exception:
            all_names = []
        registered = set(all_names)
        for n in all_names:
            if n in names or n in material_names:
                continue
            info = _entry_info(reg, n)
            cls = _classify_general(n)
            items.append({
                "name": n,
                "cn": info.get("cn") or n,
                "cat": cls["cat"],
                "desc": info.get("desc") or cls["hint"],
                "params": info.get("params") or [],
                "params_detail": info.get("params_detail") or [],
                "examples": info.get("examples") or [],
                "available": True,
                "source": info.get("source") or "MatLens 内置",
            })
    except Exception as e:
        logger.debug("registry 补充工具枚举失败: %s", e)

    for n in names:
        # **去重**：材料工具已单独呈现，不在通用清单里重复计数
        if n in material_names:
            continue
        cls = _classify_general(n)
        info = defs.get(n) or {"desc": "", "params": [], "params_detail": [], "examples": []}
        available = n in defs
        items.append({
            "name": n,
            "cn": n,                      # 通用工具无官方中文名，如实显示原名
            "cat": cls["cat"],
            "desc": info.get("desc") or cls["hint"],
            "params": info.get("params") or [],
            "params_detail": info.get("params_detail") or [],
            "examples": info.get("examples") or [],
            "available": available,        # 是否当前真能调用（check_fn 已过滤）
            "source": "Agent 核心",
        })

    buckets: Dict[str, List[str]] = {}
    hints: Dict[str, str] = {}
    for t in items:
        buckets.setdefault(t["cat"], []).append(t["name"])
        hints.setdefault(t["cat"], t["desc"])
    categories = [
        {
            "cn": c,
            "hint": hints.get(c, ""),
            "count": len(v),
            "tools": v,
            "available": sum(1 for t in items if t["cat"] == c and t.get("available")),
        }
        for c, v in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    ]
    return {
        "items": items,
        "categories": categories,
        "count": len(items),
        "available": sum(1 for t in items if t.get("available")),
        "static_total": len(static_names),
        **({"error": core_error} if core_error else {}),
    }


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@_router.get("")
def tools_catalog() -> Dict[str, Any]:
    """工具目录：**逐条**返回材料 + 通用工具（前端可直接渲染完整清单）。

    返回结构::

        {
          "ok": true,
          "material": [ {...}, ... ],        # 材料工具完整条目
          "general": {
            "items": [ {...}, ... ],          # 通用工具完整条目（已去重）
            "categories": [ {cn, hint, count, tools:[...]}, ... ],
            "count": int
          },
          "totals": {"material": int, "general": int, "all": int},
          "categories": ["材料计算", ...],    # 前端筛选标签直接用
        }
    """
    mat = _material_tools()
    gen = _general_tools(mat.get("names") or set())
    material = mat["items"]
    general_items = gen["items"]

    cats: List[str] = []
    for c in ("材料计算", "实验辅助", "数据处理", "写作", "知识库", "材料工具"):
        if any(t["cat"] == c for t in material):
            cats.append(c)
    for c in gen["categories"]:
        cn = c["cn"]
        if cn not in cats:
            cats.append(cn)

    return {
        "ok": True,
        "material": material,
        "material_count": len(material),
        "general": gen,
        "totals": {
            "material": len(material),
            "general": len(general_items),
            "all": len(material) + len(general_items),
        },
        "categories": cats,
        # 兼容旧字段（前端旧版读 general.categories[].count）
        "general_count": gen.get("count", 0),
    }


# ---------------------------------------------------------------------------
# 技能（skill）—— 让 agent 新增/自更新的 skill 在前端可见
# ---------------------------------------------------------------------------
def _skill_dirs() -> List[Dict[str, str]]:
    """扫描 skill 根目录。**目录不存在就跳过，不报错。**

    真实路径（2026-10-15 实测确认，此前用错导致端点永远返回 0）：

    - 用户级：``skill_manage`` 工具说明里写明新建 skill 落在
      ``~/AppData/Local/matlens/skills/``（Windows 实际路径）
    - 项目级：``<项目根>/skills/``

    ⚠️ 另有 ``~/.workbuddy/skills/``（WorkBuddy 自己的），目录存在但当前为空，
    仍纳入扫描以备后续启用。
    """
    home = os.path.expanduser("~")
    cands = [
        ("用户级", os.path.join(home, "AppData", "Local", "matlens", "skills")),
        ("项目级", os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "skills")),
        ("WorkBuddy", os.path.join(home, ".workbuddy", "skills")),
    ]
    out: List[Dict[str, str]] = []
    seen = set()
    for scope, d in cands:
        d = os.path.normpath(d)
        if d in seen or not os.path.isdir(d):
            continue
        seen.add(d)
        out.append({"scope": scope, "path": d})
    return out


#: skill 描述文件名候选（实测项目用 DESCRIPTION.md，通用约定是 SKILL.md）
_SKILL_MD = ("SKILL.md", "DESCRIPTION.md", "README.md")


def _read_skill_meta(md_path: str) -> Dict[str, str]:
    """从 skill 的 md 文件读 name / description（frontmatter 优先）。"""
    name, desc = "", ""
    try:
        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except OSError:
        return {"name": name, "desc": desc}
    if head.startswith("---"):
        parts = head.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                low = line.lower().strip()
                if low.startswith("name:") and not name:
                    name = line.split(":", 1)[1].strip().strip("\"'")
                elif low.startswith("description:") and not desc:
                    desc = line.split(":", 1)[1].strip().strip("\"'")
    if not desc:
        # 无 frontmatter：取第一段非标题文本作为描述
        for line in head.splitlines():
            s = line.strip()
            if s and not s.startswith(("#", "-", "*", "|", ">", "```")):
                desc = s
                break
    return {"name": name, "desc": desc[:300]}


@_router.get("/skills")
def skills_catalog(translate: bool = True) -> Dict[str, Any]:
    """技能目录：列出磁盘上真实存在的 skill 及其来源与所属分类。

    这是「agent 自更新/ 新增 skill 后能否被用户看见」的关键端点——
    此前 MatLens 9 个 API 模块**没有任何 skill 接口**，agent 装了新 skill
    用户完全无从得知。

    目录结构是**两层**：``<root>/<分类>/<skill>/SKILL.md``。

    Args:
        translate: 是否合并中文索引（默认开）。索引由
            ``matlens_kit.api.build_skill_index`` 生成并落盘，缺失时
            **静默降级为纯英文**——不影响功能，只是搜不到中文。
    """
    items: List[Dict[str, Any]] = []
    seen: set = set()
    for d in _skill_dirs():
        root = d["path"]
        try:
            level1 = sorted(os.listdir(root))
        except OSError:
            continue
        for cat in level1:
            cat_path = os.path.join(root, cat)
            if not os.path.isdir(cat_path):
                continue
            # 情形 A：<root>/<cat>/<skill>/SKILL.md
            try:
                subs = sorted(os.listdir(cat_path))
            except OSError:
                continue
            for skill in subs:
                sp = os.path.join(cat_path, skill)
                if not os.path.isdir(sp):
                    continue
                md = next((os.path.join(sp, f) for f in _SKILL_MD
                           if os.path.isfile(os.path.join(sp, f))), None)
                if not md:
                    continue
                key = os.path.normcase(os.path.abspath(sp))
                if key in seen:
                    continue
                seen.add(key)
                meta = _read_skill_meta(md)
                items.append({
                    "id": skill,
                    "name": meta["name"] or skill,
                    "dir": skill,
                    "category": cat,
                    "scope": d["scope"],
                    "desc": meta["desc"],
                    "path": sp,
                    "md": os.path.basename(md),
                })
            # 情形 B：<root>/<cat>/SKILL.md（分类本身就是一个 skill）
            md = next((os.path.join(cat_path, f) for f in _SKILL_MD
                       if os.path.isfile(os.path.join(cat_path, f))), None)
            if md:
                key = os.path.normcase(os.path.abspath(cat_path))
                if key not in seen:
                    seen.add(key)
                    meta = _read_skill_meta(md)
                    items.append({
                        "id": cat,
                        "name": meta["name"] or cat,
                        "dir": cat,
                        "category": "未分类",
                        "scope": d["scope"],
                        "desc": meta["desc"],
                        "path": cat_path,
                        "md": os.path.basename(md),
                    })

    # ── 合并中文索引（纯附加，缺失即降级） ──
    zh_map: Dict[str, Any] = {}
    zh_cats: Dict[str, str] = {}
    if translate:
        try:
            from matlens_kit.api.build_skill_index import load_index

            idx = load_index()
            zh_map = idx.get("items") or {}
            zh_cats = idx.get("categories") or {}
        except Exception:
            zh_map, zh_cats = {}, {}

    for t in items:
        k = f"{t['scope']}|{t['category']}|{t['dir']}"
        z = zh_map.get(k) or {}
        # cn / desc_cn 为空时前端自动回落到 name / desc
        t["cn"] = z.get("cn") or ""
        t["desc_cn"] = z.get("desc_cn") or ""
        t["category_cn"] = zh_cats.get(t["category"]) or t["category"]
        t["translated"] = bool(z.get("cn"))

    by_scope: Dict[str, int] = {}
    by_cat: Dict[str, int] = {}
    for t in items:
        by_scope[t["scope"]] = by_scope.get(t["scope"], 0) + 1
        by_cat[t["category"]] = by_cat.get(t["category"], 0) + 1

    return {
        "ok": True,
        "skills": items,
        "count": len(items),
        "translated": sum(1 for t in items if t.get("translated")),
        "by_scope": by_scope,
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "dirs": [d["path"] for d in _skill_dirs()],
    }
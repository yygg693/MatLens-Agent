"""MatLens 设置页统一配置存储基座（无 FastAPI 依赖）。

业务模块（论文工坊 / 知识库 / 实验 / 记忆）只 import 本文件读取/写入设置，
不要再各自直读 config.yaml。

设计要点（见 design/settings-backend-contract.md）：

- ``DEFAULTS`` 是「API 形状」的完整嵌套默认（general/memory/papers/kb/experiment），
  即 ``GET /api/settings`` 返回里那几段的形状。
- 磁盘上的真实落点与 API 形状并不一一对应：
    * general.theme / general.tool_progress   -> display.theme / display.tool_progress
    * general.reasoning_effort / max_turns    -> agent.reasoning_effort / agent.max_turns
    * memory.enabled                          -> memory.memory_enabled（沿用既有键）
    * papers/kb/experiment/memory.{auto_write,graph_auto_build,provider} -> 同名同段
  ``_FIELD_SPEC`` 是这个映射的唯一事实来源。
- 读取用 yaml 直读 config.yaml 原始值（参照 matlens_kit.ui.common._load_raw_model_config），
  绕开 matlens_cli.config.load_config() 以 DEFAULT_CONFIG 深合并时把 dict 覆盖成
  字符串的同类 bug；再以 DEFAULTS 为底逐字段叠加磁盘原始值。
- 写入复用 matlens_cli.config.save_config(cfg, merge_existing=True) 单条写路径：
  把 API 形状的嵌套 partial 翻译成磁盘形状后交给它深合并落盘。
- 整型字段（max_turns/chunk_size/chunk_overlap/dpi）强制 int；开关强制 bool。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# ---------------------------------------------------------------------------
# 字段规格：(api_section, api_key) -> (disk_section, disk_key, kind)
# kind: "str" | "int" | "bool"
# ---------------------------------------------------------------------------
_FIELD_SPEC: Dict[tuple, tuple] = {
    # general（display.* + agent.* 的投影）
    ("general", "theme"): ("display", "theme", "str"),
    ("general", "tool_progress"): ("display", "tool_progress", "bool"),
    ("general", "reasoning_effort"): ("agent", "reasoning_effort", "str"),
    ("general", "max_turns"): ("agent", "max_turns", "int"),
    # memory（enabled 沿用既有 memory.memory_enabled 键）
    ("memory", "enabled"): ("memory", "memory_enabled", "bool"),
    ("memory", "auto_write"): ("memory", "auto_write", "bool"),
    ("memory", "graph_auto_build"): ("memory", "graph_auto_build", "bool"),
    ("memory", "provider"): ("memory", "provider", "str"),
    # papers
    ("papers", "export_format"): ("papers", "export_format", "str"),
    ("papers", "cite_style"): ("papers", "cite_style", "str"),
    ("papers", "autosave"): ("papers", "autosave", "bool"),
    ("papers", "tone"): ("papers", "tone", "str"),
    # 导出质量门（见 paper/quality_gate.py）：分数过低时导出前警告（不阻断）
    ("papers", "export_quality_gate"): ("papers", "export_quality_gate", "bool"),
    ("papers", "export_min_score"): ("papers", "export_min_score", "int"),
    # kb
    ("kb", "embed_model"): ("kb", "embed_model", "str"),
    ("kb", "chunk_size"): ("kb", "chunk_size", "int"),
    ("kb", "chunk_overlap"): ("kb", "chunk_overlap", "int"),
    ("kb", "table_extract"): ("kb", "table_extract", "bool"),
    ("kb", "root"): ("kb", "root", "str"),
    # network（网页抓取 / 反追踪，2026-10-15）
    ("network", "proxy_enabled"): ("network", "proxy_enabled", "bool"),
    ("network", "proxy_url"): ("network", "proxy_url", "str"),
    ("network", "tor_control"): ("network", "tor_control", "str"),
    ("network", "rotate_enabled"): ("network", "rotate_enabled", "bool"),
    ("network", "rotate_every"): ("network", "rotate_every", "int"),
    ("network", "rotate_max_requests"): ("network", "rotate_max_requests", "int"),
    # experiment
    ("experiment", "template"): ("experiment", "template", "str"),
    ("experiment", "autosave"): ("experiment", "autosave", "bool"),
    ("experiment", "plot_format"): ("experiment", "plot_format", "str"),
    ("experiment", "dpi"): ("experiment", "dpi", "int"),
    ("experiment", "db_path"): ("experiment", "db_path", "str"),
}

# API 形状完整默认（契约第 2/3 节）
DEFAULTS: Dict[str, Dict[str, Any]] = {
    "general": {
        "theme": "dark",
        "tool_progress": True,
        "reasoning_effort": "medium",
        "max_turns": 25,
    },
    "memory": {
        "enabled": True,
        "auto_write": True,
        "graph_auto_build": True,
        "provider": "mem0",
    },
    "papers": {
        "export_format": "docx",
        "cite_style": "gb7714",
        "autosave": True,
        "tone": "formal",
        "export_quality_gate": True,
        "export_min_score": 60,
    },
    # 网络与反追踪（2026-10-15）
    # 默认全关：是否隐藏 IP 是用户的主动选择，不替他决定。
    # tor_control 需与 torrc 里的 ControlPort 一致（9051 为常用值）。
    "network": {
        "proxy_enabled": False,
        "proxy_url": "socks5h://127.0.0.1:9150",
        "tor_control": "127.0.0.1:9051",
        "rotate_enabled": False,
        "rotate_every": 30,
        "rotate_max_requests": 50,
    },
    "kb": {
        "embed_model": "local",
        "chunk_size": 800,
        "chunk_overlap": 100,
        "table_extract": True,
        "root": "~/.matlens/knowledge",
    },
    "experiment": {
        "template": "standard",
        "autosave": True,
        "plot_format": "png",
        "dpi": 300,
        "db_path": "~/.matlens/experiments.db",
    },
}

# about 段（只读展示，不落 config.yaml）
_ABOUT_VERSION = "v0.2.0"
_ABOUT_TECH_STACK = "FastAPI · 原生 JS · Mem0"


def _home() -> Path:
    """MatLens 主目录。

    2026-10-16 收拢：根因已在上游修掉 —— ``_get_platform_default_matlens_home()``
    原先在 Windows 上返回 ``%LOCALAPPDATA%/matlens``，而项目里 30+ 处硬编码
    ``~/.matlens``，导致「服务进程」与「裸跑脚本」落到两个不同目录
    （服务靠 ``matlens_kit/api/__init__.py`` 的
    ``os.environ.setdefault("MATLENS_HOME", "~/.matlens")`` 兜住，裸跑则落空）。
    现默认路径已统一为 ``~/.matlens``，这里只需跟随权威实现即可。

    ``get_matlens_home()`` 的 docstring 明写
    *"This is the single source of truth — all other copies should import this."*
    """
    try:
        from matlens_cli.config import get_matlens_home

        return get_matlens_home()
    except Exception:
        return Path(os.environ.get("MATLENS_HOME") or Path.home() / ".matlens")


def _config_path() -> Path:
    """config.yaml 路径（唯一）。"""
    return _home() / "config.yaml"


def _config_candidates() -> list:
    """config.yaml 候选路径。

    2026-10-16：原先为兼容 Windows 上的 ``%LOCALAPPDATA%`` 分叉而同时读两个
    路径；根因修复后默认路径已唯一，这里退回单路径 ——
    路径一旦多源，就会再次分叉出「保存成功却读不回来」这类静默问题。
    需要测试隔离或自定义目录时，设 ``MATLENS_HOME`` 即可（上方已支持）。
    """
    return [_config_path()]


def _read_raw_config() -> Dict[str, Any]:
    """yaml 直读 config.yaml 原始内容（不走 load_config 的 DEFAULT 合并）。"""
    for p in _config_candidates():
        if not p.exists():
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _coerce(kind: str, value: Any) -> Any:
    """按字段类型强制转换：int 段强制 int，bool 段强制 bool，str 原样。"""
    if kind == "int":
        if isinstance(value, bool):  # bool 是 int 的子类，先排除
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            # 回退到 DEFAULTS 里该字段的默认值
            return None
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    return value


def _default_for(api_section: str, api_key: str) -> Any:
    return DEFAULTS.get(api_section, {}).get(api_key)


def load_settings() -> Dict[str, Any]:
    """以 DEFAULTS 为底，叠加 config.yaml 原始读取值，返回完整嵌套 settings。

    返回形状（about 段只读展示）：
        {general:{...}, memory:{...}, papers:{...}, kb:{...},
         experiment:{...}, about:{version, tech_stack, home}}
    """
    raw = _read_raw_config()

    out: Dict[str, Dict[str, Any]] = {}
    # 从 DEFAULTS 起底，逐字段用磁盘原始值覆盖
    for api_section, keys in DEFAULTS.items():
        out[api_section] = dict(keys)
        for api_key, default_val in keys.items():
            spec = _FIELD_SPEC.get((api_section, api_key))
            if spec is None:
                continue
            disk_section, disk_key, kind = spec
            disk_val = (raw.get(disk_section) or {}).get(disk_key)
            if disk_val is None:
                continue
            coerced = _coerce(kind, disk_val)
            if coerced is None:
                # 强转失败，回退默认
                continue
            out[api_section][api_key] = coerced

    out["about"] = {
        "version": _ABOUT_VERSION,
        "tech_stack": _ABOUT_TECH_STACK,
        "home": _display_home(),
    }
    return out


def _display_home() -> str:
    """用户友好的根目录展示串（~/.matlens 形式），与契约 about.home 一致。"""
    try:
        from matlens_constants import display_matlens_home

        return display_matlens_home().rstrip("/") + "/"
    except Exception:
        return str(_home()).rstrip("\\/") + "/"


def get_section(name: str) -> Dict[str, Any]:
    """返回某一段（general/memory/papers/kb/experiment/about）。"""
    return dict(load_settings().get(name, {}))


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """原地把 src 深合并进 dst（dict 递归，叶子覆盖），返回 dst。"""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def update_settings(partial: Dict[str, Any]) -> Dict[str, Any]:
    """接收嵌套部分更新（如 {"papers": {"cite_style": "ieee"}}），
    与 config.yaml 现状深合并后持久化，返回更新后的完整 settings。

    只更新传入的叶子；未提及的段/键保持不变。
    整型字段强制 int，开关强制 bool。
    """
    if not isinstance(partial, dict) or not partial:
        return load_settings()

    # 把 API 形状 partial 翻译成磁盘形状 partial
    disk_patch: Dict[str, Dict[str, Any]] = {}
    for api_section, section_patch in partial.items():
        if not isinstance(section_patch, dict):
            continue
        for api_key, value in section_patch.items():
            spec = _FIELD_SPEC.get((api_section, api_key))
            if spec is None:
                continue  # 未登记的键（如 about 只读）忽略
            disk_section, disk_key, kind = spec
            coerced = _coerce(kind, value)
            if coerced is None:
                continue
            disk_patch.setdefault(disk_section, {})[disk_key] = coerced

    if disk_patch:
        # 复用单条写路径：merge_existing=True 会把磁盘现状深合并在 patch 之下，
        # 不影响 patch 未提及的段。
        from matlens_cli.config import save_config

        save_config(disk_patch, merge_existing=True)

    return load_settings()

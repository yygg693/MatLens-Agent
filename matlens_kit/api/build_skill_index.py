# -*- coding: utf-8 -*-
"""skill 中文索引生成器。

问题（2026-10-15）
------------------
186 个 skill 的``name`` 与 ``description`` **全是英文**，中文用户搜
"论文"、"文献"、"画图" 一个都搜不到——功能存在但等于不可见。

方案：不改skill 原文（它们是 agent 运行时读的，改了有副作用），而是维护
一份 **独立的翻译索引**（``skill_index_zh.json``），由工具中心加载后作为
额外的搜索字段与展示字段。

设计要点
--------
1. **纯附加**：原文不动，索引是旁路数据。索引缺失 → 前端自动退回英文，
   不影响任何既有功能。
2. **磁盘缓存**：翻译结果落盘，重启服务不重跑。已有条目的key 跳过。
3. **分批 + 容错**：每批 15 条，单条失败不影响整批；失败项下次补。
4. **不改名**：``name`` 保持原样（agent 按名字调用），只补 ``cn`` /``desc_cn``。
   分类名也做映射（productivity → 效率工具…）。
5. **可离线**：无 API key 时直接返回空索引，前端静默降级。

用法::

    python -m matlens_kit.api.build_skill_index          # 增量生成
    python -m matlens_kit.api.build_skill_index --force  # 全量重建
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

#: 索引落盘位置（与 papers 无关，放matlens home）
def _index_path() -> str:
    home = os.path.expanduser("~")
    base = os.path.join(home, "AppData", "Local", "matlens")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = os.path.join(home, ".matlens")
        os.makedirs(base, exist_ok=True)
    return os.path.join(base, "skill_index_zh.json")


#: 分类名中英映射（覆盖当前实际出现的全部分类，未列的走兜底）
CATEGORY_ZH: Dict[str, str] = {
    "productivity": "效率办公",
    "creative": "创意设计",
    "software-development": "软件开发",
    "github": "GitHub",
    "research": "科研学术",
    "autonomous-ai-agents": "自主 Agent",
    "mlops": "MLOps",
    "media": "音视频图像",
    "apple": "Apple 生态",
    "note-taking": "笔记",
    "social-media": "社交媒体",
    "smart-home": "智能家居",
    "未分类": "未分类",
}

#: 兜底分类翻译（按关键词猜，命中不了就用「其他」）
_CATEGORY_HINTS: List[Tuple[str, str]] = [
    ("product", "效率办公"), ("office", "效率办公"), ("productivity", "效率办公"),
    ("creative", "创意设计"), ("design", "创意设计"), ("media", "音视频图像"),
    ("video", "音视频图像"), ("audio", "音视频图像"), ("image", "音视频图像"),
    ("github", "GitHub"), ("git", "GitHub"),
    ("research", "科研学术"), ("science", "科研学术"), ("paper", "科研学术"),
    ("ml", "MLOps"), ("mlops", "MLOps"), ("model", "MLOps"), ("data", "MLOps"),
    ("dev", "软件开发"), ("code", "软件开发"), ("software", "软件开发"),
    ("test", "软件开发"), ("debug", "软件开发"),
    ("note", "笔记"), ("knowledge", "笔记"),
    ("social", "社交媒体"), ("twitter", "社交媒体"), ("email", "社交媒体"),
    ("home", "智能家居"), ("iot", "智能家居"),
]


def category_zh(cat: str) -> str:
    """分类名→ 中文。未登记的按关键词猜。"""
    c = (cat or "").strip()
    if not c:
        return "未分类"
    if c in CATEGORY_ZH:
        return CATEGORY_ZH[c]
    low = c.lower()
    for k, zh in _CATEGORY_HINTS:
        if k in low:
            return zh
    return "其他"


# ---------------------------------------------------------------------------
# 翻译（批量，走 DeepSeek）
# ---------------------------------------------------------------------------
_BATCH = 15

_SYS_PROMPT = (
    "你是材料化学科研工具的本地化助手。任务：把 AI agent 工具的英文名称与描述"
    "翻译成简体中文。严格要求：\n"
    "1. 名称用**中文短语**，5-12 字，准确传达功能（如 Manage Apple Notes via memo CLI → 管理备忘录）；\n"
    "2. 描述翻译成一句通顺的中文，保留其中的专有名词、命令、文件名、参数名不译"
    "（如 memo CLI、hf、GGUF、Stable Diffusion 保持原样）；\n"
    "3. 只输出 JSON，不要任何解释文字或markdown 代码块标记；\n"
    "4. 格式严格为 {\"items\":[{\"key\":\"<原始key>\",\"cn\":\"<中文名>\",\"desc_cn\":\"<中文描述>\"}]}"
)


def _load_key() -> Optional[str]:
    """从~/.matlens/.env 读 DEEPSEEK_API_KEY（不打印明文）。"""
    for p in (os.path.join(os.path.expanduser("~"), ".matlens", ".env"),
              os.path.join(os.path.expanduser("~"), ".env"),
              os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__)))), ".env")):
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip().startswith("DEEPSEEK_API_KEY"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return os.environ.get("DEEPSEEK_API_KEY")


def _chat(prompt: str, key: str, timeout: int = 120) -> str:
    """调 DeepSeek 拿文本。"""
    import urllib.request

    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _SYS_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
        # 关思考模式：这是纯翻译任务，thinking token 是纯浪费
        "extra_body": {"thinking": {"type": "disabled"}},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return (d.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _parse_items(text: str) -> List[Dict[str, str]]:
    """从模型输出里抠出 JSON（容忍 ``` 包裹与前后废话）。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    # 找第一个 { 到最后一个 }
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return []
    try:
        d = json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return []
    items = d.get("items") if isinstance(d, dict) else None
    return items if isinstance(items, list) else []


def load_index() -> Dict[str, Any]:
    """读取现有索引（不存在返回空壳）。"""
    p = _index_path()
    if not os.path.isfile(p):
        return {"version": 1, "items": {}, "categories": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("items"), dict):
            return d
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "items": {}, "categories": {}}


def save_index(idx: Dict[str, Any]) -> str:
    p = _index_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def collect_skills() -> List[Dict[str, Any]]:
    """从端点逻辑里取全部 skill（复用 tools_api，不重复实现扫描）。"""
    from matlens_kit.api.tools_api import _router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(_router)
    return TestClient(app).get("/api/tools/skills").json().get("skills", [])


def build(force: bool = False, batch: int = _BATCH) -> Dict[str, Any]:
    """增量生成索引。返回统计。"""
    skills = collect_skills()
    if not skills:
        return {"ok": False, "reason": "未扫描到任何 skill"}

    idx = load_index()
    items: Dict[str, Any] = idx.get("items", {}) if not force else {}
    todo: List[Dict[str, Any]] = []
    for s in skills:
        key = f"{s.get('scope')}|{s.get('category')}|{s.get('dir')}"
        if key in items and items[key].get("desc"):
            continue
        todo.append(s)

    stats = {"total": len(skills), "todo": len(todo), "translated": 0,
             "failed": 0, "cached": len(skills) - len(todo)}

    key = _load_key()
    if not todo:
        return {"ok": True, **stats, "note": "索引已是最新"}

    if not key:
        return {"ok": False, **stats, "reason": "未找到 DEEPSEEK_API_KEY"}

    import urllib.error
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        payload = "\n".join(
            f"{n}. key={s.get('scope')}|{s.get('category')}|{s.get('dir')} | "
            f"name={s.get('name')} | desc={(s.get('desc') or '')[:220]}"
            for n, s in enumerate(chunk, 1))
        try:
            text = _chat(
                f"请翻译以下 {len(chunk)} 个工具条目，按 JSON 格式返回：\n\n{payload}",
                key)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            print(f"[warn] 第 {i//batch + 1} 批请求失败：{type(e).__name__}", file=sys.stderr)
            stats["failed"] += len(chunk)
            continue

        got = _parse_items(text)
        by_name = {s.get("name"): s for s in chunk}
        for g in got:
            if not isinstance(g, dict):
                continue
            k = str(g.get("key") or "")
            # 模型可能回传 name 而非 key，兜底按 name 定位
            target = k if k in {f"{s.get('scope')}|{s.get('category')}|{s.get('dir')}"
                                for s in chunk} else None
            if target is None:
                nm = str(g.get("name") or g.get("key") or "")
                for s in chunk:
                    if s.get("name") == nm:
                        target = f"{s.get('scope')}|{s.get('category')}|{s.get('dir')}"
                        break
            if not target:
                continue
            items[target] = {
                "cn": str(g.get("cn") or "")[:40],
                "desc_cn": str(g.get("desc_cn") or "")[:220],
            }
            stats["translated"] += 1
        print(f"[batch {i//batch + 1}/{ (len(todo)+batch-1)//batch }] "
              f"累计翻译 {stats['translated']} 条", file=sys.stderr)

    # 分类中文（本地映射，无需模型）
    cats = {s.get("category") or "未分类": category_zh(s.get("category") or "")
            for s in skills}
    idx = {"version": 1, "items": items, "categories": cats,
           "generated_at": time_str()}
    p = save_index(idx)
    stats["path"] = p
    return {"ok": True, **stats}


def time_str() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 skill 中文索引")
    ap.add_argument("--force", action="store_true", help="忽略缓存，全量重建")
    ap.add_argument("--batch", type=int, default=_BATCH, help="每批条数")
    a = ap.parse_args()
    r = build(force=a.force, batch=max(1, min(a.batch, 30)))
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
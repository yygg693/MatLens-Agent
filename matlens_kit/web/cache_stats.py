# -*- coding: utf-8 -*-
"""MatLens · 抓取缓存统计（2026-10-29）。

为什么需要
----------
抓取层有磁盘缓存（``fetch_cached``，默认 24 小时 TTL），但**用户看不到它的状态**：

- 不知道缓存到底有没有起作用（重复抓同一批文献时，是命中还是每次都重抓）
- 不知道缓存占了多少磁盘（``~/.matlens/fetch_cache/`` 会一直涨）
- 不知道哪些条目已经过期（过期了其实等于没缓存）

所以提供统计：命中率、条目数、磁盘占用、过期分布，并支持清理。

⚠️ 隐私约束（与 web_fetcher 一致）
------------------------------------
缓存文件里存的是**脱敏 URL**（去 query / 去 userinfo）。本模块**只统计数量与体积**，
**绝不读取或暴露缓存内容里的 URL** —— 否则会在接口响应里泄露「用户访问过什么」，
正好抵消了脱敏的意义。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

#: 缓存默认有效期（小时），与 fetch_cached 的默认值一致。
DEFAULT_TTL_H = 24.0


def _cache_dir() -> str:
    from matlens_cli.config import get_matlens_home

    d = get_matlens_home() / "fetch_cache"
    os.makedirs(d, exist_ok=True)
    return str(d)


def _scan(ttl_h: float = DEFAULT_TTL_H) -> Dict[str, Any]:
    """扫描缓存目录，统计数量与体积（**不读取 URL 内容**）。"""
    d = _cache_dir()
    now = time.time()
    total = 0
    fresh = 0
    stale = 0
    broken = 0
    size_total = 0
    hosts: Dict[str, int] = {}
    oldest = 0.0

    try:
        names = os.listdir(d)
    except OSError:
        return {"total": 0, "fresh": 0, "stale": 0, "broken": 0,
                "size_bytes": 0, "size_human": "0 B", "hosts": {},
                "oldest_age_h": 0.0}

    for name in names:
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        total += 1
        size_total += st.st_size
        age_h = (now - st.st_mtime) / 3600.0
        if age_h > oldest:
            oldest = age_h
        if age_h <= ttl_h:
            fresh += 1
        else:
            stale += 1
        # 只取 host 维度做统计（不记录路径/参数）—— host 不算访问痕迹的具体内容
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            url = data.get("url") or ""
            host = ""
            if "://" in url:
                host = url.split("://", 1)[1].split("/", 1)[0].lower()
            if host:
                hosts[host] = hosts.get(host, 0) + 1
        except Exception:
            broken += 1

    top_hosts = sorted(hosts.items(), key=lambda kv: -kv[1])[:8]
    return {
        "total": total,
        "fresh": fresh,
        "stale": stale,
        "broken": broken,
        "size_bytes": size_total,
        "size_human": _fmt_size(size_total),
        "hosts": [{"host": h, "n": n} for h, n in top_hosts],
        "oldest_age_h": round(oldest, 1),
    }


def _fmt_size(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


#: 进程内计数（命中/未命中/写入）。跨请求累计，重启清零。
_runtime = {"hit": 0, "miss": 0, "store": 0}


def record_hit() -> None:
    _runtime["hit"] += 1


def record_miss() -> None:
    _runtime["miss"] += 1


def record_store() -> None:
    _runtime["store"] += 1


def stats(ttl_h: float = DEFAULT_TTL_H) -> Dict[str, Any]:
    """缓存统计汇总。

    命中率分两个口径：
      - **磁盘命中率**：当前缓存里有多少条仍在有效期内（未过期条数 / 总条数）
      - **运行时命中率**：本次进程内的请求命中比（hit / (hit + miss)）
    两者含义不同 —— 前者说明「缓存里有多少可用内容」，
    后者说明「实际请求有多少被缓存挡掉了」。
    """
    s = _scan(ttl_h)
    hit, miss = _runtime["hit"], _runtime["miss"]
    total_req = hit + miss
    s["runtime"] = {
        "hit": hit,
        "miss": miss,
        "store": _runtime["store"],
        "requests": total_req,
        "hit_rate": round(hit / total_req, 3) if total_req else None,
    }
    s["usable_rate"] = round(s["fresh"] / s["total"], 3) if s["total"] else None
    s["ttl_hours"] = ttl_h
    s["dir"] = _cache_dir()
    s["note"] = ("只统计 host 维度，不暴露完整 URL —— 缓存里存的是脱敏 URL，"
                 "统计接口也不该把访问痕迹泄露出去。")
    return s


def purge(stale_only: bool = True, ttl_h: float = DEFAULT_TTL_H) -> Dict[str, Any]:
    """清理缓存。默认只删过期条目（stale_only=True）。

    ⚠️ 只删**缓存文件**，不碰用户的知识库与已导入文档。
    """
    d = _cache_dir()
    now = time.time()
    removed = 0
    freed = 0
    errors = 0
    try:
        names = os.listdir(d)
    except OSError:
        return {"ok": False, "error": "缓存目录不可读", "removed": 0}

    for name in names:
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            st = os.stat(p)
            age_h = (now - st.st_mtime) / 3600.0
            if stale_only and age_h <= ttl_h:
                continue
            size = st.st_size
            os.remove(p)
            removed += 1
            freed += size
        except OSError:
            errors += 1

    return {
        "ok": True,
        "removed": removed,
        "freed_bytes": freed,
        "freed_human": _fmt_size(freed),
        "errors": errors,
        "scope": "过期条目" if stale_only else "全部条目",
    }

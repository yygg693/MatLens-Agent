# -*- coding: utf-8 -*-
"""MatLens · 源健康自检（2026-10-29）。

为什么需要
----------
现状是「**用的时候才知道**」：用户勾了 5 个源去搜，结果某个源配额耗尽
或网络不通，表现为少了一半结果，但用户不知道为什么少。

本模块提供**主动自检**：
  - 定时/按需批量探测各源可达性，结果**缓存**（默认 10 分钟）
  - 分四档状态：ok（可用）/ degraded（降级但可用）/ down（不可用）/
    need_key（需密钥未配置）/ off（默认关闭）
  - 把「为什么不可用」讲清楚（配额 / 超时 / DNS / robots / 需 key）

设计取舍
--------
- **只做轻量探测**（每个源 1 条结果），不做深度压测 —— 自检本身不能
  消耗用户配额，也不能拖慢界面。
- **缓存必须有**：自检是网络操作，每次打开页面都探一遍会拖慢首屏，
  也会让免费 API 配额白白消耗。
- **失败如实报告**：探测失败不是「源坏了」，可能是本地网络问题。
  所以错误信息里带上原因分类，让用户知道该检查网络还是该换源。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

#: 健康状态取值
OK = "ok"
DEGRADED = "degraded"
DOWN = "down"
NEED_KEY = "need_key"
OFF = "off"

#: 缓存有效期（秒）。10 分钟足够覆盖一次使用会话，
#: 又不至于让「刚修好网络」的状态迟迟不刷新。
CACHE_TTL = 600.0

#: 单源探测超时（秒）。要短 —— 逐源探测串行的话，
#: 10 个源 × 8 秒 = 80 秒，用户等不起。
PROBE_TIMEOUT = 8.0

#: 单个源的**硬上限**超时。某些源（HuggingFace 国内直连）会挂到 16s+，
#: 自检的意义是快速反馈，不是等它慢慢失败 —— 超时本身就是「不可用」的结论。
#: 实测：把 8s 压到 5s，整体自检从 22.7s 降到 ~12s。
SOURCE_TIMEOUT_CAP = 5.0

#: 并发探测数。实测 11 个源在 6 并发下要 27 秒，提到 10 后仍受最慢源拖累；
#: 真正的解法是压超时（上面 SOURCE_TIMEOUT_CAP），并发只是辅助。
PROBE_WORKERS = 10

#: 探测用的查询词。选材料方向的高频词，保证各源都有命中，
#: 否则「返回 0 条」会被误判成「源不可用」。
PROBE_QUERY = "solid oxide fuel cell electrolyte"


def _catalog_entry(source_id: str) -> Dict[str, Any]:
    """从源目录里取单个源的元信息。

    ⚠️ scholarly.get_catalog() 返回的是**列表**（每项含 id/label/…），
    不是 dict —— 当成 dict 用会抛 AttributeError（实测踩过）。
    """
    from matlens_kit.rag import scholarly

    for item in (scholarly.get_catalog() or []):
        if item.get("id") == source_id:
            return item
    return {}


def _classify_error(err: str) -> str:
    """把错误信息归类，用于给用户不同的处置建议。"""
    e = (err or "").lower()
    if any(k in e for k in ("429", "quota", "rate limit", "too many requests")):
        return "配额耗尽或被限流"
    if any(k in e for k in ("401", "403", "unauthorized", "forbidden", "api key", "apikey")):
        return "需要有效密钥或被拒绝访问"
    if "timeout" in e or "timed out" in e:
        return "连接超时（本地网络或对方繁忙）"
    if "name or service not known" in e or "nodename nor servname" in e \
            or "getaddrinfo" in e or "dns" in e:
        return "域名解析失败（网络不通）"
    if "ssl" in e or "certificate" in e:
        return "TLS/证书问题（可能是代理拦截）"
    if "robots" in e:
        return "被目标站点 robots 限制"
    if "connection" in e or "refused" in e or "reset" in e:
        return "连接被拒绝或重置"
    return "未知原因"


def _probe_one(source_id: str, timeout: float = PROBE_TIMEOUT) -> Dict[str, Any]:
    """探测单个源。返回 ``{status, ms, n, error, hint}``。"""
    from matlens_kit.rag import scholarly

    # 自检要**快速**反馈，超时本身就是结论 —— 压到硬上限
    timeout = min(timeout, SOURCE_TIMEOUT_CAP)

    meta = _catalog_entry(source_id)
    label = meta.get("label") or source_id

    # 需密钥但未配置 —— 不必探测，直接说明
    if meta.get("key_required") and not _has_key(source_id):
        return {
            "id": source_id, "label": label, "status": NEED_KEY,
            "ms": 0, "n": 0,
            "error": "未配置 API 密钥",
            "hint": "该源需要申请密钥才能用；配置后自动生效",
        }

    t0 = time.time()
    try:
        got = scholarly.check_source(source_id, timeout=timeout)
        ms = int((time.time() - t0) * 1000)
        if got.get("ok"):
            n = got.get("n") or 0
            # 返回 0 条不一定是坏了 —— 探测词可能确实没命中。
            # 但对健康检查而言，连探测词都搜不到就是异常信号，
            # 故降级为 degraded 而不是 ok，让用户看得见。
            status = OK if n > 0 else DEGRADED
            return {
                "id": source_id, "label": label, "status": status,
                "ms": ms, "n": n,
                "error": "" if n else "连通但探测词无命中",
                "hint": "" if n else "源可访问，但探测查询未命中；用别的检索式可能有结果",
            }
        err = got.get("error") or "未知错误"
        return {
            "id": source_id, "label": label, "status": DOWN,
            "ms": ms, "n": 0, "error": err[:160],
            "hint": _classify_error(err),
        }
    except Exception as e:  # noqa: BLE001
        ms = int((time.time() - t0) * 1000)
        err = f"{type(e).__name__}: {e}"[:160]
        return {
            "id": source_id, "label": label, "status": DOWN,
            "ms": ms, "n": 0, "error": err,
            "hint": _classify_error(err),
        }


def _has_key(source_id: str) -> bool:
    """该源所需的密钥是否已配置。"""
    import os
    from matlens_kit.rag import scholarly

    meta = _catalog_entry(source_id)
    key_env = meta.get("key_env") or ""
    if not key_env:
        return True
    return bool(os.environ.get(key_env, "").strip())


# ── 缓存 ──────────────────────────────────────────────
_cache: Dict[str, Any] = {"at": 0.0, "items": {}}
_lock = threading.Lock()


def get_cached() -> Dict[str, Any]:
    """取缓存结果（不触发探测）。过期返回空 items 但仍给出 at 时间。"""
    with _lock:
        return {
            "at": _cache["at"],
            "items": dict(_cache["items"]),
            "fresh": _cache["at"] > 0 and (time.time() - _cache["at"]) < CACHE_TTL,
        }


def _run_probes(targets: List[str], timeout: float) -> Dict[str, Any]:
    """并发探测一批学术源。"""
    import concurrent.futures

    results: Dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
        futs = {ex.submit(_probe_one, s, timeout): s for s in targets}
        for fut in concurrent.futures.as_completed(futs):
            sid = futs[fut]
            try:
                results[sid] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[sid] = {
                    "id": sid, "label": sid, "status": DOWN, "ms": 0, "n": 0,
                    "error": f"{type(e).__name__}: {e}"[:160],
                    "hint": "自检过程异常",
                }
    return results


def check_all(force: bool = False, timeout: float = PROBE_TIMEOUT,
              include_datasets: bool = True) -> Dict[str, Any]:
    """批量自检所有源。命中缓存则直接返回（除非 force）。

    返回 ``{at, items: {src_id: {...}}, summary: {...}}``。
    """
    import concurrent.futures

    now = time.time()
    with _lock:
        fresh = _cache["at"] > 0 and (now - _cache["at"]) < CACHE_TTL
        if fresh and not force and len(_cache["items"]):
            return {
                "at": _cache["at"],
                "items": dict(_cache["items"]),
                "summary": _summarize(_cache["items"]),
                "cached": True,
            }

    from matlens_kit.rag import scholarly

    targets: List[str] = []
    for meta in (scholarly.get_catalog() or []):
        if meta.get("unavailable"):
            continue          # 无公开接口的中文库不参与自检
        targets.append(meta.get("id"))

    # 自检模式：免重试（重试会把 5s 超时翻倍成 10.8s）。
    # ⚠️ 这是**进程级**标志，不是线程级 —— 但所有探测线程都在同一时刻
    #    只想「免重试」，所以全局打开是对的；探测结束后立刻关掉，
    #    避免影响并发的真实检索请求。
    scholarly._set_probe_mode(True)
    try:
        results = _run_probes(targets, timeout)
    finally:
        scholarly._set_probe_mode(False)

    # 数据集源单独探测（Zenodo / HuggingFace）
    if include_datasets:
        try:
            from matlens_kit.rag import datasets as ds

            def _probe_ds(sid: str) -> Dict[str, Any]:
                meta = ds.DATASET_SOURCE_INDEX.get(sid, {})
                label = meta.get("label") or sid
                t0 = time.time()
                try:
                    fn = ds.DATASET_SEARCHERS[sid]
                    got = fn(PROBE_QUERY, 1, min(timeout, SOURCE_TIMEOUT_CAP))
                    ms = int((time.time() - t0) * 1000)
                    status = OK if got else DEGRADED
                    return {
                        "id": sid, "label": label, "status": status, "ms": ms,
                        "n": len(got), "error": "" if got else "连通但无命中",
                        "hint": "" if got else "源可访问，探测查询无命中",
                        "kind": "dataset",
                    }
                except Exception as e:  # noqa: BLE001
                    ms = int((time.time() - t0) * 1000)
                    err = f"{type(e).__name__}: {e}"[:160]
                    return {
                        "id": sid, "label": label, "status": DOWN, "ms": ms, "n": 0,
                        "error": err, "hint": _classify_error(err), "kind": "dataset",
                    }

            ds._set_probe_mode(True)
            try:
                # ⚠️ 只探测**默认启用**的源。默认关闭的源（如 HuggingFace）
                # 用户本来就不会勾选，探它纯属浪费时间 ——
                # 而且它的失败是 **DNS 解析超时**（WinError 10060），
                # socket timeout 管不了，实测挂 10.9 秒，
                # 会把整个自检从 ~7 秒拖到 17 秒。
                ds_targets = [s for s in ds.DATASET_SEARCHERS
                              if (ds.DATASET_SOURCE_INDEX.get(s) or {}).get("default_on")]
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max(1, len(ds_targets))) as dex:
                    dfuts = {dex.submit(_probe_ds, s): s for s in ds_targets}
                    for dfut in concurrent.futures.as_completed(dfuts):
                        sid = dfuts[dfut]
                        try:
                            results[sid] = dfut.result()
                        except Exception as e:  # noqa: BLE001
                            results[sid] = {
                                "id": sid, "label": sid, "status": DOWN, "ms": 0, "n": 0,
                                "error": str(e)[:160], "hint": "自检过程异常", "kind": "dataset",
                            }
            finally:
                ds._set_probe_mode(False)
        except Exception:
            pass

    # 标记默认关闭的源（不是「坏了」，只是没启用）
    from matlens_kit.rag import datasets as ds
    for sid, meta in ds.DATASET_SOURCE_INDEX.items():
        if sid in results and not meta.get("default_on") and results[sid].get("status") == OK:
            results[sid]["status"] = OFF
            results[sid]["hint"] = "可用，但默认未启用"

    with _lock:
        _cache["at"] = now
        _cache["items"] = results

    return {
        "at": now,
        "items": results,
        "summary": _summarize(results),
        "cached": False,
    }


def _summarize(items: Dict[str, Any]) -> Dict[str, Any]:
    """汇总各状态计数。"""
    counts = {OK: 0, DEGRADED: 0, DOWN: 0, NEED_KEY: 0, OFF: 0}
    for v in (items or {}).values():
        st = (v or {}).get("status") or DOWN
        counts[st] = counts.get(st, 0) + 1
    return {
        "total": len(items or {}),
        "ok": counts.get(OK, 0),
        "degraded": counts.get(DEGRADED, 0),
        "down": counts.get(DOWN, 0),
        "need_key": counts.get(NEED_KEY, 0),
        "off": counts.get(OFF, 0),
    }


def invalidate() -> None:
    """清缓存，强制下次重新探测。"""
    with _lock:
        _cache["at"] = 0.0
        _cache["items"] = {}

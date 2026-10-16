# -*- coding: utf-8 -*-
"""MatLens Web 服务层 —— 知识库 API。

封装 matlens_kit.rag.kb.KnowledgeManager / KnowledgeBase（多知识库，
~/.matlens/knowledge/，FAISS + 嵌入复用主 provider）。前端知识库页依赖此层：

**题录导入（2026-10-16 新增）——中文文献唯一合规入口**
- POST   /api/kb/{name}/import-citations  导入 RIS/BibTeX/EndNote/RefWorks 题录
- POST   /api/kb/citations/preview       仅解析不落库（先看清解析对不对）

**本地**
- GET    /api/kb                      列表（含每个库 stats + 当前激活）
- POST   /api/kb                      新建 {name}
- DELETE /api/kb/{name}              删除
- POST   /api/kb/{name}/switch       切换为激活库
- GET    /api/kb/{name}              统计 + 已导入文档清单
- POST   /api/kb/{name}/documents    导入文档（multipart 上传 或 {path} 本地路径）
- GET    /api/kb/{name}/documents/{doc_id}   单篇文献全部分块（精读）
- DELETE /api/kb/{name}/documents/{doc_id}   移除单篇文献索引（不删原文件）
- POST   /api/kb/{name}/import       本地路径批量导入 {paths}
- POST   /api/kb/{name}/query        检索 {question, top_k}

**云端学术 API（2026-10-15 新增）**
- GET    /api/kb/sources             数据源目录：本地库 + 云端源 + 无公开接口的中文库
- GET    /api/kb/sources/health      单源连通性自检 ?source=
- POST   /api/kb/web-search          多源并发检索（不落库）
- POST   /api/kb/{name}/web-import   云端结果 → 写 Markdown → 索引进本地库

注意：``/api/kb/sources`` 等静态路径必须注册在 ``/api/kb/{name}`` 之前，
否则会被 FastAPI 当成知识库名匹配。
"""
from __future__ import annotations

import os
import json
import re
import shutil
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

_router = APIRouter(prefix="/api/kb", tags=["knowledge"])

# 上传暂存目录（避免与知识库数据混在一起）
_UPLOAD_DIR = None


def _upload_dir() -> str:
    global _UPLOAD_DIR
    if _UPLOAD_DIR is None:
        from matlens_cli.config import get_matlens_home

        _UPLOAD_DIR = str(get_matlens_home() / "uploads")
        os.makedirs(_UPLOAD_DIR, exist_ok=True)
    return _UPLOAD_DIR


def _get_manager():
    from matlens_kit.plugins.local_rag import get_manager

    return get_manager()


def _slugify(name: str, existing: set) -> str:
    """把（可能含中文的）库名转成 ASCII 安全的目录名。

    FAISS 在 Windows 上无法写入非 ASCII 路径，故 Web 层把展示名映射为
    ASCII slug；原始名存 .meta.json 作 display_name。
    """
    import re

    slug = re.sub(r"[^A-Za-z0-9_-]", "", name)
    if not slug:
        import hashlib

        slug = "kb_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    base, i = slug, 1
    while slug in existing:
        slug = f"{base}_{i}"
        i += 1
    return slug


def _display_name(name: str, mgr) -> str:
    meta = os.path.join(mgr.root, name, ".meta.json")
    if os.path.exists(meta):
        try:
            d = json.loads(open(meta, encoding="utf-8").read())
            return d.get("display_name") or name
        except Exception:
            pass
    return name


def _normalize_kb(name: str, mgr) -> Dict[str, Any]:
    try:
        kb = mgr.get(name)
        st = kb.stats()
        docs = kb._docs_index
    except Exception:
        st = {"name": name, "docs": 0, "chunks": 0}
        docs = []
    return {
        "name": name,
        "display_name": _display_name(name, mgr),
        "active": mgr.active == name,
        "docs": st.get("docs", 0),
        "chunks": st.get("chunks", 0),
        # 磁盘路径与向量后端：此前 stats() 里有 dir 但前端从未展示，
        # 用户无法判断「东西存哪了、用的什么索引」。这里补齐并让 UI 显示。
        "dir": st.get("dir", ""),
        "vector_backend": _detect_backend(kb),
        "size_bytes": _dir_size(st.get("dir", "")),
        "document_list": [
            {"id": d.get("id"), "source": d.get("source"), "chunks": d.get("chunks")}
            for d in docs
        ],
    }


def _detect_backend(kb) -> str:
    """探测向量后端：优先看 store 上是否有 faiss index 文件。"""
    try:
        d = str(kb.dir)
        if os.path.exists(os.path.join(d, "index.faiss")):
            return "FAISS"
        if os.path.exists(os.path.join(d, "vectors.npy")):
            return "NumPy"
        return "空"
    except Exception:
        return "未知"


def _dir_size(path: str) -> int:
    """知识库目录占用字节数（用于「存储信息」展示）。"""
    if not path or not os.path.isdir(path):
        return 0
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except Exception:
        return 0
    return total


@_router.get("")
def list_kbs() -> Dict[str, Any]:
    mgr = _get_manager()
    names = mgr.list_kbs()
    return {
        "active": mgr.active,
        "kbs": [_normalize_kb(n, mgr) for n in names],
        "count": len(names),
    }


# ---------------------------------------------------------------------------
# 数据源目录（本地库 + 云端学术 API）
#
# 注册位置关键：必须排在 @_router.get("/{name}") 之前，否则 "sources"
# 会被 FastAPI 当成知识库名匹配，返回 404。
# ---------------------------------------------------------------------------
@_router.get("/sources")
def list_sources() -> Dict[str, Any]:
    """知识库的**全部数据源**：本地向量库 + 云端学术 API。

    前端知识库页据此渲染「本地 / 云端」两栏：
    - local：已建库的清单（含磁盘路径、后端、占用）
    - cloud：可勾选的开放学术 API 目录（含学科覆盖与实测状态说明）
    - unavailable：**如实告知无公开接口**的中文库（知网/维普等）及替代路径，
      避免用户以为功能缺失或以为系统会偷偷爬取
    """
    from matlens_kit.rag import scholarly

    mgr = _get_manager()
    names = mgr.list_kbs()
    return {
        "local": {
            "kind": "local",
            "label": "本地知识库",
            "desc": "PDF / TXT / CSV 等本地文件的分块向量索引，完全离线可检索",
            "root": str(mgr.root),
            "items": [_normalize_kb(n, mgr) for n in names],
        },
        "cloud": {
            "kind": "cloud",
            "label": "云端学术 API",
            "desc": "联网检索开放学术数据库，命中的题录+摘要可一键沉淀进本地库",
            "items": scholarly.get_catalog(),
            "defaults": scholarly.DEFAULT_SOURCES,
            "budget_seconds": scholarly.TOTAL_BUDGET,
        },
        "unavailable": scholarly.UNAVAILABLE_SOURCES,
    }


@_router.get("/sources/health")
def source_health(source: str = Query(...)) -> Dict[str, Any]:
    """单源可达性自检（前端「测试连通」按钮）。"""
    from matlens_kit.rag import scholarly

    return {"source": source, **scholarly.check_source(source)}


@_router.get("/sources/oa")
def resolve_oa(doi: str = Query(...)) -> Dict[str, Any]:
    """按 DOI 解析合法开放获取全文链接（Unpaywall）。

    背景：约 30% 付费墙论文存在合法免费版本（作者主页 / 机构库 / 预印本），
    研究者常卡在「找到了但下不到」。此接口只给**合法** OA 链接，不做绕过。
    """
    from matlens_kit.rag import scholarly

    try:
        return scholarly.fetch_unpaywall(doi)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OA 解析失败：{e}")


@_router.post("/web-search")
def web_search(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """多源并发检索云端学术 API（不写入知识库，只返回结果）。

    请求体：{query, sources: [...], per_source: int}
    - 不指定 sources 时用材料化学默认三源（OpenAlex/Crossref/arXiv）
    - 单源失败不影响整体，per_source 里如实给出每个源的成功/错误
    """
    from matlens_kit.rag import scholarly

    payload = payload or {}
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 必填")
    sources = payload.get("sources")
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(",") if s.strip()]
    if not isinstance(sources, list):
        sources = None
    bad = [s for s in (sources or []) if s not in scholarly.SEARCHERS]
    if bad:
        raise HTTPException(status_code=400, detail=f"未知数据源：{', '.join(bad)}")
    try:
        per_source = int(payload.get("per_source") or 6)
    except (TypeError, ValueError):
        per_source = 6
    try:
        return scholarly.search_web(query, sources=sources,
                                    per_source=max(1, min(per_source, 20)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"云端检索失败：{e}")


@_router.post("/{name}/web-import")
def web_import(name: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """把云端检索结果写成本地 Markdown 并索引进指定知识库。

    为什么需要：云端 API 只返回**题录+摘要**，真正能被 RAG 检索到的东西
    必须落到本地库。不做这一步，「联网搜到文献」和「写作时能引用到它」
    之间是断的。
    """
    from matlens_kit.rag import scholarly

    payload = payload or {}
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items 不能为空（传云端检索结果的 items 子集）")
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)

    # 落到 ~/.matlens/uploads/cloud/ 便于追溯来源。
    # 目录按天分（cloud/20261015/），否则同一批导入的文件混在一起，
    # 文件名又长又重复，肉眼无法区分。
    stamp = time.strftime("%Y%m%d-%H%M%S")
    day = time.strftime("%Y%m%d")
    out_dir = os.path.join(_upload_dir(), "cloud", day)
    os.makedirs(out_dir, exist_ok=True)

    paths: List[str] = []
    skipped = 0
    n = 0
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        title = (it.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        path = os.path.join(out_dir, scholarly.paper_filename(it, stamp, n))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(scholarly.paper_to_markdown(it))
        except OSError:
            skipped += 1
            continue
        paths.append(path)
        n += 1

    if not paths:
        raise HTTPException(status_code=400, detail="没有可导入的条目（标题为空或写入失败）")
    try:
        res = kb.add_documents(paths)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"索引写入失败：{e}")
    return {"ok": True, "name": name, "imported": len(paths),
            "skipped": skipped, "files": [os.path.basename(p) for p in paths], **res}


@_router.post("")
def create_kb(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    payload = payload or {}
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 必填")
    mgr = _get_manager()
    # Web 层把展示名映射为 ASCII slug（FAISS Windows 非 ASCII 路径限制）
    slug = _slugify(name, set(mgr.list_kbs()))
    res = mgr.create(slug)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    # 存展示名（原始名可能含中文）
    display = payload.get("display_name") or name
    meta = os.path.join(mgr.root, slug, ".meta.json")
    try:
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"display_name": display}, f, ensure_ascii=False)
    except Exception:
        pass
    return {"ok": True, "name": slug, "display_name": display}


@_router.delete("/{name}")
def delete_kb(name: str) -> Dict[str, Any]:
    mgr = _get_manager()
    res = mgr.delete(name)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return {"ok": True, "name": name}


@_router.post("/{name}/switch")
def switch_kb(name: str) -> Dict[str, Any]:
    mgr = _get_manager()
    res = mgr.switch(name)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return {"ok": True, "active": name}


@_router.get("/{name}")
def get_kb(name: str) -> Dict[str, Any]:
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    return _normalize_kb(name, mgr)


@_router.post("/{name}/documents")
async def upload_document(
    name: str,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """上传并导入单个文档（multipart）。"""
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)

    ext = os.path.splitext(file.filename or "")[1] or ".txt"
    safe = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(_upload_dir(), safe)
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        res = kb.add_document(dest)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")
    finally:
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    return {"ok": True, "name": name, **res}


@_router.get("/{name}/documents/{doc_id}")
def get_document(name: str, doc_id: str) -> Dict[str, Any]:
    """单篇文献详情：该文献的全部分块（按 chunk_idx 排序）。

    前端「精读」用 —— 检索命中一个分块后需要能回看该文献的完整内容，
    否则只能看到被切碎的一小段，无法判断上下文。
    """
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)
    chunks = _load_chunks(kb)
    mine = [c for c in chunks if str(c.get("doc_id")) == str(doc_id)]
    if not mine:
        raise HTTPException(status_code=404, detail="文献不存在")
    mine.sort(key=lambda c: c.get("chunk_idx") or 0)
    doc = next((d for d in _load_docs(kb) if str(d.get("id")) == str(doc_id)), {})
    return {
        "doc_id": doc_id,
        "source": doc.get("source") or (mine[0].get("source") if mine else ""),
        "path": doc.get("path"),
        "chunk_count": len(mine),
        "chunks": [{"chunk_idx": c.get("chunk_idx"), "text": c.get("text") or ""} for c in mine],
    }


@_router.delete("/{name}/documents/{doc_id}")
def delete_document(name: str, doc_id: str) -> Dict[str, Any]:
    """从知识库中移除单篇文献（不删磁盘原文件）。

    为什么必须有：此前误传一份 PDF 只能整库删掉重建，
    而库里往往已有几十篇精读过的东西 —— 这是最痛的缺失。

    实现：向量库不支持按 doc_id 删，故重写 chunks.json / docs.json
    并从 vectors.npy + index.faiss 中剔除对应行（float32 矩阵 + ID 映射）。
    """
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)

    chunks = _load_chunks(kb)
    docs = _load_docs(kb)
    keep = [i for i, c in enumerate(chunks) if str(c.get("doc_id")) != str(doc_id)]
    removed = len(chunks) - len(keep)
    if removed == 0:
        raise HTTPException(status_code=404, detail="文献不存在")

    doc = next((d for d in docs if str(d.get("id")) == str(doc_id)), None)
    if doc is None:
        raise HTTPException(status_code=404, detail="文献不存在")

    # 走 VectorStore.remove_doc：faiss / numpy 两条后端路径都由它正确处理，
    # 避免在 API 层直接改文件导致 chunks 与向量行序错位。
    removed = kb.store.remove_doc(str(doc_id))
    try:
        with open(os.path.join(str(kb.dir), "docs.json"), "w", encoding="utf-8") as f:
            json.dump([d for d in docs if str(d.get("id")) != str(doc_id)], f, ensure_ascii=False)
    except OSError:
        pass
    return {"ok": True, "name": name, "doc_id": doc_id,
            "removed_chunks": removed, "source": doc.get("source")}


def _load_chunks(kb) -> List[Dict[str, Any]]:
    try:
        with open(kb.store.meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _load_docs(kb) -> List[Dict[str, Any]]:
    p = os.path.join(str(kb.dir), "docs.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


@_router.post("/{name}/import-citations")
def import_citations(name: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """导入题录文件（RIS / BibTeX / EndNote / RefWorks）。

    这是**中文文献唯一合规入口**：知网无公开 API（见 docs/kb_cloud_sources_research.md），
    官网人工检索 → 导出题录 → 在此导入。

    只解析题录元数据（题名/作者/出处/年份/DOI/关键词），**不含正文**；
    正文需用户自行下载 PDF 上传，或对有 DOI 的条目走 Unpaywall OA 降级链。
    """
    from matlens_kit.rag import bibtex as bib

    payload = payload or {}
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)

    items: List[Dict[str, Any]] = []
    source_names: List[str] = []
    # 1) 本地路径导入（用户在知网导出的文件）
    for p in (payload.get("paths") or []):
        path = str(p).strip()
        if not path:
            continue
        if not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"文件不存在：{path}")
        r = bib.parse_bibliography_file(path)
        if not r.get("ok") and r.get("errors"):
            raise HTTPException(
                status_code=400,
                detail=f"{os.path.basename(path)} 解析失败：" + "；".join(r["errors"])[:200])
        items.extend(r.get("items") or [])
        source_names.append(r.get("source_file") or os.path.basename(path))

    # 2) 直接传文本（前端粘贴 / 拖入 txt）
    text = (payload.get("text") or "").strip()
    fmt = "file"
    if text:
        r = bib.parse_bibliography(text, payload.get("filename") or "")
        fmt = r.get("format", "unknown")
        items.extend(r.get("items") or [])

    if not items:
        raise HTTPException(
            status_code=400,
            detail="未解析出任何题录。支持 RIS / BibTeX / EndNote(.enw) / RefWorks(.txt)；"
                   "请确认文件是从知网 / 万方 / PubMed 正常导出的题录（含 %T 或 TI 标题行）")

    # 去重：同 DOI 只留一条；无 DOI 则按标题
    uniq: List[Dict[str, Any]] = []
    seen = set()
    for it in items:
        key = (it.get("doi") or "").strip().lower() or (it.get("title") or "").strip()[:80]
        if key and key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # 落盘为 Markdown 便于追溯
    from matlens_cli.config import get_matlens_home

    out_dir = get_matlens_home() / "uploads" / "citations" / time.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: List[str] = []
    n = 0
    for it in uniq:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip()
        safe = re.sub(r"\s+", " ", safe)[:56].rstrip(". ") or "untitled"
        try:
            p = out_dir / f"{n + 1:02d}_{safe}.md"
            p.write_text(bib.to_markdown([it]), encoding="utf-8")
        except OSError:
            continue
        paths.append(str(p))
        n += 1

    if not paths:
        raise HTTPException(status_code=400, detail="题录缺少题名，无法写入")

    try:
        add = kb.add_documents(paths)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引写入失败：{e}")

    return {
        "ok": True, "name": name, "format": fmt,
        "parsed": len(items), "imported": n,
        "duplicates": len(items) - len(uniq),
        "sources": source_names,
        "note": "已导入题录（元数据）。正文需另行下载 PDF 上传，"
                "或对有 DOI 的条目点「找 OA 全文」自动获取开放版本。",
        **add,
    }


@_router.post("/citations/preview")
def preview_citations(payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """解析题录但不落库 —— 让用户先看清解析对不对，再决定是否导入。

    ⚠️ 必须注册在 ``/{name}/…`` 之前，否则会被当作库名匹配。
    """
    from matlens_kit.rag import bibtex as bib

    payload = payload or {}
    text = (payload.get("text") or "").strip()
    if text:
        r = bib.parse_bibliography(text, payload.get("filename") or "")
    else:
        path = (payload.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="需要 text 或 path")
        if not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"文件不存在：{path}")
        r = bib.parse_bibliography_file(path)
    # 预览截断摘要，避免响应过大
    out = []
    for it in (r.get("items") or [])[:200]:
        x = dict(it)
        if x.get("abstract"):
            x["abstract"] = str(x["abstract"])[:300]
        out.append(x)
    r["items"] = out
    return r


@_router.post("/{name}/import")
def import_documents(
    name: str,
    payload: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """批量导入本地路径文档（JSON body: {paths: [...]}）。"""
    payload = payload or {}
    paths = [p for p in (payload.get("paths") or []) if isinstance(p, str) and os.path.exists(p)]
    if not paths:
        raise HTTPException(status_code=400, detail="paths 必须包含已存在的本地文件路径")
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)
    try:
        res = kb.add_documents(paths)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")
    return {"ok": True, "name": name, **res}


@_router.post("/{name}/query")
def query_kb(
    name: str,
    payload: Dict[str, Any] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 必填")
    top_k = int(payload.get("top_k") or 5)
    mgr = _get_manager()
    if name not in mgr.list_kbs():
        raise HTTPException(status_code=404, detail=f"知识库 {name} 不存在")
    kb = mgr.get(name)
    try:
        hits = kb.query(question, top_k=top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败：{e}")
    return {"name": name, "question": question, "results": hits, "count": len(hits)}

"""Backend abstraction for Mem0 Platform and OSS modes.

Listing contract (the part that used to lie)
--------------------------------------------
``get_all`` returns ``{results, count, total, has_more}``:

* ``results`` — one *window* of rows, at most ``page_size`` of them;
* ``count``   — ``len(results)``, never anything else;
* ``total``   — the store-wide number of rows matching the filters, or
  ``None`` when the backend genuinely cannot report it;
* ``has_more``— whether rows exist after this window.

``offset`` is honoured where the storage engine can do it natively
(ChromaDB, Qdrant); page-based backends emulate it by walking the pages
that cover the requested window.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any, Optional


# mem0 promotes these payload keys to the top level of a memory item and
# keeps everything else under ``metadata`` (see mem0.memory.main).
_PROMOTED_PAYLOAD_KEYS = (
    "user_id",
    "agent_id",
    "run_id",
    "actor_id",
    "role",
    "attributed_to",
    "expiration_date",
)

_CORE_AND_PROMOTED_KEYS = {
    "data",
    "hash",
    "created_at",
    "updated_at",
    "id",
    "text_lemmatized",
    "attributed_to",
    *_PROMOTED_PAYLOAD_KEYS,
}

# Upper bound for the SDK fallback listing. mem0's OSS listing has no
# offset, so the fallback pulls a window and slices locally; beyond this
# many rows the fallback stops rather than dragging the whole store in.
_MAX_SDK_FETCH = 1000


# ---------------------------------------------------------------------------
# Shaping helpers
# ---------------------------------------------------------------------------
def _payload_is_expired(payload: Optional[dict]) -> bool:
    """Mirror mem0's expiry rule: an ``expiration_date`` in the past."""
    if not payload:
        return False
    expiration_date = payload.get("expiration_date")
    if not expiration_date:
        return False
    try:
        return date.fromisoformat(str(expiration_date)) < datetime.now(timezone.utc).date()
    except ValueError:
        return False


def _memory_item(memory_id: Any, payload: Any, text: Any = None) -> dict:
    """Shape one stored row the way mem0's own SDK shapes it.

    ``payload`` is the vector-store metadata dict; mem0 keeps the extracted
    fact in ``payload["data"]``. Mirroring the SDK layout means every
    consumer — provider, API layer, UI — reads the same field names no
    matter which backend answered.
    """
    payload = payload if isinstance(payload, dict) else {}
    item: dict[str, Any] = {
        "id": memory_id,
        "memory": payload.get("data") or text or "",
        "hash": payload.get("hash"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }
    for key in _PROMOTED_PAYLOAD_KEYS:
        if key in payload:
            item[key] = payload[key]
    item["metadata"] = {
        k: v for k, v in payload.items() if k not in _CORE_AND_PROMOTED_KEYS
    }
    return item


def _normalize_single(raw: Any) -> Optional[dict]:
    """Normalize a single-memory payload from any backend."""
    if not isinstance(raw, dict):
        return None
    item = dict(raw)
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    item["metadata"] = metadata
    if not item.get("memory"):
        item["memory"] = item.get("text") or metadata.get("data") or ""
    return item


def _unwrap_results(response: Any) -> list:
    """Normalize API response — extract results list from dict or pass through."""
    if isinstance(response, dict):
        return response.get("results", [])
    if isinstance(response, list):
        return response
    return []


def _normalize_page(response: Any, *, count_is_total: bool = False) -> dict:
    """Normalize a paged listing into ``{results, count, total}``.

    The backends disagree on shape:

    * the cloud API returns ``{count, next, previous, results}`` where
      ``count`` is the *store-wide* number of matching rows (Django REST
      Framework pagination semantics) — **not** the length of this page;
    * the self-hosted server returns ``{memories: [...], total: N}``;
    * the OSS SDK returns ``{results: [...]}`` with no count at all.

    ``count`` is therefore always the length of this page, and ``total`` is
    only populated when the backend actually reports a store-wide figure.
    ``count_is_total`` says which key carries it.
    """
    if isinstance(response, list):
        return {"results": response, "count": len(response), "total": None}
    if not isinstance(response, dict):
        return {"results": [], "count": 0, "total": None}

    results = response.get("results")
    if not isinstance(results, list):
        results = response.get("memories")
    if not isinstance(results, list):
        results = []
    total = response.get("total")
    if not isinstance(total, int):
        raw_count = response.get("count")
        total = raw_count if count_is_total and isinstance(raw_count, int) else None
    return {"results": results, "count": len(results), "total": total}


def _paged_window(
    fetch,
    *,
    page: int,
    page_size: int,
    offset: Optional[int],
    count_is_total: bool = False,
):
    """Fetch one window from a page-based backend.

    ``fetch(page, page_size)`` returns the raw backend response for that
    page. Page-based APIs can only start on a page boundary, so a window
    that does not align with the page grid is served by pulling the pages
    that cover it and slicing locally.

    Returns ``(rows, total, has_more)``.
    """
    page_size = max(1, int(page_size))

    def _one(page_no: int):
        raw = fetch(page_no, page_size)
        data = _normalize_page(raw, count_is_total=count_is_total)
        has_more = None
        if isinstance(raw, dict) and "next" in raw:
            has_more = bool(raw.get("next"))
        return data, has_more

    if offset is None:
        data, has_more = _one(page)
        rows = data["results"]
        total = data["total"]
        if has_more is None:
            has_more = len(rows) >= page_size
        if total is not None:
            has_more = (page - 1) * page_size + len(rows) < total
        return rows, total, has_more

    offset = max(0, int(offset))
    first_page = offset // page_size + 1
    sub = offset % page_size
    need = sub + page_size

    rows: list = []
    total: Optional[int] = None
    page_no = first_page
    while True:
        data, _ = _one(page_no)
        chunk = data["results"]
        rows.extend(chunk)
        if data["total"] is not None:
            total = data["total"]
        if len(rows) >= need:
            # A full chunk means the store may still hold rows past the
            # window; a short chunk means we just ran off the end.
            has_more = len(chunk) == page_size
            break
        if len(chunk) < page_size:
            has_more = False
            break
        page_no += 1

    window = rows[sub:sub + page_size]
    if total is not None:
        has_more = offset + len(window) < total
    return window, total, has_more


def _is_not_found(exc: Exception) -> bool:
    """True when an exception means "no such id" rather than "lookup failed".

    A 404 is an answer; a timeout or a 500 is not. The keyword index uses
    this distinction to decide whether a miss means the memory is gone (drop
    it from the index) or merely unreachable (keep it).
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 404:
        return True
    return str(exc).lower().startswith("not found")


class Mem0Backend(ABC):
    """Unified interface over Platform (MemoryClient) and OSS (Memory) backends."""

    @abstractmethod
    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        ...

    @abstractmethod
    def add(
        self,
        messages: list,
        *,
        user_id: str,
        agent_id: str,
        infer: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        ...

    @abstractmethod
    def update(self, memory_id: str, text: str) -> dict:
        ...

    @abstractmethod
    def delete(self, memory_id: str) -> dict:
        ...

    def get_all(
        self,
        *,
        filters: dict,
        page: int = 1,
        page_size: int = 100,
        offset: Optional[int] = None,
    ) -> dict:
        """List stored memories without a semantic query.

        Used for real counts and for paged browsing of the whole store —
        searching cannot answer either, since a vector query only ever
        returns the nearest neighbours. Backends that cannot enumerate may
        raise NotImplementedError; callers fall back to a best-effort count.

        ``offset`` (0-based) takes precedence over ``page`` when given.
        """
        raise NotImplementedError

    def get(self, memory_id: str) -> Optional[dict]:
        """Fetch one memory by id. ``None`` when the id is unknown."""
        raise NotImplementedError

    def count_all(self, *, filters: dict) -> Optional[int]:
        """Exact number of stored rows for this principal, or ``None``."""
        return None

    def close(self) -> None:
        pass


class PlatformBackend(Mem0Backend):
    """Wraps mem0.MemoryClient for Mem0 Platform (cloud API)."""

    def __init__(self, api_key: str):
        from mem0 import MemoryClient
        self._client = MemoryClient(api_key=api_key)

    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        response = self._client.search(query, filters=filters, top_k=top_k, rerank=rerank)
        return _unwrap_results(response)

    def add(
        self,
        messages: list,
        *,
        user_id: str,
        agent_id: str,
        infer: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {"user_id": user_id, "agent_id": agent_id, "infer": infer}
        if metadata:
            kwargs["metadata"] = metadata
        return self._client.add(messages, **kwargs)

    def update(self, memory_id: str, text: str) -> dict:
        self._client.update(memory_id=memory_id, text=text)
        return {"result": "Memory updated.", "memory_id": memory_id}

    def delete(self, memory_id: str) -> dict:
        self._client.delete(memory_id=memory_id)
        return {"result": "Memory deleted.", "memory_id": memory_id}

    def get(self, memory_id: str) -> Optional[dict]:
        try:
            raw = self._client.get(memory_id)
        except Exception as e:
            if _is_not_found(e):
                return None
            raise
        return _normalize_single(raw)

    def get_all(
        self,
        *,
        filters: dict,
        page: int = 1,
        page_size: int = 100,
        offset: Optional[int] = None,
    ) -> dict:
        # The cloud API paginates with page/page_size and reports the total
        # row count, which is what makes an exact count possible.
        def _fetch(page_no: int, size: int):
            kwargs: dict[str, Any] = {}
            if filters:
                kwargs["filters"] = filters
            kwargs["page"] = page_no
            kwargs["page_size"] = size
            return self._client.get_all(**kwargs)

        rows, total, has_more = _paged_window(
            _fetch, page=page, page_size=page_size, offset=offset, count_is_total=True,
        )
        return {
            "results": rows,
            "count": len(rows),
            "total": total,
            "has_more": has_more,
        }


class SelfHostedBackend(Mem0Backend):
    """Direct HTTP backend for a self-hosted Mem0 server (the FastAPI ``server/``).

    mem0.MemoryClient can't be reused for self-hosted: it is hardwired to the
    cloud API — ``Authorization: Token`` auth and a ``GET /v1/ping/`` validation
    call in ``__init__`` that the self-hosted server does not expose (it would
    404 before any real request). This client talks to that server directly,
    using its actual contract: ``X-API-Key`` auth and the ``/memories`` /
    ``/search`` routes.
    """

    def __init__(self, api_key: str, host: str, transport=None):
        import httpx

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key  # omitted only for AUTH_DISABLED servers
        # Connect-level retries smooth over transient blips so a single
        # dropped SYN doesn't count toward the provider failure breaker.
        # ``transport`` is injectable for tests (httpx.MockTransport).
        if transport is None:
            transport = httpx.HTTPTransport(retries=2)
        self._client = httpx.Client(
            base_url=host.rstrip("/"), headers=headers, timeout=30.0,
            transport=transport,
        )

    def _json(self, method: str, path: str, **kwargs) -> Any:
        resp = self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        # rerank is a platform-only feature; the self-hosted /search ignores it.
        body: dict[str, Any] = {"query": query, "top_k": top_k}
        if filters:
            body["filters"] = filters  # user_id belongs in filters (top-level is deprecated)
        return _unwrap_results(self._json("POST", "/search", json=body))

    def add(
        self,
        messages: list,
        *,
        user_id: str,
        agent_id: str,
        infer: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "messages": messages,
            "user_id": user_id,
            "agent_id": agent_id,
            "infer": infer,
        }
        if metadata:
            body["metadata"] = metadata
        return self._json("POST", "/memories", json=body)

    def update(self, memory_id: str, text: str) -> dict:
        self._json("PUT", f"/memories/{memory_id}", json={"text": text})
        return {"result": "Memory updated.", "memory_id": memory_id}

    def delete(self, memory_id: str) -> dict:
        self._json("DELETE", f"/memories/{memory_id}")
        return {"result": "Memory deleted.", "memory_id": memory_id}

    def get(self, memory_id: str) -> Optional[dict]:
        try:
            raw = self._json("GET", f"/memories/{memory_id}")
        except Exception as e:
            if _is_not_found(e):
                return None
            raise
        if isinstance(raw, dict) and isinstance(raw.get("memory"), dict):
            raw = raw["memory"]
        return _normalize_single(raw)

    def get_all(
        self,
        *,
        filters: dict,
        page: int = 1,
        page_size: int = 100,
        offset: Optional[int] = None,
    ) -> dict:
        # The self-hosted server exposes GET /memories with page/page_size.
        def _fetch(page_no: int, size: int):
            params: dict[str, Any] = {"page": page_no, "page_size": size}
            if filters:
                params["user_id"] = filters.get("user_id")
            return self._json("GET", "/memories", params=params)

        rows, total, has_more = _paged_window(
            _fetch, page=page, page_size=page_size, offset=offset,
        )
        return {
            "results": rows,
            "count": len(rows),
            "total": total,
            "has_more": has_more,
        }

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


class OSSBackend(Mem0Backend):
    """Wraps mem0.Memory for self-hosted (OSS) mode."""

    def __init__(self, oss_config: dict):
        import os
        from mem0 import Memory

        def _provider_block(name: str) -> dict:
            block = dict(oss_config[name])
            provider = str(block.get("provider") or "").strip().lower()
            provider_config = dict(block.get("config", {}))
            legacy_base = provider_config.pop("api_base", None)
            if legacy_base:
                from ._oss_providers import EMBEDDER_PROVIDERS, LLM_PROVIDERS

                provider_def = (
                    LLM_PROVIDERS if name == "llm" else EMBEDDER_PROVIDERS
                ).get(provider, {})
                canonical_key = provider_def.get("base_url_key")
                if canonical_key:
                    provider_config.setdefault(canonical_key, legacy_base)
            block["config"] = provider_config
            return block

        vector_store = dict(oss_config["vector_store"])
        vs_config = dict(vector_store.get("config", {}))

        # Kept for direct vector-store access (exact counting and native
        # paging), which the mem0 SDK does not expose.
        self._oss_config = oss_config

        if "path" in vs_config:
            vs_config["path"] = os.path.expanduser(vs_config["path"])

        embedder_config = oss_config.get("embedder", {}).get("config", {})
        dims = embedder_config.get("embedding_dims")
        if not dims:
            from ._oss_providers import KNOWN_DIMS
            model = embedder_config.get("model", "")
            dims = KNOWN_DIMS.get(model)
        if dims:
            # 注意：mem0 2.0.x 的 MemoryConfig.vector_store.config schema
            # 不允许 embedding_model_dims 字段（只允许 host/path/client/
            # collection_name/tenant/port/api_key）。维度只用于 collection
            # 重建检查，不注入 config（mem0 会从 embedding 函数自动探测）。
            self._recreate_collection_if_dims_changed(
                vector_store.get("provider", "qdrant"), vs_config, dims,
            )

        vector_store["config"] = vs_config

        config = {
            "vector_store": vector_store,
            "llm": _provider_block("llm"),
            "embedder": _provider_block("embedder"),
            "version": "v1.1",
        }
        # MatLens 科研优化：自定义记忆提取指令（材料科研场景），
        # 覆盖 mem0 默认的通用提取规则，优先记科研信息。
        ci = oss_config.get("custom_instructions")
        if ci:
            config["custom_instructions"] = ci
        self._memory = Memory.from_config(config)

    @staticmethod
    def _recreate_collection_if_dims_changed(provider: str, vs_config: dict, expected_dims: int) -> None:
        """Delete stale vector collection when embedding dimensions change."""
        collection_name = vs_config.get("collection_name", "mem0")
        if provider == "qdrant":
            try:
                from qdrant_client import QdrantClient
                path = vs_config.get("path")
                url = vs_config.get("url")
                if path:
                    client = QdrantClient(path=path)
                elif url:
                    client = QdrantClient(url=url, api_key=vs_config.get("api_key"))
                else:
                    return
                try:
                    if not client.collection_exists(collection_name):
                        return
                    info = client.get_collection(collection_name)
                    vectors = info.config.params.vectors
                    # Named-vector collections expose a dict; unnamed expose an object with .size.
                    if isinstance(vectors, dict):
                        first = next(iter(vectors.values()), None)
                        current_dims = first.size if first else None
                    else:
                        current_dims = getattr(vectors, "size", None)
                    if current_dims is not None and current_dims != expected_dims:
                        client.delete_collection(collection_name)
                finally:
                    client.close()
            except Exception:
                pass
        elif provider == "pgvector":
            try:
                import psycopg2
                from psycopg2 import sql as pgsql
                conn_params = {}
                for k in ("host", "port", "user", "password", "dbname"):
                    if vs_config.get(k):
                        conn_params[k] = vs_config[k]
                if vs_config.get("sslmode"):
                    conn_params["sslmode"] = vs_config["sslmode"]
                conn = psycopg2.connect(**conn_params)
                conn.autocommit = True
                try:
                    cur = conn.cursor()
                    try:
                        cur.execute(
                            "SELECT atttypmod FROM pg_attribute "
                            "WHERE attrelid = %s::regclass AND attname = 'vector'",
                            (collection_name,),
                        )
                        row = cur.fetchone()
                        if row and row[0] > 0 and row[0] != expected_dims:
                            cur.execute(pgsql.SQL("DROP TABLE IF EXISTS {}").format(
                                pgsql.Identifier(collection_name)
                            ))
                    finally:
                        cur.close()
                finally:
                    conn.close()
            except Exception:
                pass

    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        response = self._memory.search(query, filters=filters, top_k=top_k)
        return _unwrap_results(response)

    # -- listing ---------------------------------------------------------
    def get_all(
        self,
        *,
        filters: dict,
        page: int = 1,
        page_size: int = 100,
        offset: Optional[int] = None,
    ) -> dict:
        page_size = max(1, int(page_size))
        window_offset = (
            max(0, int(offset)) if offset is not None
            else (max(1, int(page)) - 1) * page_size
        )

        native = self._native_page(
            filters=filters, offset=window_offset, limit=page_size
        )
        if native is not None:
            rows, total = native
            has_more = (
                window_offset + len(rows) < total if total is not None else False
            )
            return {
                "results": rows,
                "count": len(rows),
                "total": total,
                "has_more": has_more,
            }

        # Fallback: the OSS SDK listing has no offset and no count, so pull a
        # window that covers the request and slice it locally.
        fetch = min(window_offset + page_size + 1, _MAX_SDK_FETCH)
        if window_offset >= fetch:
            return {"results": [], "count": 0, "total": None, "has_more": False}
        response = self._memory.get_all(filters=filters or None, top_k=fetch)
        rows = _normalize_page(response)["results"]
        window = rows[window_offset:window_offset + page_size]
        return {
            "results": window,
            "count": len(window),
            "total": None,
            "has_more": len(rows) > window_offset + page_size,
        }

    def _vector_store_info(self):
        """Return ``(provider, vs_config, collection_name)`` for the OSS store."""
        vector_store = getattr(self, "_oss_config", None) or {}
        vector_store = vector_store.get("vector_store", {}) or {}
        provider = str(vector_store.get("provider") or "").strip().lower()
        # The provider's own settings live in the nested "config" block
        # (``{"provider": "chroma", "config": {"collection_name": ...}}``),
        # not at the top level.
        vs_config = vector_store.get("config", {}) or {}
        collection_name = vs_config.get("collection_name", "mem0")
        return provider, vs_config, collection_name

    def _native_page(
        self, *, filters: dict, offset: int, limit: int
    ) -> Optional[tuple]:
        """Page the vector store directly, bypassing the SDK listing.

        Returns ``(rows, total)``, or ``None`` when the store does not
        support native paging — the caller then falls back to the SDK.
        """
        try:
            provider, vs_config, collection_name = self._vector_store_info()
            if provider == "chroma":
                return self._chroma_page(collection_name, filters, offset, limit)
            if provider == "qdrant":
                return self._qdrant_page(vs_config, collection_name, filters, offset, limit)
        except Exception:
            return None
        return None

    # -- Chroma ----------------------------------------------------------
    def _chroma_collection(self, collection_name: str):
        """Return the live Chroma collection, or ``None``."""
        vector_store = getattr(self._memory, "vector_store", None)
        if vector_store is None:
            return None
        collection = getattr(vector_store, "collection", None)
        if collection is not None and hasattr(collection, "get"):
            return collection
        client = getattr(vector_store, "client", None)
        if client is None:
            return None
        return client.get_collection(collection_name)

    def _chroma_where(self, filters: Optional[dict]):
        """Translate a mem0 filter dict into a Chroma where-clause."""
        vector_store = getattr(self._memory, "vector_store", None)
        generator = getattr(vector_store, "_generate_where_clause", None)
        if callable(generator):
            try:
                clause = generator(filters)
                if clause:
                    return clause
            except Exception:
                pass
        where: dict[str, Any] = {}
        for key, value in (filters or {}).items():
            if value is None:
                continue
            where[key] = {"$eq": value}
        return where or None

    def _chroma_page(
        self, collection_name: str, filters: Optional[dict], offset: int, limit: int
    ) -> Optional[tuple]:
        collection = self._chroma_collection(collection_name)
        if collection is None:
            return None
        where = self._chroma_where(filters)
        raw = collection.get(
            where=where, limit=limit, offset=offset,
            include=["metadatas", "documents"],
        )
        ids = raw.get("ids") or []
        metadatas = raw.get("metadatas") or []
        documents = raw.get("documents") or []
        rows = []
        for idx, memory_id in enumerate(ids):
            payload = (
                metadatas[idx]
                if idx < len(metadatas) and isinstance(metadatas[idx], dict)
                else {}
            )
            text = documents[idx] if idx < len(documents) else None
            if _payload_is_expired(payload):
                continue
            rows.append(_memory_item(memory_id, payload, text))
        total = self._chroma_count(collection, where)
        return rows, total

    def _chroma_count(self, collection, where) -> Optional[int]:
        """Exact count of the rows matching ``where``.

        Chroma's ``Collection.count()`` takes **no** filter argument, so a
        filtered count has to come from the ids of a filtered ``get``. The
        earlier implementation called ``count(where=...)``, which Chroma
        rejects with a TypeError; the exception was swallowed and the code
        fell back to the *unfiltered* collection size — wrong for every
        store that holds more than one user in the same collection.
        """
        try:
            if not where:
                return int(collection.count())
        except Exception:
            pass
        try:
            raw = collection.get(where=where, include=[])
            return len(raw.get("ids") or [])
        except Exception:
            return None

    def _count_chroma(self, collection_name: str, user_id: Optional[str]) -> Optional[int]:
        """Count rows in a Chroma collection, optionally scoped to one user."""
        collection = self._chroma_collection(collection_name)
        if collection is None:
            return None
        where = self._chroma_where({"user_id": user_id} if user_id else {})
        return self._chroma_count(collection, where)

    # -- Qdrant ----------------------------------------------------------
    def _qdrant_filter(self, filters: Optional[dict]):
        """Translate a mem0 filter dict into a Qdrant filter."""
        vector_store = getattr(self._memory, "vector_store", None)
        builder = getattr(vector_store, "_create_filter", None)
        if callable(builder):
            try:
                return builder(filters) if filters else None
            except Exception:
                pass
        if not filters:
            return None
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
        except Exception:
            return None
        must = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in filters.items()
            if value is not None
        ]
        return Filter(must=must) if must else None

    def _qdrant_page(
        self,
        vs_config: dict,
        collection_name: str,
        filters: Optional[dict],
        offset: int,
        limit: int,
    ) -> Optional[tuple]:
        from qdrant_client import QdrantClient

        path = vs_config.get("path")
        url = vs_config.get("url")
        if path:
            client = QdrantClient(path=path)
        elif url:
            client = QdrantClient(url=url, api_key=vs_config.get("api_key"))
        else:
            return None
        try:
            if not client.collection_exists(collection_name):
                return [], 0
            query_filter = self._qdrant_filter(filters)
            points, _next = client.scroll(
                collection_name=collection_name,
                scroll_filter=query_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            rows = []
            for point in points:
                payload = getattr(point, "payload", None) or {}
                if _payload_is_expired(payload):
                    continue
                rows.append(_memory_item(str(getattr(point, "id", "") or ""), payload))
            result = client.count(
                collection_name=collection_name,
                count_filter=query_filter,
                exact=True,
            )
            exact = getattr(result, "count", None)
            return rows, exact if isinstance(exact, int) else None
        finally:
            client.close()

    def _count_qdrant(
        self, vs_config: dict, collection_name: str, user_id: Optional[str]
    ) -> Optional[int]:
        try:
            from qdrant_client import QdrantClient

            path = vs_config.get("path")
            url = vs_config.get("url")
            if path:
                client = QdrantClient(path=path)
            elif url:
                client = QdrantClient(url=url, api_key=vs_config.get("api_key"))
            else:
                return None
            try:
                if not client.collection_exists(collection_name):
                    return 0
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                query_filter = None
                if user_id:
                    query_filter = Filter(
                        must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                    )
                result = client.count(collection_name=collection_name, count_filter=query_filter)
                exact = getattr(result, "count", None)
                return exact if isinstance(exact, int) else None
            finally:
                client.close()
        except Exception:
            return None

    def count_all(self, *, filters: dict) -> Optional[int]:
        """Exact number of stored memories for this principal.

        The SDK's own listing is capped by ``top_k``, so the only honest way
        to count is to ask the vector store directly. ChromaDB is the default
        OSS store here (Qdrant is also supported); both expose a count. Other
        stores return None, which callers treat as "unknown".
        """
        try:
            provider, vs_config, collection_name = self._vector_store_info()
            if provider == "chroma":
                return self._count_chroma(collection_name, (filters or {}).get("user_id"))
            if provider == "qdrant":
                return self._count_qdrant(vs_config, collection_name, (filters or {}).get("user_id"))
            return None
        except Exception:
            return None

    # -- single item -----------------------------------------------------
    def get(self, memory_id: str) -> Optional[dict]:
        # ``Memory.get`` returns None for an unknown id and raises when the
        # store itself is unreachable — the difference matters to callers
        # that prune an index, so it is deliberately not swallowed here.
        raw = self._memory.get(memory_id)
        return _normalize_single(raw)

    def add(
        self,
        messages: list,
        *,
        user_id: str,
        agent_id: str,
        infer: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {"user_id": user_id, "agent_id": agent_id, "infer": infer}
        if metadata:
            kwargs["metadata"] = metadata
        return self._memory.add(messages, **kwargs)

    def update(self, memory_id: str, text: str) -> dict:
        self._memory.update(memory_id, data=text)
        return {"result": "Memory updated.", "memory_id": memory_id}

    def delete(self, memory_id: str) -> dict:
        self._memory.delete(memory_id)
        return {"result": "Memory deleted.", "memory_id": memory_id}

    def close(self):
        try:
            telemetry = getattr(self._memory, "telemetry", None)
            if telemetry and hasattr(telemetry, "posthog"):
                try:
                    telemetry.posthog.shutdown()
                except Exception:
                    pass
            if hasattr(self._memory, "close"):
                self._memory.close()
            vs = getattr(self._memory, "vector_store", None)
            if vs and hasattr(vs, "close"):
                vs.close()
            client = getattr(vs, "client", None)
            if client and hasattr(client, "close"):
                client.close()
        except Exception:
            pass

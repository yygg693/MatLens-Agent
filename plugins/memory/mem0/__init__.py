"""Mem0 memory plugin — MemoryProvider interface.

Server-side LLM fact extraction, semantic search, and automatic deduplication
via the Mem0 Platform API (cloud) or OSS (self-hosted) via Memory.

Original PR #2933 by kartik-mem0, adapted to MemoryProvider ABC.

Configuration
-------------
Secret (lives in $MATLENS_HOME/.env or the environment):
  MEM0_API_KEY       — Mem0 Platform API key (required for platform mode)
  MEM0_HOST          — Base URL of a self-hosted Mem0 server. When set, the
                       plugin talks to that server directly over HTTP
                       (X-API-Key auth) instead of the cloud API.

Behavioral settings (live in $MATLENS_HOME/mem0.json, set via `matlens memory
setup`):
  mode               — Backend mode: "platform" (default) or "oss"
  host               — Self-hosted Mem0 server URL (alt: MEM0_HOST env var).
                       When set, routes to the self-hosted HTTP backend.
  user_id            — Canonical user identifier. When set, it is applied
                       uniformly across every gateway (CLI, Telegram, Slack,
                       Discord, …) so the same human gets one merged memory
                       store. When unset, the gateway-native id (e.g. Telegram
                       numeric id, Discord snowflake) is used instead.
  agent_id           — Agent identifier (default: matlens)

The matching MEM0_MODE / MEM0_USER_ID / MEM0_AGENT_ID environment variables are
still read as a backward-compatible fallback, but mem0.json is the canonical
home for these non-secret settings.
"""

from __future__ import annotations

import atexit
import inspect
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider, RecallStatus
from agent.secret_scope import get_secret
from tools.registry import tool_error

logger = logging.getLogger(__name__)

# Circuit breaker: after this many consecutive failures, pause API calls
# for _BREAKER_COOLDOWN_SECS to avoid hammering a down server.
_BREAKER_THRESHOLD = 5
_BREAKER_COOLDOWN_SECS = 120
_PREFETCH_WAIT_SECS = 3

_CLIENT_ERROR_TYPES = ("MemoryNotFoundError", "ValidationError")

# Sentinel returned when neither MEM0_USER_ID nor a gateway-native id is
# available. Treated as "no operator-configured user_id" by initialize() so
# that legacy mem0.json files written by the setup wizard (which historically
# wrote this exact placeholder) still allow gateway-native ids to flow
# through instead of silently overriding them with the placeholder.
_DEFAULT_USER_ID = "matlens-user"

# Provenance vocabulary shared by the ``mem0_add`` tool schema, the write
# path and the API layer that renders it. Keeping one list means the value a
# model is allowed to send, the value we persist and the badge the UI shows
# can never drift apart.
SOURCE_TYPES = ("user", "document", "agent_inference", "imported_web")


def _is_client_error(exc: Exception) -> bool:
    """True for user-caused errors (bad ID, not found) that should NOT trip circuit breaker."""
    etype = type(exc).__name__
    if etype in _CLIENT_ERROR_TYPES:
        return True
    err_str = str(exc).lower()
    return "404" in err_str or "not found" in err_str or "valid uuid" in err_str


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load config from env vars, with $MATLENS_HOME/mem0.json overrides.

    Environment variables provide defaults; mem0.json (if present) overrides
    individual keys.  This avoids a silent failure when the JSON file exists
    but is missing fields like ``api_key`` that the user set in ``.env``.
    """
    from matlens_constants import get_matlens_home

    config = {
        "mode": os.environ.get("MEM0_MODE", "platform"),
        "api_key": get_secret("MEM0_API_KEY", ""),
        "host": os.environ.get("MEM0_HOST", ""),
        "agent_id": os.environ.get("MEM0_AGENT_ID", "matlens"),
        "oss": {},
    }
    # Only carry user_id when the operator explicitly configured one (env or
    # mem0.json). An absent key tells initialize() to fall back to the
    # gateway-native id from kwargs instead of overriding it with a placeholder.
    env_user_id = os.environ.get("MEM0_USER_ID")
    if env_user_id:
        config["user_id"] = env_user_id

    config_path = get_matlens_home() / "mem0.json"
    if config_path.exists():
        try:
            file_cfg = json.loads(config_path.read_text(encoding="utf-8"))
            config.update({k: v for k, v in file_cfg.items()
                           if v is not None and v != ""})
        except Exception:
            pass

    return config


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "name": "mem0_search",
    "description": (
        "Search the user's memories by meaning; returns facts ranked by "
        "relevance. Use this before answering any question that may depend on "
        "what you know about the user (preferences, facts, history, people, "
        "projects, past decisions). For multi-part or multi-hop questions, "
        "call it several times — vary the wording and run follow-up searches "
        "on what earlier results reveal; one search is rarely enough."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "top_k": {"type": "integer", "description": "Max results (default: 10, max: 50)."},
            "rerank": {"type": "boolean", "description": "Rerank results for relevance (default: false, platform mode only)."},
        },
        "required": ["query"],
    },
}

ADD_SCHEMA = {
    "name": "mem0_add",
    "description": (
        "Store a durable fact about the user, verbatim (no LLM extraction). "
        "Call this the moment the user states a lasting preference, correction, "
        "decision, or personal detail worth recalling on future turns — don't "
        "wait to be asked to remember. Skip transient chit-chat and facts you've "
        "already stored."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The fact to store."},
            "source_type": {
                "type": "string",
                "enum": ["user", "document", "agent_inference", "imported_web"],
                "description": (
                    "Where this fact came from. Use 'user' for facts the user "
                    "stated, 'document' for imported papers/notes, "
                    "'agent_inference' for conclusions you derived, "
                    "'imported_web' for scraped web content. Optional."
                ),
            },
            "source_ref": {
                "type": "string",
                "description": (
                    "Pointer back to the source — a DOI, a file path, a session "
                    "id, a URL. Optional but strongly preferred for anything "
                    "that did not come from the user's own words."
                ),
            },
            "confidence": {
                "type": "number",
                "description": (
                    "How confident you are in this fact, between 0 and 1. "
                    "Optional."
                ),
            },
        },
        "required": ["content"],
    },
}

LIST_SCHEMA = {
    "name": "mem0_list",
    "description": (
        "List stored memories in insertion order without a semantic query. "
        "Use this to browse the whole store, to page through it, or to count "
        "it — search can only ever return the nearest neighbours to a query, "
        "so it cannot answer 'how many memories are there' or 'show me the "
        "ones older than X'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "description": "1-based page number (default: 1)."},
            "page_size": {"type": "integer", "description": "Rows per page (default: 50, max: 200)."},
        },
    },
}


UPDATE_SCHEMA = {
    "name": "mem0_update",
    "description": (
        "Replace the text of an existing memory by its ID (take the ID from a "
        "mem0_search result). Use when a stored fact has changed "
        "or was wrong — correct it in place instead of adding a duplicate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "Memory UUID to update."},
            "text": {"type": "string", "description": "New text content."},
        },
        "required": ["memory_id", "text"],
    },
}

DELETE_SCHEMA = {
    "name": "mem0_delete",
    "description": (
        "Delete a memory by its ID (take the ID from a mem0_search "
        "result). Use when a stored fact is obsolete or the user asks you to "
        "forget it; prefer mem0_update if the fact merely changed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "Memory UUID to delete."},
        },
        "required": ["memory_id"],
    },
}


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

def _source_fields(args: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate the optional provenance fields of ``mem0_add``.

    The model may pass anything, so every field is validated here rather than
    trusted: an unknown ``source_type`` or a non-numeric ``confidence`` is
    dropped rather than persisted as junk. Only the fields actually supplied
    end up in the metadata.
    """
    out: Dict[str, Any] = {}

    source_type = args.get("source_type")
    if isinstance(source_type, str):
        normalized = source_type.strip().lower()
        if normalized in SOURCE_TYPES:
            out["source_type"] = normalized

    source_ref = args.get("source_ref")
    if isinstance(source_ref, str) and source_ref.strip():
        out["source_ref"] = source_ref.strip()

    confidence = args.get("confidence")
    if confidence is not None and not isinstance(confidence, bool):
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            value = None
        if value is not None and 0.0 <= value <= 1.0:
            out["confidence"] = value

    return out


def _provenance_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Build one search result row, preserving provenance fields.

    The backend returns the full record (id / memory / score plus
    created_at / updated_at / metadata), but only id+memory+score used to be
    forwarded, so every downstream consumer — the API layer's
    ``_normalize()`` in particular — saw a memory with no timestamp and no
    source. Keep the original three fields untouched and append the
    provenance ones.

    ``metadata`` is coerced to a dict: the backend may return None or a
    non-mapping, and callers index into it directly.
    """
    raw = raw if isinstance(raw, dict) else {}
    meta = raw.get("metadata")
    if not isinstance(meta, dict):
        meta = {}

    created_at = raw.get("created_at") or meta.get("created_at")
    updated_at = raw.get("updated_at") or meta.get("updated_at")

    item = {
        "id": raw.get("id"),
        "memory": raw.get("memory", ""),
        "score": raw.get("score", 0),
        "created_at": created_at,
        "updated_at": updated_at,
        "metadata": meta,
    }
    # The hybrid search stamps its fused score on every row; carrying it
    # through lets the UI show how a memory was found (vector, keyword, or
    # both). Absent for plain vector results, so the shape stays stable.
    if isinstance(raw.get("rrf_score"), (int, float)):
        item["rrf_score"] = raw["rrf_score"]
    return item


class Mem0MemoryProvider(MemoryProvider):
    """Mem0 memory with server-side extraction and semantic search.

    Supports Platform API (cloud) and OSS (self-hosted) modes via MEM0_MODE.
    """

    def __init__(self):
        self._config = None
        self._backend = None
        # Recall indicator state (for memory_manager.describe_recall() → UI)
        self._last_recall_returned = False
        self._last_recall_count = 0
        self._mode = "platform"
        self._api_key = ""
        self._host = ""
        self._user_id = _DEFAULT_USER_ID
        self._agent_id = "matlens"
        self._rerank_default = False
        self._channel = "cli"  # gateway channel name (cli/telegram/discord/...)
        self._sync_thread = None
        self._write_thread = None
        self._prefetch_thread = None
        self._prefetch_query = ""
        self._prefetch_result = ""
        self._prefetch_items: List[Dict[str, Any]] = []
        self._prefetch_done = False
        # Keyword sidecar index (hybrid recall): lazily opened, never required.
        self._keyword_index = None
        self._index_checked = False
        self._index_dirty = False
        self._index_rebuilding = False
        # Reentrant: _ensure_index_fresh() holds this lock while calling
        # _get_keyword_index(), which takes it again.
        self._index_lock = threading.RLock()
        # Circuit breaker state
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._breaker_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._prefetch_lock = threading.Lock()
        self._atexit_registered = False

    @property
    def name(self) -> str:
        return "mem0"

    def is_available(self) -> bool:
        cfg = _load_config()
        mode = cfg.get("mode", "platform")
        if mode == "oss":
            return bool(cfg.get("oss", {}).get("vector_store"))
        # Platform needs an api_key; self-hosted needs a host (api_key optional
        # when the server runs with AUTH_DISABLED).
        return bool(cfg.get("api_key") or cfg.get("host"))

    def save_config(self, values, matlens_home):
        """Write config to $MATLENS_HOME/mem0.json."""
        import json
        from pathlib import Path
        config_path = Path(matlens_home) / "mem0.json"
        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update(values)
        from utils import atomic_json_write
        atomic_json_write(config_path, existing, mode=0o600)

    def get_config_schema(self):
        cfg = _load_config()
        mode = cfg.get("mode", "platform")
        api_key_required = mode != "oss"
        return [
            {"key": "api_key", "description": "Mem0 Platform API key", "secret": True, "required": api_key_required, "env_var": "MEM0_API_KEY", "url": "https://app.mem0.ai"},
            {"key": "host", "description": "Self-hosted Mem0 server URL (leave blank for cloud)", "required": False, "env_var": "MEM0_HOST"},
            {"key": "user_id", "description": "User identifier", "default": "matlens-user"},
            {"key": "agent_id", "description": "Agent identifier", "default": "matlens"},
            {"key": "rerank", "description": "Enable reranking for recall", "default": "false", "choices": ["true", "false"]},
        ]

    def post_setup(self, matlens_home: str, config: dict) -> None:
        from ._setup import post_setup
        post_setup(matlens_home, config)

    def _create_backend(self):
        # Lazy-install the mem0 SDK on demand before either backend imports
        # it. ensure() honors security.allow_lazy_installs (default true) and,
        # on a sealed Docker venv, redirects the install to the durable
        # target. On failure we fall through so the import inside the backend
        # produces the canonical error, captured below.
        try:
            from tools.lazy_deps import ensure as _lazy_ensure
            _lazy_ensure("memory.mem0", prompt=False)
        except ImportError:
            pass
        except Exception:
            pass
        try:
            if self._mode == "oss":
                # MatLens 本地优化：OSS 模式默认走 fastembed 本地模型缓存，
                # 强制 huggingface 离线（避免被墙的联网下载重试拖慢启动）；
                # 模型未缓存时会自然报错提示，不会静默联网。
                _oss = self._config.get("oss", {}) or {}
                if (str(_oss.get("embedder", {}).get("provider", "")).lower() == "fastembed"):
                    os.environ.setdefault("HF_HUB_OFFLINE", "1")
                from ._backend import OSSBackend
                return OSSBackend(_oss)
            if self._host:
                from ._backend import SelfHostedBackend
                return SelfHostedBackend(self._api_key, self._host)
            from ._backend import PlatformBackend
            return PlatformBackend(self._api_key)
        except Exception as e:
            logger.error("Mem0 backend failed to initialize (%s mode): %s", self._mode, e)
            self._init_error = str(e)
            return None

    def _is_breaker_open(self) -> bool:
        """Return True if the circuit breaker is tripped (too many failures)."""
        with self._breaker_lock:
            if self._consecutive_failures < _BREAKER_THRESHOLD:
                return False
            if time.monotonic() >= self._breaker_open_until:
                self._consecutive_failures = 0
                return False
            return True

    def _format_error(self, prefix: str, exc: Exception) -> str:
        msg = f"{prefix}: {exc}"
        if self._mode == "oss":
            err_str = str(exc).lower()
            if "connection" in err_str or "refused" in err_str or "timeout" in err_str:
                vs = self._config.get("oss", {}).get("vector_store", {})
                msg += f" (check that {vs.get('provider', 'vector store')} is running)"
        return msg

    def _record_success(self):
        with self._breaker_lock:
            self._consecutive_failures = 0

    def _record_failure(self):
        with self._breaker_lock:
            self._consecutive_failures += 1
            count = self._consecutive_failures
            if count >= _BREAKER_THRESHOLD:
                self._breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_SECS
            else:
                count = 0
        if count >= _BREAKER_THRESHOLD:
            hint = ""
            if self._mode == "oss":
                vs = self._config.get("oss", {}).get("vector_store", {})
                provider = vs.get("provider", "unknown")
                hint = f" Check that your {provider} vector store is running and reachable."
            logger.warning(
                "Mem0 circuit breaker tripped after %d consecutive failures. "
                "Pausing API calls for %ds.%s",
                count, _BREAKER_COOLDOWN_SECS, hint,
            )

    def initialize(self, session_id: str, **kwargs) -> None:
        self._config = _load_config()
        self._mode = self._config.get("mode", "platform")
        self._api_key = self._config.get("api_key", "")
        self._host = self._config.get("host", "")
        # Resolution order for user_id:
        #   1. Operator-configured MEM0_USER_ID (env or $MATLENS_HOME/mem0.json) —
        #      the canonical principal, applied across every gateway so the same
        #      human gets one merged memory store.
        #   2. Gateway-native id from kwargs (Telegram numeric id, Discord
        #      snowflake, etc.) — preserves per-platform isolation when no
        #      override is configured.
        #   3. Hardcoded fallback _DEFAULT_USER_ID (CLI with no auth).
        # The literal _DEFAULT_USER_ID string is treated as unset so users who
        # ran the setup wizard with the suggested default still get gateway-
        # native ids instead of being silently bucketed together.
        configured = self._config.get("user_id")
        if configured == _DEFAULT_USER_ID:
            configured = None
        self._user_id = configured or kwargs.get("user_id") or _DEFAULT_USER_ID
        self._agent_id = self._config.get("agent_id", "matlens")
        # Persisted rerank preference (setup wizard / mem0.json). Used as the
        # DEFAULT for mem0_search when the model doesn't pass ``rerank``
        # explicitly; per-call args still win. Platform-only feature — other
        # backends accept-and-ignore the flag.
        _rr = self._config.get("rerank", False)
        self._rerank_default = (
            _rr.lower() in ("true", "1", "yes") if isinstance(_rr, str) else bool(_rr)
        )
        self._channel = kwargs.get("platform") or "cli"
        self._backend = self._create_backend()
        if self._backend and not self._atexit_registered:
            atexit.register(self._shutdown_backend)
            self._atexit_registered = True

    def _read_filters(self) -> Dict[str, Any]:
        # Scoped to user_id only — by design — so recall surfaces memories
        # written from any gateway/agent under this principal. Writes attach
        # agent_id (and metadata.channel) so per-agent / per-channel views are
        # still possible at query time when needed; reads default to the wider
        # cross-agent recall.
        return {"user_id": self._user_id}

    def _write_metadata(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Tag every write with the gateway channel so the dashboard can offer
        # per-channel filtered views without coupling identity to the channel.
        #
        # ``extra`` carries provenance built by the caller — typically
        # agent/background_review.build_memory_write_metadata(), which yields
        # write_origin / execution_context / session_id / platform / tool_name
        # and friends. Before this merge existed the provider dropped that
        # payload on the floor, so every memory written through the built-in
        # memory tool reached the backend with nothing but ``channel``.
        # Merging here is what makes provenance survive the round trip.
        merged: Dict[str, Any] = {}
        if extra:
            for key, value in extra.items():
                if value is None:
                    continue
                if isinstance(value, (dict, list, tuple, set, str)) and len(value) == 0:
                    continue
                merged[key] = value
        # The channel is authoritative and must not be spoofed by ``extra``.
        if self._channel:
            merged["channel"] = self._channel
        return merged

    def system_prompt_block(self) -> str:
        # Mirror the precedence in _create_backend (oss > host > platform) so
        # the label always names the backend that actually runs. Checking
        # ``host`` first here would mislabel an ``oss``+``host`` config as
        # self-hosted HTTP even though OSS wins the routing.
        if self._mode == "oss":
            mode_label = "OSS (self-hosted)"
        elif self._host:
            mode_label = "self-hosted (HTTP API)"
        else:
            mode_label = "platform (cloud API)"
        # Rerank is a Mem0 Platform feature only.
        rerank_note = " Rerank is available on search." if (self._mode == "platform" and not self._host) else ""
        return (
            "# Mem0 Memory\n"
            f"Active. Mode: {mode_label}. User: {self._user_id}.\n"
            "You have persistent memory of this user from past conversations. "
            "You should call mem0_search before answering anything that could depend "
            "on prior context (the user's preferences, facts, history, people, "
            "projects, or earlier decisions) — do not rely on the chat window "
            "alone, and do not assume you have no memory.\n"
            "For multi-part or multi-hop questions, run several searches with "
            "different wording/angles and follow-up searches on what the first "
            "results surface; one search is rarely enough. Keep searching until "
            "you have every fact the question needs before you answer.\n"
            "Tools: mem0_search to find memories, mem0_add to store facts, "
            f"mem0_update and mem0_delete to manage by ID.{rerank_note}\n"
            "科研记忆提示：你是材料科研助手，记忆里保存着用户的研究方向、"
            "常用材料体系、实验参数偏好、关键文献结论和决策历史。当用户提到"
            "自己/自己的实验/之前讨论过的材料或结论时，先 mem0_search 再作答；"
            "新学到的科研信息（配方、参数、结论、偏好）记得 mem0_add 保存。"
        )

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        self._start_prefetch(message)

    def _consume_prefetch_result(self, query: str) -> str | None:
        with self._prefetch_lock:
            if self._prefetch_query != query or not self._prefetch_done:
                return None
            result = self._prefetch_result
            self._prefetch_result = ""
            self._prefetch_done = False
            return result

    def _start_prefetch(self, query: str) -> None:
        if not query or self._backend is None or self._is_breaker_open():
            return
        backend = self._backend
        with self._prefetch_lock:
            if self._prefetch_query == query:
                if self._prefetch_done:
                    return
                if self._prefetch_thread and self._prefetch_thread.is_alive():
                    return
            self._prefetch_query = query
            self._prefetch_result = ""
            self._prefetch_done = False

        def _run():
            body = ""
            rows: List[Dict[str, Any]] = []
            try:
                # The keyword index may be behind the store; refresh it in
                # the background so the hot path never waits for a rebuild.
                self._ensure_index_fresh(background=True)
                results = self._hybrid_search(query, top_k=10)
                lines = [r.get("memory", "") for r in (results or []) if r.get("memory")]
                if lines:
                    body = "## Mem0 Memory\n" + "\n".join(f"- {l}" for l in lines)
                # Keep the full rows (id + provenance) so the UI can answer
                # "which memories were injected this turn" instead of showing
                # the user an opaque block of text.
                rows = [_provenance_item(r) for r in (results or []) if r.get("memory")]
                self._record_success()
            except Exception as e:
                self._record_failure()
                logger.debug("Mem0 prefetch failed: %s", e)
            with self._prefetch_lock:
                if self._prefetch_query == query:
                    self._prefetch_result = body
                    self._prefetch_items = rows
                    self._prefetch_done = True

        t = threading.Thread(target=_run, daemon=True, name="mem0-prefetch")
        with self._prefetch_lock:
            self._prefetch_thread = t
        t.start()

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall memories for the CURRENT question with a short hot-path wait."""
        cached = self._consume_prefetch_result(query)
        if cached is not None:
            self._record_recall_indicator(cached)
            return cached
        self._start_prefetch(query)
        with self._prefetch_lock:
            thread = self._prefetch_thread if self._prefetch_query == query else None
        if thread:
            thread.join(timeout=_PREFETCH_WAIT_SECS)
        cached = self._consume_prefetch_result(query)
        if cached is not None:
            self._record_recall_indicator(cached)
            return cached
        # Slow backend: skip injection; mem0_search tool remains the backstop.
        self._record_recall_indicator("")
        return ""

    def _record_recall_indicator(self, body: str) -> None:
        """Track how many memories the last prefetch injected (for recall_status)."""
        if body:
            n = sum(1 for line in body.splitlines() if line.lstrip().startswith("- "))
            self._last_recall_returned = True
            self._last_recall_count = n
        else:
            self._last_recall_returned = False
            self._last_recall_count = 0

    def recall_status(self) -> Optional[RecallStatus]:
        """Report the count injected by the last prefetch (for the UI indicator).

        Returns ``None`` when nothing was injected this turn, so the agent
        doesn't emit a stale "recalled N memories" line.
        """
        if not self._last_recall_returned:
            return None
        return RecallStatus(provider_label="Mem0", count=self._last_recall_count, glyph="🧠")

    def last_injected_memories(self) -> List[Dict[str, Any]]:
        """The memories injected on the most recent recall.

        Exposes the rows (id, text, score, provenance) behind the text block
        that was spliced into the system prompt, so the UI can show what the
        agent actually used this turn instead of an opaque blob.
        """
        with self._prefetch_lock:
            return list(self._prefetch_items)

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mirror a built-in memory-tool write into the Mem0 backend.

        The built-in memory tool writes to MEMORY.md / USER.md and the manager
        (``MemoryManager.on_memory_write``) notifies external providers so they
        can keep a parallel semantic store. Mem0 previously implemented no such
        hook, so the provenance payload assembled by
        ``build_memory_write_metadata()`` — write_origin, session_id, platform
        and friends — never reached the vector store.

        ``remove`` is deliberately ignored: mem0 deletes by id, and this hook
        only receives the entry text, so there is no safe way to resolve it to
        an id. Deletions stay owned by the ``mem0_delete`` tool.
        """
        if action not in {"add", "replace"}:
            return
        text = (content or "").strip()
        if not text:
            return
        if self._backend is None or self._is_breaker_open():
            return

        # The provenance payload from the caller is forwarded verbatim so the
        # stored memory can be traced back to the session and origin that
        # produced it. ``memory_target`` records which side of the built-in
        # split this came from ("user" = user profile, "memory" = agent facts).
        merged: Dict[str, Any] = dict(metadata or {})
        merged["memory_target"] = "user" if target == "user" else "memory"

        def _write() -> None:
            backend = self._backend
            if backend is None:
                return
            try:
                result = backend.add(
                    [{"role": "user", "content": text}],
                    user_id=self._user_id,
                    agent_id=self._agent_id,
                    # infer=False: the built-in memory tool already stores a
                    # distilled fact, so re-running LLM extraction on it would
                    # only risk paraphrasing the entry a second time.
                    infer=False,
                    metadata=self._write_metadata(merged),
                )
                self._record_success()
                # Keep the keyword index in step with the store.
                self._index_added_rows(result)
            except Exception as e:
                self._record_failure()
                logger.debug("Mem0 on_memory_write failed: %s", e)

        # Serialize writes: two concurrent adds against the same Qdrant
        # collection can otherwise interleave badly.
        if self._write_thread and self._write_thread.is_alive():
            self._write_thread.join(timeout=2.0)
        self._write_thread = threading.Thread(
            target=_write, daemon=True, name="mem0-memory-write"
        )
        self._write_thread.start()

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Send the turn to Mem0 for server-side fact extraction (non-blocking)."""
        if self._backend is None or self._is_breaker_open():
            return

        def _sync():
            backend = self._backend
            if backend is None:
                return
            try:
                messages = [
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": assistant_content},
                ]
                result = backend.add(
                    messages,
                    user_id=self._user_id,
                    agent_id=self._agent_id,
                    infer=True,
                    # Facts distilled from a whole turn are agent-side
                    # inferences, not verbatim user statements. Marking them
                    # as such keeps "the user said it" and "we concluded it"
                    # distinguishable downstream.
                    metadata=self._write_metadata({
                        "source_type": "agent_inference",
                        "write_origin": "sync_turn",
                        "session_id": session_id,
                    }),
                )
                self._record_success()
                # The extracted facts are new searchable text — index them.
                self._index_added_rows(result)
            except Exception as e:
                self._record_failure()
                logger.warning("Mem0 sync failed: %s", e)

        with self._sync_lock:
            if self._sync_thread and self._sync_thread.is_alive():
                self._sync_thread.join(timeout=5.0)
            # If still alive after timeout, skip to avoid duplicate ingestion.
            if self._sync_thread and self._sync_thread.is_alive():
                return
            self._sync_thread = threading.Thread(target=_sync, daemon=True, name="mem0-sync")
            self._sync_thread.start()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        # mem0_list is deliberately NOT exposed to the model: browsing the
        # whole store is an API-layer concern, and handing the model a
        # list-everything tool invites it to page through memories instead of
        # searching semantically.
        return [SEARCH_SCHEMA, ADD_SCHEMA, UPDATE_SCHEMA, DELETE_SCHEMA]

    def _backend_accepts_offset(self) -> bool:
        """Whether the backend's ``get_all`` understands an ``offset`` kwarg.

        Third-party backends written against the older page-only contract
        would blow up on an unexpected keyword; ask the signature instead of
        guessing with a try/except around a call that may fail for unrelated
        reasons.
        """
        try:
            params = inspect.signature(self._backend.get_all).parameters
        except (TypeError, ValueError):
            return False
        if "offset" in params:
            return True
        return any(p.kind == p.VAR_KEYWORD for p in params.values())

    def list_memories(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Page through the whole store without a semantic query.

        Returns ``{results, count, total, has_more}`` where ``results`` is
        one window of raw backend rows, ``total`` is the store-wide count
        when the backend can report it, and ``has_more`` says whether rows
        exist after this window. ``offset`` (0-based) wins over ``page``
        when given.
        """
        if self._backend is None:
            return {"results": [], "count": 0, "total": 0, "has_more": False}
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        offset = None if offset is None else max(0, int(offset))
        try:
            if self._backend_accepts_offset():
                data = self._backend.get_all(
                    filters=self._read_filters(),
                    page=page,
                    page_size=page_size,
                    offset=offset,
                )
            else:
                data = self._backend.get_all(
                    filters=self._read_filters(), page=page, page_size=page_size
                )
            self._record_success()
        except NotImplementedError:
            # Backend cannot enumerate — fall back to a wide search so the
            # caller still gets something usable.
            try:
                rows = self._backend.search(
                    "", filters=self._read_filters(), top_k=page_size, rerank=False
                ) or []
            except Exception:
                rows = []
            return {"results": rows, "count": len(rows), "total": None, "has_more": False}
        except Exception as e:
            self._record_failure()
            logger.debug("Mem0 list failed: %s", e)
            return {"results": [], "count": 0, "total": 0, "has_more": False}

        if not isinstance(data, dict):
            return {"results": [], "count": 0, "total": 0, "has_more": False}
        rows = data.get("results")
        if not isinstance(rows, list):
            rows = []
        total = data.get("total")
        has_more = data.get("has_more")
        return {
            "results": rows,
            "count": data.get("count") if isinstance(data.get("count"), int) else len(rows),
            "total": total if isinstance(total, int) else None,
            "has_more": has_more if isinstance(has_more, bool) else False,
        }

    def count_memories(self) -> Optional[int]:
        """Exact number of stored memories for this principal, if knowable.

        The backend can usually answer this exactly (the vector store knows
        how many rows it holds); ``None`` means "unknown", never a guess.
        """
        if self._backend is None:
            return None
        counter = getattr(self._backend, "count_all", None)
        if not callable(counter):
            return None
        try:
            total = counter(filters=self._read_filters())
        except Exception as e:
            logger.debug("Mem0 count failed: %s", e)
            return None
        return total if isinstance(total, int) else None

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one memory by id — no semantic query involved.

        Looking a memory up by id has to be exact: a vector search can only
        return near neighbours, so it can never answer "give me *this* row".
        """
        if self._backend is None or not memory_id:
            return None
        getter = getattr(self._backend, "get", None)
        if not callable(getter):
            return None
        try:
            raw = getter(memory_id)
        except NotImplementedError:
            return None
        except Exception as e:
            self._record_failure()
            logger.debug("Mem0 get failed: %s", e)
            return None
        self._record_success()
        return raw if isinstance(raw, dict) else None

    # ------------------------------------------------------------------
    # Hybrid recall: vector (semantic) + keyword (literal) → RRF
    # ------------------------------------------------------------------
    def _get_keyword_index(self):
        """Lazily open the keyword sidecar index; ``None`` when unavailable.

        The index is optional by design: without it recall degrades to pure
        vector search, so every failure path here is a silent ``None``.
        """
        index = self._keyword_index
        if index is not None:
            return index if getattr(index, "available", False) else None
        with self._index_lock:
            if self._keyword_index is None:
                try:
                    from ._keyword_index import MemoryKeywordIndex

                    candidate = MemoryKeywordIndex()
                    if candidate.open():
                        self._keyword_index = candidate
                    else:
                        candidate.close()
                        return None
                except Exception:
                    return None
        index = self._keyword_index
        return index if index is not None and getattr(index, "available", False) else None

    def _index_memory(self, memory_id: str, text: str, *, updated_at: str = "") -> None:
        """Add one memory to the keyword index (best effort)."""
        index = self._get_keyword_index()
        if index is None or not memory_id or not text:
            return
        try:
            index.upsert(
                memory_id,
                text,
                user_id=self._user_id,
                updated_at=updated_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
        except Exception:
            pass

    def _unindex_memory(self, memory_id: str) -> None:
        """Drop one memory from the keyword index (best effort)."""
        index = self._get_keyword_index()
        if index is None or not memory_id:
            return
        try:
            index.delete(memory_id)
        except Exception:
            pass

    def _index_added_rows(self, result: Any) -> None:
        """Index every memory a write just created.

        The cloud backend extracts asynchronously and returns an event id
        instead of the stored rows — nothing to index there, so the index is
        marked dirty and refreshed on the next freshness check.
        """
        rows = []
        if isinstance(result, dict):
            candidate = result.get("results")
            if isinstance(candidate, list):
                rows = candidate
            elif isinstance(result.get("id"), str):
                rows = [result]
        elif isinstance(result, list):
            rows = result
        indexed = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            memory_id = row.get("id")
            text = row.get("memory") or row.get("text") or ""
            if memory_id and text:
                self._index_memory(
                    str(memory_id),
                    str(text),
                    updated_at=str(row.get("updated_at") or ""),
                )
                indexed += 1
        if not indexed:
            # The write happened but we cannot see its rows (async cloud
            # extraction) — the index may now be behind the store.
            self._index_dirty = True

    def _ensure_index_fresh(self, *, background: bool = False) -> None:
        """Make sure the keyword index covers the current store.

        Uses the backend's exact count (Task 2) against the index's row
        count; when the index is behind, the whole store is re-indexed from
        the vector store — cheap now that listing pages natively.
        """
        with self._index_lock:
            if self._index_checked and not self._index_dirty:
                return
            if self._index_rebuilding:
                return
            index = self._get_keyword_index()
            if index is None or self._backend is None:
                self._index_checked = True
                return
            try:
                total = self.count_memories()
            except Exception:
                total = None
            if total is None:
                self._index_checked = True
                return
            try:
                have = index.count()
            except Exception:
                have = 0
            if have >= total and not self._index_dirty:
                self._index_checked = True
                return
            self._index_checked = True
            self._index_rebuilding = True

        def _rebuild() -> None:
            try:
                self._rebuild_index()
                self._index_dirty = False
            finally:
                with self._index_lock:
                    self._index_rebuilding = False

        if background:
            threading.Thread(
                target=_rebuild, daemon=True, name="mem0-index-rebuild"
            ).start()
        else:
            _rebuild()

    def _rebuild_index(self) -> int:
        """Re-index the whole store from the vector store. Returns row count."""
        index = self._get_keyword_index()
        if index is None or self._backend is None:
            return 0
        try:
            index.clear()
        except Exception:
            pass
        indexed = 0
        offset = 0
        page_size = 200
        # Bounded so a misbehaving backend can't spin forever.
        for _ in range(1000):
            try:
                data = self.list_memories(
                    page=offset // page_size + 1, page_size=page_size, offset=offset
                )
            except Exception:
                break
            rows = data.get("results") if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                memory_id = row.get("id")
                text = row.get("memory") or ""
                if memory_id and text:
                    self._index_memory(
                        str(memory_id),
                        str(text),
                        updated_at=str(row.get("updated_at") or ""),
                    )
                    indexed += 1
            offset += len(rows)
            has_more = data.get("has_more") if isinstance(data, dict) else None
            if not has_more:
                break
        return indexed

    def _keyword_recall(self, query: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Keyword half of the hybrid search: ids → full rows from the store."""
        index = self._get_keyword_index()
        if index is None:
            return []
        getter = getattr(self._backend, "get", None) if self._backend else None
        if not callable(getter):
            return []
        try:
            hits = index.search(query, user_id=self._user_id, limit=limit)
        except Exception:
            return []
        rows: List[Dict[str, Any]] = []
        for memory_id, _score in hits or []:
            try:
                row = getter(memory_id)
            except Exception:
                # The lookup itself failed — that proves nothing about
                # whether the memory still exists. Keep the index entry and
                # skip this candidate; the next rebuild prunes it if the
                # memory really is gone.
                continue
            if isinstance(row, dict) and row.get("memory"):
                rows.append(row)
            else:
                # The store answered "no such id" — the memory is gone.
                self._unindex_memory(memory_id)
        return rows

    def _hybrid_search(
        self, query: str, *, top_k: int = 10, rerank: bool = False
    ) -> List[Dict[str, Any]]:
        """Vector recall + keyword recall, fused with Reciprocal Rank Fusion.

        Vector recall is blind to literal tokens — a material grade
        (``NCM811``), a model number, an abbreviation. The keyword index
        covers that gap; RRF merges the two rankings without needing their
        (incomparable) scores to agree on a scale. With no keyword index the
        result is exactly the vector recall.
        """
        backend = self._backend
        if backend is None:
            return []
        query = (query or "").strip()
        if not query:
            return []
        # Both recallers contribute their own top-k; RRF merges the two
        # rankings. The vector call keeps its original top_k so the fused
        # search never changes what the vector store was asked for.
        fetch = max(1, int(top_k))
        vector_rows: List[Dict[str, Any]] = []
        try:
            vector_rows = backend.search(
                query, filters=self._read_filters(), top_k=fetch, rerank=rerank
            ) or []
        except Exception as e:
            logger.debug("Mem0 vector search failed: %s", e)
        keyword_rows = self._keyword_recall(query, limit=fetch)
        if not keyword_rows:
            return list(vector_rows[:top_k])
        from ._hybrid import rrf_fuse_rows

        fused = rrf_fuse_rows([vector_rows, keyword_rows], key="id")
        return fused[:top_k]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if self._backend is None:
            err = getattr(self, "_init_error", "unknown error")
            hint = ""
            if self._mode == "oss":
                vs = self._config.get("oss", {}).get("vector_store", {})
                provider = vs.get("provider", "vector store")
                hint = f" Check that {provider} is running and reachable."
            return json.dumps({"error": f"Mem0 backend not initialized: {err}.{hint}"})

        if self._is_breaker_open():
            msg = "Mem0 temporarily unavailable (multiple consecutive failures). Will retry automatically."
            if self._mode == "oss":
                vs = self._config.get("oss", {}).get("vector_store", {})
                msg += f" Check that your {vs.get('provider', 'vector store')} is running."
            return json.dumps({"error": msg})

        if tool_name == "mem0_search":
            query = args.get("query", "")
            if not query:
                return tool_error("Missing required parameter: query")
            try:
                top_k = max(1, min(int(args.get("top_k", 10)), 50))
                rerank_raw = args.get("rerank", getattr(self, "_rerank_default", False))
                if isinstance(rerank_raw, str):
                    rerank = rerank_raw.lower() not in ("false", "0", "no")
                else:
                    rerank = bool(rerank_raw)
                self._ensure_index_fresh()
                results = self._hybrid_search(query, top_k=top_k, rerank=rerank)
                self._record_success()
                if not results:
                    return json.dumps({"result": "No relevant memories found."})
                items = [_provenance_item(r) for r in results]
                return json.dumps({"results": items, "count": len(items)})
            except Exception as e:
                if not _is_client_error(e):
                    self._record_failure()
                return tool_error(self._format_error("Search failed", e))

        elif tool_name == "mem0_add":
            content = args.get("content", "")
            if not content:
                return tool_error("Missing required parameter: content")
            try:
                result = self._backend.add(
                    [{"role": "user", "content": content}],
                    user_id=self._user_id,
                    agent_id=self._agent_id,
                    infer=False,
                    metadata=self._write_metadata(_source_fields(args)),
                )
                self._record_success()
                event_id = result.get("event_id") if isinstance(result, dict) else None
                # Keep the keyword index in step with the store.
                self._index_added_rows(result)
                # Cloud add is async (server-side extraction); OSS and self-hosted store synchronously.
                msg = "Fact stored." if (self._mode == "oss" or self._host) else "Fact queued for storage."
                return json.dumps({"result": msg, "event_id": event_id})
            except Exception as e:
                self._record_failure()
                return tool_error(self._format_error("Failed to store", e))

        elif tool_name == "mem0_update":
            memory_id = args.get("memory_id", "")
            text = args.get("text", "")
            if not memory_id:
                return tool_error("Missing required parameter: memory_id")
            if not text:
                return tool_error("Missing required parameter: text")
            try:
                result = self._backend.update(memory_id, text)
                self._record_success()
                # The store now holds the new text — keep the keyword index
                # in step (the old wording must stop matching).
                self._index_memory(memory_id, text)
                return json.dumps(result)
            except Exception as e:
                if _is_client_error(e):
                    return tool_error(f"Memory not found: {memory_id}")
                self._record_failure()
                return tool_error(self._format_error("Update failed", e))

        elif tool_name == "mem0_delete":
            memory_id = args.get("memory_id", "")
            if not memory_id:
                return tool_error("Missing required parameter: memory_id")
            try:
                result = self._backend.delete(memory_id)
                self._record_success()
                self._unindex_memory(memory_id)
                return json.dumps(result)
            except Exception as e:
                if _is_client_error(e):
                    return tool_error(f"Memory not found: {memory_id}")
                self._record_failure()
                return tool_error(self._format_error("Delete failed", e))

        return tool_error(f"Unknown tool: {tool_name}")

    def _shutdown_backend(self):
        try:
            if self._backend:
                self._backend.close()
                self._backend = None
        except Exception:
            pass

    def shutdown(self) -> None:
        for t in (self._prefetch_thread, self._sync_thread, self._write_thread):
            if t and t.is_alive():
                t.join(timeout=5.0)
        index = self._keyword_index
        if index is not None:
            try:
                index.close()
            except Exception:
                pass
            self._keyword_index = None
        self._shutdown_backend()


def register(ctx) -> None:
    """Register Mem0 as a memory provider plugin."""
    ctx.register_memory_provider(Mem0MemoryProvider())

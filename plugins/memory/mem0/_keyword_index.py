"""Keyword sidecar index over the Mem0 memory corpus (SQLite FTS5 + BM25).

Why a sidecar index at all: vector recall finds *semantically* similar
memories, but it is blind to literal tokens. A material grade (``NCM811``),
a model number, an abbreviation (``SSE``), a user's nickname — these are the
queries where an embedding drifts and the exact match wins. A keyword index
covers exactly that gap, and the two recallers are then fused with RRF so
neither has to win on its own.

Two FTS5 tables over the same rows:

* ``memory_fts`` — the default ``unicode61`` tokenizer. Good for Latin runs
  and digits; it splits Chinese into single characters, so a CJK phrase
  query degenerates into "any of these characters" and matches everything.
* ``memory_fts_cjk`` — the ``trigram`` tokenizer, which indexes overlapping
  3-character sequences and therefore matches CJK *phrases* exactly. It
  needs at least 3 characters per token; shorter CJK terms fall back to a
  LIKE substring scan.

The index is a **cache, never the source of truth** — the vector store owns
the memories. If FTS5 is unavailable, the trigram tokenizer is missing, or
the file cannot be opened, every caller silently degrades to pure vector
recall: recall quality drops, correctness does not.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from typing import List, Optional, Sequence, Tuple

from ._hybrid import rrf_fuse_ids

# CJK ideographs + kana + hangul, as maximal runs.
_CJK_RUN_RE = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]+"
)
# Latin words / numbers / identifiers.
_LATIN_RUN_RE = re.compile(r"[A-Za-z0-9_]+")

# A quoted phrase in the raw query — kept verbatim as one FTS5 phrase.
_QUOTED_RE = re.compile(r'"([^"]{1,120})"')

_MAX_TERMS = 16
_TRIGRAM_MIN_CHARS = 3
_MAX_QUERY_CHARS = 512

# Bumped whenever the on-disk schema changes. The index is a cache, so a
# mismatch simply means "drop it and let the provider rebuild from the
# vector store" — no data is lost, because the store owns the memories.
_SCHEMA_VERSION = 2


def default_index_path() -> str:
    """Where the sidecar index lives (``$MATLENS_HOME/mem0_index.sqlite3``)."""
    home = os.environ.get("MATLENS_HOME") or os.path.expanduser("~/.matlens")
    return os.path.join(home, "mem0_index.sqlite3")


def _phrase(term: str) -> str:
    """Quote a term for FTS5, escaping embedded quotes.

    Quoting every term is what makes this safe: FTS5 gives a quoted string
    phrase semantics, so operators inside user text (``AND``, ``*``, ``:``,
    unbalanced quotes) can never reach the query grammar.
    """
    return '"' + term.replace('"', '""') + '"'


def split_query_terms(query: str) -> Tuple[List[str], List[str]]:
    """Split a query into ``(latin_terms, cjk_runs)``.

    Quoted phrases in the raw query are kept whole (a quoted CJK phrase is
    one CJK run, a quoted Latin phrase one Latin term).
    """
    query = (query or "")[:_MAX_QUERY_CHARS]
    latin: List[str] = []
    cjk: List[str] = []
    for match in _QUOTED_RE.finditer(query):
        chunk = match.group(1)
        for run in _CJK_RUN_RE.findall(chunk):
            if run not in cjk:
                cjk.append(run)
        for run in _LATIN_RUN_RE.findall(chunk):
            if run not in latin:
                latin.append(run)
    rest = _QUOTED_RE.sub(" ", query)
    for run in _CJK_RUN_RE.findall(rest):
        if run not in cjk:
            cjk.append(run)
    for run in _LATIN_RUN_RE.findall(rest):
        if run not in latin:
            latin.append(run)
    return latin[:_MAX_TERMS], cjk[:_MAX_TERMS]


class MemoryKeywordIndex:
    """SQLite FTS5 index over memory texts, scoped per principal."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or default_index_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._cjk_enabled = False
        self._available = False

    # -- lifecycle -------------------------------------------------------
    @property
    def available(self) -> bool:
        """True when the index is open and usable."""
        return self._available

    def open(self) -> bool:
        """Open (and create) the index. Returns False when it cannot be used.

        Never raises: a missing index must not break recall, it must only
        remove the keyword half of the hybrid search.
        """
        with self._lock:
            if self._available:
                return True
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._apply_schema(conn)
                # The trigram tokenizer is optional: its absence only means
                # CJK phrases fall back to a LIKE scan.
                try:
                    conn.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_cjk"
                        " USING fts5(mid UNINDEXED, user_id UNINDEXED, text,"
                        " tokenize='trigram')"
                    )
                    self._cjk_enabled = True
                except sqlite3.Error:
                    self._cjk_enabled = False
                conn.commit()
                self._conn = conn
                self._available = True
                return True
            except Exception:
                self._conn = None
                self._available = False
                return False

    @staticmethod
    def _apply_schema(conn: sqlite3.Connection) -> None:
        """Create or migrate the schema.

        ``user_id`` is ``UNINDEXED`` on purpose: it scopes the search but is
        not searchable content. As an ordinary indexed column it would be
        tokenized like the memory text, so a query term that happens to
        appear in a principal's id ("user", "matlens") would match *every*
        one of their rows regardless of its text.

        The schema version lives in ``PRAGMA user_version``. A mismatch drops
        the cached tables — the index is only a cache, and the provider
        rebuilds it from the vector store.
        """
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except Exception:
            version = 0
        if version and version != _SCHEMA_VERSION:
            for table in ("memory_fts", "memory_fts_cjk", "memory_meta"):
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                except sqlite3.Error:
                    pass
            version = 0

        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_meta ("
            " id TEXT PRIMARY KEY,"
            " user_id TEXT,"
            " text TEXT,"
            " updated_at TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts"
            " USING fts5(mid UNINDEXED, user_id UNINDEXED, text)"
        )
        try:
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        except sqlite3.Error:
            pass

    def close(self) -> None:
        with self._lock:
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._available = False

    # -- writes ----------------------------------------------------------
    def upsert(
        self,
        memory_id: str,
        text: str,
        *,
        user_id: str = "",
        updated_at: str = "",
    ) -> bool:
        """Insert or replace one memory's text. Returns True on success."""
        if not memory_id:
            return False
        if not self._available:
            return False
        text = text or ""
        with self._lock:
            conn = self._conn
            if conn is None:
                return False
            try:
                conn.execute("DELETE FROM memory_fts WHERE mid = ?", (memory_id,))
                if self._cjk_enabled:
                    conn.execute(
                        "DELETE FROM memory_fts_cjk WHERE mid = ?", (memory_id,)
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO memory_meta(id, user_id, text, updated_at)"
                    " VALUES(?,?,?,?)",
                    (memory_id, user_id, text, updated_at or ""),
                )
                conn.execute(
                    "INSERT INTO memory_fts(mid, user_id, text) VALUES(?,?,?)",
                    (memory_id, user_id, text),
                )
                if self._cjk_enabled:
                    conn.execute(
                        "INSERT INTO memory_fts_cjk(mid, user_id, text) VALUES(?,?,?)",
                        (memory_id, user_id, text),
                    )
                conn.commit()
                return True
            except Exception:
                return False

    def delete(self, memory_id: str) -> bool:
        """Drop one memory from the index."""
        if not memory_id:
            return False
        if not self._available:
            return False
        with self._lock:
            conn = self._conn
            if conn is None:
                return False
            try:
                conn.execute("DELETE FROM memory_fts WHERE mid = ?", (memory_id,))
                if self._cjk_enabled:
                    conn.execute(
                        "DELETE FROM memory_fts_cjk WHERE mid = ?", (memory_id,)
                    )
                conn.execute("DELETE FROM memory_meta WHERE id = ?", (memory_id,))
                conn.commit()
                return True
            except Exception:
                return False

    def clear(self) -> bool:
        """Empty the index (used before a full rebuild)."""
        if not self._available:
            return False
        with self._lock:
            conn = self._conn
            if conn is None:
                return False
            try:
                conn.execute("DELETE FROM memory_fts")
                if self._cjk_enabled:
                    conn.execute("DELETE FROM memory_fts_cjk")
                conn.execute("DELETE FROM memory_meta")
                conn.commit()
                return True
            except Exception:
                return False

    def count(self) -> int:
        """Number of indexed memories."""
        if not self._available:
            return 0
        with self._lock:
            conn = self._conn
            if conn is None:
                return 0
            try:
                row = conn.execute("SELECT COUNT(*) FROM memory_meta").fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

    # -- reads -----------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        user_id: str = "",
        limit: int = 20,
    ) -> List[Tuple[str, float]]:
        """Rank indexed memories against ``query``.

        Returns ``[(memory_id, score)]`` best-first. The score is the fused
        RRF score across the tables that matched, so it is only meaningful
        *relative to the other results of this same call*.
        """
        if not self._available:
            return []
        latin, cjk = split_query_terms(query)
        if not latin and not cjk:
            return []
        limit = max(1, int(limit))

        rankings: List[List[str]] = []
        with self._lock:
            conn = self._conn
            if conn is None:
                return []
            if latin:
                ranked = self._match(conn, "memory_fts", latin, user_id, limit)
                if ranked:
                    rankings.append(ranked)
            if cjk:
                if self._cjk_enabled and all(len(run) >= _TRIGRAM_MIN_CHARS for run in cjk):
                    ranked = self._match(conn, "memory_fts_cjk", cjk, user_id, limit)
                else:
                    # The trigram tokenizer needs 3+ characters per token;
                    # shorter CJK terms go through a LIKE substring scan.
                    ranked = self._like_scan(conn, cjk, user_id, limit)
                if ranked:
                    rankings.append(ranked)

        if not rankings:
            return []
        return rrf_fuse_ids(rankings)[:limit]

    @staticmethod
    def _match(
        conn: sqlite3.Connection,
        table: str,
        terms: Sequence[str],
        user_id: str,
        limit: int,
    ) -> List[str]:
        """Run one FTS5 phrase query and return the matching ids, best first."""
        match_expr = " AND ".join(_phrase(term) for term in terms)
        try:
            if user_id:
                cursor = conn.execute(
                    f"SELECT mid FROM {table} WHERE {table} MATCH ? AND user_id = ?"
                    " ORDER BY rank LIMIT ?",
                    (match_expr, user_id, limit),
                )
            else:
                cursor = conn.execute(
                    f"SELECT mid FROM {table} WHERE {table} MATCH ? ORDER BY rank LIMIT ?",
                    (match_expr, limit),
                )
            return [row[0] for row in cursor.fetchall() if row and row[0]]
        except sqlite3.Error:
            return []

    @staticmethod
    def _like_scan(
        conn: sqlite3.Connection,
        cjk_runs: Sequence[str],
        user_id: str,
        limit: int,
    ) -> List[str]:
        """Substring fallback for short CJK terms (no FTS5 ranking available).

        Ranked by recency, which is the only signal left once BM25 is out.
        """
        out: List[str] = []
        seen = set()
        for run in cjk_runs:
            pattern = f"%{run}%"
            try:
                if user_id:
                    cursor = conn.execute(
                        "SELECT id FROM memory_meta WHERE user_id = ? AND text LIKE ?"
                        " ORDER BY updated_at DESC LIMIT ?",
                        (user_id, pattern, limit),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT id FROM memory_meta WHERE text LIKE ?"
                        " ORDER BY updated_at DESC LIMIT ?",
                        (pattern, limit),
                    )
            except sqlite3.Error:
                continue
            for row in cursor.fetchall():
                if row and row[0] and row[0] not in seen:
                    seen.add(row[0])
                    out.append(row[0])
        return out[:limit]

# ruff: noqa: E501
"""Layered persistent memory for LifeOS.

Layers
------
identity     rules and preferences about how JARVIS behaves
personal     facts the user gave about themselves (goals, routine, limits)
episodic     relevant events: decisions taken, problems, solutions
operational  current state worth recalling (not tasks themselves: those live
             in the planner tables)
knowledge    notes, research findings, references

Guarantees
----------
* Deduplication: the same normalized text is stored once per layer.
* History: corrections create a new version and mark the old one superseded;
  nothing is overwritten in place.
* Contradiction guard: records may carry a ``subject`` key (for example
  ``user.wake_time``). Adding different content for an active subject raises
  :class:`MemoryConflict` unless the caller explicitly asks to replace it.
* Facts vs hypotheses: every record has ``status`` confirmed or hypothesis.
* Full deletion: :meth:`MemoryStore.forget` removes a record and its history.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable, List, Optional, Sequence

from openjarvis.lifeos.db import LifeOSDB, utc_now

logger = logging.getLogger(__name__)

LAYERS = ("identity", "personal", "episodic", "operational", "knowledge")
STATUSES = ("confirmed", "hypothesis")
MAX_CONTENT_CHARS = 4000
_SEMANTIC_SCAN_LIMIT = 5000
_RRF_K = 60


class LifeOSMemoryError(ValueError):
    """Invalid memory operation (bad layer, empty content, unknown id)."""


class MemoryConflict(Exception):
    """New content contradicts an active record with the same subject."""

    def __init__(self, existing: "MemoryRecord", new_content: str) -> None:
        self.existing = existing
        self.new_content = new_content
        super().__init__(
            f"Conflito com memória #{existing.id} (assunto '{existing.subject}'): "
            f"registrado '{existing.content}', novo '{new_content}'. "
            "Use replace=true para substituir ou corrija o registro existente."
        )


@dataclass(slots=True)
class MemoryRecord:
    id: int
    layer: str
    content: str
    subject: str
    status: str
    source: str
    tags: str
    created_at: str
    updated_at: str
    superseded_by: Optional[int]
    active: bool
    score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace/punctuation."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _row_to_record(row: Any, score: Optional[float] = None) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        layer=row["layer"],
        content=row["content"],
        subject=row["subject"],
        status=row["status"],
        source=row["source"],
        tags=row["tags"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        superseded_by=row["superseded_by"],
        active=bool(row["active"]),
        score=score,
    )


def _fts_query(text: str) -> str:
    tokens = [t for t in re.findall(r"\w+", text, flags=re.UNICODE) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in tokens[:32])


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryStore:
    """CRUD + hybrid search over the ``memories`` table."""

    def __init__(self, db: LifeOSDB, embedder: Any = None) -> None:
        self._db = db
        self._embedder = embedder

    # -- validation ---------------------------------------------------------

    @staticmethod
    def _check_layer(layer: str) -> str:
        layer = (layer or "").strip().lower()
        if layer not in LAYERS:
            raise LifeOSMemoryError(
                f"Camada inválida '{layer}'. Use: {', '.join(LAYERS)}"
            )
        return layer

    @staticmethod
    def _check_status(status: str) -> str:
        status = (status or "confirmed").strip().lower()
        if status not in STATUSES:
            raise LifeOSMemoryError("status deve ser 'confirmed' ou 'hypothesis'")
        return status

    @staticmethod
    def _check_content(content: str) -> str:
        content = (content or "").strip()
        if not content:
            raise LifeOSMemoryError("Conteúdo vazio não pode ser memorizado")
        if len(content) > MAX_CONTENT_CHARS:
            raise LifeOSMemoryError(
                f"Conteúdo excede {MAX_CONTENT_CHARS} caracteres; "
                "use a camada knowledge com um resumo"
            )
        return content

    @staticmethod
    def _tags(tags: Iterable[str] | str | None) -> str:
        if tags is None:
            return ""
        if isinstance(tags, str):
            tags = tags.split(",")
        return ",".join(sorted({t.strip().lower() for t in tags if t and t.strip()}))

    def _embed(self, text: str) -> Optional[str]:
        if self._embedder is None:
            return None
        try:
            vectors = self._embedder.embed([text])
            vector = [float(x) for x in list(vectors[0])]
            return json.dumps(vector)
        except Exception as exc:  # embedding is best-effort, text search remains
            logger.warning("LifeOS embedding failed: %s", exc)
            return None

    # -- reads --------------------------------------------------------------

    def get(self, memory_id: int) -> MemoryRecord:
        row = self._db.query_one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            raise LifeOSMemoryError(f"Memória #{memory_id} não encontrada")
        return _row_to_record(row)

    def list(
        self,
        layer: Optional[str] = None,
        *,
        status: Optional[str] = None,
        include_inactive: bool = False,
        limit: int = 100,
    ) -> List[MemoryRecord]:
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []
        if layer:
            sql += " AND layer = ?"
            params.append(self._check_layer(layer))
        if status:
            sql += " AND status = ?"
            params.append(self._check_status(status))
        if not include_inactive:
            sql += " AND active = 1"
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [_row_to_record(r) for r in self._db.query(sql, params)]

    def history(self, memory_id: int) -> List[MemoryRecord]:
        """Return all versions leading to (and including) ``memory_id``."""
        chain = [self.get(memory_id)]
        seen = {memory_id}
        frontier = [memory_id]
        while frontier:
            current = frontier.pop()
            for row in self._db.query(
                "SELECT * FROM memories WHERE superseded_by = ?", (current,)
            ):
                if row["id"] not in seen:
                    seen.add(row["id"])
                    chain.append(_row_to_record(row))
                    frontier.append(row["id"])
        return sorted(chain, key=lambda r: r.id)

    def stats(self) -> dict[str, Any]:
        rows = self._db.query(
            "SELECT layer, status, COUNT(*) AS n FROM memories "
            "WHERE active = 1 GROUP BY layer, status"
        )
        out: dict[str, Any] = {
            layer: {"confirmed": 0, "hypothesis": 0} for layer in LAYERS
        }
        for r in rows:
            out[r["layer"]][r["status"]] = r["n"]
        out["total"] = sum(
            v["confirmed"] + v["hypothesis"] for k, v in out.items() if k in LAYERS
        )
        return out

    # -- writes -------------------------------------------------------------

    def remember(
        self,
        content: str,
        *,
        layer: str = "personal",
        subject: str = "",
        status: str = "confirmed",
        source: str = "user",
        tags: Iterable[str] | str | None = None,
        replace: bool = False,
    ) -> tuple[MemoryRecord, bool]:
        """Store a memory. Returns ``(record, created)``.

        ``created`` is ``False`` when an identical active memory already
        existed (it may have been promoted from hypothesis to confirmed).
        """
        content = self._check_content(content)
        layer = self._check_layer(layer)
        status = self._check_status(status)
        subject = (subject or "").strip().lower()
        tag_str = self._tags(tags)
        digest = content_hash(content)
        now = utc_now()

        with self._db.transaction() as conn:
            dup = conn.execute(
                "SELECT * FROM memories WHERE content_hash = ? AND layer = ? AND active = 1",
                (digest, layer),
            ).fetchone()
            if dup is not None:
                if dup["status"] == "hypothesis" and status == "confirmed":
                    conn.execute(
                        "UPDATE memories SET status = 'confirmed', updated_at = ? WHERE id = ?",
                        (now, dup["id"]),
                    )
                dup = conn.execute(
                    "SELECT * FROM memories WHERE id = ?", (dup["id"],)
                ).fetchone()
                return _row_to_record(dup), False

            previous = None
            if subject:
                previous = conn.execute(
                    "SELECT * FROM memories WHERE subject = ? AND layer = ? AND active = 1 "
                    "ORDER BY id DESC LIMIT 1",
                    (subject, layer),
                ).fetchone()
                if previous is not None and not replace:
                    raise MemoryConflict(_row_to_record(previous), content)

            embedding = self._embed(content)
            cur = conn.execute(
                "INSERT INTO memories(layer, content, subject, status, source, tags, "
                "content_hash, embedding, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    layer,
                    content,
                    subject,
                    status,
                    source,
                    tag_str,
                    digest,
                    embedding,
                    now,
                    now,
                ),
            )
            new_id = cur.lastrowid
            if previous is not None:
                conn.execute(
                    "UPDATE memories SET active = 0, superseded_by = ?, updated_at = ? "
                    "WHERE id = ?",
                    (new_id, now, previous["id"]),
                )
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (new_id,)
            ).fetchone()
        return _row_to_record(row), True

    def correct(
        self,
        memory_id: int,
        *,
        content: Optional[str] = None,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        tags: Iterable[str] | str | None = None,
        source: str = "user_correction",
    ) -> MemoryRecord:
        """Create a corrected version of an active memory, keeping history."""
        old = self.get(memory_id)
        if not old.active:
            raise LifeOSMemoryError(
                f"Memória #{memory_id} já foi substituída por #{old.superseded_by}"
            )
        new_content = (
            self._check_content(content) if content is not None else old.content
        )
        new_status = self._check_status(status) if status is not None else old.status
        new_subject = subject.strip().lower() if subject is not None else old.subject
        new_tags = self._tags(tags) if tags is not None else old.tags
        if (
            new_content == old.content
            and new_status == old.status
            and new_subject == old.subject
            and new_tags == old.tags
        ):
            return old
        now = utc_now()
        digest = content_hash(new_content)
        embedding = self._embed(new_content) if new_content != old.content else None
        with self._db.transaction() as conn:
            if embedding is None and new_content == old.content:
                prev = conn.execute(
                    "SELECT embedding FROM memories WHERE id = ?", (memory_id,)
                ).fetchone()
                embedding = prev["embedding"] if prev else None
            cur = conn.execute(
                "INSERT INTO memories(layer, content, subject, status, source, tags, "
                "content_hash, embedding, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    old.layer,
                    new_content,
                    new_subject,
                    new_status,
                    source,
                    new_tags,
                    digest,
                    embedding,
                    old.created_at,
                    now,
                ),
            )
            new_id = cur.lastrowid
            conn.execute(
                "UPDATE memories SET active = 0, superseded_by = ?, updated_at = ? WHERE id = ?",
                (new_id, now, memory_id),
            )
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (new_id,)
            ).fetchone()
        return _row_to_record(row)

    def forget(self, memory_id: int) -> int:
        """Permanently delete a memory and every earlier version of it."""
        ids = [r.id for r in self.history(memory_id)]
        with self._db.transaction() as conn:
            conn.executemany(
                "UPDATE memories SET superseded_by = NULL WHERE superseded_by = ?",
                [(i,) for i in ids],
            )
            conn.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])
        return len(ids)

    def forget_all(self) -> int:
        with self._db.transaction() as conn:
            n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.execute("UPDATE memories SET superseded_by = NULL")
            conn.execute("DELETE FROM memories")
        return int(n)

    # -- search -------------------------------------------------------------

    def _text_search(
        self, query: str, layers: Sequence[str], limit: int, include_hypotheses: bool
    ) -> List[MemoryRecord]:
        filters = " AND m.active = 1"
        params: list[Any] = []
        if layers:
            filters += f" AND m.layer IN ({','.join('?' * len(layers))})"
            params.extend(layers)
        if not include_hypotheses:
            filters += " AND m.status = 'confirmed'"

        if self._db.has_fts:
            match = _fts_query(query)
            if not match:
                return []
            rows = self._db.query(
                "SELECT m.*, bm25(memories_fts) AS rank FROM memories_fts "
                "JOIN memories m ON m.id = memories_fts.rowid "
                f"WHERE memories_fts MATCH ?{filters} ORDER BY rank LIMIT ?",
                [match, *params, limit],
            )
            return [_row_to_record(r, score=-float(r["rank"])) for r in rows]

        tokens = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1][:8]
        if not tokens:
            return []
        like = " OR ".join("LOWER(m.content) LIKE ?" for _ in tokens)
        rows = self._db.query(
            f"SELECT m.* FROM memories m WHERE ({like}){filters} "
            "ORDER BY m.updated_at DESC LIMIT ?",
            [*(f"%{t}%" for t in tokens), *params, limit],
        )
        return [_row_to_record(r, score=0.0) for r in rows]

    def _semantic_search(
        self, query: str, layers: Sequence[str], limit: int, include_hypotheses: bool
    ) -> List[MemoryRecord]:
        if self._embedder is None:
            return []
        q = self._embed(query)
        if q is None:
            return []
        qvec = json.loads(q)
        sql = "SELECT * FROM memories WHERE active = 1 AND embedding IS NOT NULL"
        params: list[Any] = []
        if layers:
            sql += f" AND layer IN ({','.join('?' * len(layers))})"
            params.extend(layers)
        if not include_hypotheses:
            sql += " AND status = 'confirmed'"
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(_SEMANTIC_SCAN_LIMIT)
        scored = []
        for row in self._db.query(sql, params):
            try:
                sim = _cosine(qvec, json.loads(row["embedding"]))
            except (TypeError, ValueError):
                continue
            scored.append(_row_to_record(row, score=sim))
        scored.sort(key=lambda r: r.score or 0.0, reverse=True)
        return scored[:limit]

    def search(
        self,
        query: str,
        *,
        layers: Optional[Sequence[str]] = None,
        limit: int = 10,
        include_hypotheses: bool = True,
    ) -> List[MemoryRecord]:
        """Hybrid search: FTS5/BM25 plus optional embeddings, fused with RRF."""
        query = (query or "").strip()
        if not query or limit <= 0:
            return []
        layer_list = [self._check_layer(layer) for layer in (layers or [])]
        pool = max(limit * 3, 20)
        text_hits = self._text_search(query, layer_list, pool, include_hypotheses)
        sem_hits = self._semantic_search(query, layer_list, pool, include_hypotheses)
        if not sem_hits:
            return text_hits[:limit]
        fused: dict[int, float] = {}
        records: dict[int, MemoryRecord] = {}
        for hits in (text_hits, sem_hits):
            for rank, rec in enumerate(hits):
                fused[rec.id] = fused.get(rec.id, 0.0) + 1.0 / (_RRF_K + rank + 1)
                records.setdefault(rec.id, rec)
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        out = []
        for mem_id, score in ordered:
            rec = records[mem_id]
            rec.score = score
            out.append(rec)
        return out

    def reindex_embeddings(self) -> int:
        """Compute embeddings for active memories that do not have one."""
        if self._embedder is None:
            return 0
        rows = self._db.query(
            "SELECT id, content FROM memories WHERE active = 1 AND embedding IS NULL"
        )
        done = 0
        for row in rows:
            emb = self._embed(row["content"])
            if emb is None:
                break
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE memories SET embedding = ? WHERE id = ?", (emb, row["id"])
                )
            done += 1
        return done

    def context_block(self, query: str, *, limit: int = 8) -> str:
        """Format relevant memories for injection into a system prompt."""
        if limit <= 0:
            return ""
        hits = [r for r in self.search(query, limit=limit) if r.layer != "identity"]
        if not hits:
            return ""
        lines = []
        for r in hits:
            tag = "confirmado" if r.status == "confirmed" else "hipótese"
            lines.append(
                f"- #{r.id} [{r.layer}|{tag}] {r.content} ({r.updated_at[:10]})"
            )
        return "\n".join(lines)

    def export(self) -> List[dict[str, Any]]:
        rows = self._db.query("SELECT * FROM memories ORDER BY id")
        return [_row_to_record(r).to_dict() for r in rows]


__all__ = [
    "LAYERS",
    "MemoryConflict",
    "LifeOSMemoryError",
    "MemoryRecord",
    "MemoryStore",
    "content_hash",
    "normalize_text",
]

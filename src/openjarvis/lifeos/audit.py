# ruff: noqa: E501
"""Append-only action log with a SHA-256 hash chain.

Every policy decision and every tool execution performed under LifeOS is
recorded with its category, risk, autonomy level, parameters and result.
Each row stores the hash of the previous row, so editing or deleting a past
entry is detectable with :meth:`ActionLog.verify`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.lifeos.db import LifeOSDB, utc_now

GENESIS_HASH = "0" * 64
_MAX_FIELD_CHARS = 4000


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_FIELD_CHARS else text[:_MAX_FIELD_CHARS] + "…"


def _digest(prev_hash: str, fields: Dict[str, Any]) -> str:
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


_HASHED_FIELDS = (
    "ts",
    "actor",
    "action",
    "category",
    "risk",
    "autonomy_level",
    "decision",
    "params_json",
    "result",
    "success",
)


class ActionLog:
    def __init__(self, db: LifeOSDB) -> None:
        self._db = db

    def record(
        self,
        *,
        actor: str,
        action: str,
        category: str,
        risk: str,
        autonomy_level: int,
        decision: str,
        params: Optional[Dict[str, Any]] = None,
        result: str = "",
        success: Optional[bool] = None,
    ) -> int:
        fields = {
            "ts": utc_now(),
            "actor": actor,
            "action": action,
            "category": category,
            "risk": risk,
            "autonomy_level": int(autonomy_level),
            "decision": decision,
            "params_json": _clip(
                json.dumps(params or {}, ensure_ascii=False, default=str)
            ),
            "result": _clip(str(result or "")),
            "success": None if success is None else int(bool(success)),
        }
        with self._db.transaction() as conn:
            last = conn.execute(
                "SELECT hash FROM action_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev = last["hash"] if last else GENESIS_HASH
            digest = _digest(prev, fields)
            cur = conn.execute(
                "INSERT INTO action_log(ts, actor, action, category, risk, autonomy_level, "
                "decision, params_json, result, success, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*[fields[k] for k in _HASHED_FIELDS], prev, digest),
            )
            return int(cur.lastrowid)

    def list(
        self, *, limit: int = 50, decision: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM action_log"
        params: list[Any] = []
        if decision:
            sql += " WHERE decision = ?"
            params.append(decision)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(r) for r in self._db.query(sql, params)]

    def verify(self) -> Tuple[bool, Optional[int]]:
        """Return ``(True, None)`` if intact, else ``(False, first_bad_id)``."""
        prev = GENESIS_HASH
        for row in self._db.query("SELECT * FROM action_log ORDER BY id"):
            fields = {k: row[k] for k in _HASHED_FIELDS}
            if row["prev_hash"] != prev or _digest(prev, fields) != row["hash"]:
                return False, int(row["id"])
            prev = row["hash"]
        return True, None

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) FROM action_log")
        return int(row[0]) if row else 0


__all__ = ["ActionLog", "GENESIS_HASH"]

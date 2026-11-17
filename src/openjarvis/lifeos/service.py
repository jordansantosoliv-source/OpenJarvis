# ruff: noqa: E501
"""LifeOS facade: one object that owns storage, memory, planner, reviews,
autonomy policy, approvals and the audit log."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.lifeos.audit import ActionLog
from openjarvis.lifeos.autonomy import (
    CATEGORIES,
    AutonomyLevel,
    PolicyDecision,
    Verdict,
    call_fingerprint,
    category_of,
    classify_tool_call,
    decide,
    describe_policy,
    parse_level,
)
from openjarvis.lifeos.config import LifeOSConfig, get_lifeos_dir, load_lifeos_config
from openjarvis.lifeos.db import LifeOSDB, utc_now
from openjarvis.lifeos.memory import MemoryStore
from openjarvis.lifeos.persona import ensure_persona_file, load_persona
from openjarvis.lifeos.planner import Planner
from openjarvis.lifeos.reviews import ReviewEngine

logger = logging.getLogger(__name__)

DEFAULT_GRANTS = ("report",)


class LifeOSError(RuntimeError):
    """Operation refused or impossible (unknown id, forbidden grant, ...)."""


def _build_embedder(cfg: LifeOSConfig) -> Any:
    if not cfg.semantic.enabled:
        return None
    if cfg.semantic.provider != "ollama":
        logger.warning(
            "LifeOS: unsupported embedding provider %r", cfg.semantic.provider
        )
        return None
    try:
        from openjarvis.tools.storage.embeddings import OllamaEmbedder

        return OllamaEmbedder(model=cfg.semantic.model, base_url=cfg.semantic.base_url)
    except Exception as exc:
        logger.warning("LifeOS: embedder unavailable: %s", exc)
        return None


class LifeOS:
    """Entry point for every LifeOS capability."""

    def __init__(
        self,
        config: Optional[LifeOSConfig] = None,
        *,
        embedder: Any = None,
    ) -> None:
        self.config = config or load_lifeos_config()
        self.db = LifeOSDB(self.config.resolved_db_path())
        self.memory = MemoryStore(
            self.db, embedder if embedder is not None else _build_embedder(self.config)
        )
        self.planner = Planner(self.db)
        self.reviews = ReviewEngine(self.db, self.planner, self.config.review)
        self.actions = ActionLog(self.db)
        self.persona_path = ensure_persona_file(self.config.resolved_persona_path())
        if self.db.get_meta("initialized_at") is None:
            self.db.set_meta("initialized_at", utc_now())
            for category in DEFAULT_GRANTS:
                self._insert_grant(category, "padrão")

    # -- autonomy -----------------------------------------------------------

    @property
    def autonomy_level(self) -> AutonomyLevel:
        stored = self.db.get_meta("autonomy_level")
        return parse_level(stored if stored is not None else self.config.autonomy_level)

    def set_autonomy_level(self, level: int, *, actor: str = "user") -> AutonomyLevel:
        new = parse_level(level)
        old = self.autonomy_level
        self.db.set_meta("autonomy_level", int(new))
        self.actions.record(
            actor=actor,
            action="set_autonomy_level",
            category="config_change",
            risk="high",
            autonomy_level=int(new),
            decision="executed",
            params={"from": int(old), "to": int(new)},
            result="ok",
            success=True,
        )
        return new

    def grants(self) -> List[str]:
        return [
            r["category"]
            for r in self.db.query("SELECT category FROM grants ORDER BY category")
        ]

    def _insert_grant(self, category: str, note: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO grants(category, granted_at, note) VALUES (?, ?, ?) "
                "ON CONFLICT(category) DO UPDATE SET note = excluded.note",
                (category, utc_now(), note),
            )

    def grant(self, category: str, *, note: str = "", actor: str = "user") -> None:
        if category not in CATEGORIES:
            raise LifeOSError(f"categoria desconhecida '{category}'")
        cat = CATEGORIES[category]
        if not cat.grantable:
            raise LifeOSError(
                f"'{category}' tem risco {cat.risk.value} e não pode ser pré-autorizada"
            )
        self._insert_grant(category, note)
        self.actions.record(
            actor=actor,
            action="grant",
            category="config_change",
            risk="high",
            autonomy_level=int(self.autonomy_level),
            decision="executed",
            params={"category": category, "note": note},
            result="ok",
            success=True,
        )

    def revoke(self, category: str, *, actor: str = "user") -> bool:
        with self.db.transaction() as conn:
            removed = conn.execute(
                "DELETE FROM grants WHERE category = ?", (category,)
            ).rowcount
        self.actions.record(
            actor=actor,
            action="revoke",
            category="config_change",
            risk="high",
            autonomy_level=int(self.autonomy_level),
            decision="executed",
            params={"category": category},
            result="removed" if removed else "absent",
            success=True,
        )
        return bool(removed)

    def policy_summary(self) -> str:
        return describe_policy(self.autonomy_level, self.grants())

    def authorize(
        self, tool: Any, tool_name: str, arguments: Dict[str, Any]
    ) -> PolicyDecision:
        """Apply the policy; a previously approved identical call passes once."""
        category = classify_tool_call(tool, tool_name, arguments)
        decision = decide(category, self.autonomy_level, self.grants())
        if decision.verdict is Verdict.ASK:
            fingerprint = call_fingerprint(tool_name, arguments)
            with self.db.transaction() as conn:
                row = conn.execute(
                    "SELECT id FROM pending_actions WHERE fingerprint = ? AND status = 'approved' "
                    "ORDER BY decided_at LIMIT 1",
                    (fingerprint,),
                ).fetchone()
                if row is not None:
                    conn.execute(
                        "UPDATE pending_actions SET status = 'used' WHERE id = ?",
                        (row["id"],),
                    )
                    return PolicyDecision(
                        Verdict.ALLOW,
                        category,
                        decision.level,
                        f"aprovado pelo usuário (pendência {row['id']})",
                    )
        return decision

    # -- approvals ----------------------------------------------------------

    def queue_pending(
        self, tool_name: str, arguments: Dict[str, Any], decision: PolicyDecision
    ) -> str:
        fingerprint = call_fingerprint(tool_name, arguments)
        existing = self.db.query_one(
            "SELECT id FROM pending_actions WHERE fingerprint = ? AND status = 'pending'",
            (fingerprint,),
        )
        if existing is not None:
            return str(existing["id"])
        action_id = uuid.uuid4().hex[:10]
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO pending_actions(id, created_at, tool, arguments_json, fingerprint, "
                "category, risk, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    utc_now(),
                    tool_name,
                    json.dumps(
                        arguments, ensure_ascii=False, sort_keys=True, default=str
                    ),
                    fingerprint,
                    decision.category.name,
                    decision.category.risk.value,
                    decision.reason,
                ),
            )
        return action_id

    def list_pending(self, status: str = "pending") -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM pending_actions WHERE status = ? ORDER BY created_at",
            (status,),
        )
        out = []
        for r in rows:
            item = dict(r)
            item["arguments"] = json.loads(item.pop("arguments_json"))
            out.append(item)
        return out

    def _get_pending(self, action_id: str) -> Dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
        )
        if row is None:
            raise LifeOSError(f"pendência '{action_id}' não encontrada")
        item = dict(row)
        item["arguments"] = json.loads(item.pop("arguments_json"))
        return item

    def _set_pending(self, action_id: str, status: str, result: str = "") -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE pending_actions SET status = ?, decided_at = ?, result = ? WHERE id = ?",
                (status, utc_now(), result[:4000], action_id),
            )

    def approve(self, action_id: str, *, actor: str = "user") -> Dict[str, Any]:
        """Approve a pending action.

        LifeOS tools are executed immediately. Other tools receive a one-time
        approval consumed the next time the agent issues the identical call.
        """
        item = self._get_pending(action_id)
        if item["status"] != "pending":
            raise LifeOSError(f"pendência '{action_id}' já está '{item['status']}'")
        level = int(self.autonomy_level)
        if level == AutonomyLevel.CONSULTIVE:
            raise LifeOSError(
                "modo consultivo (nível 1): eleve o nível para executar ações"
            )
        from openjarvis.lifeos.tools import LIFEOS_TOOL_CLASSES

        tool_cls = LIFEOS_TOOL_CLASSES.get(item["tool"])
        if tool_cls is None:
            self._set_pending(action_id, "approved")
            self.actions.record(
                actor=actor,
                action=f"approve:{item['tool']}",
                category=item["category"],
                risk=item["risk"],
                autonomy_level=level,
                decision="approved",
                params=item["arguments"],
                result="aprovação de uso único",
                success=True,
            )
            return {"id": action_id, "status": "approved", "executed": False}

        result = tool_cls(lifeos=self).execute(**item["arguments"])
        status = "executed" if result.success else "failed"
        self._set_pending(action_id, status, result.content)
        self.actions.record(
            actor=actor,
            action=item["tool"],
            category=item["category"],
            risk=item["risk"],
            autonomy_level=level,
            decision="executed_after_approval",
            params=item["arguments"],
            result=result.content,
            success=result.success,
        )
        return {
            "id": action_id,
            "status": status,
            "executed": True,
            "result": result.content,
        }

    def deny(self, action_id: str, *, actor: str = "user") -> Dict[str, Any]:
        item = self._get_pending(action_id)
        if item["status"] != "pending":
            raise LifeOSError(f"pendência '{action_id}' já está '{item['status']}'")
        self._set_pending(action_id, "denied")
        self.actions.record(
            actor=actor,
            action=f"deny:{item['tool']}",
            category=item["category"],
            risk=item["risk"],
            autonomy_level=int(self.autonomy_level),
            decision="denied",
            params=item["arguments"],
            result="negado pelo usuário",
            success=True,
        )
        return {"id": action_id, "status": "denied"}

    # -- persona & prompt ---------------------------------------------------

    def persona_text(self) -> str:
        persona = load_persona(self.persona_path)
        rules = self.memory.list("identity", limit=50)
        if rules:
            persona += "\n\n## Regras definidas pelo usuário\n" + "\n".join(
                f"- {r.content}" for r in reversed(rules)
            )
        if self.config.user_name:
            persona += f"\n\nO usuário se chama {self.config.user_name}."
        return persona

    def operational_snapshot(self) -> str:
        s = self.planner.summary()
        alerts = self.reviews.alerts()[:5]
        lines = [
            f"Metas ativas: {s['goals_active']} | Projetos ativos: {s['projects_active']} | "
            f"Tarefas abertas: {s['tasks_open']} (atrasadas: {s['tasks_overdue']}) | "
            f"Hábitos ativos: {s['habits_active']}"
        ]
        lines.extend(f"- ALERTA: {a.message}" for a in alerts)
        pending = len(self.list_pending())
        if pending:
            lines.append(f"- {pending} ação(ões) aguardando aprovação do usuário.")
        return "\n".join(lines)

    # -- conversations ------------------------------------------------------

    def record_message(self, session_id: str, role: str, content: str) -> None:
        if not content:
            return
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversations(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, utc_now()),
            )

    def conversation(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT role, content, created_at FROM conversations WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, max(1, int(limit))),
        )
        return [dict(r) for r in reversed(rows)]

    def sessions(self, limit: int = 30) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT session_id, MIN(created_at) AS started_at, MAX(created_at) AS last_at, "
            "COUNT(*) AS messages, "
            "(SELECT content FROM conversations c2 WHERE c2.session_id = c.session_id "
            " AND c2.role = 'user' ORDER BY id LIMIT 1) AS first_message "
            "FROM conversations c GROUP BY session_id ORDER BY last_at DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(r) for r in rows]

    # -- data ownership -----------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "db_path": str(self.db.path),
            "persona_path": str(self.persona_path),
            "autonomy_level": int(self.autonomy_level),
            "grants": self.grants(),
            "fts5": self.db.has_fts,
            "semantic_search": self.memory._embedder is not None,
            "memory": self.memory.stats(),
            "planner": self.planner.summary(),
            "pending_actions": len(self.list_pending()),
            "audit_entries": self.actions.count(),
        }

    def export(self) -> Dict[str, Any]:
        data = {
            "exported_at": utc_now(),
            "settings": {
                "autonomy_level": int(self.autonomy_level),
                "grants": self.grants(),
            },
            "persona": load_persona(self.persona_path),
            "memories": self.memory.export(),
            "planner": self.planner.export(),
            "reviews": [
                dict(r) for r in self.db.query("SELECT * FROM reviews ORDER BY id")
            ],
            "conversations": [
                dict(r)
                for r in self.db.query("SELECT * FROM conversations ORDER BY id")
            ],
            "pending_actions": [
                dict(r) for r in self.db.query("SELECT * FROM pending_actions")
            ],
            "action_log": [
                dict(r) for r in self.db.query("SELECT * FROM action_log ORDER BY id")
            ],
        }
        return data

    def export_to(self, path: Path) -> Path:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.export(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def wipe(self, *, keep_audit: bool = True) -> Dict[str, int]:
        """Delete personal data. The audit log is kept unless asked otherwise."""
        tables = [
            "conversations",
            "reviews",
            "habit_logs",
            "tasks",
            "projects",
            "goals",
            "habits",
            "commitments",
            "decisions",
            "pending_actions",
        ]
        counts: Dict[str, int] = {"memories": self.memory.forget_all()}
        with self.db.transaction() as conn:
            for table in tables:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
            if not keep_audit:
                counts["action_log"] = conn.execute(
                    "SELECT COUNT(*) FROM action_log"
                ).fetchone()[0]
                conn.execute("DELETE FROM action_log")
        if keep_audit:
            self.actions.record(
                actor="user",
                action="wipe",
                category="memory_delete",
                risk="high",
                autonomy_level=int(self.autonomy_level),
                decision="executed",
                params={},
                result=json.dumps(counts),
                success=True,
            )
        return counts

    def close(self) -> None:
        self.db.close()


_DEFAULT: Optional[LifeOS] = None
_DEFAULT_LOCK = threading.Lock()


def get_lifeos() -> LifeOS:
    """Process-wide LifeOS bound to the current ``OPENJARVIS_HOME``."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        expected = load_lifeos_config().resolved_db_path()
        if _DEFAULT is None or _DEFAULT.db.path != expected:
            if _DEFAULT is not None:
                _DEFAULT.close()
            _DEFAULT = LifeOS()
        return _DEFAULT


def reset_default_lifeos() -> None:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is not None:
            _DEFAULT.close()
        _DEFAULT = None


__all__ = [
    "DEFAULT_GRANTS",
    "LifeOS",
    "LifeOSError",
    "category_of",
    "get_lifeos",
    "get_lifeos_dir",
    "reset_default_lifeos",
]

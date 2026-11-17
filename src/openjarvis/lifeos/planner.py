# ruff: noqa: E501
"""LifeOS planner: goals, projects, tasks, habits, commitments and decisions.

All entities share one generic CRUD implementation driven by
:data:`ENTITIES`, which declares each table's writable fields and validators.
Entity-specific behavior (completing tasks, logging habits, detecting
conflicting commitments, turning a goal into concrete steps) lives in
dedicated methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence

from openjarvis.lifeos.db import LifeOSDB, utc_now


class PlannerError(ValueError):
    """Invalid planner input or unknown record."""


# -- validators ----------------------------------------------------------------


def _text(max_len: int, *, required: bool = False) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        value = "" if value is None else str(value).strip()
        if required and not value:
            raise PlannerError("campo obrigatório vazio")
        if len(value) > max_len:
            raise PlannerError(f"texto excede {max_len} caracteres")
        return value

    return check


def _choice(*options: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        value = str(value or "").strip().lower()
        if value not in options:
            raise PlannerError(f"valor '{value}' inválido; use: {', '.join(options)}")
        return value

    return check


def parse_date(value: Any) -> Optional[str]:
    """Accept ``YYYY-MM-DD`` (or empty); return normalized ISO date."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError as exc:
        raise PlannerError(f"data inválida '{value}', use AAAA-MM-DD") from exc


def parse_datetime(value: Any, *, required: bool = False) -> Optional[str]:
    """Accept ``YYYY-MM-DD HH:MM`` / ISO-8601; return ``YYYY-MM-DDTHH:MM``."""
    if value in (None, ""):
        if required:
            raise PlannerError("data/hora obrigatória")
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    raw = str(value).strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise PlannerError(
            f"data/hora inválida '{value}', use AAAA-MM-DD HH:MM"
        ) from exc
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _priority(value: Any) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError) as exc:
        raise PlannerError("prioridade deve ser inteiro de 1 (máxima) a 4") from exc
    if not 1 <= p <= 4:
        raise PlannerError("prioridade deve ser de 1 (máxima) a 4")
    return p


def _positive_int(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise PlannerError("valor deve ser inteiro positivo") from exc
    if n < 1:
        raise PlannerError("valor deve ser inteiro positivo")
    return n


def _optional_id(value: Any) -> Optional[int]:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PlannerError(f"id inválido '{value}'") from exc


@dataclass(frozen=True)
class EntitySpec:
    table: str
    label: str
    fields: Dict[str, Callable[[Any], Any]]
    required: Sequence[str]
    order_by: str
    references: Dict[str, str]


ENTITIES: Dict[str, EntitySpec] = {
    "goal": EntitySpec(
        table="goals",
        label="meta",
        fields={
            "title": _text(200, required=True),
            "description": _text(2000),
            "horizon": _choice("short", "medium", "long"),
            "status": _choice("active", "paused", "achieved", "abandoned"),
            "metric": _text(300),
            "target_date": parse_date,
        },
        required=("title",),
        order_by="status = 'active' DESC, target_date IS NULL, target_date, id",
        references={},
    ),
    "project": EntitySpec(
        table="projects",
        label="projeto",
        fields={
            "title": _text(200, required=True),
            "description": _text(2000),
            "goal_id": _optional_id,
            "status": _choice("active", "paused", "done", "cancelled"),
            "next_action": _text(300),
            "deadline": parse_date,
        },
        required=("title",),
        order_by="status = 'active' DESC, deadline IS NULL, deadline, id",
        references={"goal_id": "goals"},
    ),
    "task": EntitySpec(
        table="tasks",
        label="tarefa",
        fields={
            "title": _text(300, required=True),
            "notes": _text(2000),
            "project_id": _optional_id,
            "status": _choice("todo", "doing", "done", "cancelled"),
            "priority": _priority,
            "due_date": parse_date,
            "scheduled_date": parse_date,
        },
        required=("title",),
        order_by="status IN ('done','cancelled'), due_date IS NULL, due_date, priority, id",
        references={"project_id": "projects"},
    ),
    "habit": EntitySpec(
        table="habits",
        label="hábito",
        fields={
            "title": _text(200, required=True),
            "cadence": _choice("daily", "weekly"),
            "target_per_period": _positive_int,
            "status": _choice("active", "paused", "archived"),
        },
        required=("title",),
        order_by="status = 'active' DESC, id",
        references={},
    ),
    "commitment": EntitySpec(
        table="commitments",
        label="compromisso",
        fields={
            "title": _text(200, required=True),
            "starts_at": lambda v: parse_datetime(v, required=True),
            "ends_at": parse_datetime,
            "location": _text(200),
            "notes": _text(2000),
            "status": _choice("scheduled", "done", "cancelled"),
        },
        required=("title", "starts_at"),
        order_by="starts_at, id",
        references={},
    ),
    "decision": EntitySpec(
        table="decisions",
        label="decisão",
        fields={
            "title": _text(200, required=True),
            "context": _text(4000),
            "options": _text(4000),
            "decision": _text(2000),
            "rationale": _text(4000),
            "expected_outcome": _text(2000),
            "review_date": parse_date,
            "outcome": _text(4000),
        },
        required=("title",),
        order_by="id DESC",
        references={},
    ),
}

ENTITY_NAMES = tuple(ENTITIES)


def _spec(kind: str) -> EntitySpec:
    kind = (kind or "").strip().lower()
    if kind not in ENTITIES:
        raise PlannerError(
            f"entidade '{kind}' inválida; use: {', '.join(ENTITY_NAMES)}"
        )
    return ENTITIES[kind]


class Planner:
    """Persistence and rules for the LifeOS organization module."""

    def __init__(self, db: LifeOSDB) -> None:
        self._db = db

    # -- generic CRUD -------------------------------------------------------

    def _clean(self, spec: EntitySpec, data: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(data) - set(spec.fields)
        if unknown:
            raise PlannerError(
                f"campos desconhecidos para {spec.label}: {', '.join(sorted(unknown))}"
            )
        out: Dict[str, Any] = {}
        for key, value in data.items():
            try:
                out[key] = spec.fields[key](value)
            except PlannerError as exc:
                raise PlannerError(f"{spec.label}.{key}: {exc}") from None
        for ref_field, ref_table in spec.references.items():
            ref_id = out.get(ref_field)
            if (
                ref_id is not None
                and self._db.query_one(
                    f"SELECT 1 FROM {ref_table} WHERE id = ?", (ref_id,)
                )
                is None
            ):
                raise PlannerError(f"{ref_field} #{ref_id} não existe")
        return out

    def add(self, kind: str, **data: Any) -> Dict[str, Any]:
        spec = _spec(kind)
        values = self._clean(spec, {k: v for k, v in data.items() if v is not None})
        for req in spec.required:
            if not values.get(req):
                raise PlannerError(f"{spec.label}: campo '{req}' é obrigatório")
        if kind == "commitment":
            self._check_interval(values.get("starts_at"), values.get("ends_at"))
        now = utc_now()
        values["created_at"] = now
        values["updated_at"] = now
        cols = ", ".join(values)
        marks = ", ".join("?" * len(values))
        with self._db.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO {spec.table} ({cols}) VALUES ({marks})",
                list(values.values()),
            )
            new_id = cur.lastrowid
        return self.get(kind, new_id)

    def get(self, kind: str, item_id: int) -> Dict[str, Any]:
        spec = _spec(kind)
        row = self._db.query_one(
            f"SELECT * FROM {spec.table} WHERE id = ?", (int(item_id),)
        )
        if row is None:
            raise PlannerError(f"{spec.label} #{item_id} não encontrado(a)")
        return dict(row)

    def update(self, kind: str, item_id: int, **data: Any) -> Dict[str, Any]:
        spec = _spec(kind)
        current = self.get(kind, item_id)
        values = self._clean(spec, data)
        if not values:
            return current
        for req in spec.required:
            if req in values and not values[req]:
                raise PlannerError(f"{spec.label}: campo '{req}' é obrigatório")
        if kind == "commitment":
            self._check_interval(
                values.get("starts_at", current["starts_at"]),
                values.get("ends_at", current["ends_at"]),
            )
        if kind == "task" and "status" in values:
            if values["status"] == "done" and current["status"] != "done":
                values["completed_at"] = utc_now()
            elif values["status"] != "done":
                values["completed_at"] = None
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{k} = ?" for k in values)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE {spec.table} SET {assignments} WHERE id = ?",
                [*values.values(), int(item_id)],
            )
            if kind == "task" and current["project_id"]:
                conn.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?",
                    (values["updated_at"], current["project_id"]),
                )
        return self.get(kind, item_id)

    def delete(self, kind: str, item_id: int) -> Dict[str, Any]:
        spec = _spec(kind)
        current = self.get(kind, item_id)
        with self._db.transaction() as conn:
            conn.execute(f"DELETE FROM {spec.table} WHERE id = ?", (int(item_id),))
        return current

    def list(
        self,
        kind: str,
        *,
        status: Optional[str] = None,
        limit: int = 200,
        **filters: Any,
    ) -> List[Dict[str, Any]]:
        spec = _spec(kind)
        sql = f"SELECT * FROM {spec.table} WHERE 1=1"
        params: List[Any] = []
        if status:
            if "status" not in spec.fields:
                raise PlannerError(f"{spec.label} não possui status")
            statuses = [s.strip() for s in str(status).split(",") if s.strip()]
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params.extend(statuses)
        for key, value in filters.items():
            if value is None:
                continue
            if key not in spec.fields:
                raise PlannerError(f"filtro desconhecido '{key}' para {spec.label}")
            sql += f" AND {key} = ?"
            params.append(spec.fields[key](value))
        sql += f" ORDER BY {spec.order_by} LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(r) for r in self._db.query(sql, params)]

    # -- tasks --------------------------------------------------------------

    def complete_task(self, task_id: int) -> Dict[str, Any]:
        return self.update("task", task_id, status="done")

    def tasks_due_between(self, start: date, end: date) -> List[Dict[str, Any]]:
        rows = self._db.query(
            "SELECT * FROM tasks WHERE status IN ('todo','doing') AND "
            "COALESCE(scheduled_date, due_date) BETWEEN ? AND ? "
            "ORDER BY COALESCE(scheduled_date, due_date), priority, id",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in rows]

    def plan_steps(
        self,
        title: str,
        steps: Sequence[Any],
        *,
        goal_id: Optional[int] = None,
        project_id: Optional[int] = None,
        start_date: Optional[str] = None,
        every_days: int = 0,
    ) -> Dict[str, Any]:
        """Turn an objective into a project with ordered, concrete tasks.

        ``steps`` holds strings or ``{"title", "due_date", "priority"}`` dicts.
        When ``start_date`` and ``every_days`` are set, steps without an
        explicit date are spaced across the calendar instead of piling up.
        """
        if not steps:
            raise PlannerError("informe ao menos uma etapa")
        if len(steps) > 30:
            raise PlannerError("no máximo 30 etapas por plano; divida em fases")
        start = parse_date(start_date)
        if every_days < 0:
            raise PlannerError("every_days deve ser >= 0")
        if project_id is None:
            project = self.add(
                "project",
                title=title,
                goal_id=goal_id,
                description="Plano gerado a partir de objetivo",
            )
        else:
            project = self.get("project", project_id)
        created = []
        for index, step in enumerate(steps):
            if isinstance(step, dict):
                data = dict(step)
            else:
                data = {"title": str(step)}
            if "due_date" not in data and start and every_days:
                data["due_date"] = (
                    date.fromisoformat(start) + timedelta(days=index * every_days)
                ).isoformat()
            data["project_id"] = project["id"]
            created.append(self.add("task", **data))
        if created and not project.get("next_action"):
            project = self.update(
                "project", project["id"], next_action=created[0]["title"]
            )
        return {"project": project, "tasks": created}

    # -- habits -------------------------------------------------------------

    def log_habit(
        self, habit_id: int, log_date: Optional[str] = None, note: str = ""
    ) -> Dict[str, Any]:
        habit = self.get("habit", habit_id)
        day = parse_date(log_date) or date.today().isoformat()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO habit_logs(habit_id, log_date, note, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(habit_id, log_date) DO UPDATE SET note = excluded.note",
                (habit["id"], day, _text(500)(note), utc_now()),
            )
        return {"habit_id": habit["id"], "log_date": day}

    def habit_rate(
        self, habit_id: int, *, today: date, days: int = 7
    ) -> Dict[str, Any]:
        """Completion rate over the last ``days`` days (or weeks for weekly)."""
        habit = self.get("habit", habit_id)
        start = today - timedelta(days=days - 1)
        logs = self._db.query(
            "SELECT log_date FROM habit_logs WHERE habit_id = ? AND log_date BETWEEN ? AND ?",
            (habit["id"], start.isoformat(), today.isoformat()),
        )
        done = len(logs)
        if habit["cadence"] == "daily":
            expected = days * habit["target_per_period"]
        else:
            expected = max(1, days // 7) * habit["target_per_period"]
        created = datetime.fromisoformat(habit["created_at"]).date()
        return {
            "habit": habit,
            "done": done,
            "expected": expected,
            "rate": min(1.0, done / expected) if expected else 0.0,
            "mature": (today - created).days >= days,
        }

    # -- commitments --------------------------------------------------------

    @staticmethod
    def _check_interval(starts_at: Optional[str], ends_at: Optional[str]) -> None:
        if starts_at and ends_at and ends_at < starts_at:
            raise PlannerError("compromisso termina antes de começar")

    def commitments_between(self, start: date, end: date) -> List[Dict[str, Any]]:
        rows = self._db.query(
            "SELECT * FROM commitments WHERE status = 'scheduled' AND "
            "substr(starts_at, 1, 10) BETWEEN ? AND ? ORDER BY starts_at, id",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in rows]

    @staticmethod
    def find_conflicts(items: Sequence[Dict[str, Any]]) -> List[tuple]:
        """Overlapping pairs; commitments without an end last 1 hour."""

        def bounds(item: Dict[str, Any]) -> tuple[datetime, datetime]:
            start = datetime.fromisoformat(item["starts_at"])
            end = (
                datetime.fromisoformat(item["ends_at"])
                if item.get("ends_at")
                else start + timedelta(hours=1)
            )
            return start, end

        ordered = sorted(items, key=lambda i: i["starts_at"])
        conflicts = []
        for i, a in enumerate(ordered):
            a_start, a_end = bounds(a)
            for b in ordered[i + 1 :]:
                b_start, b_end = bounds(b)
                if b_start >= a_end:
                    break
                if b_start < a_end and a_start < b_end:
                    conflicts.append((a, b))
        return conflicts

    # -- overview -----------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        def count(sql: str, params: tuple = ()) -> int:
            row = self._db.query_one(sql, params)
            return int(row[0]) if row else 0

        today = date.today().isoformat()
        return {
            "goals_active": count("SELECT COUNT(*) FROM goals WHERE status = 'active'"),
            "projects_active": count(
                "SELECT COUNT(*) FROM projects WHERE status = 'active'"
            ),
            "tasks_open": count(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('todo','doing')"
            ),
            "tasks_overdue": count(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('todo','doing') "
                "AND due_date IS NOT NULL AND due_date < ?",
                (today,),
            ),
            "habits_active": count(
                "SELECT COUNT(*) FROM habits WHERE status = 'active'"
            ),
            "decisions": count("SELECT COUNT(*) FROM decisions"),
        }

    def export(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for kind, spec in ENTITIES.items():
            out[spec.table] = [
                dict(r) for r in self._db.query(f"SELECT * FROM {spec.table}")
            ]
        out["habit_logs"] = [
            dict(r) for r in self._db.query("SELECT * FROM habit_logs")
        ]
        return out


__all__ = [
    "ENTITIES",
    "ENTITY_NAMES",
    "Planner",
    "PlannerError",
    "parse_date",
    "parse_datetime",
]

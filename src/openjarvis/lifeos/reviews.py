# ruff: noqa: E501
"""Alert detection and periodic reviews (morning, evening, weekly, monthly).

Reports are built deterministically from the local database, so they work
without a language model and can be tested. The orchestrator may add
commentary on top of them, but the facts come from here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from openjarvis.lifeos.config import ReviewConfig
from openjarvis.lifeos.db import LifeOSDB, utc_now
from openjarvis.lifeos.planner import Planner

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
REVIEW_KINDS = ("morning", "evening", "weekly", "monthly")


@dataclass(slots=True)
class Alert:
    kind: str
    severity: str
    message: str
    ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Report:
    kind: str
    period_key: str
    title: str
    sections: Dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _task_line(t: Dict[str, Any]) -> str:
    extra = []
    if t.get("due_date"):
        extra.append(f"prazo {t['due_date']}")
    extra.append(f"P{t.get('priority', 3)}")
    return f"#{t['id']} {t['title']} ({', '.join(extra)})"


def _bullets(items: List[str], empty: str) -> str:
    return "\n".join(f"- {i}" for i in items) if items else f"- {empty}"


class ReviewEngine:
    def __init__(self, db: LifeOSDB, planner: Planner, config: ReviewConfig) -> None:
        self._db = db
        self._planner = planner
        self._cfg = config

    # -- alerts -------------------------------------------------------------

    def alerts(self, today: Optional[date] = None) -> List[Alert]:
        today = today or date.today()
        iso = today.isoformat()
        cfg = self._cfg
        found: List[Alert] = []

        overdue = self._db.query(
            "SELECT * FROM tasks WHERE status IN ('todo','doing') AND due_date IS NOT NULL "
            "AND due_date < ? ORDER BY due_date, priority",
            (iso,),
        )
        for t in overdue:
            found.append(
                Alert(
                    "overdue_task",
                    "high",
                    f"Tarefa atrasada: {_task_line(dict(t))}",
                    f"task:{t['id']}",
                )
            )

        soon_end = (today + timedelta(days=cfg.due_soon_days)).isoformat()
        for t in self._db.query(
            "SELECT * FROM tasks WHERE status IN ('todo','doing') AND due_date BETWEEN ? AND ? "
            "ORDER BY due_date, priority",
            (iso, soon_end),
        ):
            found.append(
                Alert(
                    "due_soon",
                    "medium",
                    f"Prazo próximo: {_task_line(dict(t))}",
                    f"task:{t['id']}",
                )
            )

        for p in self._db.query(
            "SELECT * FROM projects WHERE status = 'active' AND deadline IS NOT NULL AND deadline < ?",
            (iso,),
        ):
            found.append(
                Alert(
                    "overdue_project",
                    "high",
                    f"Projeto com prazo vencido: #{p['id']} {p['title']} ({p['deadline']})",
                    f"project:{p['id']}",
                )
            )

        stale_cut = (
            datetime.combine(today, datetime.min.time())
            - timedelta(days=cfg.stale_project_days)
        ).isoformat()
        for p in self._db.query(
            "SELECT p.* FROM projects p WHERE p.status = 'active' AND p.updated_at < ? AND NOT EXISTS ("
            "SELECT 1 FROM tasks t WHERE t.project_id = p.id AND t.updated_at >= ?)",
            (stale_cut, stale_cut),
        ):
            found.append(
                Alert(
                    "stale_project",
                    "medium",
                    f"Projeto sem progresso há {cfg.stale_project_days}+ dias: #{p['id']} {p['title']}",
                    f"project:{p['id']}",
                )
            )

        for g in self._db.query(
            "SELECT g.* FROM goals g WHERE g.status = 'active' AND g.updated_at < ? AND NOT EXISTS ("
            "SELECT 1 FROM projects p WHERE p.goal_id = g.id AND p.status = 'active')",
            (stale_cut,),
        ):
            found.append(
                Alert(
                    "abandoned_goal",
                    "medium",
                    f"Meta sem projeto ativo: #{g['id']} {g['title']}",
                    f"goal:{g['id']}",
                )
            )

        for h in self._db.query("SELECT id FROM habits WHERE status = 'active'"):
            stat = self._planner.habit_rate(h["id"], today=today, days=7)
            if stat["mature"] and stat["rate"] < cfg.habit_min_rate:
                found.append(
                    Alert(
                        "inconsistent_habit",
                        "low",
                        f"Hábito inconsistente: #{h['id']} {stat['habit']['title']} "
                        f"({stat['done']}/{stat['expected']} nos últimos 7 dias)",
                        f"habit:{h['id']}",
                    )
                )

        upcoming = self._planner.commitments_between(today, today + timedelta(days=7))
        for a, b in self._planner.find_conflicts(upcoming):
            found.append(
                Alert(
                    "commitment_conflict",
                    "high",
                    f"Conflito de agenda: '{a['title']}' ({a['starts_at']}) e '{b['title']}' ({b['starts_at']})",
                    f"commitment:{a['id']},{b['id']}",
                )
            )

        load: Dict[str, int] = {}
        for t in self._planner.tasks_due_between(today, today + timedelta(days=7)):
            day = t["scheduled_date"] or t["due_date"]
            load[day] = load.get(day, 0) + 1
        for day, n in sorted(load.items()):
            if n > cfg.daily_task_capacity:
                found.append(
                    Alert(
                        "overload",
                        "medium",
                        f"Planejamento excessivo em {day}: {n} tarefas para capacidade de {cfg.daily_task_capacity}",
                        f"day:{day}",
                    )
                )

        for d in self._db.query(
            "SELECT * FROM decisions WHERE review_date IS NOT NULL AND review_date <= ? AND outcome = ''",
            (iso,),
        ):
            found.append(
                Alert(
                    "decision_review",
                    "low",
                    f"Revisar resultado da decisão #{d['id']}: {d['title']}",
                    f"decision:{d['id']}",
                )
            )

        found.sort(key=lambda a: _SEVERITY_ORDER.get(a.severity, 9))
        return found[: cfg.max_alerts]

    # -- helpers ------------------------------------------------------------

    def _open_tasks(self) -> List[Dict[str, Any]]:
        return [
            dict(r)
            for r in self._db.query(
                "SELECT * FROM tasks WHERE status IN ('todo','doing')"
            )
        ]

    def _day_plan(self, today: date) -> List[Dict[str, Any]]:
        """Pick at most ``daily_task_capacity`` tasks: overdue, due, scheduled, priority."""
        iso = today.isoformat()

        def rank(t: Dict[str, Any]) -> tuple:
            due = t.get("due_date") or "9999-12-31"
            scheduled = t.get("scheduled_date") or "9999-12-31"
            return (
                0 if due < iso else 1,
                0 if (due == iso or scheduled == iso) else 1,
                0 if t["status"] == "doing" else 1,
                t["priority"],
                due,
                t["id"],
            )

        candidates = [
            t
            for t in self._open_tasks()
            if not t.get("scheduled_date") or t["scheduled_date"] <= iso
        ]
        return sorted(candidates, key=rank)[: self._cfg.daily_task_capacity]

    def _completed_between(self, start: date, end: date) -> List[Dict[str, Any]]:
        return [
            dict(r)
            for r in self._db.query(
                "SELECT * FROM tasks WHERE status = 'done' AND substr(completed_at, 1, 10) BETWEEN ? AND ? "
                "ORDER BY completed_at",
                (start.isoformat(), end.isoformat()),
            )
        ]

    def _goal_progress(self) -> List[str]:
        lines = []
        for g in self._db.query(
            "SELECT * FROM goals WHERE status = 'active' ORDER BY id"
        ):
            row = self._db.query_one(
                "SELECT COUNT(t.id) AS total, SUM(t.status = 'done') AS done FROM tasks t "
                "JOIN projects p ON p.id = t.project_id WHERE p.goal_id = ? AND t.status != 'cancelled'",
                (g["id"],),
            )
            total = int(row["total"] or 0)
            done = int(row["done"] or 0)
            pct = f"{(done / total) * 100:.0f}%" if total else "sem tarefas"
            lines.append(
                f"#{g['id']} {g['title']} [{g['horizon']}]: {done}/{total} tarefas ({pct})"
            )
        return lines

    def _habit_lines(self, today: date, days: int) -> List[str]:
        out = []
        for h in self._db.query(
            "SELECT id FROM habits WHERE status = 'active' ORDER BY id"
        ):
            s = self._planner.habit_rate(h["id"], today=today, days=days)
            out.append(
                f"#{h['id']} {s['habit']['title']}: {s['done']}/{s['expected']} ({s['rate']:.0%})"
            )
        return out

    # -- reports ------------------------------------------------------------

    def morning(self, today: Optional[date] = None) -> Report:
        today = today or date.today()
        commitments = self._planner.commitments_between(today, today)
        plan = self._day_plan(today)
        open_tasks = self._open_tasks()
        alerts = self.alerts(today)
        sections = {
            "commitments": commitments,
            "plan": plan,
            "open_tasks": len(open_tasks),
            "alerts": [a.to_dict() for a in alerts],
        }
        text = "\n\n".join(
            [
                f"# Relatório matinal — {today.isoformat()}",
                "## Compromissos\n"
                + _bullets(
                    [
                        f"{c['starts_at'][11:16]} {c['title']}"
                        + (f" @ {c['location']}" if c["location"] else "")
                        for c in commitments
                    ],
                    "Nenhum compromisso registrado.",
                ),
                "## Plano do dia (prioridades)\n"
                + _bullets([_task_line(t) for t in plan], "Nenhuma tarefa aberta."),
                f"## Pendências\n- {len(open_tasks)} tarefa(s) aberta(s) no total.",
                "## Alertas\n"
                + _bullets([a.message for a in alerts], "Nenhum alerta."),
            ]
        )
        return Report("morning", today.isoformat(), "Relatório matinal", sections, text)

    def evening(self, today: Optional[date] = None, notes: str = "") -> Report:
        today = today or date.today()
        done = self._completed_between(today, today)
        pending = [
            dict(r)
            for r in self._db.query(
                "SELECT * FROM tasks WHERE status IN ('todo','doing') AND "
                "COALESCE(scheduled_date, due_date) <= ? ORDER BY priority, due_date",
                (today.isoformat(),),
            )
        ]
        tomorrow = self._day_plan(today + timedelta(days=1))
        habits_today = [
            dict(r)
            for r in self._db.query(
                "SELECT h.title FROM habit_logs l JOIN habits h ON h.id = l.habit_id WHERE l.log_date = ?",
                (today.isoformat(),),
            )
        ]
        sections = {
            "completed": done,
            "pending": pending,
            "habits_logged": [h["title"] for h in habits_today],
            "obstacles": notes,
            "next_actions": tomorrow,
        }
        text = "\n\n".join(
            [
                f"# Revisão noturna — {today.isoformat()}",
                "## Concluído\n"
                + _bullets([_task_line(t) for t in done], "Nada concluído hoje."),
                "## Pendente\n"
                + _bullets(
                    [_task_line(t) for t in pending], "Nenhuma pendência vencida."
                ),
                "## Hábitos registrados\n"
                + _bullets([h["title"] for h in habits_today], "Nenhum."),
                "## Obstáculos\n"
                + (f"- {notes.strip()}" if notes.strip() else "- Não informados."),
                "## Próximas ações (amanhã)\n"
                + _bullets(
                    [_task_line(t) for t in tomorrow], "Sem tarefas planejadas."
                ),
            ]
        )
        return Report("evening", today.isoformat(), "Revisão noturna", sections, text)

    def _period_review(
        self, kind: str, start: date, end: date, today: date, label: str, key: str
    ) -> Report:
        done = self._completed_between(start, end)
        chronic = [
            dict(r)
            for r in self._db.query(
                "SELECT * FROM tasks WHERE status IN ('todo','doing') AND due_date IS NOT NULL AND due_date < ?",
                ((today - timedelta(days=7)).isoformat(),),
            )
        ]
        next_start = end + timedelta(days=1)
        next_end = next_start + (end - start)
        upcoming = self._planner.tasks_due_between(next_start, next_end)
        alerts = self.alerts(today)
        decisions = [
            dict(r)
            for r in self._db.query(
                "SELECT * FROM decisions WHERE substr(created_at, 1, 10) BETWEEN ? AND ? ORDER BY id",
                (start.isoformat(), end.isoformat()),
            )
        ]
        days = (end - start).days + 1
        sections = {
            "range": [start.isoformat(), end.isoformat()],
            "completed": done,
            "goal_progress": self._goal_progress(),
            "habits": self._habit_lines(min(end, today), days),
            "recurring_problems": chronic,
            "decisions": decisions,
            "alerts": [a.to_dict() for a in alerts],
            "next_period": upcoming,
        }
        adjustments = []
        if chronic:
            adjustments.append(
                f"{len(chronic)} tarefa(s) atrasada(s) há mais de 7 dias: renegociar prazo, dividir ou cancelar."
            )
        if any(a.kind == "overload" for a in alerts):
            adjustments.append("Há dias acima da capacidade: redistribuir tarefas.")
        if any(a.kind == "inconsistent_habit" for a in alerts):
            adjustments.append("Hábitos abaixo da meta: reduzir alvo ou mudar gatilho.")
        if any(a.kind in ("stale_project", "abandoned_goal") for a in alerts):
            adjustments.append(
                "Metas/projetos parados: definir próxima ação ou pausar formalmente."
            )
        sections["adjustments"] = adjustments
        text = "\n\n".join(
            [
                f"# {label} — {start.isoformat()} a {end.isoformat()}",
                f"## Concluído ({len(done)})\n"
                + _bullets([_task_line(t) for t in done], "Nada concluído no período."),
                "## Progresso das metas\n"
                + _bullets(sections["goal_progress"], "Nenhuma meta ativa."),
                "## Hábitos\n" + _bullets(sections["habits"], "Nenhum hábito ativo."),
                "## Problemas recorrentes\n"
                + _bullets([_task_line(t) for t in chronic], "Nenhum."),
                "## Decisões registradas\n"
                + _bullets(
                    [
                        f"#{d['id']} {d['title']}: {d['decision'] or '(pendente)'}"
                        for d in decisions
                    ],
                    "Nenhuma.",
                ),
                "## Ajustes necessários\n"
                + _bullets(adjustments, "Nenhum ajuste identificado."),
                "## Plano do próximo período\n"
                + _bullets(
                    [_task_line(t) for t in upcoming],
                    "Nenhuma tarefa com prazo no próximo período.",
                ),
            ]
        )
        return Report(kind, key, label, sections, text)

    def weekly(self, today: Optional[date] = None) -> Report:
        today = today or date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        iso = today.isocalendar()
        return self._period_review(
            "weekly", start, end, today, "Revisão semanal", f"{iso[0]}-W{iso[1]:02d}"
        )

    def monthly(self, today: Optional[date] = None) -> Report:
        today = today or date.today()
        start = today.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        end = next_month - timedelta(days=1)
        return self._period_review(
            "monthly", start, end, today, "Revisão mensal", start.strftime("%Y-%m")
        )

    def build(self, kind: str, today: Optional[date] = None, notes: str = "") -> Report:
        kind = (kind or "").strip().lower()
        if kind == "morning":
            return self.morning(today)
        if kind == "evening":
            return self.evening(today, notes)
        if kind == "weekly":
            return self.weekly(today)
        if kind == "monthly":
            return self.monthly(today)
        raise ValueError(
            f"tipo de revisão inválido '{kind}'; use: {', '.join(REVIEW_KINDS)}"
        )

    def save(self, report: Report, notes: str = "") -> int:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO reviews(kind, period_key, content, data_json, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(kind, period_key) DO UPDATE SET "
                "content = excluded.content, data_json = excluded.data_json, "
                "notes = excluded.notes, created_at = excluded.created_at",
                (
                    report.kind,
                    report.period_key,
                    report.text,
                    json.dumps(report.sections, ensure_ascii=False, default=str),
                    notes,
                    utc_now(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM reviews WHERE kind = ? AND period_key = ?",
                (report.kind, report.period_key),
            ).fetchone()
        return int(row["id"])

    def history(
        self, kind: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        sql = "SELECT id, kind, period_key, content, notes, created_at FROM reviews"
        params: list[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(r) for r in self._db.query(sql, params)]


__all__ = ["Alert", "REVIEW_KINDS", "Report", "ReviewEngine"]

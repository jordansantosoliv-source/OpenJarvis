from __future__ import annotations

from datetime import date, timedelta

import pytest

from openjarvis.lifeos.planner import PlannerError

TODAY = date(2026, 11, 17)  # a Tuesday


def test_goal_project_task_lifecycle(lifeos):
    p = lifeos.planner
    goal = p.add("goal", title="Melhorar desempenho acadêmico", horizon="medium")
    project = p.add("project", title="Cálculo I", goal_id=goal["id"])
    task = p.add(
        "task",
        title="Lista 3",
        project_id=project["id"],
        priority=1,
        due_date="2026-11-20",
    )
    assert task["status"] == "todo"
    done = p.complete_task(task["id"])
    assert done["status"] == "done" and done["completed_at"]
    reopened = p.update("task", task["id"], status="todo")
    assert reopened["completed_at"] is None


def test_validation_errors(lifeos):
    p = lifeos.planner
    with pytest.raises(PlannerError):
        p.add("task", title="")
    with pytest.raises(PlannerError):
        p.add("task", title="x", priority=9)
    with pytest.raises(PlannerError):
        p.add("task", title="x", due_date="20/11/2026")
    with pytest.raises(PlannerError):
        p.add("task", title="x", project_id=999)
    with pytest.raises(PlannerError):
        p.add("task", title="x", unknown_field=1)
    with pytest.raises(PlannerError):
        p.add("nonsense", title="x")
    with pytest.raises(PlannerError):
        p.add(
            "commitment",
            title="x",
            starts_at="2026-11-17 10:00",
            ends_at="2026-11-17 09:00",
        )


def test_plan_steps_spaces_dates(lifeos):
    goal = lifeos.planner.add("goal", title="Passar em Física")
    plan = lifeos.planner.plan_steps(
        "Física — preparação",
        ["Revisar cinemática", "Fazer lista", "Simulado"],
        goal_id=goal["id"],
        start_date="2026-11-18",
        every_days=2,
    )
    assert [t["due_date"] for t in plan["tasks"]] == [
        "2026-11-18",
        "2026-11-20",
        "2026-11-22",
    ]
    assert plan["project"]["next_action"] == "Revisar cinemática"
    with pytest.raises(PlannerError):
        lifeos.planner.plan_steps("x", [])


def test_habit_logging_is_idempotent_per_day(lifeos):
    h = lifeos.planner.add("habit", title="Ler 20 min")
    lifeos.planner.log_habit(h["id"], "2026-11-17")
    lifeos.planner.log_habit(h["id"], "2026-11-17")
    stat = lifeos.planner.habit_rate(h["id"], today=TODAY, days=7)
    assert stat["done"] == 1 and stat["expected"] == 7


def test_conflict_detection():
    from openjarvis.lifeos.planner import Planner

    a = {"title": "A", "starts_at": "2026-11-17T10:00", "ends_at": "2026-11-17T11:00"}
    b = {"title": "B", "starts_at": "2026-11-17T10:30", "ends_at": None}
    c = {"title": "C", "starts_at": "2026-11-17T12:00", "ends_at": None}
    conflicts = Planner.find_conflicts([c, b, a])
    assert [(x["title"], y["title"]) for x, y in conflicts] == [("A", "B")]


def _kinds(alerts):
    return {a.kind for a in alerts}


def test_alerts(lifeos):
    p = lifeos.planner
    p.add("task", title="Atrasada", due_date=(TODAY - timedelta(days=1)).isoformat())
    p.add("task", title="Logo", due_date=(TODAY + timedelta(days=1)).isoformat())
    p.add(
        "commitment",
        title="Reunião",
        starts_at="2026-11-18 10:00",
        ends_at="2026-11-18 11:00",
    )
    p.add("commitment", title="Dentista", starts_at="2026-11-18 10:30")
    for i in range(7):
        p.add("task", title=f"T{i}", scheduled_date="2026-11-19")
    p.add("decision", title="Trocar de curso", review_date="2026-11-01")
    lifeos.config.review.max_alerts = 50
    kinds = _kinds(lifeos.reviews.alerts(TODAY))
    assert {
        "overdue_task",
        "due_soon",
        "commitment_conflict",
        "overload",
        "decision_review",
    } <= kinds


def test_stale_project_and_abandoned_goal(lifeos):
    goal = lifeos.planner.add("goal", title="Aprender inglês")
    project = lifeos.planner.add("project", title="Curso")
    old = "2026-10-01T00:00:00+00:00"
    with lifeos.db.transaction() as conn:
        conn.execute("UPDATE goals SET updated_at = ? WHERE id = ?", (old, goal["id"]))
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?", (old, project["id"])
        )
    kinds = _kinds(lifeos.reviews.alerts(TODAY))
    assert {"stale_project", "abandoned_goal"} <= kinds


def test_alerts_are_capped(lifeos):
    for i in range(20):
        lifeos.planner.add("task", title=f"Velha {i}", due_date="2026-01-01")
    assert len(lifeos.reviews.alerts(TODAY)) == lifeos.config.review.max_alerts


def test_morning_plan_respects_capacity(lifeos):
    for i in range(9):
        lifeos.planner.add("task", title=f"Tarefa {i}", priority=(i % 4) + 1)
    report = lifeos.reviews.morning(TODAY)
    assert len(report.sections["plan"]) == lifeos.config.review.daily_task_capacity
    assert report.sections["plan"][0]["priority"] == 1
    assert "Relatório matinal" in report.text


def test_evening_and_weekly_reports(lifeos):
    t = lifeos.planner.add(
        "task", title="Entregar trabalho", due_date=TODAY.isoformat()
    )
    lifeos.planner.complete_task(t["id"])
    with lifeos.db.transaction() as conn:
        conn.execute(
            "UPDATE tasks SET completed_at = ? WHERE id = ?",
            (f"{TODAY}T15:00:00+00:00", t["id"]),
        )
    evening = lifeos.reviews.evening(TODAY, notes="Internet caiu")
    assert evening.sections["completed"][0]["id"] == t["id"]
    assert "Internet caiu" in evening.text
    weekly = lifeos.reviews.weekly(TODAY)
    assert weekly.period_key == "2026-W47"
    assert weekly.sections["range"] == ["2026-11-16", "2026-11-22"]
    rid = lifeos.reviews.save(weekly)
    assert lifeos.reviews.save(weekly) == rid  # upsert, not duplicate
    monthly = lifeos.reviews.monthly(TODAY)
    assert monthly.sections["range"] == ["2026-11-01", "2026-11-30"]

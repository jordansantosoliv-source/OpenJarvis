from __future__ import annotations

import pytest

from openjarvis.lifeos.autonomy import (
    CATEGORIES,
    AutonomyLevel,
    Verdict,
    category_of,
    classify_tool_call,
    decide,
)
from openjarvis.lifeos.service import LifeOSError
from openjarvis.lifeos.tools import LifeOSMemoryTool


@pytest.mark.parametrize(
    "category,level,grants,expected",
    [
        ("read", 1, (), Verdict.ALLOW),
        ("memory_write", 1, (), Verdict.DENY),
        ("memory_write", 2, ("memory_write",), Verdict.ASK),
        ("memory_write", 3, ("memory_write",), Verdict.ALLOW),
        ("memory_write", 3, (), Verdict.ASK),
        ("message_send", 4, ("message_send",), Verdict.ASK),
        ("financial", 4, ("financial",), Verdict.ASK),
        ("file_delete", 4, (), Verdict.ASK),
        ("unknown", 4, ("unknown",), Verdict.ASK),
    ],
)
def test_policy_matrix(category, level, grants, expected):
    assert decide(category_of(category), level, grants).verdict is expected


def test_high_and_critical_are_not_grantable(lifeos):
    with pytest.raises(LifeOSError):
        lifeos.grant("financial")
    with pytest.raises(LifeOSError):
        lifeos.grant("message_send")
    with pytest.raises(LifeOSError):
        lifeos.grant("bogus")
    lifeos.grant("memory_write")
    assert "memory_write" in lifeos.grants()


def test_classification():
    tool = LifeOSMemoryTool()
    assert (
        classify_tool_call(tool, "lifeos_memory", {"action": "search"}).name == "read"
    )
    assert (
        classify_tool_call(tool, "lifeos_memory", {"action": "forget"}).name
        == "memory_delete"
    )
    assert classify_tool_call(None, "shell_exec", {}).name == "code_execution"
    assert classify_tool_call(None, "never_seen", {}).name == "unknown"
    assert CATEGORIES["unknown"].risk.value == "high"


def test_default_level_and_persisted_change(lifeos):
    assert lifeos.autonomy_level is AutonomyLevel.ASSISTED
    lifeos.set_autonomy_level(3)
    assert lifeos.autonomy_level is AutonomyLevel.AUTHORIZED
    with pytest.raises(ValueError):
        lifeos.set_autonomy_level(7)


def test_pending_approval_executes_lifeos_tool(lifeos):
    args = {"action": "remember", "content": "Gosta de café"}
    decision = lifeos.authorize(LifeOSMemoryTool(lifeos), "lifeos_memory", args)
    assert decision.verdict is Verdict.ASK
    pid = lifeos.queue_pending("lifeos_memory", args, decision)
    assert lifeos.queue_pending("lifeos_memory", args, decision) == pid  # no duplicates
    out = lifeos.approve(pid)
    assert out["executed"] and out["status"] == "executed"
    assert lifeos.memory.search("café")
    with pytest.raises(LifeOSError):
        lifeos.approve(pid)


def test_one_time_approval_for_external_tool(lifeos):
    args = {"command": "dir"}
    decision = lifeos.authorize(None, "shell_exec", args)
    pid = lifeos.queue_pending("shell_exec", args, decision)
    assert lifeos.approve(pid) == {"id": pid, "status": "approved", "executed": False}
    assert lifeos.authorize(None, "shell_exec", args).verdict is Verdict.ALLOW
    assert lifeos.authorize(None, "shell_exec", args).verdict is Verdict.ASK  # consumed


def test_consultive_mode_blocks_approval(lifeos):
    args = {"action": "remember", "content": "x"}
    pid = lifeos.queue_pending(
        "lifeos_memory", args, lifeos.authorize(None, "lifeos_memory", args)
    )
    lifeos.set_autonomy_level(1)
    with pytest.raises(LifeOSError):
        lifeos.approve(pid)


def test_deny(lifeos):
    args = {"action": "forget", "id": 1}
    pid = lifeos.queue_pending(
        "lifeos_memory", args, lifeos.authorize(None, "lifeos_memory", args)
    )
    assert lifeos.deny(pid)["status"] == "denied"
    assert lifeos.list_pending() == []


def test_audit_chain_detects_tampering(lifeos):
    lifeos.set_autonomy_level(3)
    lifeos.grant("planning_write")
    assert lifeos.actions.verify() == (True, None)
    with lifeos.db.transaction() as conn:
        conn.execute("UPDATE action_log SET result = 'forjado' WHERE id = 1")
    ok, bad = lifeos.actions.verify()
    assert not ok and bad == 1


def test_export_and_wipe(lifeos, tmp_path):
    lifeos.memory.remember("Dado pessoal")
    lifeos.planner.add("task", title="Algo")
    path = lifeos.export_to(tmp_path / "export.json")
    assert "Dado pessoal" in path.read_text(encoding="utf-8")
    counts = lifeos.wipe()
    assert counts["memories"] == 1 and counts["tasks"] == 1
    assert lifeos.memory.export() == [] and lifeos.planner.list("task") == []
    assert lifeos.actions.list()[0]["action"] == "wipe"

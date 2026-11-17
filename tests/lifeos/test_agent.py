from __future__ import annotations

import json

from tests.agents.fake_engine import FakeEngine

from openjarvis.core.types import Role
from openjarvis.lifeos.agent import JarvisOrchestratorAgent


def _call(name, args, call_id="c1"):
    return {"id": call_id, "name": name, "arguments": json.dumps(args)}


def _agent(lifeos, responses, **kw):
    engine = FakeEngine(responses)
    agent = JarvisOrchestratorAgent(
        engine,
        "fake-model",
        lifeos=lifeos,
        temperature=0.1,
        max_tokens=256,
        max_turns=4,
        **kw,
    )
    return agent, engine


ADD_TASK = _call(
    "lifeos_planner",
    {
        "action": "add",
        "entity": "task",
        "data": {"title": "Estudar cálculo", "priority": 1},
    },
)


def test_lifeos_tools_are_attached(lifeos):
    agent, _ = _agent(lifeos, [{"content": "ok"}])
    names = {t.spec.name for t in agent._tools}
    assert {"lifeos_memory", "lifeos_planner", "lifeos_review"} <= names


def test_authorized_level_executes_granted_category(lifeos):
    lifeos.set_autonomy_level(3)
    lifeos.grant("planning_write")
    agent, _ = _agent(
        lifeos,
        [{"content": "", "tool_calls": [ADD_TASK]}, {"content": "Tarefa criada."}],
    )
    result = agent.run("Crie a tarefa estudar cálculo")
    assert result.content == "Tarefa criada."
    assert [t["title"] for t in lifeos.planner.list("task")] == ["Estudar cálculo"]
    decisions = [e["decision"] for e in lifeos.actions.list()]
    assert "allowed" in decisions and "executed" in decisions
    assert lifeos.actions.verify() == (True, None)


def test_assisted_level_queues_pending_action(lifeos):
    lifeos.set_autonomy_level(2)
    agent, engine = _agent(
        lifeos,
        [
            {"content": "", "tool_calls": [ADD_TASK]},
            {"content": "Aguardando aprovação."},
        ],
    )
    result = agent.run("Crie a tarefa estudar cálculo")
    assert lifeos.planner.list("task") == []
    pending = lifeos.list_pending()
    assert len(pending) == 1 and pending[0]["tool"] == "lifeos_planner"
    tool_msg = [m for m in engine.last_messages if m.role == Role.TOOL][-1]
    assert pending[0]["id"] in tool_msg.content
    assert result.content == "Aguardando aprovação."
    lifeos.approve(pending[0]["id"])
    assert len(lifeos.planner.list("task")) == 1


def test_interactive_approval_callback(lifeos):
    seen = []

    def approve(name, args, decision):
        seen.append((name, decision.category.name))
        return True

    agent, _ = _agent(
        lifeos,
        [{"content": "", "tool_calls": [ADD_TASK]}, {"content": "feito"}],
        approval_callback=approve,
    )
    agent.run("Crie a tarefa")
    assert seen == [("lifeos_planner", "planning_write")]
    assert len(lifeos.planner.list("task")) == 1


def test_generic_confirm_callback_does_not_bypass_policy(lifeos):
    lifeos.set_autonomy_level(2)
    agent, _ = _agent(
        lifeos,
        [{"content": "", "tool_calls": [ADD_TASK]}, {"content": "x"}],
        interactive=True,
        confirm_callback=lambda prompt: True,
    )
    agent.run("Crie a tarefa")
    assert lifeos.planner.list("task") == []
    assert len(lifeos.list_pending()) == 1


def test_consultive_level_denies_writes_but_allows_reads(lifeos):
    lifeos.set_autonomy_level(1)
    lifeos.memory.remember("Prefere treinar de manhã")
    search = _call("lifeos_memory", {"action": "search", "query": "treinar"}, "c2")
    agent, engine = _agent(
        lifeos,
        [
            {"content": "", "tool_calls": [ADD_TASK, search]},
            {"content": "Recomendo..."},
        ],
    )
    agent.run("Organize meu treino")
    assert lifeos.planner.list("task") == []
    tool_msgs = [m.content for m in engine.last_messages if m.role == Role.TOOL]
    assert any("modo consultivo" in c for c in tool_msgs)
    assert any("treinar de manhã" in c for c in tool_msgs)
    assert lifeos.list_pending() == []


def test_system_prompt_has_persona_rules_memory_and_snapshot(lifeos):
    lifeos.memory.remember("Nunca usar emojis", layer="identity")
    lifeos.memory.remember("Está estudando para a prova de cálculo", layer="personal")
    lifeos.planner.add("task", title="Atrasada", due_date="2020-01-01")
    agent, engine = _agent(lifeos, [{"content": "ok"}])
    agent.run("Como está minha preparação para cálculo?")
    system = engine.last_messages[0]
    assert system.role == Role.SYSTEM
    text = system.content
    assert "JARVIS" in text and "Nunca usar emojis" in text
    assert "prova de cálculo" in text
    assert "Tarefa atrasada" in text
    assert "Nível de autonomia: 3" in text


def test_conversation_persists_and_is_replayed(lifeos):
    agent, _ = _agent(lifeos, [{"content": "Primeira resposta"}])
    agent.run("Olá")
    again, engine = _agent(
        lifeos, [{"content": "Segunda"}], session_id=agent.session_id
    )
    again.run("Continue")
    contents = [m.content for m in engine.last_messages]
    assert "Olá" in contents and "Primeira resposta" in contents
    history = lifeos.conversation(agent.session_id)
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert lifeos.sessions()[0]["messages"] == 4


def test_registered_in_agent_registry():
    from openjarvis.core.registry import AgentRegistry
    from openjarvis.lifeos.agent import ensure_registered

    ensure_registered()
    assert AgentRegistry.get("jarvis_orchestrator") is JarvisOrchestratorAgent

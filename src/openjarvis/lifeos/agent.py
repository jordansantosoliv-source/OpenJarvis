# ruff: noqa: E501
"""JARVIS_ORCHESTRATOR — the LifeOS central agent.

Built on the native :class:`~openjarvis.agents.orchestrator.OrchestratorAgent`
(function-calling loop, loop guard, taint and capability checks, injection
scanning). This subclass adds:

* the JARVIS persona and user-defined identity rules,
* relevant memories and an operational snapshot in every system prompt,
* the risk-based autonomy policy on every tool call (``_check_tool_allowed``),
* an audit entry for every decision and every tool result,
* persistent conversation history per session.

Approval flow: when the policy answers ASK, an ``approval_callback`` (e.g. an
interactive terminal prompt) is consulted. Without one, the call is queued as
a pending action the user approves later (``jarvis lifeos approvals``). The
generic OpenJarvis ``confirm_callback`` is deliberately NOT used for this
decision, because ``jarvis ask`` wires it to auto-approve.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.lifeos.autonomy import Verdict

ApprovalCallback = Callable[[str, dict, Any], bool]

_ROUTING_GUIDE = """\
## Como trabalhar
1. Entenda o pedido e o contexto. Consulte a memória (lifeos_memory search)
   quando o pedido depender de informações anteriores.
2. Classifique: pergunta, análise/decisão, organização (metas, tarefas,
   hábitos), registro de memória ou revisão.
3. Planeje antes de agir. Verifique riscos. Use as ferramentas para fatos;
   não invente dados que deveriam vir do LifeOS.
4. Execute (ou solicite autorização) e confira o resultado da ferramenta.
5. Registre na memória somente o que for durável e importante.
6. Responda de forma direta. Se uma ação ficou pendente de aprovação,
   informe o identificador da pendência.
"""


@AgentRegistry.register("jarvis_orchestrator")
class JarvisOrchestratorAgent(OrchestratorAgent):
    """Central LifeOS agent with persona, layered memory and autonomy policy."""

    agent_id = "jarvis_orchestrator"

    def __init__(
        self,
        engine: Any,
        model: str,
        *,
        tools: Optional[List[Any]] = None,
        lifeos: Any = None,
        session_id: Optional[str] = None,
        approval_callback: Optional[ApprovalCallback] = None,
        include_history: bool = True,
        history_limit: int = 12,
        **kwargs: Any,
    ) -> None:
        from openjarvis.lifeos.service import get_lifeos
        from openjarvis.lifeos.tools import build_lifeos_tools

        self._lifeos = lifeos or get_lifeos()
        tool_list = list(tools or [])
        names = {getattr(t.spec, "name", "") for t in tool_list}
        for tool in build_lifeos_tools(self._lifeos):
            if tool.spec.name not in names:
                tool_list.append(tool)
        kwargs.pop("system_prompt", None)
        kwargs.pop("before_tool_call", None)
        super().__init__(engine, model, tools=tool_list, **kwargs)
        # Keep the OpenJarvis builder only to append USER/SOUL/MEMORY files and
        # the current time; JARVIS composes the leading system prompt itself.
        self._oj_prompt_builder = self._prompt_builder
        self._prompt_builder = None
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._approval_callback = approval_callback
        self._include_history = include_history
        self._history_limit = history_limit
        self._tools_by_name = {t.spec.name: t for t in tool_list}
        self._run_lock = threading.Lock()

    @property
    def lifeos(self) -> Any:
        return self._lifeos

    # -- prompt -------------------------------------------------------------

    def compose_system_prompt(self, query: str) -> str:
        lo = self._lifeos
        parts = [
            lo.persona_text(),
            _ROUTING_GUIDE,
            "## Autonomia\n" + lo.policy_summary(),
        ]
        memories = lo.memory.context_block(query, limit=lo.config.memory_context_limit)
        if memories:
            parts.append(
                "## Memórias relevantes (dados registrados; [hipótese] não é fato)\n"
                + memories
            )
        parts.append("## Situação atual (LifeOS)\n" + lo.operational_snapshot())
        prompt = "\n\n".join(parts)
        if self._oj_prompt_builder is not None:
            extra = "\n\n".join(
                p
                for p in (
                    self._oj_prompt_builder.persona_sections(),
                    self._oj_prompt_builder.current_time_section(),
                )
                if p
            )
            if extra:
                prompt += "\n\n## Perfil OpenJarvis\n" + extra
        else:
            from datetime import datetime

            prompt += f"\n\nData e hora local: {datetime.now().strftime('%Y-%m-%d %H:%M (%A)')}"
        return prompt

    # -- governance ---------------------------------------------------------

    def _audit(
        self, tc_name: str, args: dict, decision: Any, label: str, result: str = ""
    ) -> None:
        self._lifeos.actions.record(
            actor=self.agent_id,
            action=tc_name,
            category=decision.category.name,
            risk=decision.category.risk.value,
            autonomy_level=int(decision.level),
            decision=label,
            params=args,
            result=result or decision.reason,
            success=None,
        )

    def _check_tool_allowed(self, tc: ToolCall) -> Optional[ToolResult]:
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except (json.JSONDecodeError, TypeError):
            return self._governance_denial(tc.name, "argumentos inválidos")
        if not isinstance(args, dict):
            return self._governance_denial(tc.name, "argumentos não são um objeto")

        tool = self._tools_by_name.get(tc.name)
        decision = self._lifeos.authorize(tool, tc.name, args)

        if decision.verdict is Verdict.ALLOW:
            self._audit(tc.name, args, decision, "allowed")
            return None
        if decision.verdict is Verdict.DENY:
            self._audit(tc.name, args, decision, "denied")
            return ToolResult(
                tool_name=tc.name,
                content=(
                    f"[Autonomia] Ação '{tc.name}' não executada: {decision.reason}. "
                    "Apresente a recomendação ao usuário em vez de executar."
                ),
                success=False,
            )

        # ASK
        if self._approval_callback is not None:
            try:
                approved = self._approval_callback(tc.name, args, decision) is True
            except Exception:
                approved = False
            self._audit(
                tc.name,
                args,
                decision,
                "approved_by_user" if approved else "denied_by_user",
            )
            if approved:
                return None
            return ToolResult(
                tool_name=tc.name,
                content=f"[Autonomia] O usuário negou a ação '{tc.name}'. Não tente de novo sem novo pedido.",
                success=False,
            )
        pending_id = self._lifeos.queue_pending(tc.name, args, decision)
        self._audit(
            tc.name, args, decision, "pending_approval", f"pendência {pending_id}"
        )
        return ToolResult(
            tool_name=tc.name,
            content=(
                f"[Autonomia] Ação '{tc.name}' aguarda aprovação do usuário "
                f"(pendência {pending_id}; motivo: {decision.reason}). Informe ao "
                f"usuário que pode aprovar com: jarvis lifeos approvals approve {pending_id}"
            ),
            success=False,
        )

    # -- run ----------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        with self._run_lock:
            lo = self._lifeos
            if context is None:
                context = AgentContext()
                if self._include_history:
                    from openjarvis.core.types import Message, Role

                    for msg in lo.conversation(self.session_id, self._history_limit):
                        role = Role.USER if msg["role"] == "user" else Role.ASSISTANT
                        context.conversation.add(
                            Message(role=role, content=msg["content"])
                        )
            self._system_prompt = self.compose_system_prompt(input)
            lo.record_message(self.session_id, "user", input)
            try:
                result = super().run(input, context, **kwargs)
            except Exception as exc:
                lo.actions.record(
                    actor=self.agent_id,
                    action="run",
                    category="read",
                    risk="none",
                    autonomy_level=int(lo.autonomy_level),
                    decision="error",
                    params={"input": input[:500]},
                    result=repr(exc),
                    success=False,
                )
                raise
            for tr in result.tool_results:
                if tr.content.startswith(("[Autonomia]", "[Governance]")):
                    continue
                lo.actions.record(
                    actor=self.agent_id,
                    action=tr.tool_name,
                    category="result",
                    risk="-",
                    autonomy_level=int(lo.autonomy_level),
                    decision="executed",
                    params=tr.metadata.get("arguments", {}) if tr.metadata else {},
                    result=tr.content,
                    success=tr.success,
                )
            lo.record_message(self.session_id, "assistant", result.content)
            result.metadata["session_id"] = self.session_id
            return result


def ensure_registered() -> None:
    if not AgentRegistry.contains("jarvis_orchestrator"):
        AgentRegistry.register_value("jarvis_orchestrator", JarvisOrchestratorAgent)


__all__ = ["JarvisOrchestratorAgent", "ensure_registered"]

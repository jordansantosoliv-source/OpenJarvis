# ruff: noqa: E501
"""LifeOS tools exposed to agents through the OpenJarvis ``ToolRegistry``.

Each tool classifies its own calls via ``lifeos_category`` so the autonomy
policy can tell a read from a write or a deletion.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.lifeos.memory import LAYERS, LifeOSMemoryError, MemoryConflict
from openjarvis.lifeos.planner import ENTITY_NAMES, PlannerError
from openjarvis.lifeos.reviews import REVIEW_KINDS
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=1)


class _LifeOSTool(BaseTool):
    is_local = True

    def __init__(self, lifeos: Any = None) -> None:
        self._lifeos = lifeos

    @property
    def lifeos(self) -> Any:
        if self._lifeos is None:
            from openjarvis.lifeos.service import get_lifeos

            self._lifeos = get_lifeos()
        return self._lifeos

    def _ok(self, content: Any) -> ToolResult:
        text = content if isinstance(content, str) else _json(content)
        return ToolResult(tool_name=self.spec.name, content=text, success=True)

    def _fail(self, message: str) -> ToolResult:
        return ToolResult(tool_name=self.spec.name, content=message, success=False)

    def lifeos_category(self, arguments: Dict[str, Any]) -> str:  # pragma: no cover
        raise NotImplementedError

    def execute(self, **params: Any) -> ToolResult:
        try:
            return self._run(**params)
        except (
            LifeOSMemoryError,
            PlannerError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            return self._fail(f"Erro: {exc}")

    def _run(self, **params: Any) -> ToolResult:  # pragma: no cover
        raise NotImplementedError


@ToolRegistry.register("lifeos_memory")
class LifeOSMemoryTool(_LifeOSTool):
    tool_id = "lifeos_memory"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="lifeos_memory",
            description=(
                "Memória persistente em camadas do usuário. Ações: search (buscar), "
                "list, remember (registrar fato durável), correct (corrigir #id), "
                "forget (apagar #id), history. Camadas: identity (regras de "
                "comportamento), personal (fatos do usuário), episodic (eventos, "
                "decisões, problemas), operational (estado atual), knowledge "
                "(notas, pesquisas). Use status=hypothesis para o que não foi "
                "confirmado pelo usuário. Use subject para chaves únicas (ex.: "
                "'usuario.horario_acordar') e replace=true para substituir."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "search",
                            "list",
                            "remember",
                            "correct",
                            "forget",
                            "history",
                        ],
                    },
                    "query": {"type": "string", "description": "Texto da busca."},
                    "content": {
                        "type": "string",
                        "description": "Conteúdo a registrar/corrigir.",
                    },
                    "layer": {"type": "string", "enum": list(LAYERS)},
                    "subject": {"type": "string"},
                    "status": {"type": "string", "enum": ["confirmed", "hypothesis"]},
                    "tags": {"type": "string", "description": "Separadas por vírgula."},
                    "replace": {"type": "boolean"},
                    "id": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
            },
            category="memory",
            required_capabilities=["memory:write"],
        )

    def lifeos_category(self, arguments: Dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).lower()
        if action in ("search", "list", "history"):
            return "read"
        if action in ("remember", "correct"):
            return "memory_write"
        if action == "forget":
            return "memory_delete"
        return "unknown"

    def _run(self, **p: Any) -> ToolResult:
        mem = self.lifeos.memory
        action = str(p.get("action", "")).lower()
        limit = int(p.get("limit") or 10)
        if action == "search":
            layers = [p["layer"]] if p.get("layer") else None
            hits = mem.search(str(p.get("query", "")), layers=layers, limit=limit)
            return self._ok(
                [h.to_dict() for h in hits] or "Nenhuma memória encontrada."
            )
        if action == "list":
            return self._ok(
                [r.to_dict() for r in mem.list(p.get("layer"), limit=limit)]
            )
        if action == "history":
            return self._ok([r.to_dict() for r in mem.history(int(p["id"]))])
        if action == "remember":
            try:
                record, created = mem.remember(
                    str(p.get("content", "")),
                    layer=p.get("layer") or "personal",
                    subject=p.get("subject") or "",
                    status=p.get("status") or "confirmed",
                    source=p.get("source") or "jarvis",
                    tags=p.get("tags"),
                    replace=bool(p.get("replace", False)),
                )
            except MemoryConflict as exc:
                return self._fail(str(exc))
            prefix = "Registrado" if created else "Já existia (deduplicado)"
            return self._ok(
                f"{prefix}: memória #{record.id} [{record.layer}|{record.status}] {record.content}"
            )
        if action == "correct":
            record = mem.correct(
                int(p["id"]),
                content=p.get("content"),
                status=p.get("status"),
                subject=p.get("subject"),
                tags=p.get("tags"),
            )
            return self._ok(f"Corrigido: nova versão #{record.id}: {record.content}")
        if action == "forget":
            n = mem.forget(int(p["id"]))
            return self._ok(f"Apagado: {n} registro(s), incluindo histórico.")
        return self._fail(f"Ação desconhecida '{action}'")


@ToolRegistry.register("lifeos_planner")
class LifeOSPlannerTool(_LifeOSTool):
    tool_id = "lifeos_planner"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="lifeos_planner",
            description=(
                "Organização da vida: metas (goal), projetos (project), tarefas "
                "(task), hábitos (habit), compromissos (commitment) e decisões "
                "(decision). Ações: list, get, add, update, delete, complete_task, "
                "log_habit, plan (transforma um objetivo em projeto com etapas "
                "concretas). Campos em 'data'. Datas AAAA-MM-DD; compromissos "
                "AAAA-MM-DD HH:MM. Prioridade 1 (máxima) a 4. Horizonte de metas: "
                "short, medium, long."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "get",
                            "add",
                            "update",
                            "delete",
                            "complete_task",
                            "log_habit",
                            "plan",
                        ],
                    },
                    "entity": {"type": "string", "enum": list(ENTITY_NAMES)},
                    "id": {"type": "integer"},
                    "data": {
                        "type": "object",
                        "description": "Campos do registro (add/update) ou filtros (list).",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filtro de status (list).",
                    },
                    "title": {
                        "type": "string",
                        "description": "Título do plano (plan).",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Etapas concretas, em ordem (plan).",
                    },
                    "goal_id": {"type": "integer"},
                    "start_date": {"type": "string"},
                    "every_days": {"type": "integer"},
                    "date": {
                        "type": "string",
                        "description": "Data do registro de hábito.",
                    },
                },
                "required": ["action"],
            },
            category="planning",
            required_capabilities=["memory:write"],
        )

    def lifeos_category(self, arguments: Dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).lower()
        if action in ("list", "get"):
            return "read"
        if action == "delete":
            return "planning_delete"
        if action in ("add", "update", "complete_task", "log_habit", "plan"):
            return "planning_write"
        return "unknown"

    def _run(self, **p: Any) -> ToolResult:
        planner = self.lifeos.planner
        action = str(p.get("action", "")).lower()
        entity = str(p.get("entity") or "task").lower()
        data: Dict[str, Any] = dict(p.get("data") or {})
        if action == "list":
            return self._ok(
                planner.list(entity, status=p.get("status"), **data)
                or "Nenhum registro."
            )
        if action == "get":
            return self._ok(planner.get(entity, int(p["id"])))
        if action == "add":
            return self._ok({"criado": planner.add(entity, **data)})
        if action == "update":
            return self._ok(
                {"atualizado": planner.update(entity, int(p["id"]), **data)}
            )
        if action == "delete":
            return self._ok({"excluido": planner.delete(entity, int(p["id"]))})
        if action == "complete_task":
            return self._ok({"concluida": planner.complete_task(int(p["id"]))})
        if action == "log_habit":
            return self._ok(
                planner.log_habit(
                    int(p["id"]), p.get("date"), str(data.get("note", ""))
                )
            )
        if action == "plan":
            result = planner.plan_steps(
                str(p.get("title") or data.get("title") or ""),
                list(p.get("steps") or data.get("steps") or []),
                goal_id=p.get("goal_id") or data.get("goal_id"),
                start_date=p.get("start_date") or data.get("start_date"),
                every_days=int(p.get("every_days") or data.get("every_days") or 0),
            )
            return self._ok(result)
        return self._fail(f"Ação desconhecida '{action}'")


@ToolRegistry.register("lifeos_review")
class LifeOSReviewTool(_LifeOSTool):
    tool_id = "lifeos_review"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="lifeos_review",
            description=(
                "Relatórios a partir dos dados reais do LifeOS: alerts (atrasos, "
                "prazos, conflitos, projetos parados, sobrecarga), morning "
                "(relatório matinal), evening (revisão noturna; aceita notes com "
                "obstáculos), weekly, monthly, status. save=true arquiva a revisão."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["alerts", "status", *REVIEW_KINDS],
                    },
                    "notes": {"type": "string"},
                    "save": {"type": "boolean"},
                },
                "required": ["kind"],
            },
            category="planning",
            required_capabilities=["memory:read"],
        )

    def lifeos_category(self, arguments: Dict[str, Any]) -> str:
        kind = str(arguments.get("kind", "")).lower()
        if kind in ("alerts", "status"):
            return "read"
        return "report" if arguments.get("save") else "read"

    def _run(self, **p: Any) -> ToolResult:
        kind = str(p.get("kind", "")).lower()
        if kind == "alerts":
            alerts = self.lifeos.reviews.alerts()
            return self._ok([a.to_dict() for a in alerts] or "Nenhum alerta.")
        if kind == "status":
            return self._ok(self.lifeos.status())
        notes = str(p.get("notes") or "")
        report = self.lifeos.reviews.build(kind, notes=notes)
        if p.get("save"):
            review_id = self.lifeos.reviews.save(report, notes=notes)
            return self._ok(f"{report.text}\n\n(Revisão arquivada: #{review_id})")
        return self._ok(report.text)


LIFEOS_TOOL_CLASSES: Dict[str, type] = {
    "lifeos_memory": LifeOSMemoryTool,
    "lifeos_planner": LifeOSPlannerTool,
    "lifeos_review": LifeOSReviewTool,
}


def ensure_registered() -> None:
    """Re-register LifeOS tools (idempotent; tests clear registries)."""
    for name, cls in LIFEOS_TOOL_CLASSES.items():
        if not ToolRegistry.contains(name):
            ToolRegistry.register_value(name, cls)


def build_lifeos_tools(lifeos: Optional[Any] = None) -> list[BaseTool]:
    return [cls(lifeos=lifeos) for cls in LIFEOS_TOOL_CLASSES.values()]


__all__ = [
    "LIFEOS_TOOL_CLASSES",
    "LifeOSMemoryTool",
    "LifeOSPlannerTool",
    "LifeOSReviewTool",
    "build_lifeos_tools",
    "ensure_registered",
]

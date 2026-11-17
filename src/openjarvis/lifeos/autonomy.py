# ruff: noqa: E501
"""Risk-based autonomy policy.

Levels
------
1 CONSULTIVE  answer, analyze, recommend. Only read-only actions run.
2 ASSISTED    every action with side effects requires the user's approval.
3 AUTHORIZED  categories the user pre-authorized (grants) run on their own.
4 PROACTIVE   as 3, plus JARVIS may monitor goals and propose initiatives.

Invariants independent of level
-------------------------------
* HIGH risk (send messages, delete data, change configuration, run code)
  always requires confirmation and can never be pre-authorized.
* CRITICAL risk (purchases, payments, money transfers) always requires
  explicit confirmation and can never be pre-authorized.
* Unknown tools are treated as HIGH risk (fail closed).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Dict, Iterable, Optional


class AutonomyLevel(IntEnum):
    CONSULTIVE = 1
    ASSISTED = 2
    AUTHORIZED = 3
    PROACTIVE = 4


LEVEL_LABELS = {
    AutonomyLevel.CONSULTIVE: "consultivo",
    AutonomyLevel.ASSISTED: "assistido",
    AutonomyLevel.AUTHORIZED: "autorizado",
    AutonomyLevel.PROACTIVE: "proativo",
}


class Risk(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Category:
    name: str
    risk: Risk
    description: str

    @property
    def grantable(self) -> bool:
        return self.risk in (Risk.LOW, Risk.MEDIUM)


CATEGORIES: Dict[str, Category] = {
    c.name: c
    for c in (
        Category("read", Risk.NONE, "Consultar dados locais sem alterar nada"),
        Category("report", Risk.LOW, "Gerar e salvar relatórios e revisões"),
        Category("memory_write", Risk.LOW, "Registrar ou corrigir memória"),
        Category(
            "planning_write",
            Risk.LOW,
            "Criar/atualizar metas, projetos, tarefas, hábitos",
        ),
        Category(
            "external_request", Risk.MEDIUM, "Consultar serviços externos (web, APIs)"
        ),
        Category(
            "file_organize",
            Risk.MEDIUM,
            "Criar, anexar ou mover arquivos dentro das pastas permitidas de JARVIS-LifeOS",
        ),
        Category("schedule", Risk.MEDIUM, "Criar ou alterar agendamentos"),
        Category("memory_delete", Risk.HIGH, "Apagar memória"),
        Category("planning_delete", Risk.HIGH, "Apagar metas, projetos, tarefas"),
        Category("file_delete", Risk.HIGH, "Excluir arquivos"),
        Category(
            "file_modify",
            Risk.HIGH,
            "Modificar ou sobrescrever documentos existentes, ou escrever fora de JARVIS-LifeOS",
        ),
        Category(
            "external_action",
            Risk.HIGH,
            "Operações externas sensíveis (enviar dados, preencher formulários, APIs com efeito)",
        ),
        Category("message_send", Risk.HIGH, "Enviar mensagens ou e-mails"),
        Category("config_change", Risk.HIGH, "Alterar configurações importantes"),
        Category("code_execution", Risk.HIGH, "Executar código ou comandos"),
        Category(
            "financial", Risk.CRITICAL, "Compras, pagamentos, movimentações financeiras"
        ),
        Category("unknown", Risk.HIGH, "Ferramenta sem classificação"),
    )
}

# Classification of OpenJarvis built-in tools (by tool name).
BUILTIN_TOOL_CATEGORIES: Dict[str, str] = {
    "think": "read",
    "calculator": "read",
    "file_read": "read",
    "retrieval": "read",
    "memory_search": "read",
    "memory_retrieve": "read",
    "kg_query": "read",
    "kg_neighbors": "read",
    "knowledge_search": "read",
    "knowledge_sql": "read",
    "scan_chunks": "read",
    "pdf_extract": "read",
    "list_scheduled_tasks": "read",
    "get_pending_actions": "read",
    "check_permission": "read",
    "agent_list": "read",
    "llm": "read",
    "memory_store": "memory_write",
    "memory_index": "memory_write",
    "memory_manage": "memory_write",
    "user_profile_manage": "memory_write",
    "kg_add_entity": "memory_write",
    "kg_add_relation": "memory_write",
    "web_search": "external_request",
    "weather": "external_request",
    "http_request": "external_action",
    "browser_navigate": "external_request",
    "browser_extract": "external_request",
    "browser_screenshot": "external_request",
    "browser_axtree": "external_request",
    "browser_click": "external_action",
    "browser_type": "external_action",
    # Native file tools are not confined to JARVIS-LifeOS: treat as high risk.
    "file_write": "file_modify",
    "apply_patch": "file_modify",
    "schedule_task": "schedule",
    "pause_scheduled_task": "schedule",
    "resume_scheduled_task": "schedule",
    "cancel_scheduled_task": "schedule",
    "channel_send": "message_send",
    "shell_exec": "code_execution",
    "docker_shell_exec": "code_execution",
    "code_interpreter": "code_execution",
    "code_interpreter_docker": "code_execution",
    "repl": "code_execution",
    "git": "code_execution",
    "db_query": "code_execution",
    "agent_spawn": "code_execution",
    "agent_kill": "config_change",
    "skill_manage": "config_change",
    "execute_pending_actions": "config_change",
}


def category_of(name: str) -> Category:
    return CATEGORIES.get(name, CATEGORIES["unknown"])


def classify_tool_call(
    tool: Any, tool_name: str, arguments: Dict[str, Any]
) -> Category:
    """Return the category for a concrete call.

    Tools may expose ``lifeos_category(arguments) -> str`` to classify
    themselves per action (LifeOS tools do). Otherwise the built-in table is
    used; anything unknown fails closed.
    """
    classifier = getattr(tool, "lifeos_category", None)
    if callable(classifier):
        try:
            return category_of(str(classifier(arguments)))
        except Exception:
            return CATEGORIES["unknown"]
    return category_of(BUILTIN_TOOL_CATEGORIES.get(tool_name, "unknown"))


def call_fingerprint(tool_name: str, arguments: Dict[str, Any]) -> str:
    payload = json.dumps(
        {"tool": tool_name, "args": arguments}, sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Verdict
    category: Category
    level: AutonomyLevel
    reason: str


def decide(
    category: Category,
    level: AutonomyLevel | int,
    grants: Iterable[str] = (),
) -> PolicyDecision:
    """Pure policy function: what may happen with this category at this level."""
    level = AutonomyLevel(int(level))
    granted = set(grants)
    risk = category.risk
    if risk is Risk.NONE:
        return PolicyDecision(Verdict.ALLOW, category, level, "ação somente leitura")
    if level is AutonomyLevel.CONSULTIVE:
        return PolicyDecision(
            Verdict.DENY,
            category,
            level,
            "modo consultivo: apenas análise e recomendação, sem execução",
        )
    if risk is Risk.CRITICAL:
        return PolicyDecision(
            Verdict.ASK,
            category,
            level,
            "risco crítico: exige confirmação explícita a cada execução",
        )
    if risk is Risk.HIGH:
        return PolicyDecision(
            Verdict.ASK,
            category,
            level,
            "risco alto: exige confirmação a cada execução",
        )
    if level >= AutonomyLevel.AUTHORIZED and category.name in granted:
        return PolicyDecision(
            Verdict.ALLOW, category, level, "categoria pré-autorizada"
        )
    return PolicyDecision(
        Verdict.ASK,
        category,
        level,
        "requer autorização (categoria não pré-autorizada neste nível)",
    )


def describe_policy(level: AutonomyLevel | int, grants: Iterable[str]) -> str:
    """Human/LLM-readable summary of what JARVIS may do right now."""
    level = AutonomyLevel(int(level))
    granted = sorted(set(grants))
    lines = [f"Nível de autonomia: {int(level)} ({LEVEL_LABELS[level]})."]
    if level is AutonomyLevel.CONSULTIVE:
        lines.append("Somente consultas. Não execute ações; recomende.")
    elif level is AutonomyLevel.ASSISTED:
        lines.append(
            "Prepare ações; toda ação com efeito exige autorização do usuário."
        )
    else:
        lines.append(
            "Pré-autorizado: "
            + (", ".join(granted) if granted else "nenhuma categoria")
            + "."
        )
        if level is AutonomyLevel.PROACTIVE:
            lines.append(
                "Monitore objetivos e proponha iniciativas quando houver motivo concreto."
            )
    lines.append(
        "Sempre exigem confirmação: envio de mensagens, exclusões, modificação "
        "de documentos existentes, operações externas sensíveis, mudanças de "
        "configuração e execução de código. Nunca execute compras, pagamentos ou "
        "movimentações financeiras sem confirmação explícita. Arquivos: somente "
        "dentro de JARVIS-LifeOS, respeitando a permissão de cada pasta."
    )
    return " ".join(lines)


def parse_level(value: Optional[Any]) -> AutonomyLevel:
    try:
        return AutonomyLevel(int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("nível de autonomia deve ser 1, 2, 3 ou 4") from exc


__all__ = [
    "AutonomyLevel",
    "BUILTIN_TOOL_CATEGORIES",
    "CATEGORIES",
    "Category",
    "LEVEL_LABELS",
    "PolicyDecision",
    "Risk",
    "Verdict",
    "call_fingerprint",
    "category_of",
    "classify_tool_call",
    "decide",
    "describe_policy",
    "parse_level",
]

# ruff: noqa: E501
"""``jarvis lifeos`` — command line for JARVIS LifeOS."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import click

from openjarvis.lifeos.autonomy import CATEGORIES, LEVEL_LABELS, AutonomyLevel


def _lifeos() -> Any:
    from openjarvis.lifeos.service import get_lifeos

    return get_lifeos()


def _echo_json(data: Any) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _pairs(values: Tuple[str, ...]) -> Dict[str, Any]:
    """Parse ``field=value`` arguments; ints are converted when obvious."""
    out: Dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(f"use campo=valor (recebido '{item}')")
        key, value = item.split("=", 1)
        key = key.strip()
        if key.endswith("_id") or key in ("priority", "target_per_period"):
            try:
                out[key] = int(value)
                continue
            except ValueError:
                pass
        out[key] = value
    return out


def _guard(fn):
    """Turn domain errors into clean CLI errors."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from openjarvis.lifeos.memory import LifeOSMemoryError, MemoryConflict
        from openjarvis.lifeos.planner import PlannerError
        from openjarvis.lifeos.service import LifeOSError

        try:
            return fn(*args, **kwargs)
        except (
            LifeOSError,
            LifeOSMemoryError,
            MemoryConflict,
            PlannerError,
            ValueError,
        ) as exc:
            raise click.ClickException(str(exc)) from None

    return wrapper


@click.group()
def lifeos() -> None:
    """JARVIS LifeOS: memória, organização, revisões e autonomia."""


# -- setup & status --------------------------------------------------------------


@lifeos.command()
@click.option(
    "--force-config", is_flag=True, help="Recria lifeos.toml (faz backup .bak)."
)
@_guard
def init(force_config: bool) -> None:
    """Cria configuração, persona e banco de dados locais."""
    from openjarvis.lifeos.config import write_default_config

    cfg_path = write_default_config(overwrite=force_config)
    lo = _lifeos()
    click.echo(f"Configuração: {cfg_path}")
    click.echo(f"Persona:      {lo.persona_path}")
    click.echo(f"Banco:        {lo.db.path}")
    click.echo(
        f"Autonomia:    {int(lo.autonomy_level)} ({LEVEL_LABELS[lo.autonomy_level]})"
    )
    click.echo("Pronto. Converse com: jarvis lifeos chat")


@lifeos.command()
@click.option("--json", "as_json", is_flag=True)
@_guard
def status(as_json: bool) -> None:
    """Resumo do estado do LifeOS."""
    data = _lifeos().status()
    if as_json:
        _echo_json(data)
        return
    p, m = data["planner"], data["memory"]
    click.echo(
        f"Autonomia: nível {data['autonomy_level']} | pré-autorizado: {', '.join(data['grants']) or '-'}"
    )
    click.echo(
        f"Memória: {m['total']} registros ativos | busca semântica: {'sim' if data['semantic_search'] else 'não'}"
    )
    click.echo(
        f"Metas {p['goals_active']} | Projetos {p['projects_active']} | Tarefas abertas "
        f"{p['tasks_open']} (atrasadas {p['tasks_overdue']}) | Hábitos {p['habits_active']}"
    )
    click.echo(
        f"Pendências de aprovação: {data['pending_actions']} | Registros de auditoria: {data['audit_entries']}"
    )
    click.echo(f"Banco: {data['db_path']}")


# -- chat ------------------------------------------------------------------------


def _resolve_engine(engine_key: Optional[str], model: Optional[str]) -> Tuple[Any, str]:
    from openjarvis.core.config import load_config
    from openjarvis.engine import get_engine
    from openjarvis.intelligence import register_builtin_models

    config = load_config()
    register_builtin_models()
    key = engine_key or config.intelligence.preferred_engine or None
    wanted = model or config.intelligence.default_model or None
    resolved = get_engine(config, key, model=wanted)
    if resolved is None:
        raise click.ClickException(
            "Nenhum motor de inferência disponível. Inicie o Ollama (ollama serve) "
            "ou configure outro motor; veja 'jarvis doctor'."
        )
    _, engine = resolved
    if not wanted:
        try:
            models = engine.list_models()
        except Exception:
            models = []
        wanted = models[0] if models else config.intelligence.fallback_model
    if not wanted:
        raise click.ClickException("Nenhum modelo disponível no motor. Use --model.")
    return engine, wanted


def _terminal_approval(name: str, args: dict, decision: Any) -> bool:
    click.echo("")
    click.secho("JARVIS solicita autorização", fg="yellow", bold=True)
    click.echo(f"  ação:      {name}")
    click.echo(
        f"  categoria: {decision.category.name} (risco {decision.category.risk.value})"
    )
    click.echo(f"  motivo:    {decision.reason}")
    click.echo(f"  dados:     {json.dumps(args, ensure_ascii=False)[:600]}")
    return click.confirm("  Autorizar?", default=False)


@lifeos.command()
@click.option("-m", "--model", default=None, help="Modelo (padrão: o do config.toml).")
@click.option("-e", "--engine", "engine_key", default=None, help="Motor de inferência.")
@click.option("-s", "--session", "session_id", default=None, help="Retomar sessão.")
@click.option(
    "-q", "--query", default=None, help="Pergunta única (sem modo interativo)."
)
@_guard
def chat(
    model: Optional[str],
    engine_key: Optional[str],
    session_id: Optional[str],
    query: Optional[str],
) -> None:
    """Conversa com o JARVIS (pede autorização no terminal quando necessário)."""
    from openjarvis.core.config import load_config
    from openjarvis.lifeos.agent import JarvisOrchestratorAgent
    from openjarvis.prompt.builder import SystemPromptBuilder

    engine, model_name = _resolve_engine(engine_key, model)
    config = load_config()
    agent = JarvisOrchestratorAgent(
        engine,
        model_name,
        lifeos=_lifeos(),
        session_id=session_id,
        approval_callback=_terminal_approval if sys.stdin.isatty() else None,
        prompt_builder=SystemPromptBuilder(
            agent_template="",
            memory_files_config=config.memory_files,
            system_prompt_config=config.system_prompt,
        ),
    )
    if query is not None:
        click.echo(agent.run(query).content)
        return
    click.secho(
        f"JARVIS LifeOS — sessão {agent.session_id} — modelo {model_name}", fg="green"
    )
    click.echo("Digite 'sair' para encerrar.\n")
    while True:
        try:
            text = click.prompt(click.style("você", fg="green"), prompt_suffix=" › ")
        except (EOFError, click.Abort):
            break
        if text.strip().lower() in ("sair", "exit", "quit"):
            break
        try:
            reply = agent.run(text).content
        except Exception as exc:  # engine down, context overflow, ...
            click.secho(f"Erro: {exc}", fg="red")
            continue
        click.secho("jarvis › ", fg="green", nl=False)
        click.echo(reply)


# -- memory ----------------------------------------------------------------------


@lifeos.group()
def memory() -> None:
    """Consultar, registrar, corrigir e apagar memória."""


@memory.command("add")
@click.argument("content")
@click.option("--layer", default="personal", show_default=True)
@click.option("--subject", default="")
@click.option("--hypothesis", is_flag=True, help="Registrar como hipótese.")
@click.option("--tags", default="")
@click.option(
    "--replace", is_flag=True, help="Substituir registro com o mesmo assunto."
)
@_guard
def memory_add(content, layer, subject, hypothesis, tags, replace) -> None:
    rec, created = _lifeos().memory.remember(
        content,
        layer=layer,
        subject=subject,
        tags=tags,
        replace=replace,
        status="hypothesis" if hypothesis else "confirmed",
        source="user_cli",
    )
    click.echo(
        f"{'Registrado' if created else 'Já existia'}: #{rec.id} [{rec.layer}|{rec.status}] {rec.content}"
    )


@memory.command("search")
@click.argument("query")
@click.option("--layer", multiple=True)
@click.option("--limit", default=10, show_default=True)
@_guard
def memory_search(query, layer, limit) -> None:
    hits = _lifeos().memory.search(query, layers=list(layer) or None, limit=limit)
    if not hits:
        click.echo("Nada encontrado.")
    for h in hits:
        click.echo(f"#{h.id} [{h.layer}|{h.status}] {h.content}  ({h.updated_at[:10]})")


@memory.command("list")
@click.option("--layer", default=None)
@click.option(
    "--all", "include_inactive", is_flag=True, help="Incluir versões antigas."
)
@click.option("--limit", default=50, show_default=True)
@_guard
def memory_list(layer, include_inactive, limit) -> None:
    for r in _lifeos().memory.list(
        layer, include_inactive=include_inactive, limit=limit
    ):
        flag = "" if r.active else f" (substituída por #{r.superseded_by})"
        click.echo(f"#{r.id} [{r.layer}|{r.status}] {r.content}{flag}")


@memory.command("correct")
@click.argument("memory_id", type=int)
@click.option("--content", default=None)
@click.option("--status", type=click.Choice(["confirmed", "hypothesis"]), default=None)
@_guard
def memory_correct(memory_id, content, status) -> None:
    rec = _lifeos().memory.correct(memory_id, content=content, status=status)
    click.echo(f"Nova versão #{rec.id} [{rec.status}] {rec.content}")


@memory.command("forget")
@click.argument("memory_id", type=int)
@click.option("--yes", is_flag=True, help="Não pedir confirmação.")
@_guard
def memory_forget(memory_id, yes) -> None:
    lo = _lifeos()
    rec = lo.memory.get(memory_id)
    if not yes and not click.confirm(
        f"Apagar definitivamente #{rec.id} '{rec.content}' e seu histórico?"
    ):
        return
    n = lo.memory.forget(memory_id)
    lo.actions.record(
        actor="user",
        action="memory_forget",
        category="memory_delete",
        risk="high",
        autonomy_level=int(lo.autonomy_level),
        decision="executed",
        params={"id": memory_id},
        result=f"{n} registro(s)",
        success=True,
    )
    click.echo(f"Apagados {n} registro(s).")


@memory.command("history")
@click.argument("memory_id", type=int)
@_guard
def memory_history(memory_id) -> None:
    for r in _lifeos().memory.history(memory_id):
        click.echo(
            f"#{r.id} {r.updated_at} [{r.status}] {r.content} {'(ativa)' if r.active else ''}"
        )


@memory.command("reindex")
@_guard
def memory_reindex() -> None:
    """Gera embeddings faltantes (requer [semantic] enabled = true)."""
    n = _lifeos().memory.reindex_embeddings()
    click.echo(f"{n} memória(s) indexada(s).")


# -- planner ---------------------------------------------------------------------

_KINDS = click.Choice(["goal", "project", "task", "habit", "commitment", "decision"])


@lifeos.command("add")
@click.argument("kind", type=_KINDS)
@click.argument("fields", nargs=-1)
@_guard
def add_item(kind, fields) -> None:
    """Criar item. Ex.: jarvis lifeos add task title="Lista 3" priority=1 due_date=2026-11-20"""
    item = _lifeos().planner.add(kind, **_pairs(fields))
    click.echo(f"Criado {kind} #{item['id']}: {item['title']}")


@lifeos.command("list")
@click.argument("kind", type=_KINDS)
@click.option("--status", default=None, help="Ex.: todo,doing")
@click.option("--json", "as_json", is_flag=True)
@_guard
def list_items(kind, status, as_json) -> None:
    """Listar itens."""
    items = _lifeos().planner.list(kind, status=status)
    if as_json:
        _echo_json(items)
        return
    if not items:
        click.echo("Nenhum registro.")
    for it in items:
        extra = []
        for key in (
            "status",
            "priority",
            "due_date",
            "deadline",
            "target_date",
            "starts_at",
            "horizon",
            "cadence",
        ):
            if it.get(key) not in (None, ""):
                extra.append(f"{key}={it[key]}")
        click.echo(f"#{it['id']} {it['title']}  [{' '.join(extra)}]")


@lifeos.command("update")
@click.argument("kind", type=_KINDS)
@click.argument("item_id", type=int)
@click.argument("fields", nargs=-1)
@_guard
def update_item(kind, item_id, fields) -> None:
    """Atualizar item. Ex.: jarvis lifeos update task 3 status=doing"""
    item = _lifeos().planner.update(kind, item_id, **_pairs(fields))
    click.echo(f"Atualizado {kind} #{item['id']}")


@lifeos.command("delete")
@click.argument("kind", type=_KINDS)
@click.argument("item_id", type=int)
@click.option("--yes", is_flag=True)
@_guard
def delete_item(kind, item_id, yes) -> None:
    """Excluir item (pede confirmação)."""
    lo = _lifeos()
    item = lo.planner.get(kind, item_id)
    if not yes and not click.confirm(f"Excluir {kind} #{item_id} '{item['title']}'?"):
        return
    lo.planner.delete(kind, item_id)
    lo.actions.record(
        actor="user",
        action=f"delete_{kind}",
        category="planning_delete",
        risk="high",
        autonomy_level=int(lo.autonomy_level),
        decision="executed",
        params={"id": item_id},
        result=item["title"],
        success=True,
    )
    click.echo("Excluído.")


@lifeos.command("done")
@click.argument("task_id", type=int)
@_guard
def done(task_id) -> None:
    """Concluir tarefa."""
    t = _lifeos().planner.complete_task(task_id)
    click.echo(f"Concluída: #{t['id']} {t['title']}")


@lifeos.command("habit-log")
@click.argument("habit_id", type=int)
@click.option("--date", "log_date", default=None, help="AAAA-MM-DD (padrão: hoje)")
@click.option("--note", default="")
@_guard
def habit_log(habit_id, log_date, note) -> None:
    """Registrar execução de hábito."""
    r = _lifeos().planner.log_habit(habit_id, log_date, note)
    click.echo(f"Hábito #{r['habit_id']} registrado em {r['log_date']}")


@lifeos.command("plan")
@click.argument("title")
@click.argument("steps", nargs=-1, required=True)
@click.option("--goal", "goal_id", type=int, default=None)
@click.option("--start", "start_date", default=None)
@click.option("--every", "every_days", type=int, default=0)
@_guard
def plan(title, steps, goal_id, start_date, every_days) -> None:
    """Transformar objetivo em projeto com etapas concretas."""
    result = _lifeos().planner.plan_steps(
        title,
        list(steps),
        goal_id=goal_id,
        start_date=start_date,
        every_days=every_days,
    )
    click.echo(f"Projeto #{result['project']['id']} {result['project']['title']}")
    for t in result["tasks"]:
        click.echo(f"  #{t['id']} {t['title']} {t['due_date'] or ''}")


# -- reviews ---------------------------------------------------------------------


@lifeos.command()
@click.argument("kind", type=click.Choice(["morning", "evening", "weekly", "monthly"]))
@click.option("--notes", default="", help="Obstáculos/observações (revisão noturna).")
@click.option("--save", is_flag=True, help="Arquivar a revisão.")
@_guard
def review(kind, notes, save) -> None:
    """Gerar revisão periódica."""
    lo = _lifeos()
    report = lo.reviews.build(kind, notes=notes)
    click.echo(report.text)
    if save:
        rid = lo.reviews.save(report, notes=notes)
        lo.actions.record(
            actor="user",
            action=f"review_{kind}",
            category="report",
            risk="low",
            autonomy_level=int(lo.autonomy_level),
            decision="executed",
            params={"period": report.period_key},
            result=f"review #{rid}",
            success=True,
        )
        click.echo(f"\n(arquivada #{rid})")


@lifeos.command()
@_guard
def alerts() -> None:
    """Alertas atuais (atrasos, conflitos, sobrecarga...)."""
    items = _lifeos().reviews.alerts()
    if not items:
        click.echo("Nenhum alerta.")
    for a in items:
        click.echo(f"[{a.severity}] {a.message}")


# -- autonomy, approvals, audit --------------------------------------------------


@lifeos.group()
def autonomy() -> None:
    """Nível de autonomia e pré-autorizações."""


@autonomy.command("show")
@_guard
def autonomy_show() -> None:
    lo = _lifeos()
    click.echo(lo.policy_summary())
    click.echo("\nCategorias:")
    granted = set(lo.grants())
    for c in CATEGORIES.values():
        mark = "✔" if c.name in granted else (" " if c.grantable else "✖")
        click.echo(f"  {mark} {c.name:17} risco={c.risk.value:8} {c.description}")
    click.echo("\n✔ pré-autorizada  ✖ nunca pré-autorizável")


@autonomy.command("set")
@click.argument("level", type=click.IntRange(1, 4))
@_guard
def autonomy_set(level) -> None:
    new = _lifeos().set_autonomy_level(level)
    click.echo(f"Autonomia: {int(new)} ({LEVEL_LABELS[AutonomyLevel(new)]})")


@autonomy.command("grant")
@click.argument("category")
@click.option("--note", default="")
@_guard
def autonomy_grant(category, note) -> None:
    _lifeos().grant(category, note=note)
    click.echo(f"Pré-autorizado: {category} (vale nos níveis 3 e 4)")


@autonomy.command("revoke")
@click.argument("category")
@_guard
def autonomy_revoke(category) -> None:
    removed = _lifeos().revoke(category)
    click.echo("Revogado." if removed else "Não estava autorizado.")


@lifeos.group()
def approvals() -> None:
    """Ações aguardando sua aprovação."""


@approvals.command("list")
@_guard
def approvals_list() -> None:
    items = _lifeos().list_pending()
    if not items:
        click.echo("Nenhuma pendência.")
    for it in items:
        click.echo(
            f"{it['id']}  {it['tool']}  [{it['category']}/{it['risk']}]  {json.dumps(it['arguments'], ensure_ascii=False)[:200]}"
        )


@approvals.command("approve")
@click.argument("action_id")
@_guard
def approvals_approve(action_id) -> None:
    out = _lifeos().approve(action_id)
    if out["executed"]:
        click.echo(f"Executada ({out['status']}):\n{out.get('result', '')}")
    else:
        click.echo(
            "Aprovada para uso único: o JARVIS poderá executá-la ao repetir o pedido."
        )


@approvals.command("deny")
@click.argument("action_id")
@_guard
def approvals_deny(action_id) -> None:
    _lifeos().deny(action_id)
    click.echo("Negada.")


@lifeos.command()
@click.option("--limit", default=30, show_default=True)
@click.option(
    "--verify", is_flag=True, help="Verificar integridade da cadeia de hashes."
)
@_guard
def audit(limit, verify) -> None:
    """Histórico auditável de ações."""
    lo = _lifeos()
    if verify:
        ok, bad = lo.actions.verify()
        click.echo(
            "Cadeia íntegra." if ok else f"ADULTERAÇÃO detectada no registro #{bad}."
        )
        if not ok:
            sys.exit(2)
        return
    for e in lo.actions.list(limit=limit):
        status = "" if e["success"] is None else (" ok" if e["success"] else " FALHA")
        click.echo(
            f"#{e['id']} {e['ts']} {e['actor']:20} {e['action']:20} {e['category']:15} {e['decision']}{status}"
        )


# -- data & persona --------------------------------------------------------------


@lifeos.command()
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path))
@_guard
def export(path) -> None:
    """Exportar todos os dados LifeOS para JSON."""
    out = _lifeos().export_to(path)
    click.echo(f"Exportado: {out}")


@lifeos.command()
@click.option("--yes", is_flag=True)
@click.option(
    "--include-audit", is_flag=True, help="Apagar também o registro de auditoria."
)
@_guard
def wipe(yes, include_audit) -> None:
    """Apagar dados pessoais do LifeOS (irreversível)."""
    if not yes and not click.confirm(
        "Apagar TODA a memória e organização do LifeOS? Irreversível."
    ):
        return
    counts = _lifeos().wipe(keep_audit=not include_audit)
    _echo_json(counts)


@lifeos.group()
def persona() -> None:
    """Personalidade do JARVIS."""


@persona.command("show")
@_guard
def persona_show() -> None:
    click.echo(_lifeos().persona_text())


@persona.command("path")
@_guard
def persona_path() -> None:
    click.echo(_lifeos().persona_path)


@persona.command("reset")
@click.option("--yes", is_flag=True)
@_guard
def persona_reset(yes) -> None:
    from openjarvis.lifeos.persona import reset_persona

    lo = _lifeos()
    if not yes and not click.confirm(
        "Restaurar persona padrão (backup .bak será criado)?"
    ):
        return
    reset_persona(lo.persona_path)
    click.echo("Persona restaurada.")


__all__ = ["lifeos"]

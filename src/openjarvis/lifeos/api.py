"""HTTP API (``/v1/lifeos/*``) and local dashboard (``/lifeos``).

Mounted by ``openjarvis.server.app.create_app``. ``/v1/*`` routes inherit
the server's API-key middleware; the dashboard page itself holds no data and
reads everything through the API.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

_STATIC = Path(__file__).parent / "static"
_CHAT_LOCK = threading.Lock()


def _lifeos() -> Any:
    from openjarvis.lifeos.service import get_lifeos

    return get_lifeos()


def _guarded(fn, *args, **kwargs):
    from openjarvis.lifeos.memory import LifeOSMemoryError, MemoryConflict
    from openjarvis.lifeos.planner import PlannerError
    from openjarvis.lifeos.service import LifeOSError
    from openjarvis.lifeos.workspace import WorkspaceError

    try:
        return fn(*args, **kwargs)
    except WorkspaceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except MemoryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (LifeOSError, LifeOSMemoryError, PlannerError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class MemoryIn(BaseModel):
    content: str
    layer: str = "personal"
    subject: str = ""
    status: str = "confirmed"
    tags: str = ""
    replace: bool = False


class MemoryPatch(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None


class AutonomyIn(BaseModel):
    level: int = Field(ge=1, le=4)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: Optional[str] = None


class ReviewIn(BaseModel):
    notes: str = ""


def create_lifeos_router() -> APIRouter:
    router = APIRouter()

    @router.get("/lifeos", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> HTMLResponse:
        return HTMLResponse((_STATIC / "dashboard.html").read_text(encoding="utf-8"))

    api = APIRouter(prefix="/v1/lifeos", tags=["lifeos"])

    @api.get("/status")
    def status() -> Dict[str, Any]:
        return _lifeos().status()

    @api.get("/system")
    def system(request: Request) -> Dict[str, Any]:
        """Real CPU/RAM usage and model state (Ollama /api/ps when available)."""
        from openjarvis.lifeos.system import snapshot

        state = request.app.state
        data = snapshot(
            getattr(state, "engine", None),
            getattr(state, "engine_name", ""),
            getattr(state, "model", ""),
        )
        speech = getattr(state, "speech_backend", None)
        try:
            data["speech_input"] = bool(speech is not None and speech.health())
        except Exception:
            data["speech_input"] = False
        return data

    @api.get("/files")
    def files(path: str = "") -> List[Dict[str, Any]]:
        return _guarded(_lifeos().workspace.list, path)

    @api.post("/backup")
    def backup(label: str = "") -> Dict[str, Any]:
        return _lifeos().backup(label)

    # -- memory --
    @api.get("/memory")
    def memory_list(
        q: str = "", layer: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        mem = _lifeos().memory
        if q:
            recs = _guarded(
                mem.search, q, layers=[layer] if layer else None, limit=limit
            )
        else:
            recs = _guarded(mem.list, layer or None, limit=limit)
        return [r.to_dict() for r in recs]

    @api.post("/memory")
    def memory_add(body: MemoryIn) -> Dict[str, Any]:
        rec, created = _guarded(
            _lifeos().memory.remember,
            body.content,
            layer=body.layer,
            subject=body.subject,
            status=body.status,
            tags=body.tags,
            replace=body.replace,
            source="user_ui",
        )
        return {"created": created, "memory": rec.to_dict()}

    @api.patch("/memory/{memory_id}")
    def memory_correct(memory_id: int, body: MemoryPatch) -> Dict[str, Any]:
        rec = _guarded(
            _lifeos().memory.correct,
            memory_id,
            content=body.content,
            status=body.status,
        )
        return rec.to_dict()

    @api.delete("/memory/{memory_id}")
    def memory_forget(memory_id: int) -> Dict[str, Any]:
        lo = _lifeos()
        n = _guarded(lo.memory.forget, memory_id)
        lo.actions.record(
            actor="user_ui",
            action="memory_forget",
            category="memory_delete",
            risk="high",
            autonomy_level=int(lo.autonomy_level),
            decision="executed",
            params={"id": memory_id},
            result=f"{n} registro(s)",
            success=True,
        )
        return {"deleted": n}

    # -- planner --
    @api.get("/items/{kind}")
    def items_list(kind: str, status: str = "") -> List[Dict[str, Any]]:
        return _guarded(_lifeos().planner.list, kind, status=status or None)

    @api.post("/items/{kind}")
    def items_add(kind: str, data: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        return _guarded(_lifeos().planner.add, kind, **data)

    @api.patch("/items/{kind}/{item_id}")
    def items_update(
        kind: str, item_id: int, data: Dict[str, Any] = Body(...)
    ) -> Dict[str, Any]:
        return _guarded(_lifeos().planner.update, kind, item_id, **data)

    @api.delete("/items/{kind}/{item_id}")
    def items_delete(kind: str, item_id: int) -> Dict[str, Any]:
        lo = _lifeos()
        item = _guarded(lo.planner.delete, kind, item_id)
        lo.actions.record(
            actor="user_ui",
            action=f"delete_{kind}",
            category="planning_delete",
            risk="high",
            autonomy_level=int(lo.autonomy_level),
            decision="executed",
            params={"id": item_id},
            result=str(item.get("title", "")),
            success=True,
        )
        return item

    @api.post("/tasks/{task_id}/done")
    def task_done(task_id: int) -> Dict[str, Any]:
        return _guarded(_lifeos().planner.complete_task, task_id)

    @api.post("/habits/{habit_id}/log")
    def habit_log(habit_id: int, date: str = "") -> Dict[str, Any]:
        return _guarded(_lifeos().planner.log_habit, habit_id, date or None)

    # -- reviews --
    @api.get("/alerts")
    def alerts() -> List[Dict[str, Any]]:
        return [a.to_dict() for a in _lifeos().reviews.alerts()]

    @api.get("/reviews")
    def reviews_history(kind: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        return _lifeos().reviews.history(kind or None, limit)

    @api.get("/reviews/{kind}")
    def review_build(kind: str, notes: str = "") -> Dict[str, Any]:
        return _guarded(_lifeos().reviews.build, kind, notes=notes).to_dict()

    @api.post("/reviews/{kind}")
    def review_save(kind: str, body: ReviewIn) -> Dict[str, Any]:
        lo = _lifeos()
        report = _guarded(lo.reviews.build, kind, notes=body.notes)
        rid = lo.save_review(report, notes=body.notes)
        lo.actions.record(
            actor="user_ui",
            action=f"review_{kind}",
            category="report",
            risk="low",
            autonomy_level=int(lo.autonomy_level),
            decision="executed",
            params={"period": report.period_key},
            result=f"review #{rid}",
            success=True,
        )
        return {"id": rid, **report.to_dict()}

    # -- autonomy & approvals & audit --
    @api.get("/autonomy")
    def autonomy_get() -> Dict[str, Any]:
        from openjarvis.lifeos.autonomy import CATEGORIES

        lo = _lifeos()
        return {
            "level": int(lo.autonomy_level),
            "grants": lo.grants(),
            "summary": lo.policy_summary(),
            "categories": [
                {
                    "name": c.name,
                    "risk": c.risk.value,
                    "description": c.description,
                    "grantable": c.grantable,
                }
                for c in CATEGORIES.values()
            ],
        }

    @api.put("/autonomy")
    def autonomy_set(body: AutonomyIn) -> Dict[str, Any]:
        lo = _lifeos()
        _guarded(lo.set_autonomy_level, body.level, actor="user_ui")
        return {"level": int(lo.autonomy_level)}

    @api.post("/grants/{category}")
    def grant(category: str) -> Dict[str, Any]:
        lo = _lifeos()
        _guarded(lo.grant, category, actor="user_ui")
        return {"grants": lo.grants()}

    @api.delete("/grants/{category}")
    def revoke(category: str) -> Dict[str, Any]:
        lo = _lifeos()
        lo.revoke(category, actor="user_ui")
        return {"grants": lo.grants()}

    @api.get("/approvals")
    def approvals(status: str = "pending") -> List[Dict[str, Any]]:
        return _lifeos().list_pending(status)

    @api.post("/approvals/{action_id}/approve")
    def approve(action_id: str) -> Dict[str, Any]:
        return _guarded(_lifeos().approve, action_id, actor="user_ui")

    @api.post("/approvals/{action_id}/deny")
    def deny(action_id: str) -> Dict[str, Any]:
        return _guarded(_lifeos().deny, action_id, actor="user_ui")

    @api.get("/audit")
    def audit(limit: int = 50) -> Dict[str, Any]:
        lo = _lifeos()
        ok, bad = lo.actions.verify()
        return {
            "intact": ok,
            "first_bad_id": bad,
            "entries": lo.actions.list(limit=limit),
        }

    # -- conversations & chat --
    @api.get("/sessions")
    def sessions() -> List[Dict[str, Any]]:
        return _lifeos().sessions()

    @api.get("/sessions/{session_id}")
    def session(session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return _lifeos().conversation(session_id, limit)

    @api.post("/chat")
    def chat(body: ChatIn, request: Request) -> Dict[str, Any]:
        from openjarvis.lifeos.agent import JarvisOrchestratorAgent

        state = request.app.state
        engine = getattr(state, "engine", None)
        model = getattr(state, "model", "")
        if engine is None or not model:
            raise HTTPException(
                status_code=503, detail="Nenhum motor de inferência ativo no servidor"
            )
        agent = JarvisOrchestratorAgent(
            engine,
            model,
            lifeos=_lifeos(),
            session_id=body.session_id,
            bus=getattr(state, "bus", None),
            capability_policy=getattr(state, "capability_policy", None),
        )
        with _CHAT_LOCK:
            try:
                result = agent.run(body.message)
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail=f"Falha na inferência: {exc}"
                ) from None
        return {
            "session_id": agent.session_id,
            "reply": result.content,
            "tools": [
                {"tool": t.tool_name, "success": t.success, "content": t.content[:2000]}
                for t in result.tool_results
            ],
            "pending": _lifeos().list_pending(),
        }

    router.include_router(api)
    return router


__all__ = ["create_lifeos_router"]

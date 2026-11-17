"""Real resource and model status for the interface (no simulated values)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

_GB = 1024**3


def _unwrap_engine(engine: Any) -> Any:
    """Follow wrapper chains (InstrumentedEngine and similar) to the backend."""
    seen = set()
    while engine is not None and id(engine) not in seen:
        seen.add(id(engine))
        inner = getattr(engine, "_inner", None) or getattr(engine, "_engine", None)
        if inner is None:
            return engine
        engine = inner
    return engine


def resources() -> Dict[str, Any]:
    import psutil

    vm = psutil.virtual_memory()
    proc = psutil.Process(os.getpid())
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_total_gb": round(vm.total / _GB, 2),
        "ram_used_gb": round((vm.total - vm.available) / _GB, 2),
        "ram_percent": vm.percent,
        "server_rss_gb": round(proc.memory_info().rss / _GB, 3),
    }


def ollama_running(host: str, timeout: float = 2.0) -> Optional[list]:
    """Models loaded in Ollama (``GET /api/ps``) or ``None`` if unreachable."""
    try:
        resp = httpx.get(f"{host.rstrip('/')}/api/ps", timeout=timeout)
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None
    models = []
    for m in resp.json().get("models", []) or []:
        size = int(m.get("size") or 0)
        vram = int(m.get("size_vram") or 0)
        models.append(
            {
                "name": m.get("name") or m.get("model", ""),
                "size_gb": round(size / _GB, 2),
                "vram_gb": round(vram / _GB, 2),
                "processor": "CPU"
                if vram == 0
                else ("GPU" if vram >= size else "CPU/GPU"),
                "expires_at": m.get("expires_at"),
            }
        )
    return models


def model_status(engine: Any, engine_name: str, model: str) -> Dict[str, Any]:
    backend = _unwrap_engine(engine)
    try:
        healthy = bool(engine.health()) if engine is not None else False
    except Exception:
        healthy = False
    info: Dict[str, Any] = {
        "engine": engine_name or getattr(backend, "engine_id", ""),
        "model": model,
        "healthy": healthy,
        "num_ctx": os.environ.get("JARVIS_NUM_CTX", ""),
    }
    host = getattr(backend, "_host", None)
    if isinstance(host, str) and getattr(backend, "engine_id", "") == "ollama":
        info["host"] = host
        info["loaded"] = ollama_running(host)
    return info


def snapshot(engine: Any, engine_name: str, model: str) -> Dict[str, Any]:
    return {"resources": resources(), "model": model_status(engine, engine_name, model)}


__all__ = ["model_status", "ollama_running", "resources", "snapshot"]

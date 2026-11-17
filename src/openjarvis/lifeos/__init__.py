"""JARVIS LifeOS — personal intelligence and execution layer on OpenJarvis.

Modules
-------
config     separate ``lifeos.toml`` settings
db         local SQLite storage (FTS5 when available)
memory     layered persistent memory with history and conflict guard
planner    goals, projects, tasks, habits, commitments, decisions
reviews    alerts and morning/evening/weekly/monthly reviews
autonomy   risk-based autonomy policy (levels 1-4)
audit      hash-chained action log
service    ``LifeOS`` facade
tools      agent tools (``lifeos_memory``, ``lifeos_planner``, ``lifeos_review``)
agent      ``jarvis_orchestrator`` central agent
"""

from __future__ import annotations

from openjarvis.lifeos.service import LifeOS, LifeOSError, get_lifeos

__all__ = ["LifeOS", "LifeOSError", "get_lifeos"]

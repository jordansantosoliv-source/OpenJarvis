# ruff: noqa: E501
"""LifeOS configuration, kept separate from OpenJarvis' ``config.toml``.

The file lives at ``<openjarvis-home>/lifeos/lifeos.toml`` (``OPENJARVIS_HOME``
is honored through :func:`openjarvis.core.paths.get_config_dir`). Missing
keys fall back to the defaults below, unknown keys are rejected so typos are
noticed instead of silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional

import tomllib

from openjarvis.core.paths import get_config_dir

LIFEOS_DIR_NAME = "lifeos"
CONFIG_FILE_NAME = "lifeos.toml"


class LifeOSConfigError(ValueError):
    """Raised when ``lifeos.toml`` contains invalid values."""


def get_lifeos_dir() -> Path:
    """Directory holding every LifeOS file (database, persona, config)."""
    return get_config_dir() / LIFEOS_DIR_NAME


@dataclass(slots=True)
class SemanticConfig:
    """Optional embedding-based retrieval (off until a model is chosen)."""

    enabled: bool = False
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"


@dataclass(slots=True)
class ReviewConfig:
    """Thresholds used by the alert detector and periodic reviews."""

    daily_task_capacity: int = 5
    due_soon_days: int = 3
    stale_project_days: int = 14
    habit_min_rate: float = 0.5
    max_alerts: int = 7


@dataclass(slots=True)
class LifeOSConfig:
    """Top-level LifeOS settings."""

    db_path: str = ""
    persona_path: str = ""
    language: str = "pt-BR"
    user_name: str = ""
    autonomy_level: int = 2
    memory_context_limit: int = 8
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)

    def resolved_db_path(self) -> Path:
        return (
            Path(self.db_path).expanduser()
            if self.db_path
            else (get_lifeos_dir() / "lifeos.db")
        )

    def resolved_persona_path(self) -> Path:
        return (
            Path(self.persona_path).expanduser()
            if self.persona_path
            else (get_lifeos_dir() / "persona.md")
        )


def _apply(target: Any, data: Dict[str, Any], where: str) -> None:
    known = {f.name: f for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            raise LifeOSConfigError(f"Unknown key '{where}{key}' in {CONFIG_FILE_NAME}")
        current = getattr(target, key)
        if hasattr(current, "__dataclass_fields__"):
            if not isinstance(value, dict):
                raise LifeOSConfigError(f"'{where}{key}' must be a table")
            _apply(current, value, f"{where}{key}.")
            continue
        expected = type(current)
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, expected) or (
            expected is int and isinstance(value, bool)
        ):
            raise LifeOSConfigError(
                f"'{where}{key}' must be {expected.__name__}, got {type(value).__name__}"
            )
        setattr(target, key, value)


def validate_config(cfg: LifeOSConfig) -> None:
    if cfg.autonomy_level not in (1, 2, 3, 4):
        raise LifeOSConfigError("autonomy_level must be 1, 2, 3 or 4")
    if cfg.memory_context_limit < 0:
        raise LifeOSConfigError("memory_context_limit must be >= 0")
    r = cfg.review
    if r.daily_task_capacity < 1 or r.due_soon_days < 0 or r.stale_project_days < 1:
        raise LifeOSConfigError("review thresholds must be positive")
    if not 0.0 <= r.habit_min_rate <= 1.0:
        raise LifeOSConfigError("review.habit_min_rate must be between 0 and 1")
    if r.max_alerts < 1:
        raise LifeOSConfigError("review.max_alerts must be >= 1")


def load_lifeos_config(path: Optional[Path] = None) -> LifeOSConfig:
    """Load ``lifeos.toml``; return defaults when the file does not exist."""
    cfg = LifeOSConfig()
    path = path or (get_lifeos_dir() / CONFIG_FILE_NAME)
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise LifeOSConfigError(f"Invalid TOML in {path}: {exc}") from exc
        _apply(cfg, data, "")
    validate_config(cfg)
    return cfg


DEFAULT_CONFIG_TOML = """\
# JARVIS LifeOS — configuração (separada do config.toml do OpenJarvis)

language = "pt-BR"
user_name = ""

# 1 = consultivo, 2 = assistido, 3 = autorizado, 4 = proativo
autonomy_level = 2

# Quantos registros de memória entram no contexto de cada pedido
memory_context_limit = 8

[semantic]
# Busca semântica por embeddings. Desligada até você escolher o modelo
# compatível com seu hardware (ex.: `ollama pull nomic-embed-text`).
enabled = false
provider = "ollama"
model = "nomic-embed-text"
base_url = "http://localhost:11434"

[review]
daily_task_capacity = 5
due_soon_days = 3
stale_project_days = 14
habit_min_rate = 0.5
max_alerts = 7
"""


def write_default_config(
    path: Optional[Path] = None, *, overwrite: bool = False
) -> Path:
    """Write the commented default ``lifeos.toml``; never clobbers silently."""
    path = path or (get_lifeos_dir() / CONFIG_FILE_NAME)
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_bytes(path.read_bytes())
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return path


__all__ = [
    "LifeOSConfig",
    "LifeOSConfigError",
    "ReviewConfig",
    "SemanticConfig",
    "get_lifeos_dir",
    "load_lifeos_config",
    "write_default_config",
]

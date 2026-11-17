# ruff: noqa: E501
"""LifeOS configuration, kept separate from OpenJarvis' ``config.toml``.

Everything LifeOS owns lives in one dedicated directory::

    JARVIS-LifeOS/            ($JARVIS_LIFEOS_HOME, default ~/JARVIS-LifeOS)
    ├── config/               lifeos.toml, persona.md
    ├── memory/               lifeos.db (SQLite)
    ├── workspace/            files JARVIS may organize
    ├── research/             research notes and sources
    ├── reports/              archived reviews (Markdown)
    ├── logs/                 action log mirror (JSONL)
    ├── backups/              timestamped backups
    └── interface/            reserved for interface assets

The OpenJarvis ``config.toml`` is never written by LifeOS. Missing keys fall
back to the defaults below; unknown keys are rejected so typos are noticed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional

import tomllib

HOME_ENV = "JARVIS_LIFEOS_HOME"
DEFAULT_DIR_NAME = "JARVIS-LifeOS"
CONFIG_FILE_NAME = "lifeos.toml"
FOLDERS = (
    "config",
    "memory",
    "workspace",
    "research",
    "reports",
    "logs",
    "backups",
    "interface",
)
PERMISSIONS = ("none", "read", "write")


class LifeOSConfigError(ValueError):
    """Raised when ``lifeos.toml`` contains invalid values."""


def get_lifeos_dir() -> Path:
    """Root of the dedicated JARVIS-LifeOS directory."""
    custom = os.environ.get(HOME_ENV, "").strip()
    return Path(custom).expanduser() if custom else Path.home() / DEFAULT_DIR_NAME


def config_file_path() -> Path:
    return get_lifeos_dir() / "config" / CONFIG_FILE_NAME


@dataclass(slots=True)
class FoldersConfig:
    """What the agent's file tool may do in each folder: none, read, write.

    Deleting or overwriting existing files always requires confirmation, even
    in ``write`` folders. Paths outside JARVIS-LifeOS are never reachable.
    """

    config: str = "read"
    memory: str = "none"
    workspace: str = "write"
    research: str = "write"
    reports: str = "write"
    logs: str = "read"
    backups: str = "none"
    interface: str = "read"


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
    autonomy_level: int = 3
    memory_context_limit: int = 8
    root: str = ""
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    folders: FoldersConfig = field(default_factory=FoldersConfig)

    def resolved_root(self) -> Path:
        return Path(self.root).expanduser() if self.root else get_lifeos_dir()

    def folder(self, name: str) -> Path:
        if name not in FOLDERS:
            raise LifeOSConfigError(f"pasta desconhecida '{name}'")
        return self.resolved_root() / name

    def folder_permission(self, name: str) -> str:
        return getattr(self.folders, name) if name in FOLDERS else "none"

    def resolved_db_path(self) -> Path:
        return (
            Path(self.db_path).expanduser()
            if self.db_path
            else self.folder("memory") / "lifeos.db"
        )

    def resolved_persona_path(self) -> Path:
        return (
            Path(self.persona_path).expanduser()
            if self.persona_path
            else self.folder("config") / "persona.md"
        )

    def ensure_layout(self) -> Path:
        """Create the dedicated directory tree (idempotent, never deletes)."""
        root = self.resolved_root()
        for name in FOLDERS:
            (root / name).mkdir(parents=True, exist_ok=True)
        return root


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
    for name in FOLDERS:
        if getattr(cfg.folders, name) not in PERMISSIONS:
            raise LifeOSConfigError(
                f"folders.{name} must be one of: {', '.join(PERMISSIONS)}"
            )


def load_lifeos_config(path: Optional[Path] = None) -> LifeOSConfig:
    """Load ``lifeos.toml``; return defaults when the file does not exist."""
    cfg = LifeOSConfig()
    path = path or config_file_path()
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
# No nível 3, só as categorias pré-autorizadas executam sem confirmação
# (padrão: relatórios, organização dentro das pastas permitidas, pesquisas).
autonomy_level = 3

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

[folders]
# Permissão da ferramenta de arquivos do JARVIS em cada pasta de JARVIS-LifeOS:
# "none", "read" ou "write". Excluir ou sobrescrever arquivos SEMPRE pede
# confirmação. Fora de JARVIS-LifeOS o JARVIS não tem acesso.
config = "read"
memory = "none"
workspace = "write"
research = "write"
reports = "write"
logs = "read"
backups = "none"
interface = "read"
"""


def write_default_config(
    path: Optional[Path] = None, *, overwrite: bool = False
) -> Path:
    """Write the commented default ``lifeos.toml``; never clobbers silently."""
    path = path or config_file_path()
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_bytes(path.read_bytes())
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return path


__all__ = [
    "FOLDERS",
    "FoldersConfig",
    "LifeOSConfig",
    "LifeOSConfigError",
    "ReviewConfig",
    "SemanticConfig",
    "config_file_path",
    "get_lifeos_dir",
    "load_lifeos_config",
    "write_default_config",
]

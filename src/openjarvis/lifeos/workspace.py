"""Sandboxed file access inside the dedicated JARVIS-LifeOS directory.

Rules enforced here, independent of the autonomy level:

* Paths are relative to the JARVIS-LifeOS root, start with a known folder
  (``workspace/notas.md``) and must stay inside the root after resolving
  ``..`` and symbolic links. Absolute paths and drive letters are refused.
* Each folder has a permission (``none``, ``read``, ``write``) from
  ``[folders]`` in ``lifeos.toml``.
* Only UTF-8 text up to :data:`MAX_FILE_BYTES` is read or written.

Whether an allowed operation runs immediately or asks first is decided by the
autonomy policy using :meth:`Workspace.category_for`.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List

from openjarvis.lifeos.config import FOLDERS, LifeOSConfig

MAX_FILE_BYTES = 1_000_000
MAX_LIST_ENTRIES = 500
_LEVELS = {"none": 0, "read": 1, "write": 2}


class WorkspaceError(PermissionError):
    """Path outside the sandbox, forbidden folder, or invalid operation."""


@dataclass(frozen=True)
class ResolvedPath:
    relative: str
    folder: str
    path: Path


class Workspace:
    def __init__(self, config: LifeOSConfig) -> None:
        self._cfg = config
        self.root = config.resolved_root()

    # -- path handling ------------------------------------------------------

    def resolve(self, relative: str, need: str) -> ResolvedPath:
        raw = str(relative or "").strip().replace("\\", "/")
        if not raw:
            raise WorkspaceError("caminho vazio")
        if PureWindowsPath(raw).drive or PurePosixPath(raw).is_absolute():
            raise WorkspaceError(
                "use caminho relativo a JARVIS-LifeOS (ex.: workspace/notas.md)"
            )
        parts = [p for p in PurePosixPath(raw).parts if p not in ("", ".")]
        if not parts or ".." in parts:
            raise WorkspaceError("caminho inválido: '..' não é permitido")
        folder = parts[0]
        if folder not in FOLDERS:
            raise WorkspaceError(
                f"pasta '{folder}' não existe; use: {', '.join(FOLDERS)}"
            )
        allowed = self._cfg.folder_permission(folder)
        if _LEVELS[allowed] < _LEVELS[need]:
            raise WorkspaceError(
                f"sem permissão de {'escrita' if need == 'write' else 'leitura'} "
                f"em '{folder}' (permissão: {allowed})"
            )
        root = self.root.resolve()
        target = (self.root / Path(*parts)).resolve()
        if not target.is_relative_to(root / folder) and target != root / folder:
            raise WorkspaceError("caminho sai da pasta permitida (link simbólico?)")
        return ResolvedPath("/".join(parts), folder, target)

    def category_for(self, action: str, arguments: Dict[str, Any]) -> str:
        """Autonomy category of a file operation (used before it runs)."""
        action = str(action or "").lower()
        if action in ("list", "read", "info"):
            return "read"
        if action == "delete":
            return "file_delete"
        if action == "write":
            try:
                target = self.resolve(arguments.get("path", ""), "write").path
            except WorkspaceError:
                return "file_organize"  # the tool will refuse it anyway
            if target.exists() and not arguments.get("append"):
                return "file_modify"
            return "file_organize"
        if action in ("mkdir", "move"):
            if action == "move":
                try:
                    dest = self.resolve(arguments.get("destination", ""), "write").path
                except WorkspaceError:
                    return "file_organize"
                if dest.exists():
                    return "file_modify"
            return "file_organize"
        return "unknown"

    # -- operations ---------------------------------------------------------

    def list(self, relative: str = "") -> List[Dict[str, Any]]:
        if not relative:
            return [
                {
                    "name": name,
                    "type": "folder",
                    "permission": self._cfg.folder_permission(name),
                }
                for name in FOLDERS
            ]
        rp = self.resolve(relative, "read")
        if not rp.path.exists():
            raise WorkspaceError(f"'{rp.relative}' não existe")
        if rp.path.is_file():
            return [self._info(rp.path, rp.relative)]
        entries = []
        for child in sorted(
            rp.path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        ):
            entries.append(self._info(child, f"{rp.relative}/{child.name}"))
            if len(entries) >= MAX_LIST_ENTRIES:
                break
        return entries

    @staticmethod
    def _info(path: Path, relative: str) -> Dict[str, Any]:
        st = path.stat()
        return {
            "path": relative,
            "type": "folder" if path.is_dir() else "file",
            "size": st.st_size if path.is_file() else None,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }

    def read(self, relative: str) -> str:
        rp = self.resolve(relative, "read")
        if not rp.path.is_file():
            raise WorkspaceError(f"'{rp.relative}' não é um arquivo")
        if rp.path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError("arquivo grande demais para leitura (> 1 MB)")
        data = rp.path.read_bytes()
        if b"\x00" in data[:4096]:
            raise WorkspaceError("arquivo binário: somente texto é suportado")
        return data.decode("utf-8", errors="replace")

    def write(
        self,
        relative: str,
        content: str,
        *,
        append: bool = False,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        rp = self.resolve(relative, "write")
        encoded = str(content).encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise WorkspaceError("conteúdo maior que 1 MB")
        if rp.path.is_dir():
            raise WorkspaceError(f"'{rp.relative}' é uma pasta")
        existed = rp.path.exists()
        if existed and not (append or overwrite):
            raise WorkspaceError(
                f"'{rp.relative}' já existe; use append=true ou overwrite=true "
                "(sobrescrever exige confirmação)"
            )
        rp.path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with rp.path.open("ab") as fh:
                fh.write(encoded)
        else:
            tmp = rp.path.with_name(rp.path.name + ".jarvis-tmp")
            tmp.write_bytes(encoded)
            os.replace(tmp, rp.path)
        return {"path": rp.relative, "bytes": len(encoded), "created": not existed}

    def mkdir(self, relative: str) -> Dict[str, Any]:
        rp = self.resolve(relative, "write")
        rp.path.mkdir(parents=True, exist_ok=True)
        return {"path": rp.relative, "type": "folder"}

    def move(
        self, source: str, destination: str, *, overwrite: bool = False
    ) -> Dict[str, Any]:
        src = self.resolve(source, "write")
        dst = self.resolve(destination, "write")
        if src.path == self.root.resolve() / src.folder:
            raise WorkspaceError("não é permitido mover uma pasta raiz")
        if not src.path.exists():
            raise WorkspaceError(f"'{src.relative}' não existe")
        if dst.path.exists() and not overwrite:
            raise WorkspaceError(f"'{dst.relative}' já existe")
        dst.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src.path), str(dst.path))
        return {"from": src.relative, "to": dst.relative}

    def delete(self, relative: str) -> Dict[str, Any]:
        rp = self.resolve(relative, "write")
        if rp.path == self.root.resolve() / rp.folder:
            raise WorkspaceError("não é permitido excluir uma pasta raiz")
        if not rp.path.exists():
            raise WorkspaceError(f"'{rp.relative}' não existe")
        if rp.path.is_dir():
            if any(rp.path.iterdir()):
                raise WorkspaceError("a pasta não está vazia; exclua o conteúdo antes")
            rp.path.rmdir()
        else:
            rp.path.unlink()
        return {"deleted": rp.relative}


__all__ = ["MAX_FILE_BYTES", "Workspace", "WorkspaceError"]

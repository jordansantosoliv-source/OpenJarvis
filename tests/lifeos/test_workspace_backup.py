from __future__ import annotations

import json
import os
import sqlite3

import pytest

from openjarvis.lifeos.autonomy import Verdict
from openjarvis.lifeos.config import (
    FOLDERS,
    LifeOSConfig,
    LifeOSConfigError,
    load_lifeos_config,
)
from openjarvis.lifeos.service import LifeOS
from openjarvis.lifeos.tools import LifeOSFilesTool
from openjarvis.lifeos.workspace import WorkspaceError


def test_layout_created(lifeos):
    for name in FOLDERS:
        assert (lifeos.root / name).is_dir()
    assert lifeos.db.path == lifeos.root / "memory" / "lifeos.db"
    assert lifeos.persona_path == lifeos.root / "config" / "persona.md"


def test_default_root_comes_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_LIFEOS_HOME", str(tmp_path / "X"))
    assert LifeOSConfig().resolved_root() == tmp_path / "X"


@pytest.mark.parametrize(
    "path",
    [
        "../fora.txt",
        "workspace/../../fora.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:\\Users\\x\\a.txt",
        "documentos/a.txt",
        "",
    ],
)
def test_paths_outside_sandbox_are_refused(lifeos, path):
    with pytest.raises(WorkspaceError):
        lifeos.workspace.write(path, "x")


def test_folder_permissions(lifeos):
    ws = lifeos.workspace
    ws.write("workspace/notas.md", "olá")
    assert ws.read("workspace/notas.md") == "olá"
    with pytest.raises(WorkspaceError):
        ws.read("memory/lifeos.db")  # none
    with pytest.raises(WorkspaceError):
        ws.write("logs/x.txt", "x")  # read-only
    with pytest.raises(WorkspaceError):
        ws.list("backups")  # none
    assert {e["name"]: e["permission"] for e in ws.list()}["workspace"] == "write"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs privileges on Windows"
)
def test_symlink_escape_is_refused(lifeos, tmp_path):
    outside = tmp_path / "segredo"
    outside.mkdir()
    (outside / "a.txt").write_text("segredo")
    os.symlink(outside, lifeos.root / "workspace" / "link")
    with pytest.raises(WorkspaceError):
        lifeos.workspace.read("workspace/link/a.txt")


def test_write_does_not_overwrite_silently(lifeos):
    ws = lifeos.workspace
    ws.write("research/a.md", "v1")
    with pytest.raises(WorkspaceError):
        ws.write("research/a.md", "v2")
    ws.write("research/a.md", "+", append=True)
    assert ws.read("research/a.md") == "v1+"
    ws.write("research/a.md", "v2", overwrite=True)
    assert ws.read("research/a.md") == "v2"


def test_move_and_delete(lifeos):
    ws = lifeos.workspace
    ws.write("workspace/a.txt", "x")
    ws.move("workspace/a.txt", "research/b.txt")
    assert ws.read("research/b.txt") == "x"
    with pytest.raises(WorkspaceError):
        ws.delete("workspace")  # folder root
    ws.delete("research/b.txt")
    assert ws.list("research") == []


def test_file_categories_follow_user_rules(lifeos):
    tool = LifeOSFilesTool(lifeos)
    lifeos.workspace.write("workspace/existente.md", "x")
    cases = {
        ("list", "workspace", False): ("read", Verdict.ALLOW),
        ("read", "workspace/existente.md", False): ("read", Verdict.ALLOW),
        ("write", "workspace/novo.md", False): ("file_organize", Verdict.ALLOW),
        ("write", "workspace/existente.md", False): ("file_modify", Verdict.ASK),
        ("write", "workspace/novo2.md", True): ("file_modify", Verdict.ASK),
        ("delete", "workspace/existente.md", False): ("file_delete", Verdict.ASK),
    }
    for (action, path, overwrite), (category, verdict) in cases.items():
        args = {"action": action, "path": path, "overwrite": overwrite}
        decision = lifeos.authorize(tool, "lifeos_files", args)
        assert (decision.category.name, decision.verdict) == (category, verdict), args


def test_native_unconfined_tools_require_confirmation(lifeos):
    for name in ("file_write", "apply_patch", "http_request", "browser_type"):
        assert lifeos.authorize(None, name, {}).verdict is Verdict.ASK, name
    assert lifeos.authorize(None, "web_search", {"query": "x"}).verdict is Verdict.ALLOW


def test_files_tool_reports_errors_without_raising(lifeos):
    result = LifeOSFilesTool(lifeos).execute(action="read", path="../x")
    assert not result.success and "Erro" in result.content


def test_invalid_folder_permission_rejected(tmp_path):
    path = tmp_path / "lifeos.toml"
    path.write_text('[folders]\nworkspace = "everything"\n', encoding="utf-8")
    with pytest.raises(LifeOSConfigError):
        load_lifeos_config(path)


def test_backup_copies_without_touching_originals(lifeos, tmp_path, monkeypatch):
    oj_home = tmp_path / "ojhome"
    oj_home.mkdir()
    original = '[engine]\ndefault = "ollama"\n'
    (oj_home / "config.toml").write_text(original, encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_HOME", str(oj_home))
    lifeos.memory.remember("Dado para backup")
    out = lifeos.backup("teste")
    assert "lifeos.db" in out["files"] and "openjarvis-config.toml" in out["files"]
    assert (oj_home / "config.toml").read_text(encoding="utf-8") == original
    copy = sqlite3.connect(os.path.join(out["path"], "lifeos.db"))
    try:
        assert (
            copy.execute("SELECT content FROM memories").fetchone()[0]
            == "Dado para backup"
        )
    finally:
        copy.close()
    assert lifeos.backup("teste")["path"] != out["path"]  # never overwritten


def test_wipe_makes_backup_first(lifeos):
    lifeos.memory.remember("x")
    lifeos.wipe()
    backups = list((lifeos.root / "backups").iterdir())
    assert any("antes-de-apagar" in b.name for b in backups)


def test_saved_review_is_exported_as_markdown(lifeos):
    report = lifeos.reviews.build("weekly")
    lifeos.save_review(report, notes="Semana corrida")
    path = lifeos.root / "reports" / f"weekly-{report.period_key}.md"
    text = path.read_text(encoding="utf-8")
    assert "Revisão semanal" in text and "Semana corrida" in text


def test_action_log_mirrored_to_jsonl(lifeos):
    lifeos.set_autonomy_level(2)
    files = list((lifeos.root / "logs").glob("actions-*.jsonl"))
    assert files
    entry = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    assert entry["action"] == "set_autonomy_level" and len(entry["hash"]) == 64


def test_persistence_with_dedicated_root(tmp_path):
    cfg = LifeOSConfig(root=str(tmp_path / "R"))
    first = LifeOS(cfg)
    first.workspace.write("workspace/a.md", "conteúdo")
    first.memory.remember("Persistente")
    first.close()
    second = LifeOS(LifeOSConfig(root=str(tmp_path / "R")))
    try:
        assert second.memory.search("persistente")
        assert second.workspace.read("workspace/a.md") == "conteúdo"
    finally:
        second.close()

from __future__ import annotations

import pytest

from openjarvis.lifeos.config import LifeOSConfig
from openjarvis.lifeos.memory import LifeOSMemoryError, MemoryConflict
from openjarvis.lifeos.service import LifeOS


def test_remember_and_search(lifeos):
    rec, created = lifeos.memory.remember("Prefere estudar à noite", layer="personal")
    assert created and rec.id > 0
    hits = lifeos.memory.search("estudar")
    assert [h.id for h in hits] == [rec.id]


def test_search_ignores_accents(lifeos):
    lifeos.memory.remember("Objetivo: aprovação em cálculo", layer="personal")
    assert lifeos.memory.search("aprovacao calculo")


def test_deduplication_by_normalized_text(lifeos):
    a, created_a = lifeos.memory.remember("Acorda às 6h", status="hypothesis")
    b, created_b = lifeos.memory.remember("acorda as 6h!", status="confirmed")
    assert created_a and not created_b
    assert a.id == b.id
    assert b.status == "confirmed"  # promoted from hypothesis
    assert lifeos.memory.stats()["total"] == 1


def test_subject_conflict_and_replace_keeps_history(lifeos):
    old, _ = lifeos.memory.remember("Acorda às 6h", subject="usuario.acordar")
    with pytest.raises(MemoryConflict) as err:
        lifeos.memory.remember("Acorda às 7h", subject="usuario.acordar")
    assert err.value.existing.id == old.id
    new, created = lifeos.memory.remember(
        "Acorda às 7h", subject="usuario.acordar", replace=True
    )
    assert created
    assert not lifeos.memory.get(old.id).active
    assert lifeos.memory.get(old.id).superseded_by == new.id
    assert [r.id for r in lifeos.memory.history(new.id)] == [old.id, new.id]
    assert [r.id for r in lifeos.memory.list()] == [new.id]


def test_correct_creates_version_and_search_sees_only_active(lifeos):
    rec, _ = lifeos.memory.remember("Orçamento mensal de 2000 reais")
    fixed = lifeos.memory.correct(rec.id, content="Orçamento mensal de 2500 reais")
    assert fixed.id != rec.id
    assert [h.id for h in lifeos.memory.search("orçamento")] == [fixed.id]
    with pytest.raises(LifeOSMemoryError):
        lifeos.memory.correct(rec.id, content="x")


def test_forget_deletes_whole_history(lifeos):
    rec, _ = lifeos.memory.remember("Senha do wifi é segredo")
    v2 = lifeos.memory.correct(rec.id, content="Informação removida")
    assert lifeos.memory.forget(v2.id) == 2
    assert lifeos.memory.export() == []
    assert lifeos.memory.search("wifi") == []


def test_validation(lifeos):
    with pytest.raises(LifeOSMemoryError):
        lifeos.memory.remember("   ")
    with pytest.raises(LifeOSMemoryError):
        lifeos.memory.remember("x", layer="inexistente")
    with pytest.raises(LifeOSMemoryError):
        lifeos.memory.remember("x", status="talvez")


def test_hypotheses_can_be_excluded(lifeos):
    lifeos.memory.remember("Talvez goste de corrida", status="hypothesis")
    assert lifeos.memory.search("corrida")
    assert lifeos.memory.search("corrida", include_hypotheses=False) == []


def test_fts_query_sanitizes_operators(lifeos):
    lifeos.memory.remember("Projeto AND OR NOT especial")
    assert lifeos.memory.search('AND "OR" NOT* (especial')


def test_persistence_across_restarts(tmp_path):
    cfg = LifeOSConfig(
        db_path=str(tmp_path / "p.db"), persona_path=str(tmp_path / "p.md")
    )
    first = LifeOS(cfg)
    first.memory.remember("Meta: correr 5 km", layer="personal")
    first.close()
    second = LifeOS(cfg)
    try:
        assert second.memory.search("correr")[0].content == "Meta: correr 5 km"
    finally:
        second.close()


def test_semantic_search_finds_synonym(semantic_lifeos):
    lo = semantic_lifeos
    target, _ = lo.memory.remember("Toma café logo de manhã")
    lo.memory.remember("Tem prova de estudo na sexta")
    hits = lo.memory.search("espresso cedo", limit=2)
    assert hits and hits[0].id == target.id


def test_context_block_excludes_identity(lifeos):
    lifeos.memory.remember("Responder sempre em português", layer="identity")
    lifeos.memory.remember(
        "Responder rápido em português no trabalho", layer="personal"
    )
    block = lifeos.memory.context_block("português")
    assert "trabalho" in block and "sempre" not in block

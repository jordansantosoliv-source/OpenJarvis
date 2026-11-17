"""Fixtures: an isolated LifeOS on a temporary database."""

from __future__ import annotations

import pytest

from openjarvis.lifeos.config import LifeOSConfig
from openjarvis.lifeos.service import LifeOS, reset_default_lifeos


class FakeEmbedder:
    """Deterministic bag-of-words embedder over a tiny vocabulary."""

    VOCAB = (
        "cafe",
        "bebida",
        "manha",
        "acordar",
        "estudo",
        "prova",
        "dinheiro",
        "academia",
    )
    SYNONYMS = {
        "espresso": "cafe",
        "cha": "bebida",
        "cedo": "manha",
        "treino": "academia",
    }

    def embed(self, texts):
        from openjarvis.lifeos.memory import normalize_text

        out = []
        for text in texts:
            words = normalize_text(text).split()
            words = [self.SYNONYMS.get(w, w) for w in words]
            out.append([float(words.count(v)) for v in self.VOCAB])
        return out


@pytest.fixture
def lifeos(tmp_path):
    cfg = LifeOSConfig(
        db_path=str(tmp_path / "lifeos.db"),
        persona_path=str(tmp_path / "persona.md"),
    )
    lo = LifeOS(cfg)
    yield lo
    lo.close()
    reset_default_lifeos()


@pytest.fixture
def semantic_lifeos(tmp_path):
    cfg = LifeOSConfig(
        db_path=str(tmp_path / "lifeos_sem.db"),
        persona_path=str(tmp_path / "persona.md"),
    )
    lo = LifeOS(cfg, embedder=FakeEmbedder())
    yield lo
    lo.close()

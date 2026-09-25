import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).parent.parent
DOCS = RACINE / "docs"
sys.path.insert(0, str(RACINE / "backend"))


def lire(nom: str) -> bytes:
    return (DOCS / f"exemple_{nom}.json").read_bytes()


class SansLLM:
    """Remplace le client réel : aucun test ne doit appeler l'API Anthropic."""

    def __getattr__(self, nom):
        def _refus(**_):
            raise ConnectionError("LLM désactivé pendant les tests")
        return _refus


@pytest.fixture(autouse=True)
def base_vide(tmp_path, monkeypatch):
    """Chaque test tourne sur une base SQLite neuve, sans LLM réel."""
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    import db
    import llm_client
    import services
    monkeypatch.setattr(llm_client, "FICHIER_COMPTEUR", tmp_path / "usage_llm.json")
    monkeypatch.setattr(services, "_llm", SansLLM())
    db.init_db()
    yield tmp_path

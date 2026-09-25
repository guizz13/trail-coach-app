import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).parent.parent
DOCS = RACINE / "docs"
sys.path.insert(0, str(RACINE / "backend"))


def lire(nom: str) -> bytes:
    return (DOCS / f"exemple_{nom}.json").read_bytes()


@pytest.fixture(autouse=True)
def base_vide(tmp_path, monkeypatch):
    """Chaque test tourne sur une base SQLite neuve."""
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    import db
    db.init_db()
    yield tmp_path

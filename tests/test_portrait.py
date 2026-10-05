"""Portrait : orientation du manifest (Android) et écran « Tourne ton téléphone » (iOS)."""

import json
from pathlib import Path

STATIC = Path(__file__).parent.parent / "frontend" / "static"


def test_manifest_portrait():
    assert json.loads((STATIC / "manifest.json").read_text())["orientation"] == "portrait"


def test_ecran_paysage_telephone_seulement():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "@media (orientation: landscape) and (max-height: 500px)" in css
    assert "Tourne ton téléphone en portrait" in (STATIC / "app.js").read_text(encoding="utf-8")

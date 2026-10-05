"""Navigation v7 : 4 onglets + action centrale, en-tête fixe, sensation d'app."""

from pathlib import Path

from test_api import anonyme, client  # noqa: F401 (fixtures)

FRONT = Path(__file__).parent.parent / "frontend"


def test_pages(client):
    for chemin in ("/", "/semaine", "/import", "/preparer", "/evenements", "/historique"):
        assert client.get(chemin).status_code == 200, chemin
    assert client.get("/semaine").text.count("seance.js") == 1


def test_onglets_et_action_centrale():
    app = (FRONT / "static" / "app.js").read_text(encoding="utf-8")
    for icone in ("ti-home", "ti-calendar-week", "ti-plus", "ti-target", "ti-chart-line"):
        assert icone in app
    assert '"/import", "ti-upload", "Import"' not in app                 # Import et Préparer : actions du +
    for action in ("Importer un fichier", "Séance réalisée", "Ajouter une séance prévue", "Préparer la semaine prochaine"):
        assert action in app


def test_en_tete_et_sensation_d_app():
    css = (FRONT / "static" / "style.css").read_text(encoding="utf-8")
    assert "position: sticky; top: 0; z-index: 50;" in css and "env(safe-area-inset-top) + 10px" in css
    assert ".app-header.scrolled" in css and "@view-transition { navigation: auto; }" in css
    assert "overscroll-behavior-y: none" in css and "prefers-reduced-motion" in css
    for page in FRONT.glob("*.html"):
        assert 'apple-mobile-web-app-status-bar-style" content="black-translucent"' in page.read_text(encoding="utf-8")


def test_budget_du_coach(client):
    c = client.get("/api/cout_llm").json()
    assert c["plafond_usd"] == 5.0 and c["cout_usd"] == 0

"""Catalogue des sports (brief v5, section 1)."""

import sports


def test_catalogue_coherent():
    ids = [s[0] for s in sports.SPORTS]
    assert len(ids) == len(set(ids))
    for s in sports.SPORTS_PAR_ID.values():
        assert s["categorie"] in sports.CATEGORIES
        assert s["impact"] in ("faible", "modere", "eleve")
        assert s["icone"].startswith("ti-")
        assert not s["zones_course"] or s["categorie"] == "course"   # seuils de zones : course uniquement


def test_helpers():
    assert sports.categorie("badminton") == "raquette" and sports.impact("badminton") == "eleve"
    assert sports.sport("inexistant")["id"] == "autre"
    assert sports.par_strava("TrailRun") == "trail"
    assert sports.par_strava("Walk") == "randonnee"          # premier de la liste
    assert sports.par_strava("Workout") == "calisthenics"
    assert sports.par_strava("Inconnu") is None
    assert sports.sport_de({"famille": "course_tapis"}) == "course_tapis"
    assert sports.sport_de({"sport_id": "trail", "famille": "course_outdoor"}) == "trail"
    assert sports.famille_heritee("badminton") == "squash" and sports.famille_heritee("trail") == "course_outdoor"


def test_api_sports(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("COACH_PASSWORD", "x")
    import main
    with TestClient(main.app) as c:
        c.post("/login", data={"password": "x"})
        r = c.get("/api/sports").json()
    assert set(r) == {"categories", "sports", "recents"} and len(r["sports"]) == len(sports.SPORTS)

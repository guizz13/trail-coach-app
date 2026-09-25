"""API HTTP et authentification par mot de passe."""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import lire

MDP = "secret-de-test"


@pytest.fixture
def anonyme(monkeypatch):
    monkeypatch.setenv("COACH_PASSWORD", MDP)
    import main
    main._echecs.clear()
    with TestClient(main.app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def client(anonyme):
    r = anonyme.post("/login", data={"password": MDP, "suite": "/"})
    assert r.status_code == 303
    return anonyme


# ---- Authentification ------------------------------------------------------
@pytest.mark.parametrize("chemin", ["/", "/import", "/dimanche", "/evenements", "/historique", "/static/app.js"])
def test_pages_protegees(anonyme, chemin):
    r = anonyme.get(chemin)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


@pytest.mark.parametrize("methode,chemin", [
    ("get", "/api/dashboard"), ("get", "/api/seances"), ("post", "/api/import"),
    ("post", "/api/evenements"), ("delete", "/api/evenements/1"), ("get", "/api/graphiques"),
])
def test_api_protegee(anonyme, methode, chemin):
    assert getattr(anonyme, methode)(chemin).status_code == 401


def test_login_mauvais_mot_de_passe(anonyme):
    r = anonyme.post("/login", data={"password": "faux"})
    assert r.status_code == 401
    assert "coach_session" not in r.cookies
    assert anonyme.get("/api/dashboard").status_code == 401


def test_login_limite_tentatives(anonyme):
    for _ in range(5):
        anonyme.post("/login", data={"password": "faux"})
    r = anonyme.post("/login", data={"password": MDP})
    assert r.status_code == 429


def test_login_puis_logout(anonyme):
    r = anonyme.post("/login", data={"password": MDP, "suite": "/historique"})
    assert r.status_code == 303 and r.headers["location"] == "/historique"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert anonyme.get("/api/dashboard").status_code == 200
    anonyme.post("/logout")
    assert anonyme.get("/api/dashboard").status_code == 401


def test_pas_de_redirection_ouverte(anonyme):
    r = anonyme.post("/login", data={"password": MDP, "suite": "//evil.example"})
    assert r.headers["location"] == "/"


def test_jeton_falsifie(anonyme):
    import time
    anonyme.cookies.set("coach_session", f"{int(time.time()) + 999}.deadbeef")
    assert anonyme.get("/api/dashboard").status_code == 401


def test_jeton_expire(anonyme):
    import main
    anonyme.cookies.set("coach_session", main._jeton(1))
    assert anonyme.get("/api/dashboard").status_code == 401


def test_demarrage_refuse_sans_mot_de_passe(monkeypatch):
    monkeypatch.delenv("COACH_PASSWORD", raising=False)
    import main
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass


# ---- Import ----------------------------------------------------------------
def test_import_via_api(client):
    fichiers = [("fichiers", (f"{n}.json", lire(n), "application/json"))
                for n in ("course_outdoor", "course_tapis", "muscu", "squash", "velo")]
    apercus = client.post("/api/import/apercu", files=fichiers).json()
    assert [a["seance"]["famille"] for a in apercus] == \
        ["course_outdoor", "course_tapis", "muscu", "squash", "velo"]
    assert apercus[2]["split_propose"] == "push_a"

    for n in ("course_outdoor", "course_tapis", "squash", "velo"):
        r = client.post("/api/import", files={"fichier": (f"{n}.json", lire(n))})
        assert r.status_code == 200, r.text
        assert r.json()["doublon"] is False

    opts = {"muscu_detail": {"split": "push_a", "groupes": ["pectoraux"], "charges": []}}
    r = client.post("/api/import", files={"fichier": ("m.json", lire("muscu"))},
                    data={"options": json.dumps(opts)})
    assert r.json()["seance"]["famille"] == "muscu"

    # Doublon
    r = client.post("/api/import", files={"fichier": ("x.json", lire("squash"))})
    assert r.json()["doublon"] is True

    seances = client.get("/api/seances").json()
    assert len(seances) == 5
    assert len(client.get("/api/seances?famille=course").json()) == 2

    detail = client.get(f"/api/seances/{seances[0]['id']}").json()
    assert "donnees_brutes" not in detail["seance"]
    assert client.get("/api/seances/9999").status_code == 404


def test_import_fichier_invalide(client):
    r = client.post("/api/import", files={"fichier": ("x.json", b"nope")})
    assert r.status_code == 422
    r = client.post("/api/import/apercu", files=[("fichiers", ("x.json", b"nope"))])
    assert "erreur" in r.json()[0]


# ---- Dashboard, historique -------------------------------------------------
def test_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert len(d["semaine"]) == 7
    assert d["semaine"][0]["jour"] == "lundi"
    assert d["profil"]["mode_actif"] == "BASE"
    assert d["cout_llm"]["plafond_usd"] == 5.0


def test_graphiques_et_poids(client):
    client.post("/api/poids", json={"date_mesure": "2026-09-20", "poids_kg": "71,5"})
    g = client.get("/api/graphiques").json()
    assert len(g["semaines"]) == 12
    assert g["poids"][0]["poids_kg"] == 71.5
    assert client.post("/api/poids", json={"poids_kg": 5}).status_code == 422


# ---- Événements & planifiées -----------------------------------------------
def test_evenements_crud(client):
    e = {"type": "trail_race", "titre": "Trail test", "date_evt": "2027-03-01",
         "priorite": "A", "distance_km": "42", "dplus_m": "2000"}
    id_ = client.post("/api/evenements", json=e).json()["evenement"]["id"]
    assert client.get("/api/evenements").json()["evenements"][0]["titre"] == "Trail test"
    assert client.put(f"/api/evenements/{id_}", json={**e, "priorite": "B"}).json()["evenement"]["priorite"] == "B"
    assert client.post("/api/evenements", json={**e, "type": "foo"}).status_code == 422
    assert client.delete(f"/api/evenements/{id_}").status_code == 200
    assert client.delete(f"/api/evenements/{id_}").status_code == 404


def test_planifiee_edition(client):
    p = client.post("/api/planifiees", json={"date_seance": "2026-09-29", "creneau": "week-end",
                                             "type": "EF", "duree_min": "45"}).json()
    assert p["creneau"] == "journee" and p["version"] == 1
    p2 = client.put(f"/api/planifiees/{p['id']}", json={"duree_min": 50}).json()
    assert p2["version"] == 2 and p2["statut"] == "modifie" and p2["duree_min"] == 50


# ---- Routes LLM (sans LLM : dégradation propre) ------------------------------
def test_evenement_declenche_reconstruction(client):
    r = client.post("/api/evenements", json={"type": "other", "titre": "Mariage",
                                             "date_evt": "2027-06-01"}).json()
    assert r["evenement"]["id"]
    assert r["reconstruction"]["erreur_llm"]["type"] == "ConnectionError"
    assert client.delete(f"/api/evenements/{r['evenement']['id']}").json()["ok"] is True


def test_suppression_evenement_reference_par_analyse(client):
    import db
    eid = client.post("/api/evenements", json={"type": "other", "titre": "X",
                                               "date_evt": "2027-06-01"}).json()["evenement"]["id"]
    db.inserer("analyses_llm", {"type_appel": "reconstruction_evenements", "evenement_id": eid,
                                "reponse_json": {}})
    assert client.delete(f"/api/evenements/{eid}").status_code == 200


def test_dimanche_et_bilan_sans_llm(client):
    d = client.get("/api/dimanche").json()
    assert d["jours"][0] == "lundi"
    r = client.post("/api/bilan", json={"semaine_debut": d["semaine_debut"], "ressenti": 7}).json()
    assert r["reponse"] is None and r["erreur_llm"]
    assert client.post("/api/bilan", json={"ressenti": 12}).status_code == 422
    assert client.post("/api/bilan/999/valider", json={}).status_code == 422

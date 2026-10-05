"""Accueil « Aujourd'hui » : séance du jour ou prochaine, bande de la semaine, forme, bandeaux."""

from datetime import date

import pytest

import db
import services
from test_api import anonyme, client  # noqa: F401 (fixtures)

LUNDI = "2026-10-05"


def prevoir(jour, type_, creneau="matin", duree=45, **kw):
    return db.inserer("seances_planifiees", {"date_seance": jour, "creneau": creneau, "type": type_,
                                             "duree_min": duree, "origine": "bilan_hebdo", **kw})


def faire(sport, debut, duree=45, rpe=4):
    return services.saisir_seance({"sport_id": sport, "debut": debut, "duree_min": duree, "rpe": rpe},
                                  analyser=False)["seance"]["id"]


def ecran(jour):
    return services.ecran_aujourdhui(date.fromisoformat(jour))


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 7))     # mercredi


def semaine_type():
    ids = {
        "lun": prevoir("2026-10-05", "EF", duree=40),
        "mar": prevoir("2026-10-06", "muscu_pull", duree=50),
        "mer": prevoir("2026-10-07", "intervals", "soir", 50, detail="6x3 min Z4", intensite="Z4"),
        "jeu": prevoir("2026-10-08", "repos", "journee", None),
        "ven": prevoir("2026-10-09", "muscu_push", duree=50),
        "sam": prevoir("2026-10-10", "sortie_longue", duree=150),
    }
    faire("course_route", "2026-10-05T07:00", 40)
    return ids


def test_seance_du_jour_et_demain_repos():
    x = semaine_type()
    e = ecran("2026-10-07")
    assert e["quand"] == "aujourdhui" and e["seance"]["id"] == x["mer"] and e["seance"]["categorie"] == "course"
    assert e["demain"] == ["repos"] and e["decalable"]
    assert "2026-10-07" not in e["jours_decalage"] and e["jours_decalage"][0] == "2026-10-08"


def test_seance_du_jour_faite_puis_prochaine():
    x = semaine_type()
    faire("course_route", "2026-10-07T18:30", 50, 7)
    e = ecran("2026-10-07")
    assert [s["sport_id"] for s in e["faites_aujourdhui"]] == ["course_route"]
    assert e["quand"] == "prochaine" and e["seance"]["id"] == x["ven"]       # jeudi : repos


def test_bande_de_la_semaine():
    semaine_type()
    etats = {j["jour"]: j["etat"] for j in ecran("2026-10-07")["bande"]}
    assert etats == {"lundi": "fait", "mardi": "manque", "mercredi": "aujourdhui", "jeudi": "repos",
                     "vendredi": "a_faire", "samedi": "a_faire", "dimanche": "libre"}
    services.saisir_seance({"sport_id": "muscu", "debut": "2026-10-07T07:00", "duree_min": 50, "rpe": 5}, analyser=False)
    etats = {j["jour"]: j["etat"] for j in ecran("2026-10-07")["bande"]}
    assert etats["mardi"] == "decale"                                     # Pull de mardi faite mercredi


def test_prochaine_apres_aujourdhui_vide():
    x = semaine_type()
    e = ecran("2026-10-08")                                              # jeudi : repos
    assert e["quand"] == "prochaine" and e["seance"]["id"] == x["ven"]
    bande = {j["jour"]: j["etat"] for j in e["bande"]}
    assert bande["vendredi"] == "prochaine" and bande["mercredi"] == "manque"


def test_compteur_et_statut():
    semaine_type()
    b = ecran("2026-10-07")["bilan_semaine"]
    assert b["seances"] == {"prevues": 5, "faites": 1}
    assert (b["respect_global"], b["sous_statut"], b["seances_en_retard"]) == ("en_cours", "en_retard", 1)


def test_sans_plan():
    e = ecran("2026-10-07")
    assert e["seance"] is None and e["plan_semaine"] is False and e["cap_semaine"]["plan"] is False


def test_bandeau_preparer_du_vendredi_au_dimanche():
    assert ecran("2026-10-07")["preparer_semaine_prochaine"] is False         # mercredi
    assert ecran("2026-10-09")["preparer_semaine_prochaine"] is True          # vendredi, rien la semaine suivante
    prevoir("2026-10-13", "EF")
    assert ecran("2026-10-09")["preparer_semaine_prochaine"] is False


def test_alerte_acwr(monkeypatch):
    monkeypatch.setattr(services, "acwr_au", lambda d: services.metrics.ACWR(500, 300, 1.67, "danger", 40))
    assert "1.67" in ecran("2026-10-07")["alerte"]


def test_route(client):
    r = client.get("/api/aujourdhui")
    assert r.status_code == 200 and len(r.json()["bande"]) == 7

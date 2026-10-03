"""Sources : ActiviteNormalisee, Strava (sans réseau), doublons entre sources."""

import json
from pathlib import Path

import pytest

import db
import services
from conftest import lire
from sources import strava, suunto_json
from sources.base import ActiviteNormalisee

DATA = Path(__file__).parent / "data"


def exemple(nom):
    d = json.loads((DATA / f"strava_{nom}.json").read_text())
    return d["activite"], d["streams"]


def test_trailrun_avec_stream():
    act, streams = exemple("run")
    a = strava.normaliser(act, streams)
    assert isinstance(a, ActiviteNormalisee)
    assert (a.source, a.source_id, a.source_code, a.sport_id) == ("strava", "12873465012", "TrailRun", "trail")
    assert a.duree_s == 3600 and a.distance_m == 10200 and a.d_plus_m == 480 and a.fc_moy == 141 and a.gps_present
    z = a.zones_minutes
    assert z["z2"] == pytest.approx(20, abs=0.1) and z["z3"] == pytest.approx(30) and z["z4"] == pytest.approx(10)


def test_badminton_sans_stream():
    a = strava.normaliser(*exemple("badminton"))
    assert a.sport_id == "badminton" and a.sport_connu and a.zones_minutes == {} and not a.gps_present


def test_sport_type_inconnu():
    act, _ = exemple("badminton")
    a = strava.normaliser({**act, "sport_type": "Kitesurf"})
    assert a.sport_id == "autre" and not a.sport_connu and a.source_code == "Kitesurf"


def test_correspondance_apprise_prioritaire():
    act, _ = exemple("badminton")
    assert strava.normaliser({**act, "sport_type": "Workout"}).sport_id == "calisthenics"      # catalogue
    assert strava.normaliser({**act, "sport_type": "Workout"}, None, {"Workout": "muscu"}).sport_id == "muscu"


def test_import_strava_charge_et_dedoublonnage():
    act, streams = exemple("run")
    r = services.importer_strava(act, streams, analyser=False)
    s = db.seance(r["seance"]["id"])
    assert s["source"] == "strava" and s["sport_id"] == "trail" and s["famille"] == "course_outdoor"
    assert s["charge"] == pytest.approx(20 * 2 + 30 * 3 + 10 * 4, abs=0.5)     # TRIMP depuis le stream
    assert s["date_debut"] == "2026-10-04T08:30:00+02:00"
    assert services.importer_strava(act, streams)["doublon"]                    # même id Strava


def test_suunto_normalise():
    brut = lire("course_outdoor")
    a = suunto_json.normaliser(json.loads(brut), db.activity_types(), suunto_json.empreinte(brut))
    assert a.source == "suunto_json" and a.source_id == a.empreinte and a.sport_id == "course_route"
    assert a.sous_type and a.details["epoc"] is not None


def _strava_jumelle(seance, **kw):
    """Activité Strava de la même séance qu'une séance Suunto déjà importée."""
    act = {"id": 42, "name": "x", "sport_type": kw.pop("sport_type", "Squash"),
           "start_date": seance["date_debut"], "moving_time": seance["duree_min"] * 60,
           "distance": 0, "average_heartrate": 150, **kw}
    return act


def test_doublon_suunto_puis_strava():
    r = services.importer_et_analyser(lire("squash"), "s.json", analyser=False)
    s = db.seance(r["seance"]["id"])
    act = _strava_jumelle(s, start_date=s["date_debut"][:16].replace("T", "T") + ":00+02:00")
    r2 = services.importer_strava({**act, "moving_time": s["duree_min"] * 60 * 1.05}, analyser=False)
    assert r2["fusion"] and r2["seance_id"] == s["id"]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM seances_realisees")["n"] == 1
    assert db.seance(s["id"])["source"] == "suunto_json"                     # la source la plus riche reste


def test_pas_de_doublon_hors_tolerance():
    r = services.importer_et_analyser(lire("squash"), "s.json", analyser=False)
    s = db.seance(r["seance"]["id"])
    services.importer_strava({**_strava_jumelle(s), "moving_time": s["duree_min"] * 60 * 1.3}, analyser=False)
    assert db.fetch_one("SELECT COUNT(*) AS n FROM seances_realisees")["n"] == 2


def test_manuel_puis_suunto_garde_le_rpe_et_le_sport():
    r = services.importer_et_analyser(lire("squash"), "s.json", analyser=False)
    s = db.seance(r["seance"]["id"])
    with db.connexion() as c:                                        # on repart d'une saisie manuelle seule
        c.execute("DELETE FROM seances_realisees")
    services.saisir_seance({"sport_id": "badminton", "debut": s["date_debut"], "duree_min": s["duree_min"], "rpe": 8},
                           analyser=False)
    r2 = services.importer_et_analyser(lire("squash"), "s.json", analyser=False)
    assert r2.get("fusion")
    seule = db.fetch_one("SELECT * FROM seances_realisees")
    assert db.fetch_one("SELECT COUNT(*) AS n FROM seances_realisees")["n"] == 1
    assert seule["source"] == "suunto_json" and seule["rpe"] == 8 and seule["sport_id"] == "badminton"
    assert seule["charge"] == pytest.approx(s["charge"])                     # mesures du fichier
    assert services.importer_et_analyser(lire("squash"), "s.json")["doublon"]  # réimport : même hash


def test_saisie_apres_import_complete_le_rpe():
    r = services.importer_et_analyser(lire("squash"), "s.json", analyser=False)
    s = db.seance(r["seance"]["id"])
    r2 = services.saisir_seance({"sport_id": "squash", "debut": s["date_debut"], "duree_min": s["duree_min"] + 2,
                                 "rpe": 7, "note": "dur"}, analyser=False)
    assert r2["fusion"]
    apres = db.seance(s["id"])
    assert apres["rpe"] == 7 and apres["note"] == "dur" and apres["charge"] == s["charge"]

"""Import Suunto : codes appris dans activity_types, sport à préciser, proposition automatique."""

import json

import db
import extractor
import services
from conftest import lire
from test_api import anonyme, client  # noqa: F401 (fixtures)


def forger(nom, code, **header):
    data = json.loads(lire(nom))
    data["DeviceLog"]["Header"]["ActivityType"] = code
    data["DeviceLog"]["Header"].update(header)
    return json.dumps(data).encode()


def test_code_82_trail():
    r = services.importer_et_analyser(forger("course_outdoor", 82), "trail.json", analyser=False)
    s = db.seance(r["seance"]["id"])
    assert s["sport_id"] == "trail" and s["famille"] == "course_outdoor" and s["sport_a_preciser"] == 0
    assert s["sous_type"] is not None                         # détection fine de la course


def test_plus_de_table_en_dur():
    assert not hasattr(extractor, "ACTIVITY_TYPE_MAP")
    s = extractor.extraire(json.loads(lire("squash")))       # sans correspondances : jamais d'échec
    assert s.sport_id == "autre" and not s.code_connu


def test_code_inconnu_puis_appris():
    premier = forger("squash", 999)
    r = services.importer_et_analyser(premier, "a.json")      # le LLM n'est pas appelé (sport à préciser)
    sid = r["seance"]["id"]
    s = db.seance(sid)
    assert s["sport_id"] == "autre" and s["sport_a_preciser"] == 1 and s["source_code"] == "999"
    assert s["charge"] > 0                                    # charge TRIMP calculée malgré tout
    assert r["sport_a_preciser"] and r["analyse_llm"] is None and r["erreur_llm"] is None

    services.preciser_sport(sid, "badminton", analyser=False)
    s = db.seance(sid)
    assert s["sport_id"] == "badminton" and s["famille"] == "squash" and s["sport_a_preciser"] == 0
    assert db.activity_types()["999"] == "badminton"

    second = forger("squash", 999, DateTime="2026-09-30T19:00:00.000+02:00")
    r2 = services.importer_et_analyser(second, "b.json", analyser=False)
    assert db.seance(r2["seance"]["id"])["sport_id"] == "badminton" and not r2["sport_a_preciser"]


def test_preciser_reprend_les_seances_en_attente():
    a = services.importer_et_analyser(forger("squash", 555), "a.json", analyser=False)["seance"]["id"]
    b = services.importer_et_analyser(forger("squash", 555, DateTime="2026-10-01T19:00:00.000+02:00"),
                                      "b.json", analyser=False)["seance"]["id"]
    services.preciser_sport(a, "padel", analyser=False)
    assert db.seance(b)["sport_id"] == "padel" and db.seance(b)["sport_a_preciser"] == 0


def test_choix_des_l_apercu():
    brut = forger("velo", 777)
    assert services.apercu_import(brut, "x.json")["sport_a_preciser"]
    r = services.importer_et_analyser(brut, "x.json", sport_id="rameur", analyser=False)
    assert r["seance"]["sport_id"] == "rameur" and db.activity_types()["777"] == "rameur"


def test_reimport_sans_doublon():
    brut = forger("squash", 999)
    services.importer_et_analyser(brut, "a.json", analyser=False)
    assert services.importer_et_analyser(brut, "a.json")["doublon"]
    assert services.apercu_import(brut, "a.json")["doublon"]


def test_corriger_une_correspondance():
    services.importer_et_analyser(forger("squash", 37), "a.json", analyser=False)
    c = {x["code"]: x for x in services.correspondances()}["37"]
    assert c["sport_id"] == "squash" and c["seances"] == 1

    r = services.corriger_correspondance("suunto_json", "37", "badminton")         # sans réaffecter
    assert r["seances_reaffectees"] == 0
    assert db.fetch_one("SELECT sport_id FROM seances_realisees")["sport_id"] == "squash"
    r = services.corriger_correspondance("suunto_json", "37", "badminton", reaffecter=True)
    assert r["seances_reaffectees"] == 1
    assert db.fetch_one("SELECT sport_id FROM seances_realisees")["sport_id"] == "badminton"


def _seance(**kw):
    base = dict(activity_type_code=1, famille="autre", date_debut="2026-10-01T10:00:00", duree_s=3600, duree_min=60)
    return extractor.SeanceExtraite(**{**base, **kw})


def test_propositions():
    assert extractor.deviner_sport(_seance(a_gps=True, distance_km=10, d_plus_m=400))["sport_id"] == "trail"
    assert extractor.deviner_sport(_seance(a_gps=True, distance_km=10, d_plus_m=50, vitesse_moy_kmh=11))["sport_id"] == "course_route"
    assert extractor.deviner_sport(_seance(a_gps=True, distance_km=30, vitesse_moy_kmh=25))["sport_id"] == "velo_route"
    assert extractor.deviner_sport(_seance(fc_moy_bpm=150)) == {"sport_id": None, "categorie": "raquette"}
    assert extractor.deviner_sport(_seance(fc_moy_bpm=110)) is None
    assert extractor.deviner_sport(_seance(duree_min=150, fc_moy_bpm=150)) is None


def test_api(client):
    r = client.post("/api/import", files={"fichier": ("a.json", forger("squash", 999))},
                    data={"options": json.dumps({"analyser": False})}).json()
    assert r["sport_a_preciser"] and r["proposition"]["categorie"] == "raquette"
    sid = r["seance"]["id"]
    assert client.post(f"/api/seances_realisees/{sid}/sport", json={"sport_id": "inexistant"}).status_code == 422
    assert client.post(f"/api/seances_realisees/{sid}/sport", json={"sport_id": "badminton", "analyser": False}).status_code == 200
    assert any(c["code"] == "999" for c in client.get("/api/correspondances").json())
    r = client.put("/api/correspondances/suunto_json/999", json={"sport_id": "tennis", "reaffecter": True}).json()
    assert r["seances_reaffectees"] == 1

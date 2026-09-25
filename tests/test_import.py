"""Import de bout en bout sur les 5 fichiers Suunto réels, sans LLM."""

import json

import pytest

import db
import services
from conftest import lire

ATTENDUS = {
    # nom: (famille, date locale, durée min, distance km)
    "course_outdoor": ("course_outdoor", "2026-09-15", 35.1, 6.4),
    "course_tapis": ("course_tapis", "2026-09-23", 30.1, 3.85),
    "muscu": ("muscu", "2026-09-20", 81.1, 0.0),
    "squash": ("squash", "2026-08-27", 63.0, 0.0),
    "velo": ("velo", "2026-09-20", 37.1, 0.0),
}


@pytest.mark.parametrize("nom", ATTENDUS)
def test_import_cinq_fichiers(nom):
    famille, jour, duree, distance = ATTENDUS[nom]
    r = services.importer_et_analyser(lire(nom), f"{nom}.json")

    assert r["doublon"] is False
    s = r["seance"]
    assert s["famille"] == famille
    assert s["date_debut"].startswith(jour)
    assert s["date_debut"].endswith("+02:00")
    assert s["duree_min"] == duree
    assert s["distance_km"] == distance
    assert s["a_fc"] == 1 and 60 < s["fc_moy"] < 191
    assert set(s["temps_zones_pct"]) == {"z1", "z2", "z3", "z4", "z5"}
    assert s["charge"] == pytest.approx(s["epoc"], abs=0.1)
    assert r["verdict"] in ("vert", "orange", "rouge")
    assert r["analyse_llm"] is None

    # La ligne en base contient le JSON brut complet
    en_base = db.seance(s["id"])
    assert en_base["donnees_brutes"]["famille"] == famille


def test_sous_type_course():
    r = services.importer_et_analyser(lire("course_tapis"), "tapis.json")
    assert r["seance"]["sous_type"] == "EF"
    assert r["seance"]["sous_type_confiance"] == 0.85
    assert r["seance"]["sous_type_confirme"] == 0


def test_anti_doublon():
    premier = services.importer_et_analyser(lire("squash"), "a.json")
    second = services.importer_et_analyser(lire("squash"), "copie.json")
    assert second["doublon"] is True
    assert second["seance_id"] == premier["seance"]["id"]
    assert len(db.fetch_all("SELECT id FROM seances_realisees")) == 1

    apercu = services.apercu_import(lire("squash"), "copie.json")
    assert apercu["doublon"] is True


def test_apercu_sans_ecriture():
    a = services.apercu_import(lire("course_outdoor"), "outdoor.json")
    assert a["doublon"] is False
    assert a["seance"]["famille"] == "course_outdoor"
    # Confiance 0,6 : pas strictement sous le seuil
    assert a["demander_sous_type"] is False
    assert a["split_propose"] is None
    assert db.fetch_all("SELECT id FROM seances_realisees") == []


def test_rotation_muscu():
    assert services.apercu_import(lire("muscu"), "m.json")["split_propose"] == "push_a"
    services.importer_et_analyser(
        lire("muscu"), "m.json",
        muscu_detail={"split": "push_a", "groupes": ["pectoraux", "triceps", "inconnu"],
                      "charges": [{"exo": "DC haltères", "kg": "28", "reps": "8", "series": "4"},
                                  {"exo": "", "kg": "10"}]},
    )
    d = db.fetch_one("SELECT * FROM muscu_detail")
    assert d["groupes"] == ["pectoraux", "triceps"]
    assert d["charges"] == [{"exo": "DC haltères", "kg": 28, "reps": 8, "series": 4}]
    assert services.split_propose() == "pull_a"
    assert services.split_suivant("pull_b") == "push_a"


def test_rattachement_au_prevu_et_verdict():
    # EF prévue le jour de la sortie outdoor : 65 % en Z3 → rouge
    pid = db.inserer("seances_planifiees", {
        "date_seance": "2026-09-15", "creneau": "matin", "type": "EF",
        "duree_min": 40, "distance_km": 8, "origine": "manuel",
    })
    r = services.importer_et_analyser(lire("course_outdoor"), "outdoor.json")
    assert r["prevu"]["id"] == pid
    noms = {s["nom"]: s["niveau"] for s in r["indicateurs"]["signaux"]}
    assert noms.get("z3_sur_ef") == "rouge"
    assert r["verdict"] == "rouge"

    p = db.planifiee(pid)
    assert p["statut"] == "realise"
    assert p["seance_realisee_id"] == r["seance"]["id"]


def test_prevu_autre_famille_non_rattache():
    db.inserer("seances_planifiees", {"date_seance": "2026-09-20", "creneau": "matin",
                                      "type": "EF", "origine": "manuel"})
    r = services.importer_et_analyser(lire("velo"), "velo.json")
    assert r["prevu"] is None


def test_prochaine_qualite():
    db.inserer("seances_planifiees", {"date_seance": "2026-09-17", "creneau": "matin",
                                      "type": "intervals", "origine": "manuel"})
    r = services.importer_et_analyser(lire("course_outdoor"), "outdoor.json")
    # Fin de séance le 15 à ~08:02, intervals le 17 à 07:00
    assert r["indicateurs"]["prochaine_qualite_dans_h"] == pytest.approx(47.0, abs=0.1)


def test_acwr_et_distribution():
    for nom in ATTENDUS:
        services.importer_et_analyser(lire(nom), f"{nom}.json")
    from datetime import date
    a = services.acwr_au(date(2026, 9, 23))
    # Aiguë 17-23 sept : muscu + vélo + tapis ; chronique : outdoor (15) + squash (27/08)
    assert a.charge_aigue == pytest.approx(13.5 + 41.1 + 23)
    assert a.charge_chronique == pytest.approx((87.3 + 149.8) / 4)
    dist = services.distribution_semaine(date(2026, 9, 21))
    assert dist["z1_z2"] > 90


def test_type_inconnu():
    data = json.loads(lire("velo"))
    data["DeviceLog"]["Header"]["ActivityType"] = 999
    brut = json.dumps(data).encode()

    a = services.apercu_import(brut, "x.json")
    assert a["demander_famille"] is True
    with pytest.raises(services.ErreurImport):
        services.importer_et_analyser(brut, "x.json")

    r = services.importer_et_analyser(brut, "x.json", famille="velo")
    assert r["seance"]["famille"] == "velo"
    assert db.activity_types()[999] == "velo"


def test_fichier_invalide():
    with pytest.raises(services.ErreurImport):
        services.apercu_import(b"pas du json", "x.json")
    with pytest.raises(services.ErreurImport):
        services.apercu_import(b'{"autre": 1}', "x.json")

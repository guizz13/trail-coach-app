"""Saisie manuelle d'une séance réalisée, charge RPE / FC, RPE à l'import."""

import pytest

import db
import metrics
import services
import sports
from conftest import lire
from test_api import anonyme, client  # noqa: F401 (fixtures)


def saisir(**kw):
    base = {"sport_id": "badminton", "debut": "2026-10-03T10:00", "duree_min": 60, "rpe": 7}
    return services.saisir_seance({**base, **kw}, analyser=False)


def test_badminton_rpe_7():
    r = saisir()
    s = db.seance(r["seance"]["id"])
    assert s["charge"] == 180
    assert (s["source"], s["sport_id"], s["famille"]) == ("manuel", "badminton", "squash")
    assert sports.categorie(s["sport_id"]) == "raquette" and sports.impact(s["sport_id"]) == "eleve"
    assert s["date_debut"] == "2026-10-03T10:00:00+02:00" and len(s["source_id"]) == 36


def test_charge_par_la_fc():
    assert metrics.charge_manuelle(60, fc_moy=150) == 180        # Z3 (144-157)
    assert metrics.charge_manuelle(30, rpe=9, fc_moy=120) == 30   # la FC prime sur le RPE
    assert metrics.charge_manuelle(45, rpe=2) == 45


def test_charge_conservee_par_le_recalcul():
    sid = saisir()["seance"]["id"]
    services.recalculer_tout()
    assert db.seance(sid)["charge"] == 180


def test_rpe_obligatoire_sans_fc():
    with pytest.raises(services.ErreurImport):
        saisir(rpe=None)
    assert saisir(rpe=None, fc_moy=130)["seance"]["charge"] == 120


@pytest.mark.parametrize("champ,valeur", [("sport_id", "inexistant"), ("duree_min", 0), ("rpe", 11), ("debut", "hier")])
def test_validation(champ, valeur):
    with pytest.raises(services.ErreurImport):
        saisir(**{champ: valeur})


def test_distance_seulement_si_le_sport_en_a():
    assert db.seance(saisir(distance_km=5, dplus_m=100)["seance"]["id"])["distance_km"] == 0
    s = db.seance(saisir(sport_id="trail", distance_km=12, dplus_m=600, rpe=5, duree_min=90)["seance"]["id"])
    assert s["distance_km"] == 12 and s["dplus_m"] == 600 and s["famille"] == "course_outdoor"


def test_compte_dans_l_acwr():
    saisir(debut="2026-10-01T18:00")
    jours = dict(metrics.charges_par_jour(db.seances_entre("0000-01-01", "2026-10-05"),
                                          __import__("datetime").date(2026, 10, 1), __import__("datetime").date(2026, 10, 1)))
    assert list(jours.values()) == [180]


def test_rpe_a_l_import():
    r = services.importer_et_analyser(lire("squash"), "s.json", analyser=False, rpe=8)
    s = db.seance(r["seance"]["id"])
    assert s["rpe"] == 8 and s["charge"] == metrics.charge_seance({"temps_zones_s": s["temps_zones_s"]})


def test_api(client):
    r = client.post("/api/seances_realisees", json={"sport_id": "badminton", "debut": "2026-10-03T10:00",
                                                    "duree_min": 60, "rpe": 7, "analyser": False})
    assert r.status_code == 200 and r.json()["seance"]["charge"] == 180
    assert client.post("/api/seances_realisees", json={"sport_id": "badminton"}).status_code == 422

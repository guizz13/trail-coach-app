"""Règles de metrics.py : ACWR sur historique court, seuils de zones par discipline."""

from datetime import date, timedelta

import pytest

import metrics

REF = date(2026, 9, 25)


def seance(jours_avant: int, charge: float, famille: str = "course_outdoor") -> dict:
    """Séance sans FC : la charge TRIMP vaut durée × 2, on fixe donc la durée à charge / 2."""
    return {"date_debut": (REF - timedelta(days=jours_avant)).isoformat(), "duree_min": charge / 2,
            "epoc": charge, "famille": famille}


# ---- Section 3 (v4) : ACWR EWMA + calibrage ----------------------------------------------
def quotidiennes(jours: int, charge: float, fin: int = 0) -> list[dict]:
    """Une séance par jour, de `fin + jours - 1` jours avant REF jusqu'à `fin` jours avant."""
    return [seance(j, charge) for j in range(fin, fin + jours)]


def test_calibrage_17_jours():
    a = metrics.calculer_acwr(quotidiennes(18, 60), REF)      # première séance il y a 17 jours
    assert (a.zone, a.ratio, a.jours_historique) == ("calibrage", None, 17)
    assert a.verdict == "vert"


def test_calibrage_si_trou_de_plus_de_10_jours():
    # 40 jours d'historique, mais rien depuis 12 jours
    a = metrics.calculer_acwr(quotidiennes(28, 60, fin=12), REF)
    assert a.zone == "calibrage" and a.ratio is None


def test_charge_constante_ratio_un():
    a = metrics.calculer_acwr(quotidiennes(42, 60), REF)
    assert a.ratio == pytest.approx(1.0, abs=0.01) and a.zone == "optimal"


def test_quatre_seances_par_semaine_regulieres():
    seances = [seance(j, 80) for j in range(42) if j % 7 in (0, 2, 4, 5)]
    a = metrics.calculer_acwr(seances, REF)
    assert 0.8 <= a.ratio <= 1.3


def test_semaine_doublee_signal_conserve():
    seances = quotidiennes(28, 50, fin=7) + quotidiennes(7, 100)
    a = metrics.calculer_acwr(seances, REF)
    assert 1.3 <= a.ratio <= 1.6 and a.zone in ("vigilance", "danger")


def test_serie_quotidienne_sans_ratio_en_calibrage():
    serie = metrics.serie_quotidienne(quotidiennes(30, 60), REF)
    assert len(serie) == 30
    assert all(p["ratio"] is None for p in serie[:21]) and all(p["ratio"] is not None for p in serie[21:])


def test_sans_seance():
    assert metrics.calculer_acwr([], REF).zone == "calibrage"


def test_signal_info_pendant_le_calibrage():
    a = metrics.calculer_acwr(quotidiennes(10, 60), REF)
    verdict, signaux = metrics.evaluer_seance(seance(0, 60), None, a)
    assert verdict == "vert" and [x.niveau for x in signaux] == ["info"]


# ---- Point 5 : seuils par discipline -------------------------------------------------
ZONES_INTENSES = {"z1": 3, "z2": 10, "z3": 20, "z4": 35, "z5": 32}   # typique d'un match de squash


def test_squash_jamais_d_alerte_de_zones():
    s = {**seance(0, 150, "squash"), "temps_zones_pct": ZONES_INTENSES, "distance_km": 0}
    for prevu in ({"type": "EF"}, {"type": "sortie_longue"}, {"type": "squash", "distance_km": 5}, None):
        verdict, signaux = metrics.evaluer_seance(s, prevu, None)
        assert verdict == "vert" and signaux == [], prevu


def test_velo_et_muscu_sans_seuils_de_course():
    for fam in ("velo", "muscu"):
        s = {**seance(0, 140, fam), "temps_zones_pct": {"z3": 70, "z4": 20}, "distance_km": 30}
        verdict, _ = metrics.evaluer_seance(s, {"type": "EF", "distance_km": 10}, None)
        assert verdict == "vert", fam


def test_squash_garde_recovery_et_acwr():
    s = {**seance(0, 150, "squash"), "temps_zones_pct": ZONES_INTENSES, "recovery_time_h": 60}
    a = metrics.calculer_acwr(quotidiennes(28, 50, fin=7) + quotidiennes(7, 150), REF)
    assert a.zone == "danger"
    verdict, signaux = metrics.evaluer_seance(s, None, a)
    assert verdict == "rouge"
    assert {x.nom for x in signaux} == {"acwr", "recovery"}


def test_course_garde_ses_seuils():
    s = {**seance(0, 140), "temps_zones_pct": {"z3": 65}}
    verdict, signaux = metrics.evaluer_seance(s, {"type": "EF"}, None)
    assert verdict == "rouge" and {x.nom for x in signaux} == {"epoc_sur_ef", "z3_sur_ef"}


# ---- Section 2 (v4) : charge = TRIMP d'Edwards ----------------------------------------
def test_charge_trimp_squash():
    # 35 min de squash : 20 min Z4, 10 min Z5, 5 min Z2
    s = {"duree_min": 35, "epoc": 180, "temps_zones_s": {"z2": 300, "z4": 1200, "z5": 600}}
    assert 140 <= metrics.charge_seance(s) <= 150


def test_charge_ordres_de_grandeur():
    ef = {"duree_min": 45, "temps_zones_s": {"z2": 45 * 60}}
    assert metrics.charge_seance(ef) == 90
    sans_fc = {"duree_min": 40, "temps_zones_s": {}}
    assert metrics.charge_seance(sans_fc) == 80          # hypothèse Z2 moyenne
    assert metrics.charge_seance({"duree_min": 30, "epoc": 300}) == 60   # l'EPOC n'entre plus en jeu

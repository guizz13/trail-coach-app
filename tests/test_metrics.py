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


# ---- Section 4 (v4) : verdict découplé de l'ACWR ----------------------------------------------
ZONES_INTENSES = {"z1": 3, "z2": 10, "z3": 20, "z4": 35, "z5": 32}   # typique d'un match de squash
SANTE_OK = {"niveau": "100", "zones": []}


def course(**kw) -> dict:
    return {"famille": "course_outdoor", "duree_min": 45, "distance_km": 8, "temps_zones_pct": {"z2": 90, "z3": 10}, **kw}


def test_conforme_et_hors_plan():
    assert metrics.evaluer_seance(course(), {"type": "EF", "duree_min": 45, "distance_km": 8}, SANTE_OK)[0] == "vert"
    verdict, signaux = metrics.evaluer_seance(course(temps_zones_pct={"z3": 60, "z4": 30}), None, SANTE_OK)
    assert verdict == "hors_plan" and signaux == []          # aucun seuil sans prévu


def test_ef_trop_intense_orange():
    verdict, signaux = metrics.evaluer_seance(course(temps_zones_pct={"z2": 30, "z3": 65, "z4": 5}), {"type": "EF"}, SANTE_OK)
    assert verdict == "orange" and [x.nom for x in signaux] == ["ef_intensite"]


def test_seuils_de_course():
    longue = metrics.evaluer_seance(course(temps_zones_pct={"z3": 50, "z4": 35}), {"type": "sortie_longue"}, SANTE_OK)
    assert longue[0] == "orange" and longue[1][0].nom == "longue_intensite"
    ratee = metrics.evaluer_seance(course(temps_zones_pct={"z2": 70, "z3": 25, "z4": 5}), {"type": "intervals"}, SANTE_OK)
    assert ratee[0] == "orange" and ratee[1][0].nom == "intervals_non_atteints"


def test_plusieurs_oranges_jamais_rouge():
    r = course(duree_min=80, distance_km=14, temps_zones_pct={"z3": 70, "z4": 20})
    verdict, signaux = metrics.evaluer_seance(r, {"type": "EF", "duree_min": 45, "distance_km": 8}, SANTE_OK)
    assert len(signaux) == 3 and verdict == "orange"


def test_squash_jamais_d_alerte_de_zones():
    s = {"famille": "squash", "duree_min": 60, "temps_zones_pct": ZONES_INTENSES}
    for prevu in ({"type": "squash", "duree_min": 60}, {"type": "EF"}, {"type": "sortie_longue"}):
        assert metrics.evaluer_seance(s, prevu, SANTE_OK) == ("vert", []), prevu


def test_ecart_de_duree_toutes_disciplines():
    s = {"famille": "muscu", "duree_min": 30, "temps_zones_pct": {"z1": 100}}
    verdict, signaux = metrics.evaluer_seance(s, {"type": "muscu_pull", "duree_min": 60}, SANTE_OK)
    assert verdict == "orange" and signaux[0].nom == "ecart_duree"


def test_rouges_de_securite():
    assert metrics.evaluer_seance(course(douleur=5), None, SANTE_OK)[0] == "rouge"
    vigilance = {"niveau": "vigilance", "zones": ["Achille D"]}
    assert metrics.evaluer_seance(course(douleur=2, douleur_zone="Achille D"), {"type": "EF"}, vigilance)[0] == "rouge"
    assert metrics.evaluer_seance(course(douleur=2, douleur_zone="Dos"), {"type": "EF"}, vigilance)[0] == "vert"
    blessure = {"niveau": "blessure", "zones": ["Fascia G"]}
    assert metrics.evaluer_seance(course(), {"type": "EF"}, blessure)[0] == "rouge"
    assert metrics.evaluer_seance({"famille": "velo", "duree_min": 40}, None, blessure)[0] == "hors_plan"


def test_recovery_rouge_seulement_si_chevauchement():
    s = course(recovery_time_h=60)
    assert metrics.evaluer_seance(s, {"type": "EF"}, SANTE_OK, prochaine_qualite_dans_h=30)[0] == "rouge"
    assert metrics.evaluer_seance(s, {"type": "EF"}, SANTE_OK, prochaine_qualite_dans_h=72)[0] == "vert"
    assert metrics.evaluer_seance(s, {"type": "EF"}, SANTE_OK, None)[0] == "vert"
    assert metrics.evaluer_seance(course(recovery_time_h=40), {"type": "EF"}, SANTE_OK, 20)[0] == "vert"


def test_squash_35_min_ne_genere_pas_de_rouge():
    s = {"famille": "squash", "duree_min": 35, "epoc": 180, "recovery_time_h": 30,
         "temps_zones_s": {"z2": 300, "z4": 1200, "z5": 600}, "temps_zones_pct": {"z2": 14, "z4": 57, "z5": 29}}
    assert metrics.evaluer_seance(s, {"type": "squash", "duree_min": 35}, SANTE_OK, 20)[0] == "vert"


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

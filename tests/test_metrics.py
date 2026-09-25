"""Règles de metrics.py : ACWR sur historique court, seuils de zones par discipline."""

from datetime import date, timedelta

import metrics

REF = date(2026, 9, 25)


def seance(jours_avant: int, epoc: float, famille: str = "course_outdoor") -> dict:
    return {"date_debut": (REF - timedelta(days=jours_avant)).isoformat(), "epoc": epoc, "famille": famille}


# ---- Point 4 : ACWR ------------------------------------------------------------
def test_acwr_sans_historique_chronique():
    a = metrics.calculer_acwr([seance(1, 120), seance(3, 80)], REF)
    assert a.zone == "insuffisant" and a.ratio is None and a.verdict == "vert"


def test_acwr_historique_court_ne_passe_pas_en_danger():
    # Chronique : une seule séance 10 jours avant la fenêtre aiguë → ratio 3,4 mais non fiable
    a = metrics.calculer_acwr([seance(16, 150), seance(1, 128)], REF)
    assert a.ratio == round(128 / (150 / 4), 2)
    assert a.zone == "insuffisant"


def test_acwr_historique_suffisant():
    chronique = [seance(j, 100) for j in (8, 12, 16, 20, 24, 28, 32)]
    a = metrics.calculer_acwr(chronique + [seance(1, 400)], REF)
    assert a.zone == "danger" and a.ratio == round(400 / 175, 2)


def test_signal_info_si_historique_insuffisant():
    a = metrics.calculer_acwr([seance(16, 150), seance(1, 128)], REF)
    verdict, signaux = metrics.evaluer_seance(seance(1, 128), None, a)
    assert verdict == "vert"
    assert [(s.nom, s.niveau, s.detail) for s in signaux] == [("acwr", "info", "Historique de charge trop court pour évaluer")]


def test_signal_info_si_charge_chronique_faible():
    # Historique assez long mais charge chronique moyenne < 50 : pas d'alerte ACWR
    chronique = [seance(j, 20) for j in (8, 20, 32)]
    a = metrics.calculer_acwr(chronique + [seance(1, 100)], REF)
    assert a.zone == "danger" and a.charge_chronique < 50
    verdict, signaux = metrics.evaluer_seance(seance(1, 100), None, a)
    assert verdict == "vert" and signaux[0].niveau == "info"


def test_alerte_acwr_conservee_si_historique_fiable():
    chronique = [seance(j, 100) for j in (8, 12, 16, 20, 24, 28, 32)]
    a = metrics.calculer_acwr(chronique + [seance(1, 400)], REF)
    verdict, signaux = metrics.evaluer_seance(seance(1, 400), None, a)
    assert verdict == "rouge" and signaux[0].nom == "acwr" and signaux[0].niveau == "rouge"


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
    chronique = [seance(j, 100) for j in (8, 12, 16, 20, 24, 28, 32)]
    a = metrics.calculer_acwr(chronique + [seance(0, 400, "squash")], REF)
    verdict, signaux = metrics.evaluer_seance(s, None, a)
    assert verdict == "rouge"
    assert {x.nom for x in signaux} == {"acwr", "recovery"}


def test_course_garde_ses_seuils():
    s = {**seance(0, 140), "temps_zones_pct": {"z3": 65}}
    verdict, signaux = metrics.evaluer_seance(s, {"type": "EF"}, None)
    assert verdict == "rouge" and {x.nom for x in signaux} == {"epoc_sur_ef", "z3_sur_ef"}

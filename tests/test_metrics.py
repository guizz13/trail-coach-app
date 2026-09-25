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

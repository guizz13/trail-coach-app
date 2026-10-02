"""
Métriques d'entraînement : charge, ACWR, distribution polarisée, seuils.

Ces calculs sont déterministes et faits AVANT l'appel LLM.
La charge d'une séance est le TRIMP d'Edwards (minutes × poids de zone), pas l'EPOC.
Le LLM reçoit les résultats et les interprète ; il ne les recalcule pas.

Références :
  - ACWR : Gabbett 2016 — zone optimale 0,8-1,3, danger > 1,5 ; calcul EWMA (Williams et al. 2017)
  - Distribution polarisée : Seiler & Kjerland 2006 — cible ~80 % Z1-Z2
  - Seuils d'alerte : section 9 du system prompt
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Charge d'une séance
# ---------------------------------------------------------------------------
POIDS_ZONES = {"z1": 1, "z2": 2, "z3": 3, "z4": 4, "z5": 5}


def charge_seance(seance: dict) -> float:
    """
    Charge d'une séance : TRIMP d'Edwards, somme des minutes passées dans chaque zone × poids de la zone.

    Les zones viennent de extractor._calculer_zones (temps_zones_s, en secondes ; le temps sous Z1
    est compté en Z1). Sans fréquence cardiaque : hypothèse d'une Z2 moyenne (durée × 2).
    L'EPOC Suunto (pic d'excès d'oxygène, non cumulable) ne participe plus à la charge.
    """
    zones_s = seance.get("temps_zones_s") or {}
    if zones_s and sum(zones_s.values()) > 0:
        return round(sum(POIDS_ZONES[z] * zones_s.get(z, 0) / 60 for z in POIDS_ZONES), 1)
    return round(float(seance.get("duree_min") or 0) * 2, 1)


def charge_semaine(seances: Iterable[dict]) -> float:
    return sum(charge_seance(s) for s in seances)


# ---------------------------------------------------------------------------
# ACWR : moyennes mobiles exponentielles (Williams et al. 2017) + calibrage
# ---------------------------------------------------------------------------
LAMBDA_AIGU = 2 / (7 + 1)          # 0,25
LAMBDA_CHRONIQUE = 2 / (28 + 1)    # ≈ 0,069
JOURS_CALIBRAGE = 21               # historique minimal avant d'exposer un ratio
TROU_MAX_JOURS = 10                # trou toléré (jours consécutifs sans séance) sur les 28 derniers jours
FENETRE_TROU = 28


@dataclass
class ACWR:
    charge_aigue: float          # EWMA 7 j de la charge quotidienne
    charge_chronique: float      # EWMA 28 j
    ratio: Optional[float]       # None pendant le calibrage : jamais affiché ni utilisé
    zone: str                    # calibrage | sous_charge | optimal | vigilance | danger
    jours_historique: int = 0    # jours depuis la première séance

    @property
    def verdict(self) -> str:
        return {"calibrage": "vert", "sous_charge": "vert", "optimal": "vert",
                "vigilance": "orange", "danger": "rouge"}[self.zone]


def charges_par_jour(seances: Iterable[dict], du: date, au: date) -> list[tuple[date, float]]:
    """Charge quotidienne totale (toutes disciplines), jours consécutifs, 0 les jours sans séance."""
    totaux: dict[date, float] = {}
    for s in seances:
        d = _date_de(s)
        if d is not None and du <= d <= au:
            totaux[d] = totaux.get(d, 0.0) + charge_seance(s)
    return [(du + timedelta(days=i), totaux.get(du + timedelta(days=i), 0.0)) for i in range((au - du).days + 1)]


def serie_acwr(charges: list[tuple[date, float]]) -> list[dict]:
    aigu = chronique = None
    serie = []
    for jour, charge in charges:                 # jours consécutifs, sans trou
        if aigu is None:
            aigu = chronique = charge
        else:
            aigu = aigu + LAMBDA_AIGU * (charge - aigu)
            chronique = chronique + LAMBDA_CHRONIQUE * (charge - chronique)
        ratio = aigu / chronique if chronique and chronique > 1 else None
        serie.append({"date": jour, "aigu": aigu, "chronique": chronique, "ratio": ratio})
    return serie


def zone_ratio(ratio: float) -> str:
    if ratio < 0.8:
        return "sous_charge"
    if ratio <= 1.3:
        return "optimal"
    if ratio <= 1.5:
        return "vigilance"
    return "danger"


def calibre(dates_seances: set, jour: date) -> tuple[bool, int]:
    """Historique fiable si la première séance date d'au moins 21 jours et qu'aucun trou
    de plus de 10 jours consécutifs sans séance n'existe sur les 28 derniers jours."""
    passees = [d for d in dates_seances if d <= jour]
    if not passees:
        return False, 0
    jours = (jour - min(passees)).days
    if jours < JOURS_CALIBRAGE:
        return False, jours
    trou = plus_long = 0
    for k in range(FENETRE_TROU):
        if jour - timedelta(days=FENETRE_TROU - 1 - k) in dates_seances:
            trou = 0
        else:
            trou += 1
            plus_long = max(plus_long, trou)
    return plus_long <= TROU_MAX_JOURS, jours


def serie_quotidienne(seances: list[dict], au: date) -> list[dict]:
    """Série jour par jour, de la première séance à `au` : aigu, chronique, ratio (None en
    calibrage), zone et jours d'historique."""
    dates = {d for d in (_date_de(s) for s in seances) if d is not None and d <= au}
    if not dates:
        return []
    serie = serie_acwr(charges_par_jour(seances, min(dates), au))
    for point in serie:
        ok, jours = calibre(dates, point["date"])
        point["jours_historique"] = jours
        if not ok or point["ratio"] is None:
            point["ratio"], point["zone"] = None, "calibrage"
        else:
            point["ratio"] = round(point["ratio"], 2)
            point["zone"] = zone_ratio(point["ratio"])
    return serie


def calculer_acwr(seances: list[dict], date_ref: Optional[date] = None) -> ACWR:
    """
    seances : toutes les séances depuis la première (l'EWMA démarre au premier jour importé).
    date_ref : jour évalué (défaut : aujourd'hui).
    """
    date_ref = date_ref or date.today()
    serie = serie_quotidienne(seances, date_ref)
    if not serie:
        return ACWR(0.0, 0.0, None, "calibrage", 0)
    p = serie[-1]
    return ACWR(p["aigu"], p["chronique"], p["ratio"], p["zone"], p["jours_historique"])


def _date_de(s: dict) -> Optional[date]:
    iso = s.get("date_debut")
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Distribution polarisée hebdomadaire (course uniquement)
# ---------------------------------------------------------------------------
def distribution_hebdo(seances_course: Iterable[dict]) -> dict:
    """Retourne {'z1_z2': %, 'z3': %, 'z4_z5': %, 'verdict': ...}"""
    tot = {"z1": 0.0, "z2": 0.0, "z3": 0.0, "z4": 0.0, "z5": 0.0}
    for s in seances_course:
        for z, v in (s.get("temps_zones_s") or {}).items():
            tot[z] = tot.get(z, 0) + v
    total = sum(tot.values())
    if total == 0:
        return {"z1_z2": 0, "z3": 0, "z4_z5": 0, "verdict": "vert", "note": "pas de données FC"}

    z12 = round(100 * (tot["z1"] + tot["z2"]) / total, 1)
    z3 = round(100 * tot["z3"] / total, 1)
    z45 = round(100 * (tot["z4"] + tot["z5"]) / total, 1)

    if z12 < 60:
        verdict = "rouge"
    elif z12 < 70:
        verdict = "orange"
    else:
        verdict = "vert"

    return {"z1_z2": z12, "z3": z3, "z4_z5": z45, "verdict": verdict}


# ---------------------------------------------------------------------------
# Évaluation des seuils d'alerte sur UNE séance vs son prévu
# ---------------------------------------------------------------------------
SEUILS = {
    "epoc_ef":        {"orange": 100, "rouge": 130},
    "z3_sur_ef":      {"orange": 40,  "rouge": 60},
    "z45_sur_longue": {"orange": 30,  "rouge": 45},
    "ecart_volume":   {"orange": 25,  "rouge": 40},   # en %
    "acwr":           {"orange": 1.4, "rouge": 1.5},
    "recovery_h":     {"rouge": 48},
}
FAMILLES_COURSE = {"course_outdoor", "course_tapis"}


@dataclass
class Signal:
    nom: str
    niveau: str        # orange | rouge | info (informatif, sans effet sur le verdict)
    valeur: float
    seuil: float
    detail: str


def evaluer_seance(realise: dict, prevu: Optional[dict], acwr: Optional[ACWR],
                   prochaine_qualite_dans_h: Optional[float] = None) -> tuple[str, list[Signal]]:
    """
    realise : séance extraite (dict de SeanceExtraite)
    prevu   : {'type': 'EF'|'intervals'|..., 'distance_km': x, 'duree_min': y} ou None
    acwr    : résultat de calculer_acwr après intégration de cette séance
    prochaine_qualite_dans_h : heures avant la prochaine séance qualité planifiée

    Retourne (verdict, signaux).
    """
    signaux: list[Signal] = []
    pct = realise.get("temps_zones_pct") or {}
    z3 = pct.get("z3", 0)
    z45 = pct.get("z4", 0) + pct.get("z5", 0)
    epoc = realise.get("epoc") or 0
    type_prevu = (prevu or {}).get("type")
    # Seuils de zones, d'EPOC et de volume : course uniquement. Le squash vit en Z4-Z5 par nature ;
    # pour squash, vélo et muscu, seuls l'ACWR et la récupération s'appliquent.
    course = realise.get("famille") in FAMILLES_COURSE

    # EF : dérive Z3 et EPOC
    if course and type_prevu == "EF":
        _check(signaux, "epoc_sur_ef", epoc, SEUILS["epoc_ef"],
               f"EPOC {epoc:.0f} sur une séance prévue en endurance fondamentale")
        _check(signaux, "z3_sur_ef", z3, SEUILS["z3_sur_ef"],
               f"{z3:.0f} % du temps en Z3 sur une EF")

    # Sortie longue : intensité
    if course and type_prevu == "sortie_longue":
        _check(signaux, "z45_sur_longue", z45, SEUILS["z45_sur_longue"],
               f"{z45:.0f} % du temps en Z4-Z5 sur une sortie longue")

    # Écart de volume
    if course and prevu and prevu.get("distance_km") and realise.get("distance_km"):
        ecart = abs(realise["distance_km"] - prevu["distance_km"]) / prevu["distance_km"] * 100
        _check(signaux, "ecart_volume", ecart, SEUILS["ecart_volume"],
               f"écart de {ecart:.0f} % entre {realise['distance_km']} km réalisés et {prevu['distance_km']} km prévus")

    # ACWR : pas d'alerte tant que l'historique de charge est trop court pour être fiable
    if acwr and acwr.zone == "calibrage":
        signaux.append(Signal("acwr", "info", acwr.jours_historique, JOURS_CALIBRAGE,
                              "Historique de charge trop court pour évaluer"))
    elif acwr and acwr.ratio is not None:
        _check(signaux, "acwr", acwr.ratio, SEUILS["acwr"],
               f"ACWR à {acwr.ratio} (charge aiguë {acwr.charge_aigue:.0f} / chronique {acwr.charge_chronique:.0f})")

    # RecoveryTime vs prochaine qualité
    rec_h = realise.get("recovery_time_h") or 0
    if rec_h > SEUILS["recovery_h"]["rouge"]:
        signaux.append(Signal("recovery", "rouge", rec_h, 48,
                              f"récupération estimée {rec_h:.0f} h"))
    elif prochaine_qualite_dans_h is not None and rec_h > prochaine_qualite_dans_h:
        signaux.append(Signal("recovery", "orange", rec_h, prochaine_qualite_dans_h,
                              f"récupération {rec_h:.0f} h chevauche la prochaine séance qualité dans {prochaine_qualite_dans_h:.0f} h"))

    # Verdict global : rouge si un rouge ou deux oranges
    nb_rouge = sum(1 for s in signaux if s.niveau == "rouge")
    nb_orange = sum(1 for s in signaux if s.niveau == "orange")
    if nb_rouge or nb_orange >= 2:
        verdict = "rouge"
    elif nb_orange:
        verdict = "orange"
    else:
        verdict = "vert"
    return verdict, signaux


def _check(signaux: list, nom: str, valeur: float, seuils: dict, detail: str) -> None:
    if "rouge" in seuils and valeur > seuils["rouge"]:
        signaux.append(Signal(nom, "rouge", valeur, seuils["rouge"], detail))
    elif "orange" in seuils and valeur > seuils["orange"]:
        signaux.append(Signal(nom, "orange", valeur, seuils["orange"], detail))

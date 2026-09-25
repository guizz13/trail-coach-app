"""
Métriques d'entraînement : charge, ACWR, distribution polarisée, seuils.

Ces calculs sont déterministes et faits AVANT l'appel LLM.
Le LLM reçoit les résultats et les interprète ; il ne les recalcule pas.

Références :
  - ACWR : Gabbett 2016 — zone optimale 0,8-1,3, danger > 1,5
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
def charge_seance(seance: dict) -> float:
    """
    Charge unitaire d'une séance, toutes disciplines confondues.

    Priorité à l'EPOC Suunto quand il existe (il intègre déjà intensité et durée).
    Fallback : TRIMP simplifié (durée × facteur d'intensité par zone).
    """
    epoc = seance.get("epoc")
    if epoc:
        return float(epoc)

    # Fallback TRIMP pondéré par zones (Edwards)
    poids = {"z1": 1, "z2": 2, "z3": 3, "z4": 4, "z5": 5}
    zones_s = seance.get("temps_zones_s") or {}
    if zones_s:
        return sum(zones_s.get(z, 0) / 60 * w for z, w in poids.items())

    # Dernier recours : durée seule
    return float(seance.get("duree_min", 0))


def charge_semaine(seances: Iterable[dict]) -> float:
    return sum(charge_seance(s) for s in seances)


# ---------------------------------------------------------------------------
# ACWR
# ---------------------------------------------------------------------------
@dataclass
class ACWR:
    charge_aigue: float          # semaine en cours (7 derniers jours)
    charge_chronique: float      # moyenne des 4 semaines précédentes
    ratio: Optional[float]
    zone: str                    # sous_charge | optimal | vigilance | danger

    @property
    def verdict(self) -> str:
        return {"sous_charge": "vert", "optimal": "vert", "vigilance": "orange", "danger": "rouge"}[self.zone]


def calculer_acwr(seances: list[dict], date_ref: Optional[date] = None) -> ACWR:
    """
    seances : liste de dicts avec au moins 'date_debut' (ISO) et les champs de charge.
    date_ref : fin de la fenêtre aiguë (défaut : aujourd'hui).
    """
    date_ref = date_ref or date.today()
    debut_aigue = date_ref - timedelta(days=6)
    debut_chronique = date_ref - timedelta(days=34)   # 4 semaines avant la fenêtre aiguë

    aigue, chronique = [], []
    for s in seances:
        d = _date_de(s)
        if d is None:
            continue
        if debut_aigue <= d <= date_ref:
            aigue.append(s)
        elif debut_chronique <= d < debut_aigue:
            chronique.append(s)

    ca = charge_semaine(aigue)
    cc = charge_semaine(chronique) / 4 if chronique else 0.0

    if cc == 0:
        return ACWR(ca, cc, None, "sous_charge" if ca == 0 else "optimal")

    ratio = round(ca / cc, 2)
    if ratio < 0.8:
        zone = "sous_charge"
    elif ratio <= 1.3:
        zone = "optimal"
    elif ratio <= 1.5:
        zone = "vigilance"
    else:
        zone = "danger"
    return ACWR(ca, cc, ratio, zone)


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


@dataclass
class Signal:
    nom: str
    niveau: str        # orange | rouge
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

    # EF : dérive Z3 et EPOC
    if type_prevu == "EF":
        _check(signaux, "epoc_sur_ef", epoc, SEUILS["epoc_ef"],
               f"EPOC {epoc:.0f} sur une séance prévue en endurance fondamentale")
        _check(signaux, "z3_sur_ef", z3, SEUILS["z3_sur_ef"],
               f"{z3:.0f} % du temps en Z3 sur une EF")

    # Sortie longue : intensité
    if type_prevu == "sortie_longue":
        _check(signaux, "z45_sur_longue", z45, SEUILS["z45_sur_longue"],
               f"{z45:.0f} % du temps en Z4-Z5 sur une sortie longue")

    # Écart de volume
    if prevu and prevu.get("distance_km") and realise.get("distance_km"):
        ecart = abs(realise["distance_km"] - prevu["distance_km"]) / prevu["distance_km"] * 100
        _check(signaux, "ecart_volume", ecart, SEUILS["ecart_volume"],
               f"écart de {ecart:.0f} % entre {realise['distance_km']} km réalisés et {prevu['distance_km']} km prévus")

    # ACWR
    if acwr and acwr.ratio is not None:
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

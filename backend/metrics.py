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


JOURS_INITIALISATION = 7


def serie_acwr(charges: list[tuple[date, float]]) -> list[dict]:
    """charges : jours consécutifs, sans trou. Les deux moyennes partent de la charge quotidienne
    moyenne des 7 premiers jours (et non de la charge du seul premier jour, qui faussait le départ)."""
    if not charges:
        return []
    premiers = [c for _, c in charges[:JOURS_INITIALISATION]]
    aigu = chronique = sum(premiers) / len(premiers)
    serie = []
    for jour, charge in charges:
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
# Évaluation d'UNE séance vs son prévu — découplée de l'ACWR (indicateur de tendance hebdomadaire)
# ---------------------------------------------------------------------------
SEUILS = {
    "ef_z3_et_plus": 25,        # % du temps ≥ Z3 sur une EF prévue (orange)
    "longue_z45": 30,           # % du temps en Z4-Z5 sur une sortie longue prévue (orange)
    "intervals_z45_min": 8,     # % minimal en Z4-Z5 sur des intervalles prévus (orange : qualité ratée)
    "ecart_pct": 25,            # écart de durée ou de distance vs prévu (orange) — course et vélo
    "duree_min_pct": 60,        # muscu / squash : écart seulement sous 60 % de la durée prévue
    "recovery_h": 48,           # RecoveryTime chevauchant une séance qualité (rouge)
    "douleur": 4,               # douleur déclarée /10 (rouge)
}
FAMILLES_COURSE = {"course_outdoor", "course_tapis"}
FAMILLES_DUREE_MINIMALE = {"muscu", "squash"}    # plus long que prévu : jamais un écart
ZONES_BAS_DU_CORPS = {"Achille G", "Achille D", "Fascia G", "Fascia D", "Mollet G", "Mollet D",
                      "Genou G", "Genou D", "Hanche"}


@dataclass
class Signal:
    nom: str
    niveau: str        # orange | rouge | info (informatif, sans effet sur le verdict)
    valeur: float
    seuil: float
    detail: str


def evaluer_seance(realise: dict, prevu: Optional[dict], sante: Optional[dict] = None,
                   prochaine_qualite_dans_h: Optional[float] = None) -> tuple[str, list[Signal]]:
    """
    realise : séance réalisée (ligne seances_realisees ; douleur et douleur_zone facultatives)
    prevu   : {'type': 'EF'|'intervals'|'sortie_longue'|..., 'distance_km': x, 'duree_min': y} ou None
    sante   : {'niveau': '100'|'vigilance'|'blessure', 'zones': [...]}
    prochaine_qualite_dans_h : heures avant la prochaine séance qualité planifiée

    Verdicts : vert (conforme), orange (écart), rouge (alerte, sécurité uniquement),
    hors_plan (aucun prévu lié : pas de seuil, seuls les signaux de sécurité s'appliquent).
    Les oranges ne deviennent jamais rouges, même cumulés.
    """
    signaux: list[Signal] = []
    sante = sante or {}
    pct = realise.get("temps_zones_pct") or {}
    z3_plus = pct.get("z3", 0) + pct.get("z4", 0) + pct.get("z5", 0)
    z45 = pct.get("z4", 0) + pct.get("z5", 0)
    type_prevu = (prevu or {}).get("type")
    course = realise.get("famille") in FAMILLES_COURSE      # zones : course uniquement, jamais squash/muscu/vélo

    # ---- Orange : écarts au prévu ----
    if prevu and course and pct:
        if type_prevu == "EF" and z3_plus > SEUILS["ef_z3_et_plus"]:
            signaux.append(Signal("ef_intensite", "orange", round(z3_plus, 1), SEUILS["ef_z3_et_plus"],
                                  f"{z3_plus:.0f} % du temps en Z3 ou au-dessus sur une EF"))
        if type_prevu == "sortie_longue" and z45 > SEUILS["longue_z45"]:
            signaux.append(Signal("longue_intensite", "orange", round(z45, 1), SEUILS["longue_z45"],
                                  f"{z45:.0f} % du temps en Z4-Z5 sur une sortie longue"))
        if type_prevu == "intervals" and z45 < SEUILS["intervals_z45_min"]:
            signaux.append(Signal("intervals_non_atteints", "orange", round(z45, 1), SEUILS["intervals_z45_min"],
                                  f"seulement {z45:.0f} % en Z4-Z5 : séance qualité non atteinte"))
    if prevu and realise.get("famille") in FAMILLES_DUREE_MINIMALE:
        p, r = prevu.get("duree_min"), realise.get("duree_min")
        if p and r and r < p * SEUILS["duree_min_pct"] / 100:
            signaux.append(Signal("ecart_duree", "orange", round(r / p * 100), SEUILS["duree_min_pct"],
                                  f"séance écourtée : {r:g} min réalisées pour {p:g} prévues"))
    elif prevu:
        for cle, unite, nom in (("duree_min", "min", "ecart_duree"), ("distance_km", "km", "ecart_distance")):
            p, r = prevu.get(cle), realise.get(cle)
            if p and r:
                ecart = abs(r - p) / p * 100
                if ecart > SEUILS["ecart_pct"]:
                    signaux.append(Signal(nom, "orange", round(ecart), SEUILS["ecart_pct"],
                                          f"écart de {ecart:.0f} % : {r:g} {unite} réalisés pour {p:g} prévus"))

    # ---- Rouge : sécurité uniquement ----
    zones_sante = set(sante.get("zones") or [])
    niveau = sante.get("niveau") or "100"
    douleur, zone_douleur = realise.get("douleur"), realise.get("douleur_zone")
    if douleur is not None and douleur >= SEUILS["douleur"]:
        signaux.append(Signal("douleur", "rouge", douleur, SEUILS["douleur"], f"douleur déclarée {douleur}/10"))
    elif douleur and niveau in ("vigilance", "blessure") and zone_douleur in zones_sante:
        signaux.append(Signal("douleur_zone", "rouge", douleur, 0,
                              f"douleur {douleur}/10 sur une zone en {niveau} ({zone_douleur})"))
    if course and niveau == "blessure" and zones_sante & ZONES_BAS_DU_CORPS:
        signaux.append(Signal("course_en_blessure", "rouge", 1, 0,
                              "course réalisée en statut Blessure sur le bas du corps (" + ", ".join(sorted(zones_sante & ZONES_BAS_DU_CORPS)) + ")"))
    rec_h = realise.get("recovery_time_h") or 0
    if rec_h > SEUILS["recovery_h"] and prochaine_qualite_dans_h is not None and prochaine_qualite_dans_h < rec_h:
        signaux.append(Signal("recovery", "rouge", rec_h, SEUILS["recovery_h"],
                              f"récupération {rec_h:.0f} h chevauchant la séance qualité dans {prochaine_qualite_dans_h:.0f} h"))

    if any(x.niveau == "rouge" for x in signaux):
        return "rouge", signaux
    if not prevu:
        return "hors_plan", signaux
    return ("orange" if any(x.niveau == "orange" for x in signaux) else "vert"), signaux

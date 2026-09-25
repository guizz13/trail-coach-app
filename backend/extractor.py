"""
Extracteur de fichiers Suunto JSON (export DeviceLog).

Validé sur les 5 types d'activité de l'athlète :
  - Type 3  : course/trail outdoor (GPS)
  - Type 93 : course tapis (pas de GPS, vitesse + cadence)
  - Type 37 : squash
  - Type 17 : vélo salle
  - Type 23 : musculation

Points clés du format :
  - Structure : {"DeviceLog": {"Header": {...}, "Samples": [...], "Windows", "Device"}}
  - FC stockée en Hz dans Samples[].HR  →  bpm = HR * 60
  - Header contient le résumé : Duration (s), Distance (m), Ascent/Descent (m),
    EPOC, RecoveryTime (s), PeakTrainingEffect, MAXVO2, Energy (J)
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Table de correspondance ActivityType → famille d'activité
# Complétée par l'utilisateur lors du premier import d'un type inconnu.
# ---------------------------------------------------------------------------
ACTIVITY_TYPE_MAP: dict[int, str] = {
    3: "course_outdoor",
    93: "course_tapis",
    37: "squash",
    17: "velo",
    23: "muscu",
}

FAMILLE_COURSE = {"course_outdoor", "course_tapis"}

# Zones FC de l'athlète (FC max 191). À charger depuis le profil en prod.
ZONES_BPM = {
    "z1": (0, 123),
    "z2": (124, 143),
    "z3": (144, 157),
    "z4": (158, 171),
    "z5": (172, 999),
}


@dataclass
class SeanceExtraite:
    """Structure normalisée d'une séance, quel que soit son type."""

    # Identité
    activity_type_code: int
    famille: str                      # course_outdoor | course_tapis | squash | velo | muscu | inconnu
    date_debut: str                   # ISO 8601
    duree_s: float
    duree_min: float

    # Volume (course uniquement, sinon 0/None)
    distance_m: float = 0.0
    distance_km: float = 0.0
    d_plus_m: Optional[float] = None
    d_moins_m: Optional[float] = None
    vitesse_moy_kmh: Optional[float] = None
    allure_moy_min_km: Optional[float] = None

    # Cardio
    fc_moy_bpm: Optional[int] = None
    fc_max_bpm: Optional[int] = None
    fc_min_bpm: Optional[int] = None
    temps_zones_s: dict = field(default_factory=dict)      # {"z1": 600, ...}
    temps_zones_pct: dict = field(default_factory=dict)    # {"z1": 25.0, ...}

    # Charge (Suunto)
    epoc: Optional[float] = None
    recovery_time_s: Optional[float] = None
    recovery_time_h: Optional[float] = None
    peak_training_effect: Optional[float] = None
    vo2max: Optional[float] = None
    energie_kcal: Optional[float] = None
    feeling: Optional[int] = None

    # Capteurs présents
    a_gps: bool = False
    a_cadence: bool = False
    a_puissance: bool = False
    a_fc: bool = False

    # Détection fine (course uniquement, rempli par classify_course)
    sous_type: Optional[str] = None   # EF | intervals | cotes | tempo | sortie_longue | None
    confiance: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def extraire(path_or_data) -> SeanceExtraite:
    """Point d'entrée : accepte un chemin de fichier ou un dict déjà chargé."""
    if isinstance(path_or_data, (str, bytes)):
        with open(path_or_data, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = path_or_data

    dl = data["DeviceLog"]
    h = dl.get("Header", {})
    samples = dl.get("Samples", [])

    code = int(h.get("ActivityType", -1))
    famille = ACTIVITY_TYPE_MAP.get(code, "inconnu")

    duree_s = float(h.get("Duration") or 0)
    distance_m = float(h.get("Distance") or 0)

    seance = SeanceExtraite(
        activity_type_code=code,
        famille=famille,
        date_debut=h.get("DateTime", ""),
        duree_s=duree_s,
        duree_min=round(duree_s / 60, 1),
        distance_m=distance_m,
        distance_km=round(distance_m / 1000, 2),
        d_plus_m=_round_or_none(h.get("Ascent")),
        d_moins_m=_round_or_none(h.get("Descent")),
        epoc=h.get("EPOC"),
        recovery_time_s=h.get("RecoveryTime"),
        recovery_time_h=round(h["RecoveryTime"] / 3600, 1) if h.get("RecoveryTime") else None,
        peak_training_effect=h.get("PeakTrainingEffect"),
        vo2max=h.get("MAXVO2"),
        energie_kcal=round(h["Energy"] / 4184, 0) if h.get("Energy") else None,
        feeling=h.get("Feeling"),
    )

    # Vitesse / allure
    if distance_m > 0 and duree_s > 0:
        kmh = (distance_m / 1000) / (duree_s / 3600)
        seance.vitesse_moy_kmh = round(kmh, 2)
        seance.allure_moy_min_km = round(60 / kmh, 2) if kmh > 0 else None

    # Capteurs
    seance.a_gps = any(s.get("Latitude") for s in samples)
    seance.a_cadence = any(s.get("Cadence") for s in samples)
    seance.a_puissance = any(s.get("Power") for s in samples)

    # Fréquence cardiaque (Hz → bpm)
    hr_bpm = [s["HR"] * 60 for s in samples if s.get("HR")]
    if hr_bpm:
        seance.a_fc = True
        seance.fc_moy_bpm = round(statistics.mean(hr_bpm))
        seance.fc_max_bpm = round(max(hr_bpm))
        seance.fc_min_bpm = round(min(hr_bpm))
        seance.temps_zones_s, seance.temps_zones_pct = _calculer_zones(samples)

    # Détection fine pour la famille course
    if famille in FAMILLE_COURSE:
        seance.sous_type, seance.confiance = classify_course(seance)

    return seance


def _round_or_none(v) -> Optional[float]:
    return round(float(v), 1) if v is not None else None


def _calculer_zones(samples: list[dict]) -> tuple[dict, dict]:
    """Temps passé dans chaque zone, en secondes et en pourcentage.
    Approximation : chaque sample avec HR compte pour l'écart de temps
    avec le sample précédent (fallback 1 s)."""
    temps = {z: 0.0 for z in ZONES_BPM}
    prev_t = None
    total = 0.0

    for s in samples:
        if not s.get("HR"):
            continue
        t = _parse_time(s.get("TimeISO8601"))
        dt = 1.0
        if prev_t is not None and t is not None:
            dt = max(0.0, min((t - prev_t).total_seconds(), 10.0))
        prev_t = t if t is not None else prev_t

        bpm = s["HR"] * 60
        for z, (lo, hi) in ZONES_BPM.items():
            if lo <= bpm <= hi:
                temps[z] += dt
                break
        total += dt

    pct = {z: round(100 * v / total, 1) if total else 0.0 for z, v in temps.items()}
    return {z: round(v) for z, v in temps.items()}, pct


def _parse_time(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Classification des séances de course (niveau 1 : signatures de données)
# Le niveau 2 (croisement avec le prévu) est fait côté app.
# Le niveau 3 (LLM) n'intervient que si confiance < 0.6.
# ---------------------------------------------------------------------------
def classify_course(s: SeanceExtraite) -> tuple[str, float]:
    """Retourne (sous_type, confiance 0-1) à partir des signatures."""
    pct = s.temps_zones_pct or {}
    z12 = pct.get("z1", 0) + pct.get("z2", 0)
    z3 = pct.get("z3", 0)
    z45 = pct.get("z4", 0) + pct.get("z5", 0)
    dplus_par_km = (s.d_plus_m or 0) / s.distance_km if s.distance_km else 0

    # Sortie longue : durée > 75 min et/ou distance > 15 km
    if s.duree_min > 75 or s.distance_km > 15:
        return "sortie_longue", 0.9

    # Côtes : ratio D+ élevé sur courte distance + alternance forte
    if dplus_par_km > 30 and s.distance_km < 15:
        return "cotes", 0.8

    # Intervals / tempo : forte part en Z4-Z5
    if z45 >= 35:
        # Intervals : durée courte, Z5 présent
        if pct.get("z5", 0) > 5 and s.duree_min < 70:
            return "intervals", 0.75
        return "tempo", 0.7

    # EF : majorité Z1-Z2
    if z12 >= 50:
        return "EF", 0.85

    # Zone grise : probablement une EF dérivée en Z3 (tendance connue)
    if z3 >= 40:
        return "EF", 0.6   # confiance basse → signaler la dérive

    return "inconnu", 0.3


# ---------------------------------------------------------------------------
# Test rapide en ligne de commande
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        s = extraire(p)
        print(f"\n=== {p}")
        print(json.dumps(s.to_dict(), indent=2, ensure_ascii=False))

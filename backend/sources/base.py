"""Format commun à toutes les sources d'activités."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from extractor import ZONES_BPM

# Richesse des sources : en cas de doublon entre sources, la plus riche fournit les mesures
RICHESSE_SOURCE = {"suunto_json": 3, "strava": 2, "manuel": 1}


@dataclass
class ActiviteNormalisee:
    source: str                          # suunto_json | strava | manuel
    source_id: str                       # hash du fichier, id Strava, uuid
    source_code: Optional[str]           # code brut reçu ('82', 'TrailRun')
    sport_id: str                        # sport du catalogue (backend/sports.py)
    debut: str                           # ISO 8601 avec fuseau
    duree_s: float
    distance_m: float = 0.0
    d_plus_m: Optional[float] = None
    fc_moy: Optional[int] = None
    fc_max: Optional[int] = None
    zones_minutes: dict = field(default_factory=dict)       # {"z1": 12.5, …}
    echantillons_fc: Optional[list] = None                  # [(t_s, bpm), …] facultatif
    gps_present: bool = False

    # Compléments
    sport_connu: bool = True             # False : code inconnu, « autre » en attendant le choix
    zones_pct: Optional[dict] = None     # fourni par la source, sinon déduit de zones_minutes
    sous_type: Optional[str] = None      # course : EF | intervals | cotes | tempo | sortie_longue
    sous_type_confiance: Optional[float] = None
    rpe: Optional[int] = None
    note: Optional[str] = None
    nom: Optional[str] = None            # nom du fichier ou titre de l'activité
    empreinte: Optional[str] = None      # SHA-256 du fichier (anti-doublon strict)
    details: dict = field(default_factory=dict)   # mesures propres à la source (EPOC, récupération…)
    brut: Optional[dict] = None          # données brutes conservées (donnees_brutes)

    @property
    def duree_min(self) -> float:
        return round(self.duree_s / 60, 1)

    @property
    def distance_km(self) -> float:
        return round((self.distance_m or 0) / 1000, 2)


def zones_depuis_echantillons(echantillons: list) -> dict:
    """Minutes par zone (extractor.ZONES_BPM) depuis [(t_s, bpm)] : chaque échantillon compte pour
    l'écart avec le précédent, plafonné à 10 s (1 s pour le premier) — même règle que l'extracteur."""
    secondes = {z: 0.0 for z in ZONES_BPM}
    precedent = None
    for t, bpm in echantillons:
        if not bpm:
            continue
        dt = 1.0 if precedent is None else max(0.0, min(t - precedent, 10.0))
        precedent = t
        zone = next((z for z, (_, haut) in ZONES_BPM.items() if bpm <= haut), "z5")
        secondes[zone] += dt
    return {z: s / 60 for z, s in secondes.items()}

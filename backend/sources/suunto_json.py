"""Fichier JSON Suunto (export DeviceLog) → ActiviteNormalisee. Le parsing reste dans extractor.py."""

from __future__ import annotations

import hashlib
from typing import Optional

import extractor
from sources.base import ActiviteNormalisee

SOURCE = "suunto_json"
DETAILS = ("d_moins_m", "vitesse_moy_kmh", "epoc", "recovery_time_h", "peak_training_effect", "vo2max",
           "energie_kcal", "feeling", "a_fc", "fc_min_bpm")


def empreinte(fichier_bytes: bytes) -> str:
    return hashlib.sha256(fichier_bytes).hexdigest()


def normaliser(data: dict, correspondances: dict[str, str], empreinte_fichier: str, nom: Optional[str] = None,
               sport_id: Optional[str] = None) -> ActiviteNormalisee:
    """correspondances : activity_types de la source suunto_json ; sport_id : choix de l'utilisateur."""
    s = extractor.extraire(data, correspondances)
    if sport_id and sport_id != s.sport_id:
        extractor.appliquer_sport(s, sport_id)
        s.code_connu = True
    brut = s.to_dict()
    brut.pop("sport_id"), brut.pop("code_connu")
    return ActiviteNormalisee(
        source=SOURCE, source_id=empreinte_fichier, source_code=str(s.activity_type_code),
        sport_id=s.sport_id, sport_connu=s.code_connu,
        debut=s.date_debut, duree_s=s.duree_s, distance_m=s.distance_m, d_plus_m=s.d_plus_m,
        fc_moy=s.fc_moy_bpm, fc_max=s.fc_max_bpm,
        zones_minutes={z: v / 60 for z, v in (s.temps_zones_s or {}).items()},
        zones_pct=s.temps_zones_pct or None, gps_present=s.a_gps,
        sous_type=s.sous_type, sous_type_confiance=s.confiance,
        nom=nom, empreinte=empreinte_fichier,
        details={k: getattr(s, k) for k in DETAILS}, brut=brut,
    )


def seance_extraite(a: ActiviteNormalisee) -> extractor.SeanceExtraite:
    """SeanceExtraite reconstituée depuis les données brutes (proposition de sport, classification)."""
    champs = extractor.SeanceExtraite.__dataclass_fields__
    return extractor.SeanceExtraite(**{k: v for k, v in (a.brut or {}).items() if k in champs})

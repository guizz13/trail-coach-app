"""Activité Strava (API v3, JSON de /activities/{id} et streams key_by_type) → ActiviteNormalisee.

Préparation seulement : pas d'OAuth ni de client HTTP. Le sport vient d'abord des correspondances
apprises (activity_types, source 'strava' : choix explicites de l'utilisateur), puis du champ
`strava` du catalogue, sinon « autre » à préciser."""

from __future__ import annotations

from typing import Optional

import sports
from sources.base import ActiviteNormalisee, zones_depuis_echantillons

SOURCE = "strava"


def normaliser(activite_json: dict, streams: Optional[dict] = None,
               correspondances: Optional[dict[str, str]] = None) -> ActiviteNormalisee:
    code = activite_json.get("sport_type") or activite_json.get("type") or ""
    sport_id = (correspondances or {}).get(code) or sports.par_strava(code)
    echantillons = None
    zones = {}
    if streams and (streams.get("heartrate") or {}).get("data"):
        fc = streams["heartrate"]["data"]
        temps = (streams.get("time") or {}).get("data") or list(range(len(fc)))
        echantillons = list(zip(temps, fc))
        zones = zones_depuis_echantillons(echantillons)
    fc_moy = activite_json.get("average_heartrate")
    fc_max = activite_json.get("max_heartrate")
    return ActiviteNormalisee(
        source=SOURCE, source_id=str(activite_json["id"]), source_code=code or None,
        sport_id=sport_id or sports.AUTRE, sport_connu=sport_id is not None,
        debut=activite_json["start_date"], duree_s=float(activite_json.get("moving_time") or 0),
        distance_m=float(activite_json.get("distance") or 0),
        d_plus_m=activite_json.get("total_elevation_gain"),
        fc_moy=round(fc_moy) if fc_moy else None, fc_max=round(fc_max) if fc_max else None,
        zones_minutes=zones, echantillons_fc=echantillons,
        gps_present=bool(activite_json.get("start_latlng") or (activite_json.get("map") or {}).get("summary_polyline")),
        nom=activite_json.get("name"),
        details={"a_fc": bool(activite_json.get("has_heartrate") or fc_moy)},
        brut={"activite": activite_json},
    )

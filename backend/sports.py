"""
Catalogue des sports : source unique de vérité (sport, catégorie, impact, règles d'analyse).

La catégorie pilote la couleur, l'icône par défaut, la famille de liaison réalisé ↔ prévu et les
règles d'analyse. L'impact (faible / modere / eleve) mesure la charge mécanique sur le bas du corps
et les tendons ; il sert aux règles de vigilance santé.

Le catalogue est figé dans le code : l'utilisateur choisit dans la liste, « autre » couvre le reste.
"""

from __future__ import annotations

import unicodedata
from typing import Optional

CATEGORIES = {
    "course":    {"libelle": "Course",             "couleur": "--course",     "icone": "ti-run"},
    "raquette":  {"libelle": "Sports de raquette", "couleur": "--squash",     "icone": "ti-ball-tennis"},
    "force":     {"libelle": "Renforcement",       "couleur": "--muscu",      "icone": "ti-barbell"},
    "porte":     {"libelle": "Endurance portée",   "couleur": "--velo",       "icone": "ti-bike"},
    "montagne":  {"libelle": "Montagne",           "couleur": "--orange",     "icone": "ti-mountain"},
    "collectif": {"libelle": "Sports collectifs",  "couleur": "--orange",     "icone": "ti-ball-football"},
    "mobilite":  {"libelle": "Mobilité",           "couleur": "--text-muted", "icone": "ti-stretching"},
    "autre":     {"libelle": "Autre",              "couleur": "--text-muted", "icone": "ti-activity"},
}

SPORTS = [
    # id, libelle, categorie, impact, zones_course, distance, strava, icone (None = icône de la catégorie)
    ("course_route",     "Course sur route",     "course",   "eleve",  True,  True,  ["Run"], None),
    ("trail",            "Trail",                "course",   "eleve",  True,  True,  ["TrailRun"], "ti-mountain"),
    ("course_tapis",     "Course sur tapis",     "course",   "eleve",  True,  True,  ["VirtualRun"], None),
    ("course_piste",     "Piste",                "course",   "eleve",  True,  True,  [], None),
    ("course_verticale", "Kilomètre vertical",   "course",   "eleve",  True,  True,  [], "ti-trending-up"),

    ("squash",           "Squash",               "raquette", "eleve",  False, False, ["Squash"], None),
    ("badminton",        "Badminton",            "raquette", "eleve",  False, False, ["Badminton"], None),
    ("tennis",           "Tennis",               "raquette", "eleve",  False, False, ["Tennis"], None),
    ("padel",            "Padel",                "raquette", "eleve",  False, False, ["Padel"], None),
    ("tennis_table",     "Tennis de table",      "raquette", "modere", False, False, ["TableTennis"], "ti-ping-pong"),
    ("pickleball",       "Pickleball",           "raquette", "eleve",  False, False, ["Pickleball"], None),

    ("muscu",            "Musculation",          "force",    "faible", False, False, ["WeightTraining"], None),
    ("crossfit",         "CrossFit / HIIT",      "force",    "eleve",  False, False, ["Crossfit", "HighIntensityIntervalTraining"], None),
    ("calisthenics",     "Poids du corps",       "force",    "modere", False, False, ["Workout"], None),
    ("circuit",          "Circuit training",     "force",    "modere", False, False, ["Workout"], None),
    ("escalade",         "Escalade",             "force",    "faible", False, False, ["RockClimbing"], "ti-trekking"),

    ("velo_route",       "Vélo route",           "porte",    "faible", False, True,  ["Ride"], None),
    ("velo_salle",       "Vélo en salle",        "porte",    "faible", False, False, ["VirtualRide"], None),
    ("vtt",              "VTT",                  "porte",    "modere", False, True,  ["MountainBikeRide", "EMountainBikeRide"], None),
    ("gravel",           "Gravel",               "porte",    "faible", False, True,  ["GravelRide"], None),
    ("natation",         "Natation",             "porte",    "faible", False, True,  ["Swim"], "ti-swimming"),
    ("rameur",           "Rameur",               "porte",    "faible", False, True,  ["Rowing", "VirtualRow"], None),
    ("elliptique",       "Elliptique",           "porte",    "faible", False, False, ["Elliptical"], None),
    ("ski_fond",         "Ski de fond",          "porte",    "modere", False, True,  ["NordicSki"], None),
    ("stepper",          "Stepper / escaliers",  "porte",    "modere", False, False, ["StairStepper"], "ti-stairs-up"),

    ("randonnee",        "Randonnée",            "montagne", "modere", False, True,  ["Hike", "Walk"], "ti-trekking"),
    ("ski_rando",        "Ski de randonnée",     "montagne", "modere", False, True,  ["BackcountrySki"], None),
    ("ski_alpin",        "Ski alpin",            "montagne", "modere", False, False, ["AlpineSki"], None),
    ("raquettes_neige",  "Raquettes à neige",    "montagne", "modere", False, True,  ["Snowshoe"], None),
    ("alpinisme",        "Alpinisme",            "montagne", "modere", False, True,  [], None),

    ("football",         "Football",             "collectif", "eleve", False, False, ["Soccer"], None),
    ("basket",           "Basket",               "collectif", "eleve", False, False, [], None),
    ("handball",         "Handball",             "collectif", "eleve", False, False, [], None),
    ("volley",           "Volley",               "collectif", "eleve", False, False, [], None),
    ("rugby",            "Rugby",                "collectif", "eleve", False, False, [], None),

    ("yoga",             "Yoga",                 "mobilite", "faible", False, False, ["Yoga"], None),
    ("pilates",          "Pilates",              "mobilite", "faible", False, False, ["Pilates"], None),
    ("etirements",       "Étirements / mobilité", "mobilite", "faible", False, False, [], None),

    ("marche",           "Marche",               "autre",    "faible", False, True,  ["Walk"], "ti-walk"),
    ("sport_combat",     "Sport de combat",      "autre",    "eleve",  False, False, [], None),
    ("autre",            "Autre sport",          "autre",    "modere", False, False, ["Workout"], None),
]

SPORTS_PAR_ID: dict[str, dict] = {
    s[0]: {"id": s[0], "libelle": s[1], "categorie": s[2], "impact": s[3], "zones_course": s[4],
           "distance": s[5], "strava": s[6], "icone": s[7] or CATEGORIES[s[2]]["icone"]}
    for s in SPORTS
}
AUTRE = "autre"


def sport(sport_id: Optional[str]) -> dict:
    """Fiche du sport ; un identifiant inconnu donne « Autre sport »."""
    return SPORTS_PAR_ID.get(sport_id or "", SPORTS_PAR_ID[AUTRE])


def categorie(sport_id: Optional[str]) -> str:
    return sport(sport_id)["categorie"]


def impact(sport_id: Optional[str]) -> str:
    return sport(sport_id)["impact"]


def par_strava(sport_type: Optional[str]) -> Optional[str]:
    """Premier sport du catalogue qui déclare ce sport_type Strava (Walk → randonnée, Workout → poids du corps)."""
    return next((s[0] for s in SPORTS if sport_type in s[6]), None)


def sans_accents(texte: str) -> str:
    """Minuscules sans accents, pour comparer des libellés saisis librement."""
    return "".join(c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn").lower()


def ids_de_categorie(cat: str) -> set[str]:
    return {sid for sid, s in SPORTS_PAR_ID.items() if s["categorie"] == cat}


# ---------------------------------------------------------------------------
# Compatibilité avec l'ancien champ « famille » (avant v5)
# ---------------------------------------------------------------------------
SPORT_DEPUIS_FAMILLE = {"course_outdoor": "course_route", "course_tapis": "course_tapis", "squash": "squash",
                        "velo": "velo_salle", "muscu": "muscu", "autre": AUTRE, "inconnu": AUTRE}


def sport_de(seance: dict) -> str:
    """Sport d'une séance : sport_id s'il existe, sinon déduit de l'ancienne famille."""
    return seance.get("sport_id") or SPORT_DEPUIS_FAMILLE.get(seance.get("famille") or "", AUTRE)


def famille_heritee(sport_id: str) -> str:
    """Valeur écrite dans l'ancienne colonne famille (NOT NULL), conservée pour compatibilité."""
    cat = categorie(sport_id)
    if cat == "course":
        return "course_tapis" if sport_id == "course_tapis" else "course_outdoor"
    return {"raquette": "squash", "force": "muscu", "porte": "velo"}.get(cat, "autre")


def catalogue_api() -> dict:
    return {"categories": CATEGORIES, "sports": list(SPORTS_PAR_ID.values())}

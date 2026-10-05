"""
Orchestration : import de séance, bilan hebdomadaire, reconstruction des événements.

Les calculs sont faits par `metrics`, l'extraction par `extractor`, le
raisonnement par `llm_client`. Ce module ne fait qu'assembler et persister.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import db
import extractor
import metrics
import sports
import taches
from sources import strava, suunto_json
from sources.base import RICHESSE_SOURCE, ActiviteNormalisee

TZ = ZoneInfo("Europe/Paris")

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
ROTATION_MUSCU = ["push_a", "pull_a", "push_b", "pull_b"]
SPLITS_MUSCU = ROTATION_MUSCU + ["jambes", "autre"]
GROUPES_MUSCU = ["pectoraux", "triceps", "epaules", "dos", "biceps",
                 "cuisses", "ischios", "mollets", "abdos"]
FAMILLES = ["course_outdoor", "course_tapis", "squash", "velo", "muscu", "autre"]
SOUS_TYPES_COURSE = ["EF", "intervals", "cotes", "tempo", "sortie_longue"]
TYPES_QUALITE = {"intervals", "tempo", "cotes", "sortie_longue"}
HEURE_CRENEAU = {"matin": 7, "midi": 12, "journee": 9, "soir": 19}
SEUIL_CONFIANCE = 0.6


class ErreurImport(Exception):
    pass


# ---------------------------------------------------------------------------
# Dates (Europe/Paris)
# ---------------------------------------------------------------------------
def maintenant() -> datetime:
    return datetime.now(TZ)


def aujourdhui() -> date:
    return maintenant().date()


def lundi_de(d: date) -> date:
    return d - timedelta(days=d.weekday())


def en_paris(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def date_de(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def jour_de(d: date) -> str:
    return JOURS[d.weekday()]


# Créneaux, du plus tôt au plus tard ; « journee » (week-end) est rangé comme un après-midi
RANG_CRENEAU = {"matin": 0, "midi": 1, "journee": 2, "soir": 3}


def rang_creneau_realise(dt: datetime) -> int:
    """Avant 11 h : matin ; 11-14 h : midi ; 14-17 h : après-midi ; après 17 h : soir."""
    if dt.hour < 11:
        return 0
    if dt.hour < 14:
        return 1
    if dt.hour < 17:
        return 2
    return 3


# ---------------------------------------------------------------------------
# Familles de discipline (liaison réalisé ↔ prévu)
# ---------------------------------------------------------------------------
FAMILLES_PLAN = {
    "course": {"EF", "intervals", "cotes", "tempo", "sortie_longue", "course"},
    "muscu": {"muscu", "muscu_push", "muscu_pull", "muscu_jambes", "muscu_full"},
    "squash": {"squash"},
    "velo": {"velo", "velo_ef", "velo_intervals"},
}
# Types écrits librement (« Pull A », « Sortie longue ») : reconnus par mot-clé.
# Un type inconnu n'appartient à aucune famille et n'est jamais lié (avant : rangé en course par défaut).
_MOTS_FAMILLE = [
    ("muscu", "muscu"), ("push", "muscu"), ("pull", "muscu"), ("jambes", "muscu"), ("full", "muscu"),
    ("squash", "squash"), ("vélo", "velo"), ("velo", "velo"),
    ("sortie longue", "course"), ("sortie_longue", "course"), ("endurance", "course"), ("interval", "course"),
    ("fractionn", "course"), ("côte", "course"), ("cotes", "course"), ("tempo", "course"),
    ("footing", "course"), ("trail", "course"), ("course", "course"),
]


def famille_planifiee(type_: Optional[str]) -> Optional[str]:
    for f, types in FAMILLES_PLAN.items():
        if type_ in types:
            return f
    t = (type_ or "").lower()
    if not t or "repos" in t:
        return None
    return next((f for mot, f in _MOTS_FAMILLE if mot in t), None)


# Catégories du catalogue (v5) : la liaison réalisé ↔ prévu se fait par catégorie.
CATEGORIE_DEPUIS_FAMILLE = {"course": "course", "muscu": "force", "squash": "raquette", "velo": "porte"}
# Sport représentatif d'un type de séance prévue générique (impact, libellé) ; un type qui est
# déjà un sport du catalogue (« badminton ») est pris tel quel.
SPORT_TYPE_GENERIQUE = {"course": "course_route", "force": "muscu", "raquette": "squash", "porte": "velo_salle"}
# Sports attendus par un type prévu précis : un autre sport de la catégorie est une substitution
SPORTS_ATTENDUS = {"squash": {"squash"}, "velo": {"velo_route", "velo_salle", "vtt", "gravel"}}


def _sport_du_type(type_: Optional[str]) -> Optional[str]:
    """« badminton », « Badminton », « Vélo route » → id du catalogue ; sinon None."""
    if type_ in sports.SPORTS_PAR_ID:
        return type_
    t = sports.sans_accents((type_ or "").strip())
    return next((s["id"] for s in sports.SPORTS_PAR_ID.values() if sports.sans_accents(s["libelle"]) == t), None)


def categorie_planifiee(type_: Optional[str]) -> Optional[str]:
    """Catégorie d'une séance prévue : sport du catalogue, sinon types connus et mots-clés."""
    if "repos" in (type_ or "").lower():
        return None
    sid = _sport_du_type(type_)
    if sid:
        return sports.categorie(sid)
    return CATEGORIE_DEPUIS_FAMILLE.get(famille_planifiee(type_) or "")


def categorie_realisee(seance: dict) -> Optional[str]:
    """Catégorie d'une séance réalisée ; aucune tant que le sport reste à préciser (jamais liée)."""
    if seance.get("sport_a_preciser"):
        return None
    return sports.categorie(sports.sport_de(seance))


def sport_planifie(type_: Optional[str]) -> Optional[str]:
    """Sport d'une séance prévue : celui du catalogue, sinon le sport représentatif de sa catégorie."""
    return _sport_du_type(type_) or SPORT_TYPE_GENERIQUE.get(categorie_planifiee(type_) or "")


def impact_planifie(type_: Optional[str]) -> Optional[str]:
    sid = sport_planifie(type_)
    return sports.impact(sid) if sid else None


def substitution(seance: dict, prevu: Optional[dict]) -> Optional[str]:
    """« Substitution : badminton au lieu de squash » quand le sport diffère dans la catégorie."""
    if not prevu:
        return None
    sid = sports.sport_de(seance)
    attendus = SPORTS_ATTENDUS.get(prevu["type"]) or ({_sport_du_type(prevu["type"])} - {None})
    if not attendus or sid in attendus:
        return None
    libelle_prevu = sports.sport(next(iter(attendus)))["libelle"] if len(attendus) == 1 else prevu["type"]
    return f"Substitution : {sports.sport(sid)['libelle'].lower()} au lieu de {libelle_prevu.lower()}"


def split_suivant(dernier: Optional[str]) -> str:
    if dernier in ROTATION_MUSCU:
        return ROTATION_MUSCU[(ROTATION_MUSCU.index(dernier) + 1) % len(ROTATION_MUSCU)]
    return ROTATION_MUSCU[0]


def split_propose() -> str:
    return split_suivant(db.derniere_muscu_split())


# ---------------------------------------------------------------------------
# Import : extraction
# ---------------------------------------------------------------------------
def hash_fichier(fichier_bytes: bytes) -> str:
    return suunto_json.empreinte(fichier_bytes)


def _activite_suunto(fichier_bytes: bytes, nom: Optional[str] = None, sport_id: Optional[str] = None,
                     sous_type: Optional[str] = None) -> tuple[ActiviteNormalisee, bool]:
    """Fichier Suunto → ActiviteNormalisee, corrections utilisateur comprises.
    Retourne (activité, sous_type_confirme)."""
    try:
        data = json.loads(fichier_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ErreurImport(f"Fichier JSON invalide : {e}") from e
    if not isinstance(data, dict) or "DeviceLog" not in data:
        raise ErreurImport("Format inattendu : clé 'DeviceLog' absente (export Suunto attendu).")
    if sport_id and sport_id not in sports.SPORTS_PAR_ID:
        raise ErreurImport(f"Sport inconnu : {sport_id}")
    try:
        a = suunto_json.normaliser(data, db.activity_types(suunto_json.SOURCE), hash_fichier(fichier_bytes),
                                   nom, sport_id)
    except (KeyError, TypeError, ValueError) as e:
        raise ErreurImport(f"Extraction impossible : {e}") from e
    if not a.debut:
        raise ErreurImport("Date de début absente du fichier.")

    confirme = False
    if sous_type and sports.categorie(a.sport_id) == "course":
        if sous_type not in SOUS_TYPES_COURSE:
            raise ErreurImport(f"Sous-type inconnu : {sous_type}")
        confirme = True
        a.sous_type = sous_type
    return a, confirme


def apercu_import(fichier_bytes: bytes, nom: str) -> dict:
    """Extraction sans écriture, pour la carte résumé et les questions à poser."""
    h = hash_fichier(fichier_bytes)
    existant = db.seance_par_hash(h)
    if existant:
        return {"nom": nom, "hash": h, "doublon": True, "seance_id": existant["id"],
                "message": f"Déjà importé le {existant['importe_le'][:10]} (séance #{existant['id']})."}

    a, _ = _activite_suunto(fichier_bytes, nom)
    d = {**a.brut, "sport_id": a.sport_id, "sous_type": a.sous_type}
    jumelle = doublon_entre_sources(a)
    return {
        "nom": nom,
        "hash": h,
        "doublon": False,
        "seance": d,
        "charge": round(metrics.charge_seance(d), 1),
        "sport_a_preciser": not a.sport_connu,
        "proposition": extractor.deviner_sport(suunto_json.seance_extraite(a)) if not a.sport_connu else None,
        "fusion_avec": {"id": jumelle["id"], "source": jumelle["source"]} if jumelle else None,
        "demander_sous_type": sports.categorie(a.sport_id) == "course" and (a.sous_type_confiance or 0) < SEUIL_CONFIANCE,
        "split_propose": split_propose() if a.sport_id == "muscu" else None,
        "sous_types": SOUS_TYPES_COURSE,
        "groupes_muscu": GROUPES_MUSCU,
        "splits_muscu": SPLITS_MUSCU,
    }


def _ligne_seance(a: ActiviteNormalisee, confirme: bool = False) -> dict:
    """Ligne seances_realisees depuis une activité normalisée (toutes sources)."""
    zones_s = {z: round(m * 60, 3) for z, m in (a.zones_minutes or {}).items()}
    total = sum(zones_s.values())
    pct = a.zones_pct or ({z: round(100 * v / total, 1) for z, v in zones_s.items()} if total else {})
    det = a.details or {}
    vitesse = det.get("vitesse_moy_kmh")
    if vitesse is None and a.distance_m and a.duree_s:
        vitesse = round(a.distance_km / (a.duree_s / 3600), 2)
    ligne = {
        "fichier_hash": a.empreinte or f"{a.source}:{a.source_id}",
        "fichier_nom": a.nom,
        "activity_type_code": int(a.source_code) if (a.source_code or "").isdigit() else 0,
        "famille": sports.famille_heritee(a.sport_id),
        "sport_id": a.sport_id,
        "sport_a_preciser": int(not a.sport_connu),
        "source": a.source,
        "source_id": a.source_id,
        "source_code": a.source_code,
        "sous_type": a.sous_type,
        "sous_type_confiance": a.sous_type_confiance,
        "sous_type_confirme": int(confirme),
        "date_debut": en_paris(a.debut).isoformat(timespec="seconds"),
        "duree_min": a.duree_min,
        "distance_km": a.distance_km,
        "dplus_m": a.d_plus_m,
        "dmoins_m": det.get("d_moins_m"),
        "vitesse_moy_kmh": vitesse,
        "fc_moy": a.fc_moy,
        "fc_max": a.fc_max,
        "temps_zones_s": zones_s,
        "temps_zones_pct": pct,
        "epoc": det.get("epoc"),
        "recovery_time_h": det.get("recovery_time_h"),
        "peak_training_effect": det.get("peak_training_effect"),
        "vo2max": det.get("vo2max"),
        "energie_kcal": det.get("energie_kcal"),
        "feeling": det.get("feeling"),
        "a_gps": int(a.gps_present),
        "a_fc": int(bool(det.get("a_fc"))),
        "rpe": a.rpe,
        "note": a.note,
        "donnees_brutes": a.brut,
        "importe_le": maintenant().isoformat(timespec="seconds"),
    }
    ligne["charge"] = round(metrics.charge_seance(ligne), 1)
    return ligne


def _valider_muscu(detail: dict) -> dict:
    split = detail.get("split") or None
    if split and split not in SPLITS_MUSCU:
        raise ErreurImport(f"Split inconnu : {split}")
    groupes = [g for g in (detail.get("groupes") or []) if g in GROUPES_MUSCU]
    charges = []
    for c in detail.get("charges") or []:
        exo = (c.get("exo") or "").strip()
        if not exo:
            continue
        charges.append({"exo": exo, "kg": _nombre(c.get("kg")),
                        "reps": _nombre(c.get("reps")), "series": _nombre(c.get("series"))})
    return {"split": split, "groupes": groupes, "charges": charges,
            "notes": (detail.get("notes") or "").strip() or None}


def _nombre(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        f = float(str(v).replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


# ---------------------------------------------------------------------------
# Import : contexte (prévu, ACWR, prochaine qualité)
# ---------------------------------------------------------------------------
DECALAGE_MAX_JOURS = 2


def relier(du: date, au: date) -> None:
    """Liaison automatique sur une semaine [du, au] : libère les liens automatiques, puis
    1. relie chaque séance réalisée à une séance prévue du même jour et de la même catégorie ;
    2. pour celles restées sans prévu : séance décalée, même catégorie, même semaine, à 2 jours au
       plus, d'abord une séance prévue passée (report, la plus proche), puis future (avance).
    Les séances prévues remplacées sont ignorées. Une séance avec lien_manuel=1 n'est jamais touchée."""
    with db.connexion() as c:
        c.execute(
            "UPDATE seances_planifiees SET seance_realisee_id = NULL WHERE date_seance BETWEEN ? AND ? "
            "AND seance_realisee_id IN (SELECT id FROM seances_realisees WHERE lien_manuel = 0)",
            (du.isoformat(), au.isoformat()))
        c.execute("UPDATE seances_realisees SET decalage_jours = 0 WHERE lien_manuel = 0 "
                  "AND substr(date_debut, 1, 10) BETWEEN ? AND ?", (du.isoformat(), au.isoformat()))
    remplacees = db.planifiees_remplacees()
    plan = [p for p in db.planifiees_entre(du.isoformat(), au.isoformat()) if p["id"] not in remplacees]
    libres = lambda cat: [p for p in plan if p["seance_realisee_id"] is None and cat
                          and categorie_planifiee(p["type"]) == cat]
    sans_prevu = []
    for s in db.seances_entre(du.isoformat(), au.isoformat()):
        if s["lien_manuel"]:
            continue
        debut = en_paris(s["date_debut"])
        candidats = [p for p in libres(categorie_realisee(s)) if p["date_seance"] == debut.date().isoformat()]
        if not candidats:
            sans_prevu.append(s)
            continue
        rang = rang_creneau_realise(debut)
        choisi = min(candidats, key=lambda p: (abs(RANG_CRENEAU.get(p["creneau"], 2) - rang),
                                                RANG_CRENEAU.get(p["creneau"], 2)))
        choisi["seance_realisee_id"] = s["id"]
        db.maj("seances_planifiees", choisi["id"], {"seance_realisee_id": s["id"]})
    for s in sans_prevu:
        jour = date_de(s["date_debut"])
        ecart = lambda p: (jour - date.fromisoformat(p["date_seance"])).days
        candidats = [p for p in libres(categorie_realisee(s)) if 0 < abs(ecart(p)) <= DECALAGE_MAX_JOURS]
        if not candidats:
            continue          # hors plan
        choisi = min(candidats, key=lambda p: (ecart(p) < 0, abs(ecart(p))))    # report avant avance
        choisi["seance_realisee_id"] = s["id"]
        db.maj("seances_planifiees", choisi["id"], {"seance_realisee_id": s["id"]})
        db.maj("seances_realisees", s["id"], {"decalage_jours": ecart(choisi)})


def mettre_a_jour_statuts(du: date, au: date) -> None:
    """realise si une séance y est liée le même jour, decale si elle est liée à une séance d'un autre
    jour, remplacee si une séance d'un autre sport la remplace ; manque si la date est passée
    (aujourd'hui ne l'est jamais) ; sinon prévu (ou modifié si elle l'était). Un repos n'est jamais manqué."""
    jour = aujourdhui().isoformat()
    remplacees = db.planifiees_remplacees()
    for p in db.planifiees_entre(du.isoformat(), au.isoformat()):
        if p["seance_realisee_id"]:
            r = db.seance(p["seance_realisee_id"])
            statut = "decale" if r and r["date_debut"][:10] != p["date_seance"] else "realise"
        elif p["id"] in remplacees:
            statut = "remplacee"
        elif p["type"] != "repos" and p["date_seance"] < jour:
            statut = "manque"
        else:
            statut = "modifie" if p["statut"] == "modifie" else "prevu"
        if statut != p["statut"]:
            db.maj("seances_planifiees", p["id"], {"statut": statut})


def prevu_de(seance_id: int) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM seances_planifiees WHERE seance_realisee_id = ?", (seance_id,))


TYPES_COURSE_CONNUS = {"EF", "intervals", "cotes", "tempo", "sortie_longue"}


def type_plan_normalise(type_: Optional[str]) -> Optional[str]:
    """« Sortie longue », « Fractionné »… ramenés au code de séance utilisé par les seuils."""
    if type_ in TYPES_COURSE_CONNUS:
        return type_
    return type_depuis_texte(type_ or "") or type_


def sante_profil(p: Optional[dict] = None) -> dict:
    """Statut santé structuré {niveau, zones, note, protocole} ; lit l'ancien format texte
    (« vigilance:achille gauche ») tant que les colonnes structurées n'existent pas."""
    p = p if p is not None else db.profil()
    if "sante_niveau" in p:
        zones = p.get("sante_zones") or []
        return {"niveau": p.get("sante_niveau") or "100", "zones": zones if isinstance(zones, list) else [],
                "note": p.get("sante_note"), "protocole": p.get("sante_protocole")}
    brut = (p.get("statut_sante") or "100%").strip()
    niveau, _, note = brut.partition(":")
    niveau = niveau if niveau in ("vigilance", "blessure") else "100"
    return {"niveau": niveau, "zones": [], "note": note.strip() or None, "protocole": None}


NIVEAUX_SANTE = ("100", "vigilance", "blessure")


def sante_libelle_court(sante: dict) -> dict:
    """Pastille courte : « Santé 100 % », « Vigilance · Achille D+G », « Blessure · 3 zones »."""
    niveau, zones = sante.get("niveau") or "100", sante.get("zones") or []
    if niveau == "100":
        return {"texte": "Santé 100 %", "couleur": "vert"}
    if len(zones) > 2:
        detail = f"{len(zones)} zones"
    else:
        groupes: dict[str, list[str]] = {}
        for z in zones:
            base, _, cote = z.rpartition(" ") if z.endswith((" G", " D")) else (z, "", "")
            groupes.setdefault(base, []).append(cote)
        detail = " · ".join(f"{b} {'+'.join(sorted(c for c in cotes if c))}".strip() for b, cotes in groupes.items())
    texte = ("Vigilance" if niveau == "vigilance" else "Blessure") + (f" · {detail}" if zones else "")
    return {"texte": texte, "couleur": "orange" if niveau == "vigilance" else "rouge"}


def enregistrer_sante(sante: dict) -> dict:
    niveau = sante.get("niveau") or "100"
    if niveau not in NIVEAUX_SANTE:
        raise ValueError("Niveau de santé invalide : 100, vigilance ou blessure.")
    zones = [z for z in (sante.get("zones") or []) if z in db.ZONES_SANTE] if niveau != "100" else []
    note = (sante.get("note") or "").strip() or None
    protocole = (sante.get("protocole") or "").strip() or None
    db.maj_profil(sante_niveau=niveau, sante_zones=zones, sante_note=note, sante_protocole=protocole,
                  statut_sante="100%" if niveau == "100" else f"{niveau}:{', '.join(zones) or note or ''}")
    return sante_profil()


def texte_sante_llm(sante: dict) -> str:
    """Contenu de <statut_sante> : niveau, zones, note et protocole kiné."""
    morceaux = [f"niveau: {'100 %' if sante['niveau'] == '100' else sante['niveau']}"]
    if sante.get("zones"):
        morceaux.append("zones: " + ", ".join(sante["zones"]))
    if sante.get("note"):
        morceaux.append(f"note: {sante['note']}")
    if sante.get("protocole"):
        morceaux.append(f"protocole kiné: {sante['protocole']}")
    return " | ".join(morceaux)


# Mots qui, dans l'analyse du LLM, justifient une alerte de sécurité… ou la disqualifient
_MOTS_SECURITE = ("douleur", "blessure", "récupération", "recovery")
_MOTS_ACWR = ("acwr", "ratio", "charge chronique", "charge aiguë", "charge aigue")
ORDRE_GRAVITE = {"vert": 0, "orange": 1, "rouge": 2}


def verdict_final(code: str, reponse: Optional[dict]) -> str:
    """Le verdict affiché est celui du backend. Du LLM, on garde le plus bas des deux, sauf s'il cite
    un signal de sécurité (il peut alors porter un rouge). Un verdict justifié par l'ACWR est ignoré."""
    v = (reponse or {}).get("verdict")
    if v not in ORDRE_GRAVITE:
        return code
    texte = " ".join([str(reponse.get("analyse") or "")] + [str(x) for x in reponse.get("signaux") or []]).lower()
    if any(m in texte for m in _MOTS_ACWR):
        return code
    if v == "rouge" and any(m in texte for m in _MOTS_SECURITE):
        return "rouge"
    if code == "hors_plan" or code == "rouge":
        return code          # hors plan reste neutre ; un rouge de sécurité calculé n'est jamais adouci
    return min(code, v, key=ORDRE_GRAVITE.get)


def _derniere_reponse_llm(seance_id: int) -> Optional[dict]:
    for a in db.analyses_seance(seance_id):
        if a["type_appel"] == "analyse_seance" and isinstance(a["reponse_json"], dict) and "verdict" in a["reponse_json"]:
            return {k: v for k, v in a["reponse_json"].items() if k != "recalcul"}
    return None


def evaluer(seance: dict, reponse_llm: Optional[dict] = None) -> tuple[str, list]:
    """Verdict d'une séance réalisée d'après son prévu lié, le statut santé et la récupération
    (jamais l'ACWR), combiné à la dernière analyse du LLM s'il y en a une."""
    prevu = prevu_de(seance["id"])
    prevu_eval = {"type": type_plan_normalise(prevu["type"]), "distance_km": prevu["distance_km"],
                  "duree_min": prevu["duree_min"]} if prevu else None
    code, signaux = metrics.evaluer_seance(seance, prevu_eval, sante_profil(), _prochaine_qualite_dans_h(seance))
    reponse = reponse_llm if reponse_llm is not None else _derniere_reponse_llm(seance["id"])
    return verdict_final(code, reponse), signaux


def evaluer_et_stocker(seance: dict, horodatage: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Recalcule le verdict d'une séance, le range dans seances_realisees et dans ses analyses
    (la réponse du LLM est conservée, le recalcul ajouté sous « recalcul »). Retourne (nouveau, ancien)."""
    verdict, signaux = evaluer(seance)
    analyses = [a for a in db.analyses_seance(seance["id"]) if a["type_appel"] == "analyse_seance"]
    ancien = seance.get("verdict") or (analyses[0]["verdict"] if analyses else None)
    sig = [asdict(x) for x in signaux]
    db.maj("seances_realisees", seance["id"], {"verdict": verdict, "signaux": sig})
    for a in analyses:
        rep = a["reponse_json"] if isinstance(a["reponse_json"], dict) else {}
        rep["recalcul"] = {"verdict": verdict, "signaux": sig, "le": horodatage or maintenant().isoformat(timespec="seconds")}
        db.maj("analyses_llm", a["id"], {"verdict": verdict, "reponse_json": rep})
    return verdict, ancien


def recalculer_semaine(lundi: date, modification: Optional[str] = None) -> dict:
    """Après tout changement (import, lier/délier, édition du plan), sans LLM : liaison, statuts,
    verdicts et totaux. `modification` (texte) marque le plan comme modifié par l'utilisateur."""
    dimanche = lundi + timedelta(days=6)
    relier(lundi, dimanche)
    mettre_a_jour_statuts(lundi, dimanche)
    for s in db.seances_entre(lundi.isoformat(), dimanche.isoformat()):
        evaluer_et_stocker(s)
    if modification:
        db.noter_modification(lundi.isoformat(), modification)
    return totaux_semaine(lundi)


def totaux_semaine(lundi: date) -> dict:
    """Volume prévu vs réalisé (course) et distribution des zones de la semaine."""
    du, au = lundi.isoformat(), (lundi + timedelta(days=6)).isoformat()
    plan = [p for p in db.planifiees_entre(du, au) if categorie_planifiee(p["type"]) == "course"]
    course = db.seances_entre(du, au, familles=extractor.FAMILLE_COURSE)
    return {
        "course_prevue_min": sum(p["duree_min"] or 0 for p in plan),
        "course_prevue_km": round(sum(p["distance_km"] or 0 for p in plan), 1),
        "course_realisee_min": round(sum(s["duree_min"] or 0 for s in course)),
        "course_realisee_km": round(sum(s["distance_km"] or 0 for s in course), 1),
        "distribution": metrics.distribution_hebdo(course),
    }


def liaisons_actuelles() -> dict[int, int]:
    return {r["id"]: r["seance_realisee_id"] for r in
            db.fetch_all("SELECT id, seance_realisee_id FROM seances_planifiees WHERE seance_realisee_id IS NOT NULL")}


def defaire_liaisons_incoherentes() -> list[dict]:
    """Garde-fou : délie toute séance prévue liée à une séance réalisée d'une autre discipline
    (héritage de l'ancien code, qui rangeait les types inconnus en course), puis recalcule les
    semaines touchées. Appelé au démarrage et par le recalcul admin."""
    lignes = db.fetch_all(
        "SELECT p.id, p.type, p.date_seance, r.id AS realisee, r.famille, r.sport_id, r.sport_a_preciser "
        "FROM seances_planifiees p "
        "JOIN seances_realisees r ON r.id = p.seance_realisee_id")
    defaites = [l for l in lignes if categorie_planifiee(l["type"]) != categorie_realisee(l)]
    if not defaites:
        return []
    with db.connexion() as c:
        for l in defaites:
            c.execute("UPDATE seances_planifiees SET seance_realisee_id = NULL WHERE id = ?", (l["id"],))
            c.execute("UPDATE seances_realisees SET lien_manuel = 0 WHERE id = ?", (l["realisee"],))
    for lundi in sorted({lundi_de(date.fromisoformat(l["date_seance"])) for l in defaites}):
        recalculer_semaine(lundi)
    return [{"planifiee": f"{l['type']} du {l['date_seance']}", "realisee": l["famille"]} for l in defaites]


# ---------------------------------------------------------------------------
# Liaison manuelle
# ---------------------------------------------------------------------------
def _seance_ou_erreur(seance_id: int) -> dict:
    s = db.seance(seance_id)
    if not s:
        raise ValueError("Séance réalisée introuvable.")
    return s


def candidats_liaison(seance_id: int) -> list[dict]:
    """Séances prévues non liées, de la même catégorie, dans la semaine de la séance réalisée."""
    s = _seance_ou_erreur(seance_id)
    lundi = lundi_de(date_de(s["date_debut"]))
    cat = categorie_realisee(s)
    return [p for p in db.planifiees_entre(lundi.isoformat(), (lundi + timedelta(days=6)).isoformat())
            if p["seance_realisee_id"] is None and cat and categorie_planifiee(p["type"]) == cat]


def lier(seance_id: int, planifiee_id: int) -> dict:
    s = _seance_ou_erreur(seance_id)
    p = db.planifiee(planifiee_id)
    if not p:
        raise ValueError("Séance prévue introuvable.")
    if not categorie_realisee(s) or categorie_planifiee(p["type"]) != categorie_realisee(s):
        raise ValueError("Liaison refusée : la séance prévue n'est pas de la même discipline (catégorie de sport).")
    lundi = lundi_de(date_de(s["date_debut"]))
    if lundi_de(date.fromisoformat(p["date_seance"])) != lundi:
        raise ValueError("Liaison refusée : la séance prévue n'est pas dans la même semaine.")
    if p["seance_realisee_id"] not in (None, seance_id):
        raise ValueError("Cette séance prévue est déjà liée à une autre séance réalisée.")
    decalage = (date_de(s["date_debut"]) - date.fromisoformat(p["date_seance"])).days
    with db.connexion() as c:
        c.execute("UPDATE seances_planifiees SET seance_realisee_id = NULL WHERE seance_realisee_id = ?", (seance_id,))
        c.execute("UPDATE seances_planifiees SET seance_realisee_id = ? WHERE id = ?", (seance_id, planifiee_id))
        c.execute("UPDATE seances_realisees SET lien_manuel = 1, decalage_jours = ? WHERE id = ?", (decalage, seance_id))
    recalculer_semaine(lundi)
    return detail_seance(seance_id)


def delier(seance_id: int) -> dict:
    s = _seance_ou_erreur(seance_id)
    with db.connexion() as c:
        c.execute("UPDATE seances_planifiees SET seance_realisee_id = NULL WHERE seance_realisee_id = ?", (seance_id,))
        # lien_manuel=1 : la liaison automatique ne la recollera pas
        c.execute("UPDATE seances_realisees SET lien_manuel = 1, decalage_jours = 0 WHERE id = ?", (seance_id,))
    recalculer_semaine(lundi_de(date_de(s["date_debut"])))
    return detail_seance(seance_id)


# ---------------------------------------------------------------------------
# Remplacement manuel : une séance réalisée remplace une ou plusieurs séances prévues
# (badminton au lieu d'EF + muscu). Décision manuelle, conservée par le recalcul admin.
# ---------------------------------------------------------------------------
def remplacables(seance_id: int) -> list[dict]:
    """Séances prévues de la semaine, toutes catégories, ni faites, ni décalées, ni déjà remplacées."""
    s = _seance_ou_erreur(seance_id)
    lundi = lundi_de(date_de(s["date_debut"]))
    deja = db.planifiees_remplacees()
    return [p for p in db.planifiees_entre(lundi.isoformat(), (lundi + timedelta(days=6)).isoformat())
            if p["seance_realisee_id"] is None and p["id"] not in deja and p["type"] != "repos"]


def remplacer(seance_id: int, planifiee_ids: list[int]) -> dict:
    s = _seance_ou_erreur(seance_id)
    if prevu_de(seance_id):
        raise ValueError("Cette séance est liée à une séance prévue : délie-la d'abord.")
    if not planifiee_ids:
        raise ValueError("Choisir au moins une séance prévue.")
    possibles = {p["id"] for p in remplacables(seance_id)}
    if not set(planifiee_ids) <= possibles:
        raise ValueError("Séance prévue non remplaçable : déjà faite, déjà remplacée ou hors de la semaine.")
    with db.connexion() as c:
        for pid in planifiee_ids:
            c.execute("INSERT OR IGNORE INTO remplacements (seance_realisee_id, seance_planifiee_id) VALUES (?, ?)",
                      (seance_id, pid))
    recalculer_semaine(lundi_de(date_de(s["date_debut"])))
    return detail_seance(seance_id)


def annuler_remplacement(seance_id: int) -> dict:
    s = _seance_ou_erreur(seance_id)
    with db.connexion() as c:
        c.execute("DELETE FROM remplacements WHERE seance_realisee_id = ?", (seance_id,))
    recalculer_semaine(lundi_de(date_de(s["date_debut"])))
    return detail_seance(seance_id)


# ---------------------------------------------------------------------------
# Bilan de la semaine par catégorie (sans LLM), recalculé à chaque affichage
# ---------------------------------------------------------------------------
# Charge prévue estimée, même échelle que le TRIMP : durée × poids de zone typique de la séance
POIDS_TYPE_PREVU = {"EF": 2, "sortie_longue": 2, "tempo": 3, "cotes": 3, "intervals": 3}
POIDS_CATEGORIE_PREVUE = {"course": 2, "force": 2, "raquette": 3, "collectif": 3, "porte": 2, "montagne": 2,
                          "mobilite": 1, "autre": 2}
LIBELLES_COURTS = {"EF": "EF", "intervals": "Intervalles", "cotes": "Côtes", "tempo": "Tempo",
                   "sortie_longue": "Sortie longue", "muscu_push": "Push", "muscu_pull": "Pull",
                   "muscu_jambes": "Jambes", "squash": "Squash", "velo": "Vélo"}
SEUIL_RESPECT_CATEGORIE = 0.8


def charge_prevue(p: dict) -> float:
    poids = POIDS_TYPE_PREVU.get(p["type"]) or POIDS_CATEGORIE_PREVUE.get(categorie_planifiee(p["type"]) or "", 0)
    return (p["duree_min"] or 0) * poids


def libelle_court(p: dict) -> str:
    """« EF 40 min », « Push »."""
    nom = LIBELLES_COURTS.get(p["type"]) or (sports.sport(_sport_du_type(p["type"]))["libelle"]
                                            if _sport_du_type(p["type"]) else p["type"])
    return f"{nom} {p['duree_min']:g} min" if p.get("duree_min") and p["type"] not in ("muscu_push", "muscu_pull", "muscu_jambes") else nom


def _suites_de_jours(jours: list[str]) -> list[list[str]]:
    """Suites d'au moins deux jours consécutifs."""
    suites, courante = [], []
    for j in sorted(set(jours)):
        if courante and (date.fromisoformat(j) - date.fromisoformat(courante[-1])).days == 1:
            courante.append(j)
        else:
            if len(courante) > 1:
                suites.append(courante)
            courante = [j]
    return suites + ([courante] if len(courante) > 1 else [])


def bilan_semaine(lundi: date) -> dict:
    """Réalisé vs prévu par catégorie, charge, décalages, remplacements, manques et jours d'impact
    élevé. respect_global se juge sur la partie écoulée : séances prévues avant aujourd'hui, ou déjà
    faites, décalées ou remplacées."""
    lundi = lundi_de(lundi)
    du, au = lundi.isoformat(), (lundi + timedelta(days=6)).isoformat()
    jour = aujourdhui().isoformat()
    remplacees = db.remplacements_par_planifiee()
    plan = [p for p in db.planifiees_entre(du, au) if p["type"] != "repos" and categorie_planifiee(p["type"])]
    faites = db.seances_entre(du, au)
    par_id = {s["id"]: s for s in faites}

    par_categorie: dict[str, dict] = {}
    ligne = lambda c: par_categorie.setdefault(c, {"prevu_seances": 0, "realise_seances": 0, "prevu_min": 0, "realise_min": 0})
    for p in plan:
        l = ligne(categorie_planifiee(p["type"]))
        l["prevu_seances"] += 1
        l["prevu_min"] += round(p["duree_min"] or 0)
    for s in faites:
        l = ligne(categorie_realisee(s) or "autre")
        l["realise_seances"] += 1
        l["realise_min"] += round(s["duree_min"] or 0)

    decalages = [{"seance": libelle_court(p), "de": p["date_seance"], "a": par_id[p["seance_realisee_id"]]["date_debut"][:10]}
                 for p in plan if p["seance_realisee_id"] in par_id
                 and par_id[p["seance_realisee_id"]]["date_debut"][:10] != p["date_seance"]]
    remplacements = []
    for s in faites:
        remplacees_s = db.remplacees_par(s["id"])
        if remplacees_s:
            remplacements.append({"par": f"{sports.sport(sports.sport_de(s))['libelle'].lower()} {round(s['duree_min'] or 0)} min",
                                  "remplace": [libelle_court(p) for p in remplacees_s]})
    manques = [{"seance": libelle_court(p), "date": p["date_seance"]} for p in plan if p["statut"] == "manque"]
    jours_impact = sorted({s["date_debut"][:10] for s in faites if sports.impact(sports.sport_de(s)) == "eleve"})
    consecutifs = _suites_de_jours(jours_impact)

    # Respect de la semaine, sur la partie écoulée
    echues = [p for p in plan if p["date_seance"] < jour or p["seance_realisee_id"] or p["id"] in remplacees]
    categories_ko = []
    for c in {categorie_planifiee(p["type"]) for p in echues}:
        prevues = [p for p in echues if categorie_planifiee(p["type"]) == c]
        couvertes = sum(1 for p in prevues if p["id"] in remplacees)
        faites_c = sum(1 for s in faites if categorie_realisee(s) == c and s["date_debut"][:10] <= jour)
        if min(len(prevues), faites_c + couvertes) < SEUIL_RESPECT_CATEGORIE * len(prevues):
            categories_ko.append(c)
    charge_prevue_echue = sum(charge_prevue(p) for p in echues)
    charge_realisee = sum(s["charge"] or 0 for s in faites if s["date_debut"][:10] <= jour)
    ratio = charge_realisee / charge_prevue_echue if charge_prevue_echue else None
    if not echues:
        respect = None                                          # rien de prévu à cette date
    elif (ratio is not None and not 0.6 <= ratio <= 1.4) or len(categories_ko) * 2 > len({categorie_planifiee(p["type"]) for p in echues}):
        respect = "non_respectee"
    elif categories_ko or (ratio is not None and not 0.8 <= ratio <= 1.2):
        respect = "partielle"
    else:
        respect = "respectee"

    sante = sante_profil()
    zones = set(sante.get("zones") or []) & metrics.ZONES_BAS_DU_CORPS
    alerte = None
    if consecutifs and sante["niveau"] in ("vigilance", "blessure") and zones:
        alerte = (f"Impact élevé plusieurs jours de suite ({', '.join(jour_de(date.fromisoformat(j)) for j in consecutifs[0])}) "
                  f"en {sante['niveau']} {', '.join(sorted(zones))}.")
    return {
        "lundi": du,
        "par_categorie": par_categorie,
        "charge_totale": {"prevu": round(sum(charge_prevue(p) for p in plan)), "realise": round(sum(s["charge"] or 0 for s in faites))},
        "jours_impact_eleve": jours_impact,
        "jours_consecutifs_impact_eleve": consecutifs,
        "decalages": decalages,
        "remplacements": remplacements,
        "manques": manques,
        "respect_global": respect,
        "categories_sous_80": sorted(categories_ko),
        "alerte": alerte,
    }


def _datetime_planifiee(p: dict) -> datetime:
    d = date.fromisoformat(p["date_seance"])
    return datetime(d.year, d.month, d.day, HEURE_CRENEAU.get(p["creneau"], 9), tzinfo=TZ)


def _prochaine_qualite_dans_h(seance: dict) -> Optional[float]:
    fin = en_paris(seance["date_debut"]) + timedelta(minutes=seance["duree_min"] or 0)
    for p in db.planifiees_entre(fin.date().isoformat(), (fin.date() + timedelta(days=7)).isoformat()):
        # Le chevauchement compte quel que soit le statut (prévue, réalisée, manquée)
        if p["type"] in TYPES_QUALITE:
            dt = _datetime_planifiee(p)
            if dt > fin:
                return round((dt - fin).total_seconds() / 3600, 1)
    return None


def acwr_au(d: date) -> metrics.ACWR:
    """ACWR au jour d : l'EWMA part de la première séance importée."""
    return metrics.calculer_acwr(db.seances_entre("0000-01-01", d.isoformat()), date_ref=d)


def distribution_semaine(lundi: date) -> dict:
    course = db.seances_entre(lundi.isoformat(), (lundi + timedelta(days=6)).isoformat(),
                              familles=extractor.FAMILLE_COURSE)
    return metrics.distribution_hebdo(course)


def acwr_dict(a: metrics.ACWR) -> dict:
    """Pendant le calibrage, ni ratio ni charges : seul l'avancement (J X/21) est exposé."""
    if a.zone == "calibrage":
        return {"ratio": None, "zone": "calibrage", "verdict": a.verdict,
                "jours_historique": a.jours_historique, "jours_calibrage": metrics.JOURS_CALIBRAGE}
    return {"ratio": a.ratio, "zone": a.zone, "verdict": a.verdict, "jours_historique": a.jours_historique,
            "charge_aigue": round(a.charge_aigue, 1), "charge_chronique": round(a.charge_chronique, 1)}


# ---------------------------------------------------------------------------
# Import : pipeline complet
# ---------------------------------------------------------------------------
def importer_et_analyser(fichier_bytes: bytes, nom: str, muscu_detail: Optional[dict] = None,
                         sport_id: Optional[str] = None, sous_type: Optional[str] = None,
                         analyser: bool = True, douleur: Optional[int] = None,
                         douleur_zone: Optional[str] = None, famille: Optional[str] = None,
                         rpe: Optional[int] = None) -> dict:
    """Import d'un fichier Suunto. Un code ActivityType inconnu ne fait jamais échouer l'import :
    la séance est enregistrée en « autre », marquée sport_a_preciser, et l'analyse LLM attend le
    choix du sport (preciser_sport). famille : ancien paramètre (avant v5), converti en sport."""
    # 1. Hash, anti-doublon
    h = hash_fichier(fichier_bytes)
    existant = db.seance_par_hash(h)
    if existant:
        return {"doublon": True, "seance_id": existant["id"],
                "message": f"Fichier déjà importé (séance #{existant['id']})."}

    # 2. Extraction → ActiviteNormalisee
    if famille and not sport_id:
        if famille not in FAMILLES:
            raise ErreurImport(f"Famille inconnue : {famille}")
        sport_id = sports.SPORT_DEPUIS_FAMILLE[famille]
    a, confirme = _activite_suunto(fichier_bytes, nom, sport_id, sous_type)
    if sport_id and a.source_code not in db.activity_types(suunto_json.SOURCE):
        # Choix fait dès l'aperçu pour un code inconnu : appris pour les prochains fichiers
        db.enregistrer_activity_type(a.source_code, sport_id, suunto_json.SOURCE)
    if rpe not in (None, ""):
        a.rpe = _rpe_valide(rpe)
    return importer_activite(a, confirme, analyser, muscu_detail, douleur, douleur_zone)


def importer_strava(activite_json: dict, streams: Optional[dict] = None, analyser: bool = True) -> dict:
    """Activité Strava déjà téléchargée (pas de client HTTP en V1)."""
    return importer_activite(strava.normaliser(activite_json, streams, db.activity_types(strava.SOURCE)),
                             analyser=analyser)


def importer_activite(a: ActiviteNormalisee, confirme: bool = False, analyser: bool = True,
                      muscu_detail: Optional[dict] = None, douleur: Optional[int] = None,
                      douleur_zone: Optional[str] = None) -> dict:
    """Point d'entrée commun à toutes les sources : anti-doublon, fusion entre sources, insertion,
    puis analyse (analyser_seance)."""
    ligne = _ligne_seance(a, confirme)
    if douleur not in (None, ""):
        d_val = int(douleur)
        if not 0 <= d_val <= 10:
            raise ErreurImport("Douleur : valeur entre 0 et 10.")
        ligne.update(douleur=d_val, douleur_zone=(douleur_zone or None))

    # Anti-doublon strict : même fichier, même activité de la source
    existant = db.seance_par_hash(ligne["fichier_hash"]) or db.fetch_one(
        "SELECT * FROM seances_realisees WHERE source = ? AND source_id = ?", (a.source, a.source_id))
    if existant:
        return {"doublon": True, "seance_id": existant["id"], "message": "Déjà importée."}
    # Même séance arrivée par une autre source : pas de nouvelle ligne, on complète l'existante
    jumelle = doublon_entre_sources(a)
    if jumelle:
        return fusionner(jumelle, ligne)

    try:
        with db.connexion() as c:
            seance_id = db.inserer("seances_realisees", ligne, conn=c)
            # 3. Détail muscu
            if a.sport_id == "muscu" and muscu_detail:
                db.inserer("muscu_detail", {"seance_id": seance_id, **_valider_muscu(muscu_detail)}, conn=c)
    except sqlite3.IntegrityError:
        existant = db.seance_par_hash(ligne["fichier_hash"])
        return {"doublon": True, "seance_id": existant["id"] if existant else None, "message": "Déjà importée."}
    return analyser_seance(seance_id, analyser, confirme)


ECART_DEBUT_DOUBLON = timedelta(minutes=3)
ECART_DUREE_DOUBLON = 0.10
LIBELLES_SOURCE = {"suunto_json": "fichier Suunto", "strava": "Strava", "manuel": "saisie manuelle"}
# Champs qu'une source moins riche peut compléter (jamais écraser)
CHAMPS_COMPLETABLES = ("rpe", "note", "dplus_m", "distance_km", "fc_moy", "fc_max", "douleur", "douleur_zone",
                       "temps_zones_s", "temps_zones_pct", "a_gps", "a_fc", "vitesse_moy_kmh")


def doublon_entre_sources(a: ActiviteNormalisee) -> Optional[dict]:
    """Séance déjà enregistrée par une autre source : même catégorie (ou sport encore à préciser),
    début à ± 3 min, durée à ± 10 %."""
    debut = en_paris(a.debut)
    for s in db.seances_entre((debut.date() - timedelta(days=1)).isoformat(),
                              (debut.date() + timedelta(days=1)).isoformat()):
        if s["source"] == a.source:
            continue
        meme_categorie = sports.categorie(s["sport_id"]) == sports.categorie(a.sport_id) \
            or s["sport_a_preciser"] or not a.sport_connu
        duree = max(s["duree_min"] or 0, a.duree_min) or 1
        if meme_categorie and abs(en_paris(s["date_debut"]) - debut) <= ECART_DEBUT_DOUBLON \
                and abs((s["duree_min"] or 0) - a.duree_min) <= ECART_DUREE_DOUBLON * duree:
            return s
    return None


def _vide(v) -> bool:
    return v in (None, "", 0, {}) or (isinstance(v, dict) and not any(v.values()))


def fusionner(existante: dict, nouvelle: dict) -> dict:
    """Une seule ligne par séance. La source la plus riche (Suunto JSON > Strava > manuel) fournit les
    mesures ; RPE, note, douleur et sport déjà choisis sont conservés. Sinon : la nouvelle source
    complète seulement les champs vides."""
    if RICHESSE_SOURCE.get(nouvelle["source"], 0) > RICHESSE_SOURCE.get(existante["source"], 0):
        maj = {k: v for k, v in nouvelle.items() if k != "importe_le"}
        for k in ("rpe", "note", "douleur", "douleur_zone"):
            if _vide(maj.get(k)):
                maj.pop(k, None)
        if not existante["sport_a_preciser"]:              # sport déjà connu : il est gardé
            for k in ("sport_id", "famille", "sport_a_preciser"):
                maj.pop(k)
            if sports.categorie(existante["sport_id"]) != "course":
                maj.update(sous_type=None, sous_type_confiance=None)
    else:
        maj = {k: nouvelle[k] for k in CHAMPS_COMPLETABLES
               if k in nouvelle and _vide(existante.get(k)) and not _vide(nouvelle[k])}
    if maj:
        maj["charge"] = round(metrics.charge_seance({**existante, **maj}), 1)
        db.maj("seances_realisees", existante["id"], maj)
        recalculer_semaine(lundi_de(date_de(existante["date_debut"])))
    seance = db.seance(existante["id"])
    return {"doublon": True, "fusion": True, "seance_id": seance["id"], "seance": _seance_publique(seance),
            "message": f"Même séance que la {LIBELLES_SOURCE.get(existante['source'], existante['source'])} "
                       f"du {seance['date_debut'][:10]} : complétée, pas de doublon."}


def analyser_seance(seance_id: int, analyser: bool = True, confirme: bool = False) -> dict:
    """Étapes 4 à 12 de l'import, pour une séance déjà enregistrée (fichier, saisie manuelle,
    ou sport précisé après coup). Pas d'analyse LLM tant que le sport reste à préciser."""
    # 4 et 10. Liaison au prévu (même jour, même famille) et statuts de la semaine
    d = date_de(db.seance(seance_id)["date_debut"])
    recalculer_semaine(lundi_de(d))
    seance = db.seance(seance_id)
    prevu = prevu_de(seance_id)

    # 5-7. Indicateurs et verdict déterministe
    acwr = acwr_au(d)
    prochaine_h = _prochaine_qualite_dans_h(seance)
    verdict, signaux = evaluer(seance)
    indicateurs = {
        "signaux": [asdict(x) for x in signaux],
        "distribution_semaine": distribution_semaine(lundi_de(d)),
        "prochaine_qualite_dans_h": prochaine_h,
    }

    # 8-9. Analyse LLM, tracée dans analyses_llm
    reponse, erreur, analyse_id = None, None, None
    if analyser and not seance["sport_a_preciser"]:
        lundi = lundi_de(d)
        reste = [_planifiee_llm(p) for p in db.planifiees_entre(d.isoformat(), (lundi + timedelta(days=6)).isoformat())]
        seance_llm = _seance_llm(seance)
        if seance["sport_id"] == "muscu":
            seance_llm["muscu_detail"] = db.muscu_detail(seance_id)
        p = db.profil()
        reponse, erreur, trace = _appel_llm(
            "analyse_seance", lambda llm: llm.analyse_seance(
                seance=seance_llm, prevu=prevu and _planifiee_llm(prevu), semaine=reste,
                indicateurs={**indicateurs, "verdict_calcule": verdict},   # pas d'ACWR : il ne juge pas une séance
                profil=_profil_llm(p), statut_sante=texte_sante_llm(sante_profil(p)), mode=p.get("mode_actif", "BASE")))
        if reponse is not None:
            verdict = verdict_final(verdict, reponse)
        analyse_id = _tracer("analyse_seance", reponse, erreur, trace, verdict=verdict, seance_id=seance_id)
    db.maj("seances_realisees", seance_id, {"verdict": verdict})

    # Niveau 3 de classification : le LLM tranche un sous-type incertain
    if reponse and seance["famille"] in extractor.FAMILLE_COURSE and not confirme \
            and (seance["sous_type_confiance"] or 0) < SEUIL_CONFIANCE \
            and reponse.get("type_detecte") in SOUS_TYPES_COURSE:
        db.maj("seances_realisees", seance_id, {"sous_type": reponse["type_detecte"], "sous_type_confirme": 1})
        seance = db.seance(seance_id)

    # 11. Ajustements : appliqués d'office sauf en rouge (validation utilisateur)
    ajustements = (reponse or {}).get("ajustements") or []
    validation_requise = verdict == "rouge" and bool(ajustements)
    appliques = []
    if ajustements and not validation_requise:
        appliques = appliquer_ajustements(ajustements, d)
        db.maj("analyses_llm", analyse_id, {"valide_par_user": 1})

    return {
        "doublon": False,
        "seance": _seance_publique(seance),
        "sport_a_preciser": bool(seance["sport_a_preciser"]),
        "proposition": proposition_sport(seance) if seance["sport_a_preciser"] else None,
        "prevu": prevu,
        "verdict": verdict,
        "indicateurs": {**indicateurs, "acwr": acwr_dict(acwr)},   # affichage seulement
        "analyse_id": analyse_id,
        "analyse_llm": reponse,
        "erreur_llm": erreur,
        "ajustements": ajustements,
        "ajustements_appliques": appliques,
        "validation_requise": validation_requise,
    }


def _rpe_valide(rpe) -> int:
    try:
        v = int(rpe)
    except (TypeError, ValueError):
        raise ErreurImport("RPE : valeur entre 1 et 10.")
    if not 1 <= v <= 10:
        raise ErreurImport("RPE : valeur entre 1 et 10.")
    return v


def saisir_seance(donnees: dict, analyser: bool = True) -> dict:
    """Séance réalisée saisie à la main (sans fichier) : sport, début, durée, RPE (obligatoire sans FC),
    FC moyenne, distance et D+ si le sport en a, douleur, note. Charge : metrics.charge_manuelle."""
    sport_id = donnees.get("sport_id")
    if sport_id not in sports.SPORTS_PAR_ID:
        raise ErreurImport("Choisir un sport.")
    try:
        debut = en_paris(str(donnees.get("debut") or ""))
    except ValueError:
        raise ErreurImport("Date et heure de début invalides.")
    duree = _nombre(donnees.get("duree_min"))
    if not duree or duree <= 0 or duree > 24 * 60:
        raise ErreurImport("Durée invalide (minutes).")
    fc = _nombre(donnees.get("fc_moy"))
    if fc is not None and not 30 <= fc <= 230:
        raise ErreurImport("FC moyenne invalide.")
    rpe = _rpe_valide(donnees["rpe"]) if donnees.get("rpe") not in (None, "") else None
    if rpe is None and not fc:
        raise ErreurImport("RPE obligatoire sans fréquence cardiaque.")
    avec_distance = sports.sport(sport_id)["distance"]
    a = ActiviteNormalisee(
        source="manuel", source_id=str(uuid.uuid4()), source_code=None, sport_id=sport_id,
        debut=debut.isoformat(timespec="seconds"), duree_s=duree * 60,
        distance_m=((_nombre(donnees.get("distance_km")) or 0) * 1000) if avec_distance else 0,
        d_plus_m=_nombre(donnees.get("dplus_m")) if avec_distance else None,
        fc_moy=int(fc) if fc else None, rpe=rpe, note=(donnees.get("note") or "").strip() or None,
    )
    return importer_activite(a, analyser=analyser, douleur=donnees.get("douleur"),
                             douleur_zone=donnees.get("douleur_zone"))


def proposition_sport(seance: dict) -> Optional[dict]:
    brut = seance.get("donnees_brutes")
    if not isinstance(brut, dict):
        return None
    champs = extractor.SeanceExtraite.__dataclass_fields__
    return extractor.deviner_sport(extractor.SeanceExtraite(**{k: v for k, v in brut.items() if k in champs}))


# ---------------------------------------------------------------------------
# Sport à préciser, correspondances apprises (activity_types)
# ---------------------------------------------------------------------------
def _sport_valide(sport_id: str) -> str:
    if sport_id not in sports.SPORTS_PAR_ID:
        raise ValueError(f"Sport inconnu : {sport_id}")
    return sport_id


def _changer_sport(seance: dict, sport_id: str) -> None:
    """Sport d'une séance existante : famille héritée, sous-type de course recalculé si besoin."""
    maj = {"sport_id": sport_id, "famille": sports.famille_heritee(sport_id), "sport_a_preciser": 0}
    if sports.categorie(sport_id) != "course":
        maj.update(sous_type=None, sous_type_confiance=None, sous_type_confirme=0)
    elif not seance.get("sous_type") or sports.categorie(sports.sport_de(seance)) != "course":
        brut = seance.get("donnees_brutes") if isinstance(seance.get("donnees_brutes"), dict) else {}
        champs = extractor.SeanceExtraite.__dataclass_fields__
        try:
            st, conf = extractor.classify_course(extractor.SeanceExtraite(**{k: v for k, v in brut.items() if k in champs}))
        except TypeError:          # séance manuelle : pas de données brutes
            st, conf = None, None
        maj.update(sous_type=None if st == "inconnu" else st, sous_type_confiance=conf, sous_type_confirme=0)
    db.maj("seances_realisees", seance["id"], maj)


def preciser_sport(seance_id: int, sport_id: str, analyser: bool = True) -> dict:
    """Choix du sport d'une séance (bottom sheet « Quel sport ? »). Pour un fichier, le code reçu est
    appris : les séances en attente avec ce code et les prochains fichiers le reprennent."""
    s = _seance_ou_erreur(seance_id)
    _sport_valide(sport_id)
    a_preciser = bool(s["sport_a_preciser"])
    if s["source"] in ("suunto_json", "strava") and s["source_code"]:
        db.enregistrer_activity_type(s["source_code"], sport_id, s["source"])
        for autre in db.fetch_all("SELECT * FROM seances_realisees WHERE source = ? AND source_code = ? "
                                  "AND sport_a_preciser = 1 AND id != ?", (s["source"], s["source_code"], seance_id)):
            _changer_sport(autre, sport_id)
            recalculer_semaine(lundi_de(date_de(autre["date_debut"])))
    _changer_sport(s, sport_id)
    # Première précision : l'analyse qui avait été suspendue est lancée
    if a_preciser:
        return analyser_seance(seance_id, analyser)
    recalculer_semaine(lundi_de(date_de(s["date_debut"])))
    return {"seance": _seance_publique(db.seance(seance_id))}


def correspondances() -> list[dict]:
    """Codes appris par source, avec le nombre de séances importées sous chaque code."""
    comptes = {(r["source"], r["source_code"]): r["n"] for r in db.fetch_all(
        "SELECT source, source_code, COUNT(*) AS n FROM seances_realisees GROUP BY source, source_code")}
    return [{**c, "libelle": sports.sport(c["sport_id"])["libelle"], "confirme": bool(c["confirme"]),
             "seances": comptes.get((c["source"], c["code"]), 0)} for c in db.correspondances()]


def corriger_correspondance(source: str, code: str, sport_id: str, reaffecter: bool = False) -> dict:
    """Corrige un code appris ; reaffecter=True change aussi le sport des séances déjà importées."""
    _sport_valide(sport_id)
    db.enregistrer_activity_type(code, sport_id, source)
    seances_code = db.fetch_all("SELECT * FROM seances_realisees WHERE source = ? AND source_code = ?", (source, code))
    a_changer = [x for x in seances_code if reaffecter or x["sport_a_preciser"]]
    for x in a_changer:
        _changer_sport(x, sport_id)
    for lundi in sorted({lundi_de(date_de(x["date_debut"])) for x in a_changer}):
        recalculer_semaine(lundi)
    return {"code": code, "source": source, "sport_id": sport_id, "seances_reaffectees": len(a_changer)}


# ---------------------------------------------------------------------------
# Recalcul des verdicts (sans appel LLM)
# ---------------------------------------------------------------------------
def recalculer_tout() -> dict:
    """Recalcul admin, sans LLM : remet à zéro les liaisons automatiques, relie tout l'historique,
    recalcule charges, statuts et verdicts. Les liaisons manuelles (lien_manuel=1) sont conservées."""
    horodatage = maintenant().isoformat(timespec="seconds")
    liens_avant = liaisons_actuelles()
    incoherentes = defaire_liaisons_incoherentes()
    with db.connexion() as c:
        c.execute("UPDATE seances_planifiees SET seance_realisee_id = NULL "
                  "WHERE seance_realisee_id IN (SELECT id FROM seances_realisees WHERE lien_manuel = 0)")
    seances = db.fetch_all("SELECT * FROM seances_realisees ORDER BY date_debut")
    for s in seances:
        db.maj("seances_realisees", s["id"], {"charge": round(metrics.charge_seance(s), 1)})
    dates = {date_de(s["date_debut"]) for s in seances} | {
        date.fromisoformat(r["date_seance"]) for r in db.fetch_all("SELECT DISTINCT date_seance FROM seances_planifiees")}
    for lundi in sorted({lundi_de(d) for d in dates}):
        relier(lundi, lundi + timedelta(days=6))
        mettre_a_jour_statuts(lundi, lundi + timedelta(days=6))
    changements, nb_analyses, sans_analyse = [], 0, 0
    for s in db.fetch_all("SELECT * FROM seances_realisees ORDER BY date_debut"):
        apres, avant = evaluer_et_stocker(s, horodatage)
        n = sum(1 for a in db.analyses_seance(s["id"]) if a["type_appel"] == "analyse_seance")
        nb_analyses += n
        sans_analyse += 0 if n else 1
        if avant != apres:
            changements.append({"seance_id": s["id"], "date": s["date_debut"][:10], "famille": s["famille"],
                                "avant": avant, "apres": apres})
    liens_apres = liaisons_actuelles()
    plan = {p["id"]: p for p in db.fetch_all("SELECT id, type, date_seance FROM seances_planifiees")}
    familles = {s["id"]: s["famille"] for s in db.fetch_all("SELECT id, famille FROM seances_realisees")}
    corrigees = [{"planifiee": f"{plan[i]['type']} du {plan[i]['date_seance']}",
                  "avant": familles.get(liens_avant.get(i)), "apres": familles.get(liens_apres.get(i))}
                 for i in sorted(set(liens_avant) | set(liens_apres))
                 if liens_avant.get(i) != liens_apres.get(i) and i in plan]
    return {"seances": len(seances), "analyses_mises_a_jour": nb_analyses, "seances_sans_analyse": sans_analyse,
            "seances_liees": len(liens_apres), "liaisons_corrigees": corrigees,
            "liaisons_incoherentes_defaites": incoherentes, "changements": changements}


recalculer_verdicts = recalculer_tout      # nom historique de la route admin


def _seance_publique(s: dict) -> dict:
    """Séance sans le JSON brut (volumineux et redondant), avec la date prévue si elle a été
    décalée (« Prévue samedi »)."""
    out = {k: v for k, v in s.items() if k != "donnees_brutes"}
    if s.get("decalage_jours"):
        out["prevue_le"] = (date_de(s["date_debut"]) - timedelta(days=s["decalage_jours"])).isoformat()
    if s.get("id"):
        out["remplace"] = [{k: p[k] for k in ("id", "type", "date_seance", "duree_min")} for p in db.remplacees_par(s["id"])]
    return out


# ---------------------------------------------------------------------------
# Catalogue des sports
# ---------------------------------------------------------------------------
def sports_recents(n: int = 6) -> list[str]:
    """Les n derniers sports utilisés (séances réalisées, plus récentes d'abord)."""
    vus = []
    for r in db.fetch_all("SELECT * FROM seances_realisees WHERE sport_a_preciser = 0 "
                          "ORDER BY date_debut DESC LIMIT 200"):
        sid = sports.sport_de(r)
        if sid not in vus:
            vus.append(sid)
        if len(vus) == n:
            break
    return vus


def catalogue_sports() -> dict:
    return {**sports.catalogue_api(), "recents": sports_recents()}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def marquer_manquees(avant: date) -> None:
    """Séances prévues d'un jour passé et jamais réalisées → 'manque'."""
    with db.connexion() as c:
        c.execute(
            "UPDATE seances_planifiees SET statut = 'manque' "
            "WHERE date_seance < ? AND statut IN ('prevu', 'modifie') "
            "AND seance_realisee_id IS NULL AND type <> 'repos'",
            (avant.isoformat(),),
        )


def semaine(lundi: date) -> list[dict]:
    """7 jours avec séances planifiées et réalisées."""
    dimanche = lundi + timedelta(days=6)
    remplacees = db.remplacements_par_planifiee()
    plan = [{**p, "remplacee_par": remplacees.get(p["id"])}
            for p in db.planifiees_entre(lundi.isoformat(), dimanche.isoformat())]
    faites = [_seance_publique(s) for s in db.seances_entre(lundi.isoformat(), dimanche.isoformat())]
    liees = {p["seance_realisee_id"] for p in plan if p["seance_realisee_id"]}
    jours = []
    for i in range(7):
        d = (lundi + timedelta(days=i)).isoformat()
        jours.append({
            "date": d,
            "jour": JOURS[i],
            "planifiees": [p for p in plan if p["date_seance"] == d],
            "realisees_hors_plan": [s for s in faites if s["date_debut"][:10] == d and s["id"] not in liees],
        })
    return jours


def phase_active(d: date) -> Optional[dict]:
    iso = d.isoformat()
    for p in db.plan_prepa():
        if p["du"] <= iso <= p["au"]:
            return p
    return None


def prochain_evenement_a(d: date) -> Optional[dict]:
    for e in db.evenements(depuis=d.isoformat()):
        if e["priorite"] == "A":
            return {**e, "dans_jours": (date.fromisoformat(e["date_evt"]) - d).days}
    return None


def cout_llm_mois() -> dict:
    import llm_client
    u = llm_client.cout_du_mois()
    return {"mois": u.mois, "cout_usd": round(u.cout_usd, 4), "nb_appels": u.nb_appels,
            "plafond_usd": llm_client.PLAFOND_MENSUEL_USD}


def tableau_de_bord(d: Optional[date] = None) -> dict:
    d = d or aujourdhui()
    lundi = lundi_de(d)
    marquer_manquees(d)
    seances_sem = db.seances_entre(lundi.isoformat(), (lundi + timedelta(days=6)).isoformat())
    derniere = db.derniere_analyse()
    return {
        "aujourdhui": d.isoformat(),
        "lundi": lundi.isoformat(),
        "profil": db.profil(),
        "phase": phase_active(d),
        "prochain_a": prochain_evenement_a(d),
        "semaine": semaine(lundi),
        "acwr": acwr_dict(acwr_au(d)),
        "distribution": distribution_semaine(lundi),
        "charge_semaine": round(metrics.charge_semaine(seances_sem), 1),
        "derniere_analyse": derniere,
        "cout_llm": cout_llm_mois(),
        "ajustement": etat_ajustement(d),
        "sante": {**sante_profil(), **sante_libelle_court(sante_profil())},
        "bilan_semaine": bilan_semaine(lundi),
    }


# ---------------------------------------------------------------------------
# Édition du plan de la semaine en cours (recalcul automatique, sans LLM)
# ---------------------------------------------------------------------------
class Refus(Exception):
    """Action refusée en l'état (ex. supprimer une séance prévue déjà liée)."""


def _verifier_semaine_courante(date_iso: str) -> date:
    try:
        d = date.fromisoformat(date_iso)
    except (TypeError, ValueError):
        raise ValueError("Date invalide (AAAA-MM-JJ).")
    lundi = lundi_de(aujourdhui())
    if not lundi <= d <= lundi + timedelta(days=6):
        raise ValueError("Seules les séances de la semaine en cours peuvent être modifiées.")
    return d


def _libelle_seance(p: dict) -> str:
    return f"{p['type']} du {jour_de(date.fromisoformat(p['date_seance']))} {p['creneau']}"


def creer_planifiee(valeurs: dict) -> dict:
    v = valider_planifiee({**valeurs, "statut": None})
    _verifier_semaine_courante(v["date_seance"])
    id_ = db.inserer("seances_planifiees", {**v, "origine": "manuel"})
    p = db.planifiee(id_)
    totaux = recalculer_semaine(lundi_de(date.fromisoformat(p["date_seance"])), f"Ajout : {_libelle_seance(p)}")
    return {"seance": db.planifiee(id_), "totaux": totaux}


def modifier_planifiee(id_: int, valeurs: dict) -> dict:
    actuelle = db.planifiee(id_)
    if not actuelle:
        raise ValueError("Séance prévue introuvable.")
    _verifier_semaine_courante(actuelle["date_seance"])
    champs = ("date_seance", "creneau", "type", "duree_min", "distance_km", "detail", "intensite", "dplus_m")
    v = valider_planifiee({**{k: actuelle[k] for k in champs}, **{k: valeurs[k] for k in champs if k in valeurs}})
    _verifier_semaine_courante(v["date_seance"])
    v["version"] = actuelle["version"] + 1
    if actuelle["statut"] == "prevu":
        v["statut"] = "modifie"
    db.maj("seances_planifiees", id_, v)
    apres = db.planifiee(id_)
    diff = [f"{k} {actuelle[k]} → {apres[k]}" for k in ("date_seance", "creneau", "type", "duree_min", "distance_km")
            if actuelle[k] != apres[k]]
    texte = f"Modification : {_libelle_seance(actuelle)}" + (f" ({', '.join(diff)})" if diff else "")
    totaux = recalculer_semaine(lundi_de(date.fromisoformat(apres["date_seance"])), texte)
    return {"seance": db.planifiee(id_), "totaux": totaux}


def supprimer_planifiee(id_: int) -> dict:
    p = db.planifiee(id_)
    if not p:
        raise ValueError("Séance prévue introuvable.")
    _verifier_semaine_courante(p["date_seance"])
    if p["seance_realisee_id"]:
        raise Refus("Cette séance prévue est liée à une séance réalisée : délie-la d'abord.")
    db.supprimer("seances_planifiees", id_)
    return {"ok": True, "totaux": recalculer_semaine(lundi_de(date.fromisoformat(p["date_seance"])),
                                                    f"Suppression : {_libelle_seance(p)}")}


# ---------------------------------------------------------------------------
# Réajustement de la semaine par le LLM (à la demande)
# ---------------------------------------------------------------------------
TYPES_COURSE_LONGUE_MAX_MIN = 75
MESSAGE_AJUSTEMENT_INVALIDE = "Sensei n'a pas trouvé d'ajustement valide, ton plan actuel est conservé."


def _premier_jour_modifiable(d: date) -> date:
    """Demain si quelque chose a déjà été réalisé aujourd'hui, sinon aujourd'hui."""
    return d + timedelta(days=1) if db.seances_entre(d.isoformat(), d.isoformat()) else d


def etat_ajustement(d: Optional[date] = None) -> dict:
    d = d or aujourdhui()
    lundi = lundi_de(d)
    du, au = lundi.isoformat(), (lundi + timedelta(days=6)).isoformat()
    etat = db.etat_semaine(du)
    raisons = []
    if etat["plan_modifie"]:
        raisons.append("plan modifié")
    if any(p["statut"] == "manque" for p in db.planifiees_entre(du, au)):
        raisons.append("séance manquée")
    if any(s.get("verdict") == "hors_plan" for s in db.seances_entre(du, au)):
        raisons.append("séance hors plan")
    premier = _premier_jour_modifiable(d)
    return {"possible": bool(raisons) and premier <= lundi + timedelta(days=6), "raisons": raisons,
            "plan_modifie": etat["plan_modifie"], "premier_jour": premier.isoformat()}


def _seances_proposees(reponse: dict) -> dict[str, list[dict]]:
    return {j.get("date"): [x for x in (j.get("seances") or []) if isinstance(x, dict)]
            for j in reponse.get("jours") or [] if isinstance(j, dict)}


def valider_ajustement(reponse: dict, lundi: date, premier: date) -> list[str]:
    """Règles dures vérifiables en code, sur la semaine complète (réalisé + plan conservé + proposition)."""
    violations = []
    dimanche = lundi + timedelta(days=6)
    proposes = _seances_proposees(reponse)
    if not proposes:
        return ["Aucun jour proposé."]
    for d_iso in proposes:
        try:
            d = date.fromisoformat(d_iso or "")
        except ValueError:
            violations.append(f"Date invalide : {d_iso}.")
            continue
        if not premier <= d <= dimanche:
            violations.append(f"Date {d_iso} hors des jours modifiables ({premier.isoformat()} → {dimanche.isoformat()}).")
    # jour → [(catégorie, durée, origine, sport)]
    activites: dict[date, list[tuple[str, Optional[float], str, str]]] = {}
    for i in range(7):
        d = lundi + timedelta(days=i)
        jour = []
        for s in db.seances_entre(d.isoformat(), d.isoformat()):
            if categorie_realisee(s):
                jour.append((categorie_realisee(s), s["duree_min"], "realise", sports.sport_de(s)))
        if d.isoformat() in proposes and d >= premier:
            sources = [(x.get("type"), x.get("duree_min")) for x in proposes[d.isoformat()]]
        else:
            sources = [(p["type"], p["duree_min"]) for p in db.planifiees_entre(d.isoformat(), d.isoformat())
                       if p["seance_realisee_id"] is None and p["statut"] not in ("manque", "remplacee")]
        jour += [(categorie_planifiee(t), m, "plan", sport_planifie(t)) for t, m in sources if categorie_planifiee(t)]
        activites[d] = jour
    if all(activites[d] for d in activites):
        violations.append("Aucun jour de repos complet sur la semaine.")
    nb_muscu = sum(1 for j in activites.values() for c, _, _, _ in j if c == "force")
    if nb_muscu < 2:
        violations.append(f"{nb_muscu} séance(s) de musculation sur la semaine (minimum 2).")
    for d, j in activites.items():
        if d.weekday() >= 5:
            continue
        nom = jour_de(d)
        if any(c == "course" and (m or 0) > TYPES_COURSE_LONGUE_MAX_MIN and o == "plan" for c, m, o, _ in j):
            violations.append(f"Course de plus de 1h15 en semaine ({nom}).")
        if {"force", "course"} <= {c for c, _, _, _ in j}:
            violations.append(f"Muscu et course le même jour en semaine ({nom}).")
    violations += regle_vigilance(sum(m or 0 for j in activites.values() for c, m, _, _ in j if c == "course"), lundi)
    violations += regle_impact([(d, sid, o) for d, j in activites.items() for _, _, o, sid in j])
    return violations


def ajuster_semaine(note: Optional[str] = None) -> dict:
    d = aujourdhui()
    lundi = lundi_de(d)
    dimanche = lundi + timedelta(days=6)
    premier = _premier_jour_modifiable(d)
    if premier > dimanche:
        raise ValueError("Plus aucun jour à réajuster cette semaine.")
    du, au = lundi.isoformat(), dimanche.isoformat()
    p = db.profil()
    imp = db.imperatifs(du) or {}
    contexte = {
        "semaine_du": du,
        "premier_jour_modifiable": premier.isoformat(),
        "jours_restants": [(premier + timedelta(days=i)).isoformat() for i in range((dimanche - premier).days + 1)],
        "plan_actuel": [{**_planifiee_llm(x), "lie_a_une_seance_realisee": bool(x["seance_realisee_id"])}
                        for x in db.planifiees_entre(du, au)],
        "modifications": db.etat_semaine(du)["modifications"],
        "realise": [{**_seance_llm(s), "verdict": s.get("verdict")} for s in db.seances_entre(du, au)],
        "imperatifs": {k: imp.get(k) for k in ("squash_jours", "contraintes", "ressenti", "sommeil", "notes")},
        **({"demande_athlete": note.strip()} if note and note.strip() else {}),
    }
    erreur_precedente, analyse_id, violations = None, None, []
    for _ in range(2):                         # un seul nouvel essai, avec l'erreur en contexte
        ctx = {**contexte, **({"erreur_tentative_precedente": erreur_precedente} if erreur_precedente else {})}
        reponse, erreur, trace = _appel_llm("ajustement_semaine", lambda llm: llm.ajustement_semaine(
            contexte=ctx, profil=_profil_llm(p), statut_sante=texte_sante_llm(sante_profil(p)),
            mode=p.get("mode_actif", "BASE")))
        analyse_id = _tracer("ajustement_semaine", reponse, erreur, trace, semaine_debut=du)
        if reponse is None:
            return {"ok": False, "erreur_llm": erreur, "analyse_id": analyse_id}
        violations = valider_ajustement(reponse, lundi, premier)
        if not violations:
            return {"ok": True, "analyse_id": analyse_id, "changements": reponse.get("changements") or [],
                    "message_coach": reponse.get("message_coach"), "jours": reponse.get("jours")}
        erreur_precedente = "Règles violées, corrige-les : " + " ; ".join(violations)
    return {"ok": False, "message": MESSAGE_AJUSTEMENT_INVALIDE, "violations": violations, "analyse_id": analyse_id}


def appliquer_ajustement(analyse_id: int) -> dict:
    a = db.analyse(analyse_id)
    if not a or a["type_appel"] != "ajustement_semaine" or not isinstance(a["reponse_json"], dict):
        raise ValueError("Ajustement introuvable.")
    d = aujourdhui()
    lundi = lundi_de(d)
    if a["semaine_debut"] != lundi.isoformat():
        raise ValueError("Cet ajustement concerne une autre semaine.")
    if a["valide_par_user"]:
        raise ValueError("Ajustement déjà appliqué.")
    premier = _premier_jour_modifiable(d)
    violations = valider_ajustement(a["reponse_json"], lundi, premier)
    if violations:                             # le réalisé a pu changer depuis l'aperçu
        raise ValueError("Ajustement plus valide : " + " ; ".join(violations))
    proposes = _seances_proposees(a["reponse_json"])
    with db.connexion() as c:
        for d_iso, seances in proposes.items():
            # Les séances prévues non liées du jour sont remplacées ; les liées restent
            c.execute("DELETE FROM seances_planifiees WHERE date_seance = ? AND seance_realisee_id IS NULL", (d_iso,))
            for x in seances:
                v = valider_planifiee({"date_seance": d_iso, "creneau": x.get("creneau"), "type": x.get("type"),
                                       "duree_min": x.get("duree_min"), "distance_km": x.get("distance_km"),
                                       "intensite": x.get("intensite"), "detail": x.get("description")})
                db.inserer("seances_planifiees", {**v, "origine": "ajustement_semaine"}, conn=c)
        c.execute("UPDATE analyses_llm SET valide_par_user = 1 WHERE id = ?", (analyse_id,))
    totaux = recalculer_semaine(lundi)
    db.plan_reajuste(lundi.isoformat())
    return {"ok": True, "totaux": totaux}


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------
def historique(famille: Optional[str] = None, du: Optional[str] = None,
               au: Optional[str] = None) -> list[dict]:
    du = du or "0000-01-01"
    au = au or "9999-12-31"
    familles = extractor.FAMILLE_COURSE if famille == "course" else None
    rows = db.seances_entre(du, au, famille=None if familles else famille, familles=familles)
    return [_seance_publique(s) for s in reversed(rows)]


def detail_seance(id_: int) -> Optional[dict]:
    s = db.seance(id_)
    if not s:
        return None
    return {
        "seance": _seance_publique(s),
        "muscu_detail": db.muscu_detail(id_),
        "analyses": db.analyses_seance(id_),
        "prevu": (prevu := prevu_de(id_)),
        "substitution": substitution(s, prevu),
    }


def graphiques(nb_semaines: int = 12, d: Optional[date] = None) -> dict:
    d = d or aujourdhui()
    lundi_courant = lundi_de(d)
    semaines = []
    for i in range(nb_semaines - 1, -1, -1):
        lundi = lundi_courant - timedelta(weeks=i)
        dimanche = lundi + timedelta(days=6)
        course = db.seances_entre(lundi.isoformat(), dimanche.isoformat(), familles=extractor.FAMILLE_COURSE)
        toutes = db.seances_entre(lundi.isoformat(), dimanche.isoformat())
        a = acwr_au(min(dimanche, d))
        semaines.append({
            "lundi": lundi.isoformat(),
            "km": round(sum(s["distance_km"] or 0 for s in course), 2),
            "dplus": round(sum(s["dplus_m"] or 0 for s in course)),
            "charge": round(metrics.charge_semaine(toutes), 1),
            "acwr": a.ratio,                     # fin de semaine, None en calibrage
            "acwr_zone": a.zone,
            "jours_historique": a.jours_historique,
        })
    # Série quotidienne de l'ACWR sur 26 semaines (graphique Stats) ; ratio None les jours de calibrage
    debut = lundi_courant - timedelta(weeks=25)
    serie = [{"date": p["date"].isoformat(), "ratio": p["ratio"], "zone": p["zone"]}
             for p in metrics.serie_quotidienne(db.seances_entre("0000-01-01", d.isoformat()), d)
             if p["date"] >= debut]
    return {"semaines": semaines, "acwr_quotidien": serie, "poids": db.poids_liste()}


def charges_muscu() -> dict:
    """{exercice: [{date, kg, reps, series}]} trié par date."""
    rows = db.fetch_all(
        "SELECT m.charges, m.split, s.date_debut FROM muscu_detail m "
        "JOIN seances_realisees s ON s.id = m.seance_id ORDER BY s.date_debut"
    )
    par_exo: dict[str, list] = {}
    for r in rows:
        for c in r["charges"] or []:
            par_exo.setdefault(c["exo"].strip().lower(), []).append(
                {"date": r["date_debut"][:10], "split": r["split"], **c})
    return par_exo


# ---------------------------------------------------------------------------
# Événements (CRUD) — la reconstruction LLM est déclenchée par l'appelant
# ---------------------------------------------------------------------------
TYPES_EVENEMENT = ("trail_race", "squash_competition", "other")


def valider_evenement(e: dict) -> dict:
    if e.get("type") not in TYPES_EVENEMENT:
        raise ValueError(f"Type d'événement invalide : {e.get('type')}")
    if e.get("priorite", "B") not in ("A", "B", "C"):
        raise ValueError("Priorité invalide (A, B ou C).")
    titre = (e.get("titre") or "").strip()
    if not titre:
        raise ValueError("Titre obligatoire.")
    try:
        date.fromisoformat(e.get("date_evt") or "")
    except ValueError:
        raise ValueError("Date invalide (AAAA-MM-JJ).")
    return {
        "type": e["type"], "titre": titre, "date_evt": e["date_evt"],
        "priorite": e.get("priorite", "B"),
        "distance_km": _nombre(e.get("distance_km")), "dplus_m": _nombre(e.get("dplus_m")),
        "notes": (e.get("notes") or "").strip() or None,
    }


# ---------------------------------------------------------------------------
# Séances planifiées (édition manuelle)
# ---------------------------------------------------------------------------
CRENEAUX = ("matin", "midi", "soir", "journee")
STATUTS = ("prevu", "realise", "manque", "modifie", "decale", "remplacee")


def normaliser_creneau(c: Optional[str]) -> str:
    """Le schéma n'accepte que 4 créneaux ; tout le reste (week-end, après-midi…) → journee."""
    c = (c or "").lower().replace("é", "e").strip()
    return c if c in CRENEAUX else "journee"


def valider_planifiee(p: dict) -> dict:
    try:
        date.fromisoformat(p.get("date_seance") or "")
    except ValueError:
        raise ValueError("Date de séance invalide (AAAA-MM-JJ).")
    type_ = (p.get("type") or "").strip()
    if not type_:
        raise ValueError("Type de séance obligatoire.")
    out = {
        "date_seance": p["date_seance"],
        "creneau": normaliser_creneau(p.get("creneau")),
        "type": type_,
        "detail": (p.get("detail") or "").strip() or None,
        "intensite": (p.get("intensite") or "").strip() or None,
        "duree_min": _nombre(p.get("duree_min")),
        "distance_km": _nombre(p.get("distance_km")),
        "dplus_m": _nombre(p.get("dplus_m")),
    }
    if p.get("statut"):
        if p["statut"] not in STATUTS:
            raise ValueError("Statut invalide.")
        out["statut"] = p["statut"]
    return out


# ---------------------------------------------------------------------------
# LLM : client, appel tracé, formats de contexte
# ---------------------------------------------------------------------------
_llm = None


def client_llm():
    """Instancié à la demande : l'app fonctionne sans clé API (import, historique…)."""
    global _llm
    if _llm is None:
        import llm_client
        _llm = llm_client.CoachLLM()
    return _llm


def _appel_llm(type_appel: str, fn) -> tuple[Optional[dict], Optional[dict], dict]:
    """Exécute fn(client). Retourne (réponse, erreur, trace tokens/coût).

    Les tokens et le coût sont lus par différence sur le compteur de llm_client,
    ce qui couvre aussi les appels dont la réponse n'est pas du JSON valide."""
    import llm_client
    avant = llm_client.cout_du_mois()
    reponse, erreur = None, None
    try:
        reponse = fn(client_llm())
        if not isinstance(reponse, dict):
            raise ValueError(f"Réponse LLM inattendue (objet JSON attendu) : {str(reponse)[:500]}")
    except ValueError as e:          # JSON invalide : message + texte brut
        reponse, erreur = None, {"type": "json_invalide", "message": str(e)}
    except RuntimeError as e:        # plafond mensuel
        erreur = {"type": "plafond", "message": str(e)}
    except Exception as e:           # clé absente, réseau, API…
        erreur = {"type": type(e).__name__, "message": str(e)}
    apres = llm_client.cout_du_mois()
    meme_mois = apres.mois == avant.mois
    trace = {
        "modele": llm_client.MODELE_PAR_APPEL[type_appel],
        "tokens_in": (apres.input_tokens + apres.cache_read_tokens + apres.cache_write_tokens)
        - ((avant.input_tokens + avant.cache_read_tokens + avant.cache_write_tokens) if meme_mois else 0),
        "tokens_out": apres.output_tokens - (avant.output_tokens if meme_mois else 0),
        "cout_usd": round(apres.cout_usd - (avant.cout_usd if meme_mois else 0), 5),
    }
    return reponse, erreur, trace


def _tracer(type_appel: str, reponse: Optional[dict], erreur: Optional[dict], trace: dict,
            **liens) -> Optional[int]:
    """Enregistre l'appel dans analyses_llm (sauf s'il n'a rien coûté ni rien produit)."""
    if reponse is None and not trace["tokens_in"]:
        return None
    return db.inserer("analyses_llm", {
        "type_appel": type_appel,
        "reponse_json": reponse if reponse is not None else {"erreur": erreur},
        "modele": trace["modele"], "tokens_in": trace["tokens_in"],
        "tokens_out": trace["tokens_out"], "cout_usd": trace["cout_usd"],
        "cree_le": maintenant().isoformat(timespec="seconds"),
        **{k: v for k, v in liens.items() if v is not None},
    })


def _seance_llm(s: dict) -> dict:
    """Séance réalisée pour le LLM : sport, catégorie, impact, RPE et source explicites."""
    exclus = {"donnees_brutes", "fichier_hash", "fichier_nom", "importe_le", "sport_id", "source_id"}
    sid = sports.sport_de(s)
    return {"sport": sports.sport(sid)["libelle"] + (" (à préciser)" if s.get("sport_a_preciser") else ""),
            "categorie": sports.categorie(sid), "impact": sports.impact(sid),
            "rpe": s.get("rpe"), "source": s.get("source") or "suunto_json",
            **{k: v for k, v in s.items() if k not in exclus}}


def _planifiee_llm(p: dict) -> dict:
    return {"jour": jour_de(date.fromisoformat(p["date_seance"])), "date": p["date_seance"],
            "creneau": p["creneau"], "type": p["type"], "detail": p["detail"],
            "intensite": p["intensite"], "duree_min": p["duree_min"],
            "distance_km": p["distance_km"], "dplus_m": p["dplus_m"], "statut": p["statut"]}


def _profil_llm(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in ("id", "maj_le")}


def resume_semaines(nb: int, avant_lundi: date) -> list[dict]:
    """Synthèse hebdo des nb semaines précédant avant_lundi (plus compact que les séances brutes)."""
    out = []
    for i in range(nb, 0, -1):
        lundi = avant_lundi - timedelta(weeks=i)
        dimanche = lundi + timedelta(days=6)
        seances = db.seances_entre(lundi.isoformat(), dimanche.isoformat())
        course = [s for s in seances if s["famille"] in extractor.FAMILLE_COURSE]
        par_sport: dict[str, int] = {}
        for s in seances:
            libelle = sports.sport(sports.sport_de(s))["libelle"]
            par_sport[libelle] = par_sport.get(libelle, 0) + 1
        out.append({
            "semaine_du": lundi.isoformat(),
            "volume_course_km": round(sum(s["distance_km"] or 0 for s in course), 2),
            "d_plus_m": round(sum(s["dplus_m"] or 0 for s in course)),
            "charge": round(metrics.charge_semaine(seances), 1),
            "seances_par_sport": par_sport,
            "jours_impact_eleve": len({s["date_debut"][:10] for s in seances
                                       if sports.impact(sports.sport_de(s)) == "eleve"}),
            "distribution_zones": metrics.distribution_hebdo(course),
            "acwr": acwr_au(dimanche).ratio,
        })
    return out


# ---------------------------------------------------------------------------
# Ajustements proposés par analyse_seance
# ---------------------------------------------------------------------------
_MOTS_TYPES = [
    ("sortie longue", "sortie_longue"), ("sortie_longue", "sortie_longue"),
    ("repos", "repos"), ("intervals", "intervals"), ("fractionn", "intervals"), ("vma", "intervals"),
    ("tempo", "tempo"), ("seuil", "tempo"), ("côtes", "cotes"), ("cotes", "cotes"),
    ("squash", "squash"), ("vélo", "velo"), ("velo", "velo"),
    ("push", "muscu_push"), ("pull", "muscu_pull"), ("jambes", "muscu_jambes"),
    ("ef ", "EF"), ("endurance", "EF"), ("footing", "EF"),
]


def type_depuis_texte(texte: str) -> Optional[str]:
    t = f"{(texte or '').lower()} "
    for mot, type_ in _MOTS_TYPES:
        if mot in t:
            return type_
    return None


def _minutes(texte: str) -> Optional[int]:
    import re
    m = re.search(r"(\d+)\s*(?:min|')", texte or "")
    return int(m.group(1)) if m else None


def appliquer_ajustements(ajustements: list[dict], depuis: date) -> list[dict]:
    """Applique chaque ajustement sur la semaine de `depuis`, jours à venir uniquement."""
    lundi = lundi_de(depuis)
    plancher = max(depuis, aujourdhui())
    resultats = []
    for a in ajustements:
        jour = (a.get("jour") or "").lower().strip()
        if jour not in JOURS:
            resultats.append({**a, "applique": False, "motif": f"jour inconnu « {jour} »"})
            continue
        d = lundi + timedelta(days=JOURS.index(jour))
        if d < plancher:
            resultats.append({**a, "applique": False, "motif": "jour passé"})
            continue

        propose = a.get("seance_proposee") or ""
        candidats = [p for p in db.planifiees_entre(d.isoformat(), d.isoformat())
                     if p["statut"] in ("prevu", "modifie") and p["seance_realisee_id"] is None]
        type_initial = type_depuis_texte(a.get("seance_initiale") or "")
        cible = next((p for p in candidats if p["type"] == type_initial), None) \
            or next((p for p in candidats if p["type"] != "repos"), None) \
            or (candidats[0] if candidats else None)

        detail = f"{propose} — {a['raison']}" if a.get("raison") else propose
        nouveau_type = type_depuis_texte(propose)
        if cible:
            db.maj("seances_planifiees", cible["id"], {
                "type": nouveau_type or cible["type"],
                "detail": detail,
                "duree_min": _minutes(propose) or cible["duree_min"],
                "statut": "modifie",
                "version": cible["version"] + 1,
                "origine": "analyse_seance",
            })
            resultats.append({**a, "applique": True, "seance_planifiee_id": cible["id"]})
        else:
            id_ = db.inserer("seances_planifiees", {
                "date_seance": d.isoformat(), "creneau": "matin",
                "type": nouveau_type or "autre", "detail": detail,
                "duree_min": _minutes(propose), "statut": "modifie", "origine": "analyse_seance",
            })
            resultats.append({**a, "applique": True, "seance_planifiee_id": id_, "ajoutee": True})
    if any(r.get("applique") for r in resultats):
        recalculer_semaine(lundi)          # liaison et statuts à jour (pas une modification utilisateur)
    return resultats


def decider_ajustements(analyse_id: int, accepter: bool) -> dict:
    """Verdict rouge : l'utilisateur accepte les ajustements ou garde le plan initial."""
    a = db.analyse(analyse_id)
    if not a or a["type_appel"] != "analyse_seance":
        raise ValueError("Analyse introuvable.")
    if a["valide_par_user"]:
        raise ValueError("Décision déjà prise pour cette analyse.")
    appliques = []
    if accepter:
        s = db.seance(a["seance_id"])
        appliques = appliquer_ajustements(a["reponse_json"].get("ajustements") or [], date_de(s["date_debut"]))
    db.maj("analyses_llm", analyse_id, {"valide_par_user": 1 if accepter else -1})
    return {"accepte": accepter, "ajustements_appliques": appliques}


# ---------------------------------------------------------------------------
# Bilan hebdomadaire
# ---------------------------------------------------------------------------
TYPES_COURSE_PLAN = {"EF", "intervals", "cotes", "tempo", "sortie_longue"}
DUREE_MAX_COURSE_SEMAINE = 75


def semaine_a_planifier(d: Optional[date] = None) -> date:
    """Lundi de la semaine à planifier : demain si on est dimanche, sinon le lundi suivant."""
    d = d or aujourdhui()
    return d if d.weekday() == 0 else lundi_de(d) + timedelta(weeks=1)


# ---------------------------------------------------------------------------
# Progression en Vigilance (sans protocole kiné) : +10 % max sur la moyenne des 3 dernières semaines
# ---------------------------------------------------------------------------
PROGRESSION_VIGILANCE = 1.10


def plafond_course_vigilance(lundi: date) -> Optional[float]:
    """Minutes de course autorisées sur la semaine de `lundi`, ou None si la règle ne s'applique pas
    (pas en vigilance, protocole kiné renseigné — il prime —, ou aucun historique de course)."""
    sante = sante_profil()
    if sante["niveau"] != "vigilance" or sante.get("protocole"):
        return None
    minutes = [sum(s["duree_min"] or 0 for s in db.seances_entre(
        (lundi - timedelta(weeks=k)).isoformat(), (lundi - timedelta(weeks=k) + timedelta(days=6)).isoformat(),
        familles=extractor.FAMILLE_COURSE)) for k in (1, 2, 3)]
    moyenne = sum(minutes) / 3
    return round(moyenne * PROGRESSION_VIGILANCE) if moyenne > 0 else None


def regle_vigilance(minutes_course: float, lundi: date) -> list[str]:
    plafond = plafond_course_vigilance(lundi)
    if plafond is not None and minutes_course > plafond:
        return [f"Vigilance sans protocole : {minutes_course:.0f} min de course prévues, plafond {plafond:.0f} min "
                f"(+10 % sur la moyenne des 3 dernières semaines)."]
    return []


def regle_impact(seances: list[tuple[date, Optional[str], str]], sante: Optional[dict] = None) -> list[str]:
    """Vigilance ou Blessure sur le bas du corps : toute séance à impact élevé (course, raquette,
    sport collectif…) est un jour de charge tendineuse, jamais deux jours consécutifs.
    En Blessure, aucune séance prévue à impact élevé. seances : [(jour, sport_id, 'plan' | 'realise')]."""
    sante = sante or sante_profil()
    zones = set(sante.get("zones") or []) & metrics.ZONES_BAS_DU_CORPS
    if sante["niveau"] not in ("vigilance", "blessure") or not zones:
        return []
    libelle_sante = f"{NIVEAUX_SANTE_LIBELLES[sante['niveau']]} {', '.join(sorted(zones))}"
    par_jour: dict[date, list[str]] = {}
    for d, sid, origine in seances:
        if sid and sports.impact(sid) == "eleve":
            par_jour.setdefault(d, []).append(sports.sport(sid)["libelle"].lower())
            if sante["niveau"] == "blessure" and origine == "plan":
                return [f"{libelle_sante} : {sports.sport(sid)['libelle'].lower()} prévu le {jour_de(d)} "
                        f"(impact élevé interdit en blessure du bas du corps)."]
    jours = sorted(par_jour)
    return [f"{libelle_sante} : impact élevé deux jours de suite ({' + '.join(par_jour[a])} {jour_de(a)}, "
            f"{' + '.join(par_jour[b])} {jour_de(b)})."
            for a, b in zip(jours, jours[1:]) if (b - a).days == 1]


NIVEAUX_SANTE_LIBELLES = {"vigilance": "Vigilance", "blessure": "Blessure"}


def verifier_regles(seances: list[dict], jour_repos: Optional[str] = None, lundi: Optional[date] = None) -> dict:
    """Double sécurité côté code sur la semaine générée.
    Retourne {'bloquantes': [...], 'avertissements': [...]}."""
    bloquantes, avert = [], []
    actives = [s for s in seances if (s.get("type") or "").lower() != "repos"]

    for s in seances:
        if (s.get("jour") or "").lower() not in JOURS:
            bloquantes.append(f"Jour invalide : « {s.get('jour')} ».")
    jours_charges = {(s.get("jour") or "").lower() for s in actives}

    # 1. Repos complet
    if len(jours_charges & set(JOURS)) >= 7:
        bloquantes.append("Aucun jour de repos complet : 7 jours de charge.")
    if jour_repos and jour_repos.lower() in jours_charges:
        bloquantes.append(f"Le jour de repos annoncé ({jour_repos}) contient une séance.")

    # 2. Au moins 2 muscu haut du corps
    muscu_haut = [s for s in actives if s["type"].startswith("muscu") and s["type"] != "muscu_jambes"]
    if len(muscu_haut) < 2:
        bloquantes.append(f"{len(muscu_haut)} séance(s) de musculation haut du corps (minimum 2).")

    for s in actives:
        jour = (s.get("jour") or "").lower()
        semaine = jour in JOURS[:5]
        # 3. Pas de sortie longue ni de course > 1h15 en semaine
        if semaine and s["type"] == "sortie_longue":
            bloquantes.append(f"Sortie longue placée en semaine ({jour}).")
        elif semaine and s["type"] in TYPES_COURSE_PLAN and (s.get("duree_min") or 0) > DUREE_MAX_COURSE_SEMAINE:
            bloquantes.append(f"Course de {s['duree_min']} min en semaine ({jour}) : > 1h15 réservé au week-end.")
        # Créneaux structurels
        if semaine and s["type"] in TYPES_COURSE_PLAN and s.get("creneau") != "matin":
            avert.append(f"Course en semaine hors créneau du matin ({jour} {s.get('creneau')}).")
        if s["type"].startswith("muscu") and s.get("creneau") not in ("matin", None):
            avert.append(f"Musculation hors créneau du matin ({jour} {s.get('creneau')}).")

    # PUSH le matin + squash le soir : interdit
    for jour in JOURS:
        du_jour = [s for s in actives if (s.get("jour") or "").lower() == jour]
        if any(s["type"] == "muscu_push" for s in du_jour) and any(s["type"] == "squash" for s in du_jour):
            bloquantes.append(f"Muscu PUSH et squash le même jour ({jour}).")

    if lundi is not None:
        course = sum(s.get("duree_min") or 0 for s in actives if categorie_planifiee(s.get("type")) == "course")
        bloquantes += regle_vigilance(course, lundi)
        # Impact élevé : jours prévus + la veille du lundi (séances réalisées)
        veille = lundi - timedelta(days=1)
        impact = [(veille, sports.sport_de(x), "realise")
                  for x in db.seances_entre(veille.isoformat(), veille.isoformat()) if categorie_realisee(x)]
        impact += [(lundi + timedelta(days=JOURS.index((x.get("jour") or "").lower())), sport_planifie(x.get("type")), "plan")
                   for x in actives if (x.get("jour") or "").lower() in JOURS]
        bloquantes += regle_impact(impact)
    return {"bloquantes": bloquantes, "avertissements": avert}


def enregistrer_imperatifs(imperatifs: dict) -> tuple[date, dict]:
    """Valide et enregistre les impératifs de la semaine et le statut santé. Retourne (lundi, santé)."""
    lundi = lundi_de(date.fromisoformat(imperatifs.get("semaine_debut") or semaine_a_planifier().isoformat()))
    if isinstance(imperatifs.get("sante"), dict):
        nouvelle_sante = imperatifs["sante"]
    else:                                          # ancien format « vigilance:<zone> »
        statut = (imperatifs.get("statut_sante") or "100%").strip()
        if not (statut == "100%" or statut.startswith(("vigilance:", "blessure:"))):
            raise ValueError("Statut santé invalide : '100%', 'vigilance:<zone>' ou 'blessure:<zone>'.")
        niveau, _, note = statut.partition(":")
        nouvelle_sante = {"niveau": "100" if statut == "100%" else niveau,
                          "zones": db.zones_depuis_texte(note), "note": note or None}
    for k in ("ressenti", "sommeil"):
        v = imperatifs.get(k)
        if v not in (None, "") and not 1 <= int(v) <= 10:
            raise ValueError(f"{k} doit être entre 1 et 10.")
    db.sauver_imperatifs(lundi.isoformat(), {
        "squash_jours": imperatifs.get("squash") or [],
        "contraintes": imperatifs.get("contraintes") or [],
        "ressenti": int(imperatifs["ressenti"]) if imperatifs.get("ressenti") else None,
        "sommeil": int(imperatifs["sommeil"]) if imperatifs.get("sommeil") else None,
        "notes": (imperatifs.get("notes") or "").strip() or None,
    })
    return lundi, enregistrer_sante(nouvelle_sante)


def bilan_hebdo(imperatifs: dict) -> dict:
    # 1. Impératifs
    lundi, sante = enregistrer_imperatifs(imperatifs)
    lundi_prec = lundi - timedelta(weeks=1)
    dimanche_prec = lundi - timedelta(days=1)
    statut = texte_sante_llm(sante)

    # 2. Chargement
    marquer_manquees(aujourdhui())
    ecoulee = db.seances_entre(lundi_prec.isoformat(), dimanche_prec.isoformat())
    plan = db.planifiees_entre(lundi_prec.isoformat(), dimanche_prec.isoformat())
    evenements = db.evenements(depuis=lundi.isoformat())
    phase = phase_active(lundi)
    p = db.profil()

    # 3. Indicateurs
    course = [s for s in ecoulee if s["famille"] in extractor.FAMILLE_COURSE]
    indicateurs = {
        # Absent pendant le calibrage : le LLM ne reçoit jamais un ratio non fiable
        **({} if (a := acwr_au(min(dimanche_prec, aujourdhui()))).zone == "calibrage" else {"acwr": acwr_dict(a)}),
        "distribution_hebdo": metrics.distribution_hebdo(course),
        "volume_course_km": round(sum(s["distance_km"] or 0 for s in course), 2),
        "d_plus_m": round(sum(s["dplus_m"] or 0 for s in course)),
        "charge_semaine": round(metrics.charge_semaine(ecoulee), 1),
        "seances_manquees": [_planifiee_llm(x) for x in plan if x["statut"] == "manque"],
        # Le plan transmis est le plan tel que modifié ; voici ce qui a changé
        "modifications_du_plan": db.etat_semaine(lundi_prec.isoformat())["modifications"],
    }
    imperatifs_llm = {
        "semaine_du": lundi.isoformat(),
        "squash": imperatifs.get("squash") or [],
        "contraintes": imperatifs.get("contraintes") or [],
        "ressenti": imperatifs.get("ressenti"), "sommeil": imperatifs.get("sommeil"),
        "notes": imperatifs.get("notes"),
    }

    # 4-5. LLM + trace ; en vigilance sans protocole, un nouvel essai si le volume de course dépasse +10 %
    historique = resume_semaines(4, lundi_prec)
    cout_total = 0.0
    for essai in range(2):
        reponse, erreur, trace = _appel_llm("bilan_hebdo", lambda llm: llm.bilan_hebdo(
            semaine_ecoulee=[_seance_llm(s) for s in ecoulee],
            plan_prevu=[_planifiee_llm(x) for x in plan],
            imperatifs=imperatifs_llm,
            historique_4sem=historique,
            evenements=evenements, indicateurs=indicateurs, profil=_profil_llm(p),
            statut_sante=statut, mode=p.get("mode_actif", "BASE"), phase_prepa=phase,
            bilan_semaine=bilan_semaine(lundi_prec)))
        analyse_id = _tracer("bilan_hebdo", reponse, erreur, trace, semaine_debut=lundi.isoformat())
        cout_total += trace["cout_usd"]
        if reponse is None:
            break
        prevues = (reponse.get("semaine_suivante") or {}).get("seances") or []
        exces = regle_vigilance(sum(s.get("duree_min") or 0 for s in prevues if isinstance(s, dict)
                                    and categorie_planifiee(s.get("type")) == "course"), lundi)
        if not exces or essai == 1:
            break
        imperatifs_llm = {**imperatifs_llm, "erreur_tentative_precedente": "Règle violée, corrige-la : " + exces[0]}

    # Phase de prépa : code fermé, le texte libre passe dans « detail »
    if reponse is not None and isinstance(reponse.get("position_prepa"), dict):
        reponse["position_prepa"] = normaliser_position_prepa(reponse["position_prepa"])

    # Double sécurité : règles dures
    regles = None
    if reponse is not None:
        sem = reponse.get("semaine_suivante") or {}
        regles = verifier_regles(sem.get("seances") or [], sem.get("jour_repos"), lundi)

    return {"analyse_id": analyse_id, "semaine_debut": lundi.isoformat(), "indicateurs": indicateurs,
            "reponse": reponse, "erreur_llm": erreur, "regles": regles, "cout": round(cout_total, 5)}


PHASES_PREPA = ("BASE", "BUILD", "PIC", "AFFUTAGE", "LIBRE")
_MOTS_PHASE = [("affût", "AFFUTAGE"), ("affut", "AFFUTAGE"), ("taper", "AFFUTAGE"), ("pic", "PIC"), ("peak", "PIC"),
               ("build", "BUILD"), ("construction", "BUILD"), ("spécifique", "BUILD"), ("specifique", "BUILD"),
               ("base", "BASE"), ("reprise", "BASE"), ("foncier", "BASE"), ("libre", "LIBRE")]


def normaliser_position_prepa(pp: dict) -> dict:
    """phase ∈ BASE | BUILD | PIC | AFFUTAGE | LIBRE ; sinon correspondance par mot-clé (ou LIBRE)
    et texte d'origine déplacé dans « detail »."""
    brut = str(pp.get("phase") or "").strip()
    if brut.upper() in PHASES_PREPA:
        return {**pp, "phase": brut.upper()}
    code = next((c for mot, c in _MOTS_PHASE if mot in brut.lower()), "LIBRE")
    detail = " — ".join(x for x in (brut, pp.get("detail")) if x) or None
    return {**pp, "phase": code, "detail": detail}


def valider_semaine(analyse_id: int, seances: Optional[list[dict]] = None) -> dict:
    """Écrit la semaine (éventuellement éditée) dans seances_planifiees, si les règles dures passent."""
    a = db.analyse(analyse_id)
    if not a or a["type_appel"] != "bilan_hebdo" or "semaine_suivante" not in a["reponse_json"]:
        raise ValueError("Bilan introuvable.")
    sem = a["reponse_json"]["semaine_suivante"]
    seances = seances if seances is not None else sem.get("seances") or []
    regles = verifier_regles(seances, sem.get("jour_repos"), date.fromisoformat(a["semaine_debut"]))
    if regles["bloquantes"]:
        raise ValueError("Validation refusée, règles dures violées : " + " ; ".join(regles["bloquantes"]))

    lundi = date.fromisoformat(a["semaine_debut"])
    dimanche = lundi + timedelta(days=6)
    lignes = []
    for s in seances:
        d = lundi + timedelta(days=JOURS.index(s["jour"].lower()))
        lignes.append({**valider_planifiee({**s, "date_seance": d.isoformat(), "statut": None}),
                       "origine": "bilan_hebdo", "cree_le": maintenant().isoformat(timespec="seconds")})
    jour_repos = (sem.get("jour_repos") or "").lower()
    if jour_repos in JOURS and not any(l["type"] == "repos" for l in lignes):
        lignes.append({"date_seance": (lundi + timedelta(days=JOURS.index(jour_repos))).isoformat(),
                       "creneau": "journee", "type": "repos", "origine": "bilan_hebdo"})

    with db.connexion() as c:
        # Remplace le plan non réalisé de la semaine ; les séances déjà liées restent
        c.execute("DELETE FROM seances_planifiees WHERE date_seance BETWEEN ? AND ? "
                  "AND seance_realisee_id IS NULL AND statut IN ('prevu', 'modifie', 'manque')",
                  (lundi.isoformat(), dimanche.isoformat()))
        for l in lignes:
            db.inserer("seances_planifiees", l, conn=c)
        c.execute("UPDATE analyses_llm SET valide_par_user = 1 WHERE id = ?", (analyse_id,))
    recalculer_semaine(lundi)
    return {"semaine_debut": lundi.isoformat(), "nb_seances": len(lignes),
            "avertissements": regles["avertissements"]}


# ---------------------------------------------------------------------------
# Reconstruction après modification des événements
# ---------------------------------------------------------------------------
PHASES = ("BASE", "BUILD", "PIC", "AFFUTAGE")


def reconstruire(evenement_id: Optional[int] = None) -> dict:
    d = aujourdhui()
    evenements = db.evenements(depuis=d.isoformat())
    plan_actuel = db.plan_prepa()
    p = db.profil()

    reponse, erreur, trace = _appel_llm("reconstruction_evenements", lambda llm: llm.reconstruction_evenements(
        evenements=evenements, historique=resume_semaines(8, lundi_de(d) + timedelta(weeks=1)),
        plan_actuel={"phases": plan_actuel} if plan_actuel else None, profil=_profil_llm(p),
        statut_sante=texte_sante_llm(sante_profil(p)), mode=p.get("mode_actif", "BASE")))
    lien = evenement_id if evenement_id and db.evenement(evenement_id) else None
    analyse_id = _tracer("reconstruction_evenements", reponse, erreur, trace, evenement_id=lien)

    bascule = None
    if reponse is not None:
        phases = []
        courses_a = [e for e in evenements if e["type"] == "trail_race" and e["priorite"] == "A"]
        for ph in reponse.get("plan_macro") or []:
            try:
                du, au = date.fromisoformat(ph["du"]), date.fromisoformat(ph["au"])
            except (KeyError, TypeError, ValueError):
                continue
            if ph.get("phase") not in PHASES or au < du:
                continue
            cible = next((e for e in courses_a if e["date_evt"] >= du.isoformat()), None)
            phases.append({"evenement_id": cible["id"] if cible else None, "phase": ph["phase"],
                           "du": du.isoformat(), "au": au.isoformat(), "objectif": ph.get("objectif"),
                           "sortie_longue_cible": ph.get("sortie_longue_cible"),
                           "genere_le": maintenant().isoformat(timespec="seconds")})
        if phases or not reponse.get("plan_macro"):
            db.remplacer_plan_prepa(phases)
        mode = reponse.get("mode_recommande")
        if mode in ("BASE", "RACE_PREP") and mode != p.get("mode_actif"):
            bascule = {"de": p.get("mode_actif"), "vers": mode, "le": reponse.get("bascule_le")}

    return {"analyse_id": analyse_id, "reponse": reponse, "erreur_llm": erreur,
            "plan_prepa": db.plan_prepa(), "bascule_proposee": bascule}


# ---------------------------------------------------------------------------
# Tâches IA (backend/taches.py) : chaque appel LLM tourne en tâche de fond
# ---------------------------------------------------------------------------
FONCTIONS_TACHES = {
    "analyse_seance": lambda p: analyser_seance(p["seance_id"], True, bool(p.get("confirme"))),
    "bilan_hebdo": lambda p: bilan_hebdo(p["imperatifs"]),
    "ajustement_semaine": lambda p: ajuster_semaine(p.get("note")),
    "reconstruction_evenements": lambda p: reconstruire(p.get("evenement_id")),
}


def lancer_analyse(seance_id: int, confirme: bool = False) -> dict:
    s = _seance_ou_erreur(seance_id)
    if s["sport_a_preciser"]:
        raise ValueError("Précise d'abord le sport de la séance.")
    return taches.lancer("analyse_seance", f"analyse_seance:{seance_id}",
                         {"seance_id": seance_id, "confirme": confirme}, FONCTIONS_TACHES["analyse_seance"])


def lancer_bilan(imperatifs: dict) -> dict:
    """Saisie validée et enregistrée tout de suite (erreur immédiate si invalide), LLM en tâche de fond."""
    lundi, _ = enregistrer_imperatifs(imperatifs)
    return taches.lancer("bilan_hebdo", f"bilan_hebdo:{lundi.isoformat()}",
                         {"imperatifs": {**imperatifs, "semaine_debut": lundi.isoformat()}},
                         FONCTIONS_TACHES["bilan_hebdo"])


def lancer_ajustement(note: Optional[str] = None) -> dict:
    d = aujourdhui()
    lundi = lundi_de(d)
    if _premier_jour_modifiable(d) > lundi + timedelta(days=6):
        raise ValueError("Plus aucun jour à réajuster cette semaine.")
    return taches.lancer("ajustement_semaine", f"ajustement_semaine:{lundi.isoformat()}", {"note": note},
                         FONCTIONS_TACHES["ajustement_semaine"])


def lancer_reconstruction(evenement_id: Optional[int] = None) -> dict:
    # Une reconstruction en cours a lu les événements avant ce changement : elle sera rejouée
    return taches.lancer("reconstruction_evenements", "reconstruction_evenements", {"evenement_id": evenement_id},
                         FONCTIONS_TACHES["reconstruction_evenements"], rejouer_si_en_cours=True)


def relancer_tache(id_: str) -> dict:
    t = taches.lire(id_)
    if not t:
        raise ValueError("Tâche introuvable.")
    return taches.relancer(id_, FONCTIONS_TACHES[t["type"]])

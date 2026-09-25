"""
Orchestration : import de séance, bilan hebdomadaire, reconstruction des événements.

Les calculs sont faits par `metrics`, l'extraction par `extractor`, le
raisonnement par `llm_client`. Ce module ne fait qu'assembler et persister.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import db
import extractor
import metrics

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


def creneau_de(dt: datetime) -> str:
    if dt.hour < 11:
        return "matin"
    if dt.hour < 15:
        return "midi"
    return "soir"


# ---------------------------------------------------------------------------
# Familles
# ---------------------------------------------------------------------------
def famille_generale(famille: str) -> str:
    """course_outdoor / course_tapis → course."""
    return "course" if famille in extractor.FAMILLE_COURSE else famille


def famille_du_type_planifie(type_: str) -> str:
    t = (type_ or "").lower()
    if t.startswith("muscu"):
        return "muscu"
    if t in ("squash", "velo", "repos"):
        return t
    return "course"


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
    return hashlib.sha256(fichier_bytes).hexdigest()


def _extraire(fichier_bytes: bytes, famille: Optional[str] = None,
              sous_type: Optional[str] = None) -> tuple[extractor.SeanceExtraite, bool]:
    """Extraction + corrections utilisateur. Retourne (séance, sous_type_confirme)."""
    try:
        data = json.loads(fichier_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ErreurImport(f"Fichier JSON invalide : {e}") from e
    if not isinstance(data, dict) or "DeviceLog" not in data:
        raise ErreurImport("Format inattendu : clé 'DeviceLog' absente (export Suunto attendu).")

    # Types d'activité ajoutés depuis l'UI (table activity_types)
    extractor.ACTIVITY_TYPE_MAP.update(db.activity_types())
    try:
        s = extractor.extraire(data)
    except (KeyError, TypeError, ValueError) as e:
        raise ErreurImport(f"Extraction impossible : {e}") from e
    if not s.date_debut:
        raise ErreurImport("Date de début absente du fichier.")

    if famille and famille != s.famille:
        if famille not in FAMILLES:
            raise ErreurImport(f"Famille inconnue : {famille}")
        s.famille = famille
        s.sous_type, s.confiance = (None, None)
        if famille in extractor.FAMILLE_COURSE:
            s.sous_type, s.confiance = extractor.classify_course(s)

    confirme = False
    if sous_type and s.famille in extractor.FAMILLE_COURSE:
        if sous_type not in SOUS_TYPES_COURSE:
            raise ErreurImport(f"Sous-type inconnu : {sous_type}")
        confirme = True
        s.sous_type = sous_type
    return s, confirme


def apercu_import(fichier_bytes: bytes, nom: str) -> dict:
    """Extraction sans écriture, pour la carte résumé et les questions à poser."""
    h = hash_fichier(fichier_bytes)
    existant = db.seance_par_hash(h)
    if existant:
        return {"nom": nom, "hash": h, "doublon": True, "seance_id": existant["id"],
                "message": f"Déjà importé le {existant['importe_le'][:10]} (séance #{existant['id']})."}

    s, _ = _extraire(fichier_bytes)
    d = s.to_dict()
    return {
        "nom": nom,
        "hash": h,
        "doublon": False,
        "seance": d,
        "charge": round(metrics.charge_seance(d), 1),
        "demander_famille": s.famille == "inconnu",
        "demander_sous_type": s.famille in extractor.FAMILLE_COURSE and (s.confiance or 0) < SEUIL_CONFIANCE,
        "split_propose": split_propose() if s.famille == "muscu" else None,
        "familles": FAMILLES,
        "sous_types": SOUS_TYPES_COURSE,
        "groupes_muscu": GROUPES_MUSCU,
        "splits_muscu": SPLITS_MUSCU,
    }


def _ligne_seance(s: extractor.SeanceExtraite, h: str, nom: str, confirme: bool) -> dict:
    d = s.to_dict()
    return {
        "fichier_hash": h,
        "fichier_nom": nom,
        "activity_type_code": s.activity_type_code,
        "famille": s.famille,
        "sous_type": s.sous_type,
        "sous_type_confiance": s.confiance,
        "sous_type_confirme": int(confirme),
        "date_debut": en_paris(s.date_debut).isoformat(timespec="seconds"),
        "duree_min": s.duree_min,
        "distance_km": s.distance_km,
        "dplus_m": s.d_plus_m,
        "dmoins_m": s.d_moins_m,
        "vitesse_moy_kmh": s.vitesse_moy_kmh,
        "fc_moy": s.fc_moy_bpm,
        "fc_max": s.fc_max_bpm,
        "temps_zones_s": s.temps_zones_s,
        "temps_zones_pct": s.temps_zones_pct,
        "epoc": s.epoc,
        "recovery_time_h": s.recovery_time_h,
        "peak_training_effect": s.peak_training_effect,
        "vo2max": s.vo2max,
        "energie_kcal": s.energie_kcal,
        "feeling": s.feeling,
        "a_gps": int(s.a_gps),
        "a_fc": int(s.a_fc),
        "charge": round(metrics.charge_seance(d), 1),
        "donnees_brutes": d,
        "importe_le": maintenant().isoformat(timespec="seconds"),
    }


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
def _trouver_prevu(seance: dict) -> Optional[dict]:
    """Séance planifiée du même jour et de la même famille, non encore réalisée."""
    debut = en_paris(seance["date_debut"])
    jour = debut.date().isoformat()
    fam = famille_generale(seance["famille"])
    candidats = [
        p for p in db.planifiees_entre(jour, jour)
        if p["seance_realisee_id"] is None
        and p["statut"] in ("prevu", "modifie")
        and famille_du_type_planifie(p["type"]) == fam
    ]
    if not candidats:
        return None
    creneau = creneau_de(debut)
    candidats.sort(key=lambda p: p["creneau"] != creneau)
    return candidats[0]


def _datetime_planifiee(p: dict) -> datetime:
    d = date.fromisoformat(p["date_seance"])
    return datetime(d.year, d.month, d.day, HEURE_CRENEAU.get(p["creneau"], 9), tzinfo=TZ)


def _prochaine_qualite_dans_h(seance: dict) -> Optional[float]:
    fin = en_paris(seance["date_debut"]) + timedelta(minutes=seance["duree_min"] or 0)
    for p in db.planifiees_entre(fin.date().isoformat(), (fin.date() + timedelta(days=7)).isoformat()):
        if p["type"] in TYPES_QUALITE and p["statut"] in ("prevu", "modifie"):
            dt = _datetime_planifiee(p)
            if dt > fin:
                return round((dt - fin).total_seconds() / 3600, 1)
    return None


def acwr_au(d: date) -> metrics.ACWR:
    seances = db.seances_entre((d - timedelta(days=34)).isoformat(), d.isoformat())
    return metrics.calculer_acwr(seances, date_ref=d)


def distribution_semaine(lundi: date) -> dict:
    course = db.seances_entre(lundi.isoformat(), (lundi + timedelta(days=6)).isoformat(),
                              familles=extractor.FAMILLE_COURSE)
    return metrics.distribution_hebdo(course)


def acwr_dict(a: metrics.ACWR) -> dict:
    return {"ratio": a.ratio, "zone": a.zone, "verdict": a.verdict,
            "charge_aigue": round(a.charge_aigue, 1), "charge_chronique": round(a.charge_chronique, 1)}


# ---------------------------------------------------------------------------
# Import : pipeline complet
# ---------------------------------------------------------------------------
def importer_et_analyser(fichier_bytes: bytes, nom: str, muscu_detail: Optional[dict] = None,
                         famille: Optional[str] = None, sous_type: Optional[str] = None) -> dict:
    # 1. Hash, anti-doublon
    h = hash_fichier(fichier_bytes)
    existant = db.seance_par_hash(h)
    if existant:
        return {"doublon": True, "seance_id": existant["id"],
                "message": f"Fichier déjà importé (séance #{existant['id']})."}

    # 2. Extraction → seances_realisees
    s, confirme = _extraire(fichier_bytes, famille, sous_type)
    if s.famille == "inconnu":
        raise ErreurImport(f"Type d'activité {s.activity_type_code} inconnu : préciser la famille.")
    if famille:
        db.enregistrer_activity_type(s.activity_type_code, s.famille)

    ligne = _ligne_seance(s, h, nom, confirme)
    try:
        with db.connexion() as c:
            seance_id = db.inserer("seances_realisees", ligne, conn=c)
            # 3. Détail muscu
            if s.famille == "muscu" and muscu_detail:
                db.inserer("muscu_detail", {"seance_id": seance_id, **_valider_muscu(muscu_detail)}, conn=c)
    except sqlite3.IntegrityError:
        existant = db.seance_par_hash(h)
        return {"doublon": True, "seance_id": existant["id"] if existant else None,
                "message": "Fichier déjà importé."}
    seance = db.seance(seance_id)

    # 4. Séance prévue
    prevu = _trouver_prevu(seance)
    prevu_eval = {"type": prevu["type"], "distance_km": prevu["distance_km"],
                  "duree_min": prevu["duree_min"]} if prevu else None

    # 5-7. Indicateurs et verdict déterministe
    d = date_de(seance["date_debut"])
    acwr = acwr_au(d)
    prochaine_h = _prochaine_qualite_dans_h(seance)
    verdict, signaux = metrics.evaluer_seance(seance, prevu_eval, acwr, prochaine_h)
    indicateurs = {
        "acwr": acwr_dict(acwr),
        "signaux": [asdict(x) for x in signaux],
        "distribution_semaine": distribution_semaine(lundi_de(d)),
        "prochaine_qualite_dans_h": prochaine_h,
    }

    # 10. Lier le prévu
    if prevu:
        db.maj("seances_planifiees", prevu["id"], {"statut": "realise", "seance_realisee_id": seance_id})

    return {
        "doublon": False,
        "seance": _seance_publique(seance),
        "prevu": prevu,
        "verdict": verdict,
        "indicateurs": indicateurs,
        "analyse_llm": None,
        "ajustements": [],
        "validation_requise": False,
    }


def _seance_publique(s: dict) -> dict:
    """Séance sans le JSON brut (volumineux et redondant)."""
    return {k: v for k, v in s.items() if k != "donnees_brutes"}


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
    plan = db.planifiees_entre(lundi.isoformat(), dimanche.isoformat())
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
    }


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
        "prevu": db.fetch_one("SELECT * FROM seances_planifiees WHERE seance_realisee_id = ?", (id_,)),
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
            "km": round(sum(s["distance_km"] or 0 for s in course), 1),
            "dplus": round(sum(s["dplus_m"] or 0 for s in course)),
            "charge": round(metrics.charge_semaine(toutes), 1),
            "acwr": a.ratio,
        })
    return {"semaines": semaines, "poids": db.poids_liste()}


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
STATUTS = ("prevu", "realise", "manque", "modifie")


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

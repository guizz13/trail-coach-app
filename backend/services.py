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
                         famille: Optional[str] = None, sous_type: Optional[str] = None,
                         analyser: bool = True) -> dict:
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

    # 8-9. Analyse LLM, tracée dans analyses_llm
    reponse, erreur, analyse_id = None, None, None
    if analyser:
        lundi = lundi_de(d)
        reste = [_planifiee_llm(p) for p in db.planifiees_entre(d.isoformat(), (lundi + timedelta(days=6)).isoformat())]
        seance_llm = _seance_llm(seance)
        if s.famille == "muscu":
            seance_llm["muscu_detail"] = db.muscu_detail(seance_id)
        p = db.profil()
        reponse, erreur, trace = _appel_llm(
            "analyse_seance", lambda llm: llm.analyse_seance(
                seance=seance_llm, prevu=prevu and _planifiee_llm(prevu), semaine=reste,
                indicateurs={**indicateurs, "verdict_calcule": verdict},
                profil=_profil_llm(p), statut_sante=p.get("statut_sante", "100%"), mode=p.get("mode_actif", "BASE")))
        if reponse is not None:
            verdict = _plus_severe(verdict, reponse.get("verdict"))
        analyse_id = _tracer("analyse_seance", reponse, erreur, trace, verdict=verdict, seance_id=seance_id)

    # 10. Lier le prévu
    if prevu:
        db.maj("seances_planifiees", prevu["id"], {"statut": "realise", "seance_realisee_id": seance_id})

    # Niveau 3 de classification : le LLM tranche un sous-type incertain
    if reponse and s.famille in extractor.FAMILLE_COURSE and not confirme \
            and (s.confiance or 0) < SEUIL_CONFIANCE and reponse.get("type_detecte") in SOUS_TYPES_COURSE:
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
        "prevu": prevu,
        "verdict": verdict,
        "indicateurs": indicateurs,
        "analyse_id": analyse_id,
        "analyse_llm": reponse,
        "erreur_llm": erreur,
        "ajustements": ajustements,
        "ajustements_appliques": appliques,
        "validation_requise": validation_requise,
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
            "km": round(sum(s["distance_km"] or 0 for s in course), 2),
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


# ---------------------------------------------------------------------------
# LLM : client, appel tracé, formats de contexte
# ---------------------------------------------------------------------------
_llm = None
ORDRE_VERDICT = {"vert": 0, "orange": 1, "rouge": 2}


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


def _plus_severe(a: str, b: Optional[str]) -> str:
    return b if b in ORDRE_VERDICT and ORDRE_VERDICT[b] > ORDRE_VERDICT.get(a, 0) else a


def _seance_llm(s: dict) -> dict:
    exclus = {"donnees_brutes", "fichier_hash", "fichier_nom", "importe_le"}
    return {k: v for k, v in s.items() if k not in exclus}


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
        par_famille: dict[str, int] = {}
        for s in seances:
            par_famille[s["famille"]] = par_famille.get(s["famille"], 0) + 1
        out.append({
            "semaine_du": lundi.isoformat(),
            "volume_course_km": round(sum(s["distance_km"] or 0 for s in course), 2),
            "d_plus_m": round(sum(s["dplus_m"] or 0 for s in course)),
            "charge": round(metrics.charge_semaine(seances), 1),
            "seances_par_famille": par_famille,
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


def verifier_regles(seances: list[dict], jour_repos: Optional[str] = None) -> dict:
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

    return {"bloquantes": bloquantes, "avertissements": avert}


def bilan_hebdo(imperatifs: dict) -> dict:
    lundi = date.fromisoformat(imperatifs.get("semaine_debut") or semaine_a_planifier().isoformat())
    lundi = lundi_de(lundi)
    lundi_prec = lundi - timedelta(weeks=1)
    dimanche_prec = lundi - timedelta(days=1)

    # 1. Impératifs
    statut = (imperatifs.get("statut_sante") or "100%").strip()
    if not (statut == "100%" or statut.startswith(("vigilance:", "blessure:"))):
        raise ValueError("Statut santé invalide : '100%', 'vigilance:<zone>' ou 'blessure:<zone>'.")
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
    db.maj_profil(statut_sante=statut)

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
        "acwr": acwr_dict(acwr_au(min(dimanche_prec, aujourdhui()))),
        "distribution_hebdo": metrics.distribution_hebdo(course),
        "volume_course_km": round(sum(s["distance_km"] or 0 for s in course), 2),
        "d_plus_m": round(sum(s["dplus_m"] or 0 for s in course)),
        "charge_semaine": round(metrics.charge_semaine(ecoulee), 1),
        "seances_manquees": [_planifiee_llm(x) for x in plan if x["statut"] == "manque"],
    }
    imperatifs_llm = {
        "semaine_du": lundi.isoformat(),
        "squash": imperatifs.get("squash") or [],
        "contraintes": imperatifs.get("contraintes") or [],
        "ressenti": imperatifs.get("ressenti"), "sommeil": imperatifs.get("sommeil"),
        "notes": imperatifs.get("notes"),
    }

    # 4-5. LLM + trace
    reponse, erreur, trace = _appel_llm("bilan_hebdo", lambda llm: llm.bilan_hebdo(
        semaine_ecoulee=[_seance_llm(s) for s in ecoulee],
        plan_prevu=[_planifiee_llm(x) for x in plan],
        imperatifs=imperatifs_llm,
        historique_4sem=resume_semaines(4, lundi_prec),
        evenements=evenements, indicateurs=indicateurs, profil=_profil_llm(p),
        statut_sante=statut, mode=p.get("mode_actif", "BASE"), phase_prepa=phase))
    analyse_id = _tracer("bilan_hebdo", reponse, erreur, trace, semaine_debut=lundi.isoformat())

    # Double sécurité : règles dures
    regles = None
    if reponse is not None:
        sem = reponse.get("semaine_suivante") or {}
        regles = verifier_regles(sem.get("seances") or [], sem.get("jour_repos"))

    return {"analyse_id": analyse_id, "semaine_debut": lundi.isoformat(), "indicateurs": indicateurs,
            "reponse": reponse, "erreur_llm": erreur, "regles": regles, "cout": trace["cout_usd"]}


def valider_semaine(analyse_id: int, seances: Optional[list[dict]] = None) -> dict:
    """Écrit la semaine (éventuellement éditée) dans seances_planifiees, si les règles dures passent."""
    a = db.analyse(analyse_id)
    if not a or a["type_appel"] != "bilan_hebdo" or "semaine_suivante" not in a["reponse_json"]:
        raise ValueError("Bilan introuvable.")
    sem = a["reponse_json"]["semaine_suivante"]
    seances = seances if seances is not None else sem.get("seances") or []
    regles = verifier_regles(seances, sem.get("jour_repos"))
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
        statut_sante=p.get("statut_sante", "100%"), mode=p.get("mode_actif", "BASE")))
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

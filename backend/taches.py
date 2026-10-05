"""
Tâches IA persistantes : un appel LLM vit côté serveur, indépendamment de la page qui l'a lancé.

Changer d'onglet décharge la page (et iOS suspend le JS d'une app en arrière-plan) : la requête
HTTP en cours serait perdue. Le POST lance donc une tâche et répond aussitôt ; le travail tourne
dans un thread, écrit son résultat en base (plan, analyse) puis dans taches_ia. Les pages lisent
l'état par GET /api/taches.

Une seule tâche en cours par clé (ex. 'bilan_hebdo:2026-10-12') : retaper sur « Générer » ne
relance pas d'appel LLM.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import db

TZ = ZoneInfo("Europe/Paris")
TYPES = ("analyse_seance", "bilan_hebdo", "ajustement_semaine", "reconstruction_evenements")
DUREE_MAX = timedelta(minutes=10)     # au-delà, une tâche « en cours » est considérée perdue
MESSAGE_REDEMARRAGE = "Interrompue par un redémarrage, relance-la."

# Tests : exécution immédiate dans le thread appelant (résultat déterministe)
SYNCHRONE = False
_executeur = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tache-ia")
_verrou = threading.Lock()
_a_rejouer: dict[str, tuple] = {}     # clé → (type, paramètres, fonction) à relancer après la tâche en cours


def _maintenant() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def publique(t: Optional[dict]) -> Optional[dict]:
    if t is None:
        return None
    out = dict(t)
    for k in ("resultat", "parametres"):
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except json.JSONDecodeError:
                pass
    out["vue"] = bool(out.get("vue"))
    return out


def lire(id_: str) -> Optional[dict]:
    expirer()
    return publique(db.fetch_one("SELECT * FROM taches_ia WHERE id = ?", (id_,)))


def en_cours(cle: str) -> Optional[dict]:
    return publique(db.fetch_one("SELECT * FROM taches_ia WHERE cle = ? AND statut = 'en_cours' "
                                 "ORDER BY cree_le DESC LIMIT 1", (cle,)))


def actives() -> list[dict]:
    """Tâches en cours, et tâches terminées ou en erreur que l'utilisateur n'a pas encore vues."""
    expirer()
    return [publique(t) for t in db.fetch_all(
        "SELECT * FROM taches_ia WHERE statut = 'en_cours' OR vue = 0 ORDER BY cree_le")]


def derniere(cle: str) -> Optional[dict]:
    return publique(db.fetch_one("SELECT * FROM taches_ia WHERE cle = ? ORDER BY cree_le DESC LIMIT 1", (cle,)))


def marquer_vue(id_: str) -> Optional[dict]:
    with db.connexion() as c:
        c.execute("UPDATE taches_ia SET vue = 1 WHERE id = ? AND statut != 'en_cours'", (id_,))
    return lire(id_)


def lancer(type_: str, cle: str, parametres: dict, fonction: Callable[[dict], dict],
           rejouer_si_en_cours: bool = False) -> dict:
    """Lance fonction(parametres) en tâche de fond, ou renvoie la tâche déjà en cours pour cette clé.
    rejouer_si_en_cours : la tâche en cours a pu partir de données périmées (ex. reconstruction
    lancée avant l'ajout d'un 2e événement) : une nouvelle exécution suivra, une seule fois."""
    if type_ not in TYPES:
        raise ValueError(f"Type de tâche inconnu : {type_}")
    expirer()
    with _verrou:
        existante = en_cours(cle)
        if existante:
            if rejouer_si_en_cours:
                _a_rejouer[cle] = (type_, parametres, fonction)
            return existante
        id_ = str(uuid.uuid4())
        db.inserer("taches_ia", {"id": id_, "type": type_, "cle": cle, "statut": "en_cours",
                                 "parametres": json.dumps(parametres, ensure_ascii=False, default=str),
                                 "cree_le": _maintenant()})
    if SYNCHRONE:
        _executer(id_, cle, parametres, fonction)
    else:
        _executeur.submit(_executer, id_, cle, parametres, fonction)
    return lire(id_)


def _echec_llm(resultat) -> Optional[str]:
    """Un service qui renvoie erreur_llm sans réponse a échoué (réseau, plafond, JSON invalide)."""
    if isinstance(resultat, dict) and resultat.get("erreur_llm") \
            and not (resultat.get("reponse") or resultat.get("analyse_llm") or resultat.get("ok")):
        e = resultat["erreur_llm"]
        return e.get("message") if isinstance(e, dict) else str(e)
    return None


def _executer(id_: str, cle: str, parametres: dict, fonction: Callable[[dict], dict]) -> None:
    try:
        resultat = fonction(parametres)
        erreur = _echec_llm(resultat)
        maj = {"statut": "erreur" if erreur else "termine", "erreur": erreur}
    except Exception as e:        # noqa: BLE001 — l'erreur est rangée dans la tâche, jamais perdue
        traceback.print_exc()
        resultat, maj = None, {"statut": "erreur", "erreur": str(e) or type(e).__name__}
    with db.connexion() as c:
        c.execute("UPDATE taches_ia SET statut = ?, erreur = ?, resultat = ?, termine_le = ? "
                  "WHERE id = ? AND statut = 'en_cours'",
                  (maj["statut"], maj["erreur"], json.dumps(resultat, ensure_ascii=False, default=str),
                   _maintenant(), id_))
    rejeu = _a_rejouer.pop(cle, None)
    if rejeu:
        # La première tâche n'a plus d'intérêt : seule la nouvelle sera montrée
        marquer_vue(id_)
        lancer(rejeu[0], cle, rejeu[1], rejeu[2])


def relancer(id_: str, fonction: Callable[[dict], dict]) -> dict:
    t = lire(id_)
    if not t:
        raise ValueError("Tâche introuvable.")
    marquer_vue(id_)
    return lancer(t["type"], t["cle"], t["parametres"] or {}, fonction)


def interrompre_au_demarrage() -> int:
    """Au démarrage du serveur, aucune tâche ne peut être en cours (les threads sont morts avec
    l'ancien processus) : toutes passent en erreur, avec un message pour la relancer."""
    with db.connexion() as c:
        return c.execute("UPDATE taches_ia SET statut = 'erreur', erreur = ?, termine_le = ? WHERE statut = 'en_cours'",
                         (MESSAGE_REDEMARRAGE, _maintenant())).rowcount


def expirer() -> None:
    """Filet de sécurité : une tâche en cours depuis plus de 10 min est considérée perdue."""
    limite = (datetime.now(TZ) - DUREE_MAX).isoformat(timespec="seconds")
    with db.connexion() as c:
        c.execute("UPDATE taches_ia SET statut = 'erreur', erreur = ?, termine_le = ? "
                  "WHERE statut = 'en_cours' AND cree_le < ?",
                  ("Délai dépassé, relance-la.", _maintenant(), limite))

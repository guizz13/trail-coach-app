"""
Accès SQLite : connexion, initialisation du schéma, helpers CRUD.

Une connexion par opération (SQLite local, un seul utilisateur).
Les colonnes JSON sont encodées à l'écriture et décodées à la lecture.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Colonnes stockées en JSON texte, décodées automatiquement à la lecture
COLONNES_JSON = {
    "temps_zones_s", "temps_zones_pct", "donnees_brutes",
    "groupes", "charges",
    "squash_jours", "contraintes",
    "reponse_json",
}


def data_dir() -> Path:
    d = Path(os.getenv("COACH_DATA_DIR", "./data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "coach.db"


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------
def _ouvrir() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connexion() -> Iterator[sqlite3.Connection]:
    """Transaction : commit si tout passe, rollback sinon."""
    conn = _ouvrir()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connexion() as c:
        c.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers génériques
# ---------------------------------------------------------------------------
def _decoder(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    for k in COLONNES_JSON & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def _encoder(valeurs: dict) -> dict:
    return {
        k: json.dumps(v, ensure_ascii=False, default=str) if k in COLONNES_JSON and v is not None and not isinstance(v, str) else v
        for k, v in valeurs.items()
    }


def fetch_one(sql: str, params: tuple = ()) -> Optional[dict]:
    with connexion() as c:
        return _decoder(c.execute(sql, params).fetchone())


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    with connexion() as c:
        return [_decoder(r) for r in c.execute(sql, params).fetchall()]


def inserer(table: str, valeurs: dict, conn: Optional[sqlite3.Connection] = None) -> int:
    v = _encoder(valeurs)
    cols = ", ".join(v)
    marks = ", ".join("?" for _ in v)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"
    if conn is not None:
        return conn.execute(sql, tuple(v.values())).lastrowid
    with connexion() as c:
        return c.execute(sql, tuple(v.values())).lastrowid


def maj(table: str, id_: Any, valeurs: dict, cle: str = "id",
        conn: Optional[sqlite3.Connection] = None) -> None:
    if not valeurs:
        return
    v = _encoder(valeurs)
    sets = ", ".join(f"{k} = ?" for k in v)
    sql = f"UPDATE {table} SET {sets} WHERE {cle} = ?"
    params = (*v.values(), id_)
    if conn is not None:
        conn.execute(sql, params)
        return
    with connexion() as c:
        c.execute(sql, params)


def supprimer(table: str, id_: Any, cle: str = "id") -> int:
    with connexion() as c:
        return c.execute(f"DELETE FROM {table} WHERE {cle} = ?", (id_,)).rowcount


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------
def profil() -> dict:
    return fetch_one("SELECT * FROM profil WHERE id = 1") or {}


def maj_profil(**valeurs) -> None:
    valeurs["maj_le"] = _maintenant_sql()
    maj("profil", 1, valeurs)


# ---------------------------------------------------------------------------
# Types d'activité
# ---------------------------------------------------------------------------
def activity_types() -> dict[int, str]:
    return {r["code"]: r["famille"] for r in fetch_all("SELECT code, famille FROM activity_types")}


def enregistrer_activity_type(code: int, famille: str, libelle: Optional[str] = None) -> None:
    with connexion() as c:
        c.execute(
            "INSERT INTO activity_types (code, famille, libelle) VALUES (?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET famille = excluded.famille, libelle = excluded.libelle",
            (code, famille, libelle),
        )


# ---------------------------------------------------------------------------
# Séances réalisées
# ---------------------------------------------------------------------------
def seance_par_hash(h: str) -> Optional[dict]:
    return fetch_one("SELECT * FROM seances_realisees WHERE fichier_hash = ?", (h,))


def seance(id_: int) -> Optional[dict]:
    return fetch_one("SELECT * FROM seances_realisees WHERE id = ?", (id_,))


def seances_entre(du: str, au: str, famille: Optional[str] = None,
                  familles: Optional[set] = None) -> list[dict]:
    """Séances dont la date (YYYY-MM-DD) est dans [du, au]."""
    sql = "SELECT * FROM seances_realisees WHERE substr(date_debut, 1, 10) BETWEEN ? AND ?"
    params: list = [du, au]
    if famille:
        sql += " AND famille = ?"
        params.append(famille)
    if familles:
        sql += f" AND famille IN ({', '.join('?' for _ in familles)})"
        params.extend(sorted(familles))
    return fetch_all(sql + " ORDER BY date_debut", tuple(params))


def derniere_muscu_split() -> Optional[str]:
    r = fetch_one(
        "SELECT m.split FROM muscu_detail m JOIN seances_realisees s ON s.id = m.seance_id "
        "WHERE m.split IS NOT NULL ORDER BY s.date_debut DESC, m.id DESC LIMIT 1"
    )
    return r["split"] if r else None


def muscu_detail(seance_id: int) -> Optional[dict]:
    return fetch_one("SELECT * FROM muscu_detail WHERE seance_id = ?", (seance_id,))


# ---------------------------------------------------------------------------
# Séances planifiées
# ---------------------------------------------------------------------------
def planifiees_entre(du: str, au: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM seances_planifiees WHERE date_seance BETWEEN ? AND ? "
        "ORDER BY date_seance, CASE creneau WHEN 'matin' THEN 0 WHEN 'midi' THEN 1 "
        "WHEN 'journee' THEN 2 ELSE 3 END, id",
        (du, au),
    )


def planifiee(id_: int) -> Optional[dict]:
    return fetch_one("SELECT * FROM seances_planifiees WHERE id = ?", (id_,))


# ---------------------------------------------------------------------------
# Analyses LLM
# ---------------------------------------------------------------------------
def analyse(id_: int) -> Optional[dict]:
    return fetch_one("SELECT * FROM analyses_llm WHERE id = ?", (id_,))


def analyses_seance(seance_id: int) -> list[dict]:
    return fetch_all("SELECT * FROM analyses_llm WHERE seance_id = ? ORDER BY id DESC", (seance_id,))


def derniere_analyse(type_appel: Optional[str] = None) -> Optional[dict]:
    if type_appel:
        return fetch_one("SELECT * FROM analyses_llm WHERE type_appel = ? ORDER BY id DESC LIMIT 1", (type_appel,))
    return fetch_one("SELECT * FROM analyses_llm ORDER BY id DESC LIMIT 1")


# ---------------------------------------------------------------------------
# Événements & plan de prépa
# ---------------------------------------------------------------------------
def evenements(depuis: Optional[str] = None) -> list[dict]:
    if depuis:
        return fetch_all("SELECT * FROM evenements WHERE date_evt >= ? ORDER BY date_evt", (depuis,))
    return fetch_all("SELECT * FROM evenements ORDER BY date_evt")


def evenement(id_: int) -> Optional[dict]:
    return fetch_one("SELECT * FROM evenements WHERE id = ?", (id_,))


def plan_prepa() -> list[dict]:
    return fetch_all("SELECT * FROM plan_prepa ORDER BY du")


def remplacer_plan_prepa(phases: list[dict]) -> None:
    with connexion() as c:
        c.execute("DELETE FROM plan_prepa")
        for p in phases:
            inserer("plan_prepa", p, conn=c)


# ---------------------------------------------------------------------------
# Impératifs & poids
# ---------------------------------------------------------------------------
def sauver_imperatifs(semaine_debut: str, valeurs: dict) -> None:
    v = _encoder({**valeurs, "semaine_debut": semaine_debut, "saisi_le": _maintenant_sql()})
    cols = ", ".join(v)
    marks = ", ".join("?" for _ in v)
    updates = ", ".join(f"{k} = excluded.{k}" for k in v if k != "semaine_debut")
    with connexion() as c:
        c.execute(
            f"INSERT INTO imperatifs_semaine ({cols}) VALUES ({marks}) "
            f"ON CONFLICT(semaine_debut) DO UPDATE SET {updates}",
            tuple(v.values()),
        )


def imperatifs(semaine_debut: str) -> Optional[dict]:
    return fetch_one("SELECT * FROM imperatifs_semaine WHERE semaine_debut = ?", (semaine_debut,))


def poids_liste(depuis: Optional[str] = None) -> list[dict]:
    if depuis:
        return fetch_all("SELECT * FROM poids WHERE date_mesure >= ? ORDER BY date_mesure", (depuis,))
    return fetch_all("SELECT * FROM poids ORDER BY date_mesure")


def sauver_poids(date_mesure: str, poids_kg: float, masse_grasse_pct: Optional[float] = None) -> None:
    with connexion() as c:
        c.execute(
            "INSERT INTO poids (date_mesure, poids_kg, masse_grasse_pct) VALUES (?, ?, ?) "
            "ON CONFLICT(date_mesure) DO UPDATE SET poids_kg = excluded.poids_kg, "
            "masse_grasse_pct = excluded.masse_grasse_pct",
            (date_mesure, poids_kg, masse_grasse_pct),
        )


def _maintenant_sql() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")

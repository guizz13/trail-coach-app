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
    "reponse_json", "signaux", "modifications", "sante_zones",
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
        migrer(c)


# ---------------------------------------------------------------------------
# Migrations idempotentes (bases créées avant l'ajout des colonnes)
# ---------------------------------------------------------------------------
COLONNES_AJOUTEES = [
    # (table, colonne, définition)
    ("seances_realisees", "lien_manuel", "INTEGER NOT NULL DEFAULT 0"),
    ("seances_realisees", "verdict", "TEXT"),            # vert | orange | rouge | hors_plan
    ("seances_realisees", "signaux", "TEXT"),            # JSON : signaux du dernier calcul
    ("seances_realisees", "douleur", "INTEGER"),         # douleur déclarée /10 (facultative)
    ("seances_realisees", "douleur_zone", "TEXT"),
    ("imperatifs_semaine", "plan_modifie", "INTEGER NOT NULL DEFAULT 0"),
    ("imperatifs_semaine", "modifications", "TEXT"),     # JSON : modifications faites par l'utilisateur
    ("profil", "sante_niveau", "TEXT NOT NULL DEFAULT '100'"),   # '100' | 'vigilance' | 'blessure'
    ("profil", "sante_zones", "TEXT NOT NULL DEFAULT '[]'"),     # JSON array
    ("profil", "sante_note", "TEXT"),
    ("profil", "sante_protocole", "TEXT"),                       # consignes du kiné
    # v5 multisport : sport du catalogue + provenance
    ("seances_realisees", "sport_id", "TEXT"),
    ("seances_realisees", "source", "TEXT NOT NULL DEFAULT 'suunto_json'"),   # suunto_json | strava | manuel
    ("seances_realisees", "source_id", "TEXT"),          # hash du fichier Suunto, id Strava, uuid
    ("seances_realisees", "source_code", "TEXT"),        # code brut reçu ('82', 'TrailRun')
    ("seances_realisees", "rpe", "INTEGER"),             # 1-10, saisi par l'utilisateur
    ("seances_realisees", "note", "TEXT"),
    ("seances_realisees", "sport_a_preciser", "INTEGER NOT NULL DEFAULT 0"),
    # v5 semaine réelle : date réalisée − date prévue de la séance liée (+ reportée, − avancée)
    ("seances_realisees", "decalage_jours", "INTEGER NOT NULL DEFAULT 0"),
]


def _colonnes(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


ACTIVITY_TYPES_INITIAUX = [("suunto_json", "3", "course_route"), ("suunto_json", "82", "trail"),
                           ("suunto_json", "93", "course_tapis"), ("suunto_json", "37", "squash"),
                           ("suunto_json", "17", "velo_salle"), ("suunto_json", "23", "muscu")]


def migrer(c: sqlite3.Connection) -> None:
    sante_a_convertir = "sante_niveau" not in _colonnes(c, "profil")
    sports_a_remplir = "sport_id" not in _colonnes(c, "seances_realisees")
    _migrer_activity_types(c)
    for table, colonne, definition in COLONNES_AJOUTEES:
        if colonne not in _colonnes(c, table):
            c.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}")
    if sante_a_convertir:
        _convertir_sante(c)
    if sports_a_remplir:
        _remplir_sports(c)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_realisees_source ON seances_realisees(source, source_id)")
    _elargir_types_appel(c)
    _elargir_statuts_planifiees(c)


def _migrer_activity_types(c: sqlite3.Connection) -> None:
    """Ancienne table (code entier → famille) → (source, code, sport_id). Les codes appris sont conservés."""
    from sports import SPORT_DEPUIS_FAMILLE
    if "source" not in _colonnes(c, "activity_types"):
        anciens = c.execute("SELECT code, famille FROM activity_types").fetchall()
        c.execute("DROP TABLE IF EXISTS activity_types_old")
        c.execute("ALTER TABLE activity_types RENAME TO activity_types_old")
        c.execute("CREATE TABLE activity_types (source TEXT NOT NULL, code TEXT NOT NULL, sport_id TEXT NOT NULL, "
                  "confirme INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (source, code))")
        for code, famille in anciens:
            if str(code) not in {x[1] for x in ACTIVITY_TYPES_INITIAUX}:
                c.execute("INSERT OR IGNORE INTO activity_types (source, code, sport_id) VALUES ('suunto_json', ?, ?)",
                          (str(code), SPORT_DEPUIS_FAMILLE.get(famille, "autre")))
        c.execute("DROP TABLE activity_types_old")
    c.executemany("INSERT OR IGNORE INTO activity_types (source, code, sport_id) VALUES (?, ?, ?)", ACTIVITY_TYPES_INITIAUX)


def _remplir_sports(c: sqlite3.Connection) -> None:
    """sport_id déduit de l'ancienne famille ; un course_outdoor à plus de 15 m de D+/km devient du trail ;
    une séance « inconnu » de code 82 aussi (82 = trail dans les exports JSON)."""
    from sports import SPORT_DEPUIS_FAMILLE
    for id_, famille, code, km, dplus, h in c.execute(
            "SELECT id, famille, activity_type_code, distance_km, dplus_m, fichier_hash FROM seances_realisees").fetchall():
        sport = SPORT_DEPUIS_FAMILLE.get(famille, "autre")
        if famille == "course_outdoor" and km and (dplus or 0) / km > 15:
            sport = "trail"
        if famille == "inconnu" and str(code) == "82":
            sport = "trail"
        c.execute("UPDATE seances_realisees SET sport_id = ?, source_code = ?, source_id = ? WHERE id = ?",
                  (sport, None if code is None else str(code), h, id_))


ZONES_SANTE = ["Achille G", "Achille D", "Fascia G", "Fascia D", "Mollet G", "Mollet D",
               "Genou G", "Genou D", "Hanche", "Dos", "Épaule", "Autre"]


def zones_depuis_texte(texte: str) -> list[str]:
    """« achille gauche et droit » → [Achille G, Achille D] ; reconnaissance simple par mots-clés."""
    t = (texte or "").lower()
    zones = []
    for nom, mots in (("Achille", ("achille",)), ("Fascia", ("fascia", "aponévr", "aponevr")),
                      ("Mollet", ("mollet",)), ("Genou", ("genou",))):
        if any(m in t for m in mots):
            cotes = [c for c, m in (("G", "gauche"), ("D", "droit")) if m in t] or ["G", "D"]
            zones += [f"{nom} {c}" for c in cotes]
    for nom, mot in (("Hanche", "hanche"), ("Dos", "dos"), ("Épaule", "paule")):
        if mot in t:
            zones.append(nom)
    return zones


def _convertir_sante(c: sqlite3.Connection) -> None:
    """Ancien statut texte (« vigilance:achille gauche ») → niveau + zones reconnues + note."""
    r = c.execute("SELECT statut_sante, notes_sante FROM profil WHERE id = 1").fetchone()
    if not r:
        return
    brut = (r[0] or "100%").strip()
    niveau = "blessure" if "blessure" in brut.lower() else "vigilance" if "vigilance" in brut.lower() else "100"
    note = brut.partition(":")[2].strip() if niveau != "100" else None
    note = " — ".join(x for x in (note, r[1]) if x) or None
    c.execute("UPDATE profil SET sante_niveau = ?, sante_zones = ?, sante_note = ? WHERE id = 1",
              (niveau, json.dumps(zones_depuis_texte(note or "") if niveau != "100" else [], ensure_ascii=False), note))


def _elargir_types_appel(c: sqlite3.Connection) -> None:
    """SQLite ne sait pas modifier une contrainte CHECK : la table analyses_llm est reconstruite
    (même colonnes, mêmes données) pour accepter le type d'appel « ajustement_semaine »."""
    sql = c.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'analyses_llm'").fetchone()[0]
    if "ajustement_semaine" in sql:
        return
    colonnes = ", ".join(r[1] for r in c.execute("PRAGMA table_info(analyses_llm)"))
    c.execute("ALTER TABLE analyses_llm RENAME TO analyses_llm_ancienne")
    c.execute(sql.replace("'reconstruction_evenements')", "'reconstruction_evenements','ajustement_semaine')"))
    c.execute(f"INSERT INTO analyses_llm ({colonnes}) SELECT {colonnes} FROM analyses_llm_ancienne")
    c.execute("DROP TABLE analyses_llm_ancienne")


def _elargir_statuts_planifiees(c: sqlite3.Connection) -> None:
    """Statuts « decale » et « remplacee » (v5) : SQLite ne modifie pas une contrainte CHECK, la table
    est reconstruite. On ne renomme pas l'ancienne table : avec foreign_keys=ON, SQLite réécrirait
    la clé étrangère de remplacements vers elle. Nouvelle table → copie → suppression de l'ancienne
    (remplacements est encore vide à ce stade) → renommage de la nouvelle."""
    sql = c.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'seances_planifiees'").fetchone()[0]
    if "'decale'" in sql:
        return
    colonnes = ", ".join(r[1] for r in c.execute("PRAGMA table_info(seances_planifiees)"))
    nouvelle = sql.replace("'modifie')", "'modifie','decale','remplacee')")
    nouvelle = nouvelle.replace("seances_planifiees", "seances_planifiees_v5", 1)
    c.execute("DROP TABLE IF EXISTS seances_planifiees_v5")
    c.execute(nouvelle)
    c.execute(f"INSERT INTO seances_planifiees_v5 ({colonnes}) SELECT {colonnes} FROM seances_planifiees")
    c.execute("DROP TABLE seances_planifiees")
    c.execute("ALTER TABLE seances_planifiees_v5 RENAME TO seances_planifiees")
    c.execute("CREATE INDEX IF NOT EXISTS idx_planifiees_date ON seances_planifiees(date_seance)")


# ---------------------------------------------------------------------------
# État de la semaine (plan modifié par l'utilisateur)
# ---------------------------------------------------------------------------
def etat_semaine(lundi: str) -> dict:
    r = fetch_one("SELECT plan_modifie, modifications FROM imperatifs_semaine WHERE semaine_debut = ?", (lundi,))
    return {"plan_modifie": bool(r and r["plan_modifie"]), "modifications": (r and r["modifications"]) or []}


def noter_modification(lundi: str, modification: str) -> None:
    etat = etat_semaine(lundi)
    mods = etat["modifications"] + [modification]
    with connexion() as c:
        c.execute("INSERT INTO imperatifs_semaine (semaine_debut, plan_modifie, modifications) VALUES (?, 1, ?) "
                  "ON CONFLICT(semaine_debut) DO UPDATE SET plan_modifie = 1, modifications = excluded.modifications",
                  (lundi, json.dumps(mods, ensure_ascii=False)))


def plan_reajuste(lundi: str) -> None:
    with connexion() as c:
        c.execute("UPDATE imperatifs_semaine SET plan_modifie = 0 WHERE semaine_debut = ?", (lundi,))


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
def activity_types(source: str = "suunto_json") -> dict[str, str]:
    """{code: sport_id} pour une source."""
    return {r["code"]: r["sport_id"] for r in
            fetch_all("SELECT code, sport_id FROM activity_types WHERE source = ?", (source,))}


def correspondances(source: Optional[str] = None) -> list[dict]:
    if source:
        return fetch_all("SELECT * FROM activity_types WHERE source = ? ORDER BY CAST(code AS INTEGER), code", (source,))
    return fetch_all("SELECT * FROM activity_types ORDER BY source, CAST(code AS INTEGER), code")


def enregistrer_activity_type(code, sport_id: str, source: str = "suunto_json", confirme: bool = True) -> None:
    with connexion() as c:
        c.execute(
            "INSERT INTO activity_types (source, code, sport_id, confirme) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(source, code) DO UPDATE SET sport_id = excluded.sport_id, confirme = excluded.confirme",
            (source, str(code), sport_id, int(confirme)),
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
def remplacees_par(seance_id: int) -> list[dict]:
    return fetch_all("SELECT p.* FROM remplacements r JOIN seances_planifiees p ON p.id = r.seance_planifiee_id "
                     "WHERE r.seance_realisee_id = ? ORDER BY p.date_seance, p.id", (seance_id,))


def remplacements_par_planifiee() -> dict[int, int]:
    return {r["seance_planifiee_id"]: r["seance_realisee_id"] for r in fetch_all("SELECT * FROM remplacements")}


def planifiees_remplacees() -> set[int]:
    return {r["seance_planifiee_id"] for r in fetch_all("SELECT seance_planifiee_id FROM remplacements")}


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

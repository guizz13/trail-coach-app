"""Migration v5 : catalogue des sports, provenance des séances, correspondances apprises."""

import sqlite3
import subprocess

import pytest

import db
import services


def base_prod(dossier):
    """Base au format de main (production avant v5) avec des séances de chaque cas."""
    schema = subprocess.run(["git", "show", "31f6211:backend/schema.sql"], capture_output=True, text=True, check=True).stdout
    c = sqlite3.connect(dossier / "coach.db")
    c.executescript(schema)
    lignes = [  # id, hash, code, famille, km, D+
        (1, "h-route", 3, "course_outdoor", 10.0, 60),
        (2, "h-trail", 3, "course_outdoor", 12.0, 450),       # 37,5 m/km → trail
        (3, "h-82", 82, "inconnu", 9.0, 300),
        (4, "h-velo", 17, "velo", None, None),
        (5, "h-pull", 23, "muscu", None, None),
        (6, "h-tapis", 93, "course_tapis", 8.0, 0),
    ]
    for id_, h, code, fam, km, dplus in lignes:
        c.execute("INSERT INTO seances_realisees (id, fichier_hash, activity_type_code, famille, date_debut, duree_min, "
                  "distance_km, dplus_m, charge) VALUES (?, ?, ?, ?, '2026-09-28T07:30:00+02:00', 45, ?, ?, 50)",
                  (id_, h, code, fam, km, dplus))
    c.execute("INSERT INTO activity_types (code, famille, libelle) VALUES (999, 'velo', 'appris')")
    c.commit()
    c.close()


@pytest.fixture
def prod(tmp_path, monkeypatch):
    dossier = tmp_path / "prod"
    dossier.mkdir()
    base_prod(dossier)
    monkeypatch.setenv("COACH_DATA_DIR", str(dossier))
    db.init_db()
    return dossier


def test_sport_deduit_de_la_famille(prod):
    sports = {i: db.seance(i)["sport_id"] for i in range(1, 7)}
    assert sports == {1: "course_route", 2: "trail", 3: "trail", 4: "velo_salle", 5: "muscu", 6: "course_tapis"}


def test_provenance(prod):
    s = db.seance(3)
    assert (s["source"], s["source_id"], s["source_code"]) == ("suunto_json", "h-82", "82")
    assert s["rpe"] is None and s["sport_a_preciser"] == 0


def test_correspondances_initiales_et_apprises(prod):
    assert db.activity_types() == {"3": "course_route", "82": "trail", "93": "course_tapis", "37": "squash",
                                   "17": "velo_salle", "23": "muscu", "999": "velo_salle"}


def test_migration_idempotente(prod):
    db.init_db()
    db.init_db()
    assert db.seance(2)["sport_id"] == "trail"
    assert len(db.activity_types()) == 7


def test_unicite_par_source(prod):
    with pytest.raises(sqlite3.IntegrityError):
        with db.connexion() as c:
            c.execute("INSERT INTO seances_realisees (fichier_hash, famille, date_debut, source, source_id) "
                      "VALUES ('autre-hash', 'muscu', '2026-09-29T08:00:00+02:00', 'suunto_json', 'h-route')")


def test_base_neuve():
    assert db.activity_types()["82"] == "trail"
    assert db.correspondances("strava") == []


def test_import_enregistre_sport_et_provenance():
    from conftest import lire
    r = services.importer_et_analyser(lire("course_outdoor"), "course.json")
    s = db.seance(r["seance"]["id"])
    assert s["sport_id"] == "course_route" and s["source"] == "suunto_json"
    assert s["source_id"] == s["fichier_hash"] and s["source_code"] == "3"

"""Complément v5 : semaine réelle (reports, remplacements, bilan par catégorie)."""

import sqlite3
import subprocess
from datetime import date

import pytest

import db
import services

LUNDI = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 4))   # dimanche


def prevoir(jour, type_, creneau="matin", duree=45):
    return db.inserer("seances_planifiees", {"date_seance": jour, "creneau": creneau, "type": type_,
                                             "duree_min": duree, "origine": "bilan_hebdo"})


def faire(sport, debut, duree=45, rpe=4):
    return services.saisir_seance({"sport_id": sport, "debut": debut, "duree_min": duree, "rpe": rpe},
                                  analyser=False)["seance"]["id"]


def statut(p):
    return db.planifiee(p)["statut"]


def lie_a(p):
    return db.planifiee(p)["seance_realisee_id"]


# ---- 1. Report / avance ---------------------------------------------------------------------------
def test_report_prioritaire_sur_l_avance():
    lundi, jeudi = prevoir("2026-09-28", "EF"), prevoir("2026-10-01", "EF")
    mardi = faire("course_route", "2026-09-29T07:00")
    assert lie_a(lundi) == mardi and lie_a(jeudi) is None
    assert db.seance(mardi)["decalage_jours"] == 1 and statut(lundi) == "decale"


def test_avance_de_deux_jours_maximum():
    mercredi, vendredi = prevoir("2026-09-30", "EF"), prevoir("2026-10-02", "EF")
    lundi = faire("course_route", "2026-09-28T07:00")
    assert lie_a(mercredi) == lundi and db.seance(lundi)["decalage_jours"] == -2
    assert statut(mercredi) == "decale" and lie_a(vendredi) is None


def test_au_dela_de_deux_jours_hors_plan():
    vendredi = prevoir("2026-10-02", "EF")
    s = faire("course_route", "2026-09-28T07:00")
    assert lie_a(vendredi) is None and db.seance(s)["verdict"] == "hors_plan"


def test_pas_de_liaison_entre_deux_semaines():
    dimanche_avant = prevoir("2026-09-27", "EF")
    s = faire("course_route", "2026-09-28T07:00")
    assert lie_a(dimanche_avant) is None and db.seance(s)["decalage_jours"] == 0


def test_le_meme_jour_reste_prioritaire():
    # Mercredi réalisé après coup : il reprend l'EF de mercredi, la course de lundi redevient hors plan
    mercredi = prevoir("2026-09-30", "EF")
    lundi = faire("course_route", "2026-09-28T07:00")
    assert lie_a(mercredi) == lundi
    mer = faire("course_route", "2026-09-30T07:00")
    assert lie_a(mercredi) == mer and db.seance(lundi)["decalage_jours"] == 0
    assert db.seance(lundi)["verdict"] == "hors_plan" and statut(mercredi) == "realise"


def test_cas_reel_muscu_decalee_au_dimanche():
    ef_sam, push_sam = prevoir("2026-10-03", "EF", "matin", 40), prevoir("2026-10-03", "muscu_push", "soir", 50)
    ef_dim = prevoir("2026-10-04", "EF", "matin", 40)
    faire("badminton", "2026-10-03T10:00", 75, 7)
    ef = faire("course_route", "2026-10-04T08:00", 40)
    push = faire("muscu", "2026-10-04T10:00", 55)
    assert lie_a(ef_dim) == ef and statut(ef_dim) == "realise"
    assert lie_a(push_sam) == push and statut(push_sam) == "decale"
    assert db.seance(push)["decalage_jours"] == 1
    assert services.detail_seance(push)["seance"]["prevue_le"] == "2026-10-03"
    assert statut(ef_sam) == "manque"                      # tant que le remplacement n'est pas déclaré
    assert db.seance(push)["verdict"] == "vert"            # verdict calculé contre la séance liée


def test_recalcul_admin_conserve_le_report():
    sam = prevoir("2026-10-03", "muscu_push", "soir", 50)
    push = faire("muscu", "2026-10-04T10:00", 55)
    services.recalculer_tout()
    assert lie_a(sam) == push and db.seance(push)["decalage_jours"] == 1


def test_migration_des_statuts(tmp_path, monkeypatch):
    schema = subprocess.run(["git", "show", "main:backend/schema.sql"], capture_output=True, text=True, check=True).stdout
    dossier = tmp_path / "prod"
    dossier.mkdir()
    c = sqlite3.connect(dossier / "coach.db")
    c.executescript(schema)
    c.execute("INSERT INTO seances_planifiees (id, date_seance, creneau, type, statut) VALUES (7, '2026-10-03', 'soir', 'Push', 'manque')")
    c.commit()
    c.close()
    monkeypatch.setenv("COACH_DATA_DIR", str(dossier))
    db.init_db()
    db.init_db()                                            # idempotente
    assert db.planifiee(7)["statut"] == "manque"
    db.maj("seances_planifiees", 7, {"statut": "decale"})
    sid = faire("badminton", "2026-10-03T10:00")
    with db.connexion() as conn:
        conn.execute("INSERT INTO remplacements VALUES (?, 7)", (sid,))
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'remplacements'").fetchone()[0]
    assert fk == [] and "REFERENCES seances_planifiees(" in sql


# ---- 2. Remplacements ------------------------------------------------------------------------------
def semaine_du_28():
    """Cas réel de la section 0 : samedi EF + Push prévus, badminton samedi, EF + muscu dimanche."""
    ids = {"ef_sam": prevoir("2026-10-03", "EF", "matin", 40), "push_sam": prevoir("2026-10-03", "muscu_push", "soir", 50),
           "ef_dim": prevoir("2026-10-04", "EF", "matin", 40)}
    ids["bad"] = faire("badminton", "2026-10-03T10:00", 75, 7)
    ids["ef"] = faire("course_route", "2026-10-04T08:00", 40)
    ids["push"] = faire("muscu", "2026-10-04T10:00", 55)
    return ids


def test_cas_reel_aucune_seance_manquee_apres_remplacement():
    x = semaine_du_28()
    assert [p["id"] for p in services.remplacables(x["bad"])] == [x["ef_sam"]]     # Push décalée, EF dim. faite
    d = services.remplacer(x["bad"], [x["ef_sam"]])
    assert [p["type"] for p in d["seance"]["remplace"]] == ["EF"]
    assert statut(x["ef_sam"]) == "remplacee" and statut(x["push_sam"]) == "decale"
    semaine = db.planifiees_entre("2026-09-28", "2026-10-04")
    assert not [p for p in semaine if p["statut"] == "manque"]
    jour = next(j for j in services.semaine(LUNDI) if j["date"] == "2026-10-03")
    assert next(p for p in jour["planifiees"] if p["id"] == x["ef_sam"])["remplacee_par"] == x["bad"]


def test_remplacement_conserve_par_le_recalcul_admin():
    x = semaine_du_28()
    services.remplacer(x["bad"], [x["ef_sam"]])
    services.recalculer_tout()
    assert statut(x["ef_sam"]) == "remplacee" and lie_a(x["ef_sam"]) is None
    assert db.planifiees_remplacees() == {x["ef_sam"]}


def test_annuler_le_remplacement():
    x = semaine_du_28()
    services.remplacer(x["bad"], [x["ef_sam"]])
    d = services.annuler_remplacement(x["bad"])
    assert d["seance"]["remplace"] == [] and statut(x["ef_sam"]) == "manque"


def test_remplacement_refuse():
    x = semaine_du_28()
    with pytest.raises(ValueError, match="liée"):
        services.remplacer(x["push"], [x["ef_sam"]])                 # la muscu est liée (décalée)
    with pytest.raises(ValueError, match="non remplaçable"):
        services.remplacer(x["bad"], [x["ef_dim"]])                  # déjà faite
    autre = prevoir("2026-10-05", "EF")
    with pytest.raises(ValueError, match="non remplaçable"):
        services.remplacer(x["bad"], [autre])                        # autre semaine


def test_seance_remplacee_jamais_liee():
    ef = prevoir("2026-10-01", "EF")
    bad = faire("badminton", "2026-10-01T10:00")
    services.remplacer(bad, [ef])
    faire("course_route", "2026-10-02T08:00")                        # report possible (+1 j) … mais remplacée
    assert lie_a(ef) is None and statut(ef) == "remplacee"


def test_suppression_en_cascade():
    ef = prevoir("2026-10-01", "EF")
    bad = faire("badminton", "2026-10-01T10:00")
    services.remplacer(bad, [ef])
    with db.connexion() as c:
        c.execute("DELETE FROM seances_realisees WHERE id = ?", (bad,))
    assert db.planifiees_remplacees() == set()

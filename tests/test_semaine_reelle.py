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
    schema = subprocess.run(["git", "show", "31f6211:backend/schema.sql"], capture_output=True, text=True, check=True).stdout
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


# ---- 3. Bilan de la semaine par catégorie -------------------------------------------------------------
def test_bilan_semaine_cas_reel():
    x = semaine_du_28()
    # Reste de la semaine, fait comme prévu
    for jour, type_, sport, duree, rpe in (("2026-09-28", "muscu_pull", "muscu", 50, 4), ("2026-09-29", "velo", "velo_salle", 60, 4),
                                           ("2026-09-30", "squash", "squash", 60, 5), ("2026-10-01", "EF", "course_route", 45, 4)):
        prevoir(jour, type_, "soir", duree)
        faire(sport, f"{jour}T18:00", duree, rpe)
    services.remplacer(x["bad"], [x["ef_sam"]])
    b = services.bilan_semaine(LUNDI)
    assert b["par_categorie"]["course"] == {"prevu_seances": 3, "realise_seances": 2, "prevu_min": 125, "realise_min": 85}
    assert b["par_categorie"]["raquette"] == {"prevu_seances": 1, "realise_seances": 2, "prevu_min": 60, "realise_min": 135}
    assert b["par_categorie"]["force"]["realise_seances"] == 2
    assert b["decalages"] == [{"seance": "Push", "de": "2026-10-03", "a": "2026-10-04"}]
    assert b["remplacements"] == [{"par": "badminton 75 min", "remplace": ["EF 40 min"]}]
    assert b["manques"] == [] and b["categories_sous_80"] == []
    assert b["jours_consecutifs_impact_eleve"] == [["2026-09-30", "2026-10-01"], ["2026-10-03", "2026-10-04"]]
    assert b["charge_totale"] == {"prevu": 750, "realise": 845}
    assert b["respect_global"] == "respectee"
    assert b["alerte"] is None                                      # santé 100 %


def test_bilan_semaine_charge_trop_haute():
    x = semaine_du_28()                                             # semaine courte : le badminton pèse lourd
    services.remplacer(x["bad"], [x["ef_sam"]])
    b = services.bilan_semaine(LUNDI)
    assert b["categories_sous_80"] == [] and b["charge_totale"] == {"prevu": 260, "realise": 415}
    assert b["respect_global"] == "non_respectee"                  # 160 % de la charge prévue


def test_bilan_semaine_alerte_vigilance_achille():
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille G"], "protocole": "kiné"})
    faire("badminton", "2026-10-03T10:00", 75, 7)
    faire("course_route", "2026-10-04T08:00", 40)
    b = services.bilan_semaine(LUNDI)
    assert b["jours_consecutifs_impact_eleve"] == [["2026-10-03", "2026-10-04"]]
    assert "samedi, dimanche" in b["alerte"] and "Achille G" in b["alerte"]
    assert services.tableau_de_bord(date(2026, 10, 4))["bilan_semaine"]["alerte"] == b["alerte"]


def test_bilan_semaine_respect():
    # Deux EF prévues et passées, une seule faite, sans remplacement : course à 50 % → partielle au mieux
    prevoir("2026-09-29", "EF", duree=40)
    prevoir("2026-10-01", "EF", duree=40)
    prevoir("2026-09-30", "muscu_pull", duree=50)
    faire("course_route", "2026-09-29T07:00", 40, 4)
    faire("muscu", "2026-09-30T07:00", 50, 4)
    b = services.bilan_semaine(LUNDI)
    assert b["manques"] == [{"seance": "EF 40 min", "date": "2026-10-01"}]
    assert b["categories_sous_80"] == ["course"] and b["respect_global"] in ("partielle", "non_respectee")


def test_bilan_semaine_sans_plan():
    faire("yoga", "2026-09-29T07:00", 30, 2)
    b = services.bilan_semaine(LUNDI)
    assert b["respect_global"] is None and b["par_categorie"]["mobilite"]["realise_seances"] == 1


# ---- 4. Bilan du dimanche (LLM) ----------------------------------------------------------------------
def test_bilan_hebdo_recoit_le_bilan_de_semaine(monkeypatch):
    from test_llm import FauxLLM, SEMAINE_VIGILANCE, bilan
    faux = FauxLLM(bilan_hebdo=bilan(SEMAINE_VIGILANCE))
    monkeypatch.setattr(services, "_llm", faux)
    x = semaine_du_28()
    services.remplacer(x["bad"], [x["ef_sam"]])
    services.bilan_hebdo({"semaine_debut": "2026-10-05", "ressenti": 7, "sommeil": 7, "sante": {"niveau": "100"}})
    ctx = faux.appels[0][1]
    b = ctx["bilan_semaine"]
    assert b["lundi"] == "2026-09-28" and b["remplacements"][0]["par"] == "badminton 75 min"
    assert b["decalages"][0]["seance"] == "Push"
    assert ctx["indicateurs"]["seances_manquees"] == []            # décalée ou remplacée : pas manquée


def test_prompt_section_10_2():
    from pathlib import Path
    prompt = (Path(__file__).parent.parent / "prompts" / "system_prompt_coach.md").read_text(encoding="utf-8")
    debut, fin = prompt.index("### 10.2"), prompt.index("### 10.3")
    assert "Tu reçois <bilan_semaine>" in prompt[debut:fin]
    assert "Tu ne rattrapes jamais ce qui manque." in prompt[debut:fin]


def test_client_llm_transmet_le_bilan(monkeypatch):
    import llm_client
    vu = {}
    client = llm_client.CoachLLM.__new__(llm_client.CoachLLM)
    monkeypatch.setattr(client, "_appel", lambda type_appel, ctx, *a: vu.update(ctx) or {}, raising=False)
    client.bilan_hebdo([], [], {}, [], [], {}, {}, "100%", "BASE", None, bilan_semaine={"respect_global": "respectee"})
    assert vu["bilan_semaine"] == {"respect_global": "respectee"}


# ---- 5. Routes HTTP --------------------------------------------------------------------------------
from test_api import anonyme, client  # noqa: E402,F401 (fixtures)


def test_api_remplacement_et_bilan(client):
    x = semaine_du_28()
    assert [p["id"] for p in client.get(f"/api/seances_realisees/{x['bad']}/remplacables").json()] == [x["ef_sam"]]
    assert client.post(f"/api/seances_realisees/{x['bad']}/remplacer", json={"seance_planifiee_ids": "1"}).status_code == 422
    r = client.post(f"/api/seances_realisees/{x['bad']}/remplacer", json={"seance_planifiee_ids": [x["ef_sam"]]})
    assert r.status_code == 200 and r.json()["seance"]["remplace"][0]["id"] == x["ef_sam"]
    b = client.get("/api/bilan_semaine?lundi=2026-09-30").json()            # n'importe quel jour de la semaine
    assert b["lundi"] == "2026-09-28" and b["remplacements"] and b["manques"] == []
    semaine = client.get("/api/semaine?lundi=2026-09-28").json()
    sam = next(j for j in semaine if j["date"] == "2026-10-03")
    assert {p["statut"] for p in sam["planifiees"]} == {"remplacee", "decale"}
    r = client.post(f"/api/seances_realisees/{x['bad']}/annuler_remplacement")
    assert r.status_code == 200 and r.json()["seance"]["remplace"] == []
    assert client.post(f"/api/seances_realisees/{x['push']}/remplacer",
                       json={"seance_planifiee_ids": [x["ef_sam"]]}).status_code == 422   # liée : refus

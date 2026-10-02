"""Section 1 du correctif v4 : liaison réalisé ↔ prévu par famille de discipline."""

from datetime import date

import pytest

import db
import services

LUNDI = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 2))   # vendredi


_n = 0


def realisee(debut: str, famille: str, duree: float = 45, zones_s: dict = None) -> int:
    global _n
    _n += 1
    return db.inserer("seances_realisees", {
        "fichier_hash": f"h{_n}", "activity_type_code": 0, "famille": famille, "date_debut": debut,
        "duree_min": duree, "distance_km": 0, "temps_zones_s": zones_s or {"z2": duree * 60},
        "temps_zones_pct": {}, "charge": 0,
    })


def planifier(jour: str, type_: str, creneau: str = "matin") -> int:
    return db.inserer("seances_planifiees", {"date_seance": jour, "creneau": creneau, "type": type_, "origine": "test"})


def lie_a(planifiee_id: int):
    return db.planifiee(planifiee_id)["seance_realisee_id"]


def test_familles():
    assert services.famille_planifiee("muscu_pull") == "muscu"
    assert services.famille_planifiee("Pull A") == "muscu"           # type écrit librement
    assert services.famille_planifiee("Sortie longue") == "course"
    assert services.famille_planifiee("EF") == "course"
    assert services.famille_planifiee("repos") is None
    assert services.famille_planifiee("Yoga") is None                # inconnu : jamais lié


@pytest.mark.parametrize("type_pull", ["muscu_pull", "Pull A"])
def test_semaine_du_28_septembre(type_pull):
    pull = planifier("2026-09-28", type_pull)
    muscu_mer = planifier("2026-09-30", "muscu_push")
    course_lundi = realisee("2026-09-28T07:30:00+02:00", "course_outdoor")
    muscu = realisee("2026-09-30T08:00:00+02:00", "muscu")

    services.recalculer_semaine(LUNDI)

    assert lie_a(pull) is None                                         # la course ne prend pas la muscu
    assert db.planifiee(pull)["statut"] == "manque"
    assert lie_a(muscu_mer) == muscu
    assert db.planifiee(muscu_mer)["statut"] == "realise"
    assert services.prevu_de(course_lundi) is None                     # course hors plan


def test_deux_seances_le_meme_jour():
    squash_p = planifier("2026-10-01", "squash", "soir")
    muscu_p = planifier("2026-10-01", "muscu_pull", "matin")
    muscu = realisee("2026-10-01T08:00:00+02:00", "muscu")
    squash = realisee("2026-10-01T19:00:00+02:00", "squash")
    services.recalculer_semaine(LUNDI)
    assert (lie_a(muscu_p), lie_a(squash_p)) == (muscu, squash)


def test_creneau_le_plus_proche():
    matin = planifier("2026-10-01", "EF", "matin")
    soir = planifier("2026-10-01", "intervals", "soir")
    course = realisee("2026-10-01T18:30:00+02:00", "course_tapis")
    services.recalculer_semaine(LUNDI)
    assert lie_a(soir) == course and lie_a(matin) is None


def test_aujourdhui_jamais_manque_et_futur_a_faire():
    aujourd = planifier("2026-10-02", "EF")
    demain = planifier("2026-10-03", "sortie_longue")
    repos = planifier("2026-09-29", "repos", "journee")
    services.recalculer_semaine(LUNDI)
    assert [db.planifiee(i)["statut"] for i in (aujourd, demain, repos)] == ["prevu", "prevu", "prevu"]


def test_pas_de_liaison_sur_une_autre_date():
    planifier("2026-09-29", "squash", "soir")
    squash = realisee("2026-09-30T19:00:00+02:00", "squash")
    services.recalculer_semaine(LUNDI)
    assert services.prevu_de(squash) is None


def test_lier_et_delier_manuellement():
    mardi = planifier("2026-09-29", "squash", "soir")
    squash = realisee("2026-09-30T19:00:00+02:00", "squash")
    services.recalculer_semaine(LUNDI)
    assert [p["id"] for p in services.candidats_liaison(squash)] == [mardi]

    d = services.lier(squash, mardi)
    assert d["prevu"]["id"] == mardi and db.seance(squash)["lien_manuel"] == 1
    assert db.planifiee(mardi)["statut"] == "realise"

    services.recalculer_tout()                                          # le lien manuel survit
    assert lie_a(mardi) == squash

    services.delier(squash)
    assert lie_a(mardi) is None and db.planifiee(mardi)["statut"] == "manque"
    services.recalculer_tout()                                          # et le déliage aussi
    assert lie_a(mardi) is None


def test_liaison_refusee_autre_famille_ou_semaine():
    muscu_p = planifier("2026-09-29", "muscu_pull")
    autre_semaine = planifier("2026-10-06", "squash", "soir")
    squash = realisee("2026-09-30T19:00:00+02:00", "squash")
    with pytest.raises(ValueError, match="discipline"):
        services.lier(squash, muscu_p)
    with pytest.raises(ValueError, match="semaine"):
        services.lier(squash, autre_semaine)


def test_recalcul_admin_relie_tout_l_historique():
    pull = planifier("2026-09-28", "Pull A")
    course = realisee("2026-09-28T07:30:00+02:00", "course_outdoor")
    # Liaison erronée héritée de l'ancien code : course liée à « Pull A »
    db.maj("seances_planifiees", pull, {"seance_realisee_id": course, "statut": "realise"})
    r = services.recalculer_tout()
    assert lie_a(pull) is None and db.planifiee(pull)["statut"] == "manque"
    assert r["seances_liees"] == 0


# ---- Cas réel : base de prod créée avant le correctif v4 ------------------------------------
# Schéma d'avant v4 (commit 74e3528) et état laissé par l'ancien code : la course du lundi 28/09
# liée à « Pull A », parce que l'ancien code rangeait les types inconnus en course.
COMMIT_AVANT_V4 = "74e3528"


def base_avant_v4(dossier):
    import sqlite3
    import subprocess
    schema = subprocess.run(["git", "show", f"{COMMIT_AVANT_V4}:backend/schema.sql"],
                            capture_output=True, text=True, check=True).stdout
    c = sqlite3.connect(dossier / "coach.db")
    c.executescript(schema)
    c.execute("INSERT INTO seances_realisees (id, fichier_hash, activity_type_code, famille, date_debut, duree_min, "
              "distance_km, temps_zones_s, temps_zones_pct, epoc, charge) VALUES (1, 'h-lundi', 3, 'course_outdoor', "
              "'2026-09-28T07:30:00+02:00', 35, 6.4, '{\"z2\": 1500, \"z3\": 600}', '{\"z2\": 71, \"z3\": 29}', 87.3, 87.3)")
    c.execute("INSERT INTO seances_planifiees (id, date_seance, creneau, type, detail, statut, seance_realisee_id, origine) "
              "VALUES (1, '2026-09-28', 'matin', 'Pull A', 'Tractions, rowing', 'realise', 1, 'bilan_hebdo')")
    c.execute("INSERT INTO seances_planifiees (id, date_seance, creneau, type, statut, origine) "
              "VALUES (2, '2026-09-30', 'matin', 'Push B', 'prevu', 'bilan_hebdo')")
    c.commit()
    c.close()


def test_cas_reel_migration_puis_garde_fou(tmp_path, monkeypatch):
    dossier = tmp_path / "prod"
    dossier.mkdir()
    base_avant_v4(dossier)
    monkeypatch.setenv("COACH_DATA_DIR", str(dossier))
    db.init_db()                                                        # migration v4
    assert db.seance(1)["lien_manuel"] == 0                             # la migration ne marque rien en manuel
    assert lie_a(1) == 1                                                # le lien hérité est encore là…

    defaites = services.defaire_liaisons_incoherentes()                # …jusqu'au garde-fou (démarrage)
    assert defaites == [{"planifiee": "Pull A du 2026-09-28", "realisee": "course_outdoor"}]
    assert lie_a(1) is None and db.planifiee(1)["statut"] == "manque"
    assert db.seance(1)["verdict"] == "hors_plan"


def test_cas_reel_recalcul_admin(tmp_path, monkeypatch):
    dossier = tmp_path / "prod"
    dossier.mkdir()
    base_avant_v4(dossier)
    monkeypatch.setenv("COACH_DATA_DIR", str(dossier))
    db.init_db()
    r = services.recalculer_tout()
    assert r["liaisons_incoherentes_defaites"][0]["planifiee"] == "Pull A du 2026-09-28"
    assert {"planifiee": "Pull A du 2026-09-28", "avant": "course_outdoor", "apres": None} in r["liaisons_corrigees"]
    assert lie_a(1) is None and db.seance(1)["lien_manuel"] == 0


def test_cas_reel_au_demarrage_de_l_application(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    dossier = tmp_path / "prod"
    dossier.mkdir()
    base_avant_v4(dossier)
    monkeypatch.setenv("COACH_DATA_DIR", str(dossier))
    monkeypatch.setenv("COACH_PASSWORD", "x")
    import main
    with TestClient(main.app):
        pass                                                            # démarrage = migration + garde-fou
    assert lie_a(1) is None


@pytest.mark.parametrize("type_", ["Pull A", "pull_a", "PULL A", "Musculation Pull A", "Pull A — dos, biceps", "Pull A"])
def test_variantes_d_ecriture_de_pull_a(type_):
    assert services.famille_planifiee(type_) == "muscu"

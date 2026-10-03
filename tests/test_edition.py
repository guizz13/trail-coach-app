"""Section 5 du correctif v4 : modifier la semaine après validation, réajustement par Sensei."""

from datetime import date

import pytest

import db
import llm_client
import services
from test_liaison import planifier, realisee

AUJOURDHUI = date(2026, 10, 2)    # vendredi
LUNDI = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: AUJOURDHUI)


class FauxAjusteur:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []

    def ajustement_semaine(self, contexte, **_):
        self.appels.append(contexte)
        u = llm_client._charger_usage()
        u.nb_appels += 1
        u.input_tokens += 500
        llm_client._sauver_usage(u)
        return self.reponses.pop(0)


def seance(t, m, creneau="matin", **kw):
    return {"type": t, "creneau": creneau, "duree_min": m, "description": f"{t} {m} min", **kw}


# ---- 5.1 / 5.2 : édition + recalcul automatique ------------------------------------
def test_deplacer_la_muscu_relie_immediatement():
    muscu_p = planifier("2026-09-30", "muscu_push")          # prévue mercredi
    muscu = realisee("2026-10-01T08:00:00+02:00", "muscu")   # faite jeudi
    services.recalculer_semaine(LUNDI)
    assert db.planifiee(muscu_p)["statut"] == "decale"          # report d'un jour (complément v5)

    r = services.modifier_planifiee(muscu_p, {"date_seance": "2026-10-01"})
    assert r["seance"]["seance_realisee_id"] == muscu and r["seance"]["statut"] == "realise"
    assert db.seance(muscu)["verdict"] == "vert"
    etat = db.etat_semaine(LUNDI.isoformat())
    assert etat["plan_modifie"] and "Modification" in etat["modifications"][0]


def test_supprimer_une_seance_liee_refuse():
    squash_p = planifier("2026-09-30", "squash", "soir")
    realisee("2026-09-30T19:00:00+02:00", "squash")
    services.recalculer_semaine(LUNDI)
    with pytest.raises(services.Refus, match="délie"):
        services.supprimer_planifiee(squash_p)
    assert db.planifiee(squash_p) is not None


def test_edition_limitee_a_la_semaine_en_cours():
    with pytest.raises(ValueError, match="semaine en cours"):
        services.creer_planifiee({"date_seance": "2026-10-06", "type": "EF"})
    passee = planifier("2026-09-22", "EF")
    with pytest.raises(ValueError, match="semaine en cours"):
        services.modifier_planifiee(passee, {"duree_min": 30})


def test_bilan_recoit_les_modifications(monkeypatch):
    planifier("2026-09-30", "muscu_push")
    services.creer_planifiee({"date_seance": "2026-10-03", "type": "EF", "duree_min": 40})
    vu = {}

    class Faux:
        def bilan_hebdo(self, **ctx):
            vu.update(ctx)
            raise ConnectionError("pas d'appel réel")
    monkeypatch.setattr(services, "_llm", Faux())
    services.bilan_hebdo({"semaine_debut": "2026-10-05"})
    assert vu["indicateurs"]["modifications_du_plan"][0].startswith("Ajout : EF")


# ---- 5.3 : réajustement par Sensei -----------------------------------------------------
def preparer_semaine():
    planifier("2026-09-28", "muscu_pull")
    planifier("2026-09-30", "muscu_push")
    realisee("2026-09-28T08:00:00+02:00", "muscu")
    realisee("2026-09-30T08:00:00+02:00", "muscu")
    planifier("2026-10-01", "intervals")                     # manquée
    services.recalculer_semaine(LUNDI)


def test_etat_ajustement():
    preparer_semaine()
    e = services.etat_ajustement()
    assert e["possible"] and "séance manquée" in e["raisons"] and e["premier_jour"] == "2026-10-02"


def test_ajustement_invalide_puis_valide(monkeypatch):
    preparer_semaine()
    invalide = {"jours": [{"date": "2026-09-29", "seances": [seance("EF", 90)]}],          # mardi passé, 1h30
                "changements": ["x"], "message_coach": "x"}
    valide = {"jours": [{"date": "2026-10-03", "seances": [seance("sortie_longue", 100)]},
                        {"date": "2026-10-04", "seances": []}],
              "changements": ["Sortie longue raccourcie à 1h40"], "message_coach": "On ne rattrape pas mardi."}
    faux = FauxAjusteur(invalide, valide)
    monkeypatch.setattr(services, "_llm", faux)
    r = services.ajuster_semaine()
    assert len(faux.appels) == 2 and "erreur_tentative_precedente" in faux.appels[1]
    assert r["ok"] and r["changements"] == ["Sortie longue raccourcie à 1h40"]

    services.appliquer_ajustement(r["analyse_id"])
    plan = db.planifiees_entre("2026-10-03", "2026-10-04")
    assert [(p["type"], p["duree_min"]) for p in plan] == [("sortie_longue", 100)]
    assert not db.etat_semaine(LUNDI.isoformat())["plan_modifie"]
    with pytest.raises(ValueError, match="déjà appliqué"):
        services.appliquer_ajustement(r["analyse_id"])


def test_course_longue_un_mardi_rejetee_deux_fois(monkeypatch):
    preparer_semaine()
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 9, 29))   # mardi
    mauvais = {"jours": [{"date": "2026-09-29", "seances": [seance("EF", 90)]}], "changements": [], "message_coach": ""}
    faux = FauxAjusteur(mauvais, mauvais)
    monkeypatch.setattr(services, "_llm", faux)
    r = services.ajuster_semaine()
    assert len(faux.appels) == 2
    assert not r["ok"] and r["message"] == services.MESSAGE_AJUSTEMENT_INVALIDE
    assert any("1h15" in v for v in r["violations"])


def test_regles_dures_ajustement():
    preparer_semaine()
    lundi, premier = LUNDI, date(2026, 10, 2)
    # Mardi et jeudi sont vides : une proposition chargée vendredi-dimanche garde un repos
    plein = {"jours": [{"date": d, "seances": [seance("EF", 40)]} for d in ("2026-10-02", "2026-10-03", "2026-10-04")]}
    assert not any("repos" in x for x in services.valider_ajustement(plein, lundi, premier))
    realisee("2026-09-29T19:00:00+02:00", "squash")
    realisee("2026-10-01T19:00:00+02:00", "squash")
    assert any("repos" in x for x in services.valider_ajustement(plein, lundi, premier))
    combo = {"jours": [{"date": "2026-10-02", "seances": [seance("EF", 40), seance("muscu_pull", 50)]}]}
    assert any("Muscu et course" in x for x in services.valider_ajustement(combo, lundi, premier))
    week_end = {"jours": [{"date": "2026-10-03", "seances": [seance("EF", 40), seance("muscu_pull", 50)]}]}
    assert not any("Muscu et course" in x for x in services.valider_ajustement(week_end, lundi, premier))


def test_ajustement_vigilance_impact_eleve():
    # Vigilance Achille : badminton réalisé jeudi, EF proposée vendredi → deux jours d'impact élevé de suite
    preparer_semaine()
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille G"], "protocole": "kiné"})
    services.saisir_seance({"sport_id": "badminton", "debut": "2026-10-01T19:00", "duree_min": 60, "rpe": 7},
                           analyser=False)
    lundi, premier = LUNDI, date(2026, 10, 2)
    ef_vendredi = {"jours": [{"date": "2026-10-02", "seances": [seance("EF", 40)]}]}
    assert any("deux jours de suite" in x for x in services.valider_ajustement(ef_vendredi, lundi, premier))
    velo_vendredi = {"jours": [{"date": "2026-10-02", "seances": [seance("velo", 40)]}]}
    assert not any("deux jours de suite" in x for x in services.valider_ajustement(velo_vendredi, lundi, premier))

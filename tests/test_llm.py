"""Orchestration LLM (analyse, bilan, reconstruction) avec un faux client déterministe."""

from datetime import date

import pytest

import db
import llm_client
import services
from conftest import lire

AUJOURDHUI = date(2026, 9, 23)   # mercredi, jour de la séance tapis


class FauxLLM:
    """Renvoie des réponses préparées et comptabilise un usage comme le vrai client."""

    def __init__(self, **reponses):
        self.reponses = reponses
        self.appels = []

    def _repondre(self, type_appel, **ctx):
        self.appels.append((type_appel, ctx))
        u = llm_client._charger_usage()
        u.input_tokens += 1000
        u.output_tokens += 200
        u.cout_usd += 0.02
        u.nb_appels += 1
        llm_client._sauver_usage(u)
        r = self.reponses[type_appel]
        if isinstance(r, Exception):
            raise r
        return r

    def analyse_seance(self, **ctx):
        return self._repondre("analyse_seance", **ctx)

    def bilan_hebdo(self, **ctx):
        return self._repondre("bilan_hebdo", **ctx)

    def reconstruction_evenements(self, **ctx):
        return self._repondre("reconstruction_evenements", **ctx)


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: AUJOURDHUI)


def brancher(monkeypatch, **reponses) -> FauxLLM:
    faux = FauxLLM(**reponses)
    monkeypatch.setattr(services, "_llm", faux)
    return faux


def planifier(jour, type_, creneau="matin", **kw):
    return db.inserer("seances_planifiees", {"date_seance": jour, "creneau": creneau, "type": type_,
                                             "origine": "manuel", **kw})


ANALYSE_ORANGE = {
    "verdict": "orange", "type_detecte": "EF", "conforme_au_prevu": True,
    "analyse": "EF bien tenue.", "signaux": [],
    "ajustements": [{"jour": "vendredi", "seance_initiale": "intervals 6x3min",
                     "seance_proposee": "EF 40 min Z2", "raison": "Fatigue accumulée."}],
    "validation_requise": False,
}


# ---- analyse_seance --------------------------------------------------------
def test_analyse_ajustements_appliques(monkeypatch):
    faux = brancher(monkeypatch, analyse_seance=ANALYSE_ORANGE)
    planifier("2026-09-23", "EF", duree_min=30, distance_km=4)
    inter = planifier("2026-09-25", "intervals", detail="6x3min")

    r = services.importer_et_analyser(lire("course_tapis"), "tapis.json")
    assert r["verdict"] == "vert"               # EF conforme : le LLM n'aggrave pas sans signal de sécurité
    assert r["validation_requise"] is False
    assert r["ajustements_appliques"][0]["applique"] is True

    p = db.planifiee(inter)
    assert (p["type"], p["statut"], p["version"], p["duree_min"]) == ("EF", "modifie", 2, 40)
    assert "Fatigue" in p["detail"]

    # Contexte transmis au LLM
    _, ctx = faux.appels[0]
    assert ctx["prevu"]["type"] == "EF"
    assert "acwr" not in ctx["indicateurs"] and "distribution_semaine" in ctx["indicateurs"]
    assert "donnees_brutes" not in ctx["seance"]
    assert ctx["mode"] == "BASE" and ctx["statut_sante"] == "niveau: 100 %"

    # Trace en base avec tokens et coût
    a = db.analyse(r["analyse_id"])
    assert (a["tokens_in"], a["tokens_out"], a["cout_usd"]) == (1000, 200, 0.02)
    assert a["verdict"] == "vert" and a["valide_par_user"] == 1


def test_analyse_rouge_attend_validation(monkeypatch):
    rouge = {**ANALYSE_ORANGE, "verdict": "rouge", "validation_requise": True,
             "analyse": "Douleur au tendon d'Achille signalée en fin de séance."}
    brancher(monkeypatch, analyse_seance=rouge)
    planifier("2026-09-23", "EF")              # la séance tapis du jour (sinon : avance sur vendredi)
    inter = planifier("2026-09-25", "intervals")

    r = services.importer_et_analyser(lire("course_tapis"), "tapis.json")
    assert r["verdict"] == "rouge" and r["validation_requise"] is True
    assert db.planifiee(inter)["statut"] == "prevu"          # rien d'appliqué

    d = services.decider_ajustements(r["analyse_id"], accepter=True)
    assert d["ajustements_appliques"][0]["applique"] is True
    assert db.planifiee(inter)["type"] == "EF"
    with pytest.raises(ValueError):
        services.decider_ajustements(r["analyse_id"], accepter=False)


def test_garder_plan_initial(monkeypatch):
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "rouge", "analyse": "Douleur au mollet droit."})
    planifier("2026-09-23", "EF")
    inter = planifier("2026-09-25", "intervals")
    r = services.importer_et_analyser(lire("course_tapis"), "tapis.json")
    services.decider_ajustements(r["analyse_id"], accepter=False)
    assert db.planifiee(inter)["statut"] == "prevu"
    assert db.analyse(r["analyse_id"])["valide_par_user"] == -1


def test_llm_peut_adoucir_mais_pas_aggraver(monkeypatch):
    # EF prévue, 76 % en Z3+ : orange côté code
    planifier("2026-09-15", "EF")
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "vert", "ajustements": []})
    assert services.importer_et_analyser(lire("course_outdoor"), "o.json")["verdict"] == "vert"   # le plus bas


def test_llm_rouge_sans_securite_ignore(monkeypatch):
    planifier("2026-09-15", "EF")
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "rouge", "ajustements": [],
                                          "analyse": "Séance bien trop intense pour une EF."})
    assert services.importer_et_analyser(lire("course_outdoor"), "o.json")["verdict"] == "orange"


def test_llm_rouge_justifie_par_l_acwr_ignore(monkeypatch):
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "rouge", "ajustements": [],
                                          "analyse": "ACWR à 4,2 : risque de blessure, douleur probable."})
    assert services.importer_et_analyser(lire("squash"), "s.json")["verdict"] == "hors_plan"


def test_analyse_seance_sans_acwr(monkeypatch):
    faux = brancher(monkeypatch, analyse_seance=ANALYSE_ORANGE)
    services.importer_et_analyser(lire("course_tapis"), "t.json")
    _, ctx = faux.appels[0]
    assert "acwr" not in ctx["indicateurs"]


def test_ajustement_jour_passe_ignore(monkeypatch):
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "ajustements": [
        {"jour": "lundi", "seance_initiale": "EF", "seance_proposee": "repos", "raison": "x"}]})
    r = services.importer_et_analyser(lire("course_tapis"), "tapis.json")
    assert r["ajustements_appliques"][0] == {**r["ajustements"][0], "applique": False, "motif": "jour passé"}


def test_json_invalide_trace_et_import_conserve(monkeypatch):
    brancher(monkeypatch, analyse_seance=ValueError("Réponse LLM non-JSON pour analyse_seance : ...\nblabla"))
    r = services.importer_et_analyser(lire("squash"), "s.json")
    assert r["seance"]["id"]
    assert r["erreur_llm"]["type"] == "json_invalide"
    assert "blabla" in r["erreur_llm"]["message"]
    a = db.analyse(r["analyse_id"])
    assert a["cout_usd"] == 0.02 and "erreur" in a["reponse_json"]


def test_sans_llm_pas_de_trace():
    r = services.importer_et_analyser(lire("velo"), "v.json")
    assert r["erreur_llm"]["type"] == "ConnectionError"
    assert r["analyse_id"] is None
    assert db.fetch_all("SELECT * FROM analyses_llm") == []


def test_import_sans_analyse(monkeypatch):
    faux = brancher(monkeypatch, analyse_seance=ANALYSE_ORANGE)
    r = services.importer_et_analyser(lire("velo"), "v.json", analyser=False)
    assert faux.appels == [] and r["erreur_llm"] is None


# ---- bilan_hebdo -----------------------------------------------------------
def seance(jour, type_, creneau="matin", duree=60):
    return {"jour": jour, "creneau": creneau, "type": type_, "detail": f"{type_} {jour}",
            "intensite": "modérée", "duree_min": duree}


SEMAINE_OK = [
    seance("lundi", "muscu_pull"), seance("lundi", "squash", "soir"),
    seance("mardi", "intervals", duree=50), seance("mercredi", "squash", "soir"),
    seance("jeudi", "muscu_push"), seance("vendredi", "EF", duree=45),
    seance("samedi", "sortie_longue", duree=150),
]

# Vigilance Achille : jamais deux jours d'impact élevé (course, squash) de suite
SEMAINE_VIGILANCE = [
    seance("lundi", "muscu_pull"), seance("lundi", "squash", "soir"),
    seance("mardi", "velo", duree=50), seance("mercredi", "intervals", duree=50),
    seance("jeudi", "muscu_push"), seance("vendredi", "velo", duree=45),
    seance("samedi", "sortie_longue", duree=150),
]


def bilan(seances, jour_repos="dimanche"):
    return {"bilan": {"resume": "ok"}, "position_prepa": None,
            "semaine_suivante": {"objectif": "tenir", "seances": seances, "jour_repos": jour_repos,
                                 "alternatives": []},
            "message_coach": "Tiens la Z2."}


def test_regles_dures():
    assert services.verifier_regles(SEMAINE_OK, "dimanche")["bloquantes"] == []

    mauvaise = SEMAINE_OK + [seance("dimanche", "EF")]
    mauvaise[4] = seance("jeudi", "squash", "soir")                # plus qu'une muscu
    mauvaise.append(seance("mardi", "sortie_longue", duree=120))   # longue en semaine
    mauvaise.append(seance("mercredi", "muscu_push"))              # push + squash
    mauvaise.append(seance("vendredi", "EF", duree=90))            # course > 1h15 en semaine
    b = services.verifier_regles(mauvaise, "dimanche")["bloquantes"]
    texte = " | ".join(b)
    for attendu in ("repos", "Sortie longue placée en semaine", "PUSH et squash", "Course de 90 min"):
        assert attendu in texte, texte

    une_muscu = [s for s in SEMAINE_OK if s["type"] != "muscu_push"]
    assert "1 séance(s) de musculation haut du corps" in services.verifier_regles(une_muscu)["bloquantes"][0]
    jambes = une_muscu + [seance("jeudi", "muscu_jambes")]
    assert services.verifier_regles(jambes)["bloquantes"], "muscu jambes ne compte pas en haut du corps"


def test_bilan_puis_validation(monkeypatch):
    faux = brancher(monkeypatch, bilan_hebdo=bilan(SEMAINE_VIGILANCE))
    services.importer_et_analyser(lire("course_tapis"), "t.json", analyser=False)
    r = services.bilan_hebdo({"semaine_debut": "2026-09-28", "squash": [{"jour": "lundi", "creneau": "soir"}],
                              "contraintes": [{"jour": "jeudi", "creneau": "soir", "raison": "réunion"}],
                              "ressenti": 7, "sommeil": 6,
                              "sante": {"niveau": "vigilance", "zones": ["Achille G"], "note": "achille gauche",
                                        "protocole": "course 30 min max"}})   # le protocole prime sur le plafond +10 %
    assert r["regles"]["bloquantes"] == []
    assert services.sante_profil() == {"niveau": "vigilance", "zones": ["Achille G"], "note": "achille gauche",
                                       "protocole": "course 30 min max"}
    assert db.imperatifs("2026-09-28")["contraintes"][0]["raison"] == "réunion"

    _, ctx = faux.appels[0]
    assert [s["famille"] for s in ctx["semaine_ecoulee"]] == ["course_tapis"]
    assert len(ctx["historique_4sem"]) == 4
    assert ctx["indicateurs"]["volume_course_km"] == 3.85

    v = services.valider_semaine(r["analyse_id"])
    assert v["nb_seances"] == 8     # 7 séances + repos
    plan = db.planifiees_entre("2026-09-28", "2026-10-04")
    assert plan[0]["date_seance"] == "2026-09-28" and plan[0]["type"] == "muscu_pull"
    assert any(p["type"] == "repos" and p["date_seance"] == "2026-10-04" for p in plan)
    assert next(p for p in plan if p["type"] == "sortie_longue")["date_seance"] == "2026-10-03"

    # Revalider remplace au lieu de dupliquer
    services.valider_semaine(r["analyse_id"])
    assert len(db.planifiees_entre("2026-09-28", "2026-10-04")) == 8


def test_bilan_invalide_validation_refusee(monkeypatch):
    sans_repos = SEMAINE_OK + [seance("dimanche", "EF")]
    brancher(monkeypatch, bilan_hebdo=bilan(sans_repos, jour_repos=None))
    r = services.bilan_hebdo({"semaine_debut": "2026-09-28"})
    assert r["regles"]["bloquantes"]
    with pytest.raises(ValueError, match="règles dures"):
        services.valider_semaine(r["analyse_id"])
    assert db.planifiees_entre("2026-09-28", "2026-10-04") == []

    # Édition manuelle : on retire la séance du dimanche → validation acceptée
    services.valider_semaine(r["analyse_id"], SEMAINE_OK)
    assert len(db.planifiees_entre("2026-09-28", "2026-10-04")) == 7


def test_bilan_statut_invalide():
    with pytest.raises(ValueError):
        services.bilan_hebdo({"statut_sante": "bof"})


# ---- reconstruction --------------------------------------------------------
RECONSTRUCTION = {
    "analyse_conflits": "aucun", "mode_recommande": "RACE_PREP", "bascule_le": "2026-10-05",
    "plan_macro": [
        {"phase": "BASE", "du": "2026-10-05", "au": "2026-11-01", "objectif": "volume", "sortie_longue_cible": "20 km"},
        {"phase": "BUILD", "du": "2026-11-02", "au": "2026-12-06", "objectif": "D+"},
        {"phase": "INVENTEE", "du": "2026-12-07", "au": "2026-12-10"},
        {"phase": "AFFUTAGE", "du": "pas une date", "au": "2026-12-20"},
    ],
    "evenements_integres": [], "message_coach": "Cohérent.",
}


def test_reconstruction(monkeypatch):
    brancher(monkeypatch, reconstruction_evenements=RECONSTRUCTION)
    eid = db.inserer("evenements", {"type": "trail_race", "titre": "Ultra", "date_evt": "2026-12-27",
                                    "priorite": "A"})
    r = services.reconstruire(eid)
    assert [p["phase"] for p in r["plan_prepa"]] == ["BASE", "BUILD"]
    assert r["plan_prepa"][0]["evenement_id"] == eid
    assert r["bascule_proposee"] == {"de": "BASE", "vers": "RACE_PREP", "le": "2026-10-05"}
    assert db.profil()["mode_actif"] == "BASE"          # jamais appliqué automatiquement
    assert db.analyse(r["analyse_id"])["evenement_id"] == eid


def test_reconstruction_echec_conserve_plan(monkeypatch):
    brancher(monkeypatch, reconstruction_evenements=RECONSTRUCTION)
    services.reconstruire()
    brancher(monkeypatch, reconstruction_evenements=RuntimeError("Plafond mensuel LLM atteint"))
    r = services.reconstruire()
    assert r["erreur_llm"]["type"] == "plafond"
    assert len(r["plan_prepa"]) == 2


# ---- Recalcul des verdicts (sans appel LLM) ---------------------------------------
def test_recalcul_des_verdicts(monkeypatch):
    faux = brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "rouge", "ajustements": [],
                                                 "analyse": "Squash trop intense."})
    squash = services.importer_et_analyser(lire("squash"), "s.json")
    # Verdict laissé par l'ancienne logique (zones + LLM plus sévère)
    db.maj("analyses_llm", squash["analyse_id"], {"verdict": "rouge"})
    db.maj("seances_realisees", squash["seance"]["id"], {"verdict": "rouge"})
    planifier("2026-09-15", "EF")
    course = services.importer_et_analyser(lire("course_outdoor"), "o.json")
    services.importer_et_analyser(lire("velo"), "v.json", analyser=False)
    nb_appels = len(faux.appels)

    r = services.recalculer_tout()
    assert len(faux.appels) == nb_appels                                    # aucun appel LLM
    assert (r["seances"], r["analyses_mises_a_jour"], r["seances_sans_analyse"]) == (3, 2, 1)

    a = db.analyse(squash["analyse_id"])
    assert a["verdict"] == "hors_plan"                                      # squash hors plan, jamais d'alerte de zones
    assert a["reponse_json"]["analyse"] == "Squash trop intense."           # réponse du LLM conservée
    assert a["reponse_json"]["recalcul"]["verdict"] == "hors_plan"
    assert {"seance_id": squash["seance"]["id"], "date": "2026-08-27", "famille": "squash",
            "avant": "rouge", "apres": "hors_plan"} in r["changements"]

    c = db.analyse(course["analyse_id"])
    assert c["verdict"] == "orange"                                         # 76 % en Z3+ sur EF prévue
    assert "ef_intensite" in {s["nom"] for s in c["reponse_json"]["recalcul"]["signaux"]}


def test_ancien_format_sante_toujours_accepte(monkeypatch):
    brancher(monkeypatch, bilan_hebdo=bilan(SEMAINE_OK))
    services.bilan_hebdo({"semaine_debut": "2026-09-28", "statut_sante": "vigilance:achille gauche"})
    assert services.sante_profil()["zones"] == ["Achille G"]


# ---- Section 7 (v4) : progression plafonnée en vigilance sans protocole -------------------------
def test_vigilance_sans_protocole_nouvel_essai(monkeypatch):
    # 3 semaines d'historique : tapis 30 min le 23/09 et outdoor 35 min le 15/09 → moyenne 21,7 min → plafond 24
    services.importer_et_analyser(lire("course_tapis"), "t.json", analyser=False)
    services.importer_et_analyser(lire("course_outdoor"), "o.json", analyser=False)
    trop = SEMAINE_OK                                                     # 50 + 45 + 150 = 245 min de course
    sobre = [{**x, "duree_min": 20} if x["type"] == "EF" else x
             for x in SEMAINE_OK if x["type"] not in ("intervals", "sortie_longue")]   # 20 min de course
    faux = FauxLLM(bilan_hebdo=bilan(trop))
    reponses = [bilan(trop), bilan(sobre)]
    faux.bilan_hebdo = lambda **ctx: (faux.appels.append(("bilan_hebdo", ctx)), reponses.pop(0))[1]
    monkeypatch.setattr(services, "_llm", faux)
    r = services.bilan_hebdo({"semaine_debut": "2026-09-28", "sante": {"niveau": "vigilance", "zones": ["Achille D"]}})
    assert len(faux.appels) == 2
    assert "erreur_tentative_precedente" in faux.appels[1][1]["imperatifs"]
    assert not any("Vigilance" in b for b in r["regles"]["bloquantes"])


def test_vigilance_deux_echecs_bloquent_la_validation(monkeypatch):
    services.importer_et_analyser(lire("course_tapis"), "t.json", analyser=False)
    brancher(monkeypatch, bilan_hebdo=bilan(SEMAINE_OK))
    r = services.bilan_hebdo({"semaine_debut": "2026-09-28", "sante": {"niveau": "vigilance", "zones": ["Achille D"]}})
    assert any("Vigilance sans protocole" in b for b in r["regles"]["bloquantes"])
    with pytest.raises(ValueError, match="règles dures"):
        services.valider_semaine(r["analyse_id"])


def test_plafond_ne_s_applique_pas_avec_protocole_ou_sans_historique():
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille D"]})
    assert services.plafond_course_vigilance(date(2026, 9, 28)) is None          # aucun historique
    services.importer_et_analyser(lire("course_tapis"), "t.json", analyser=False)
    assert services.plafond_course_vigilance(date(2026, 9, 28)) == 11             # 30 min / 3 × 1,1
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille D"], "protocole": "30 min max"})
    assert services.plafond_course_vigilance(date(2026, 9, 28)) is None

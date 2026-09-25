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
    assert r["verdict"] == "orange"
    assert r["validation_requise"] is False
    assert r["ajustements_appliques"][0]["applique"] is True

    p = db.planifiee(inter)
    assert (p["type"], p["statut"], p["version"], p["duree_min"]) == ("EF", "modifie", 2, 40)
    assert "Fatigue" in p["detail"]

    # Contexte transmis au LLM
    _, ctx = faux.appels[0]
    assert ctx["prevu"]["type"] == "EF"
    assert "acwr" in ctx["indicateurs"] and "distribution_semaine" in ctx["indicateurs"]
    assert "donnees_brutes" not in ctx["seance"]
    assert ctx["mode"] == "BASE" and ctx["statut_sante"] == "100%"

    # Trace en base avec tokens et coût
    a = db.analyse(r["analyse_id"])
    assert (a["tokens_in"], a["tokens_out"], a["cout_usd"]) == (1000, 200, 0.02)
    assert a["verdict"] == "orange" and a["valide_par_user"] == 1


def test_analyse_rouge_attend_validation(monkeypatch):
    rouge = {**ANALYSE_ORANGE, "verdict": "rouge", "validation_requise": True}
    brancher(monkeypatch, analyse_seance=rouge)
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
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "rouge"})
    inter = planifier("2026-09-25", "intervals")
    r = services.importer_et_analyser(lire("course_tapis"), "tapis.json")
    services.decider_ajustements(r["analyse_id"], accepter=False)
    assert db.planifiee(inter)["statut"] == "prevu"
    assert db.analyse(r["analyse_id"])["valide_par_user"] == -1


def test_verdict_code_prime_sur_llm_plus_clement(monkeypatch):
    # Outdoor sur une EF prévue : 65 % Z3 → rouge côté code, même si le LLM dit vert
    brancher(monkeypatch, analyse_seance={**ANALYSE_ORANGE, "verdict": "vert", "ajustements": []})
    planifier("2026-09-15", "EF")
    r = services.importer_et_analyser(lire("course_outdoor"), "o.json")
    assert r["verdict"] == "rouge"


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
    faux = brancher(monkeypatch, bilan_hebdo=bilan(SEMAINE_OK))
    services.importer_et_analyser(lire("course_tapis"), "t.json", analyser=False)
    r = services.bilan_hebdo({"semaine_debut": "2026-09-28", "squash": [{"jour": "lundi", "creneau": "soir"}],
                              "contraintes": [{"jour": "jeudi", "creneau": "soir", "raison": "réunion"}],
                              "ressenti": 7, "sommeil": 6, "statut_sante": "vigilance:achille gauche"})
    assert r["regles"]["bloquantes"] == []
    assert db.profil()["statut_sante"] == "vigilance:achille gauche"
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

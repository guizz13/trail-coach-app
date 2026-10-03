"""Contexte LLM v5 : sport, catégorie, impact, RPE et source sur chaque séance réalisée ; prompt."""

from pathlib import Path

import services
from conftest import lire
from test_llm import ANALYSE_ORANGE, FauxLLM, date_fixe  # noqa: F401 (fixture)

CHAMPS = {"sport", "categorie", "impact", "rpe", "source"}


def test_prompt_contient_la_sous_section():
    prompt = (Path(__file__).parent.parent / "prompts" / "system_prompt_coach.md").read_text(encoding="utf-8")
    assert "### Sports pratiqués et charge mécanique" in prompt
    assert prompt.index("### Sports pratiqués") < prompt.index("## 7. ÉVÉNEMENTS")


def test_analyse_seance(monkeypatch):
    faux = FauxLLM(analyse_seance={**ANALYSE_ORANGE, "ajustements": []})
    monkeypatch.setattr(services, "_llm", faux)
    services.saisir_seance({"sport_id": "badminton", "debut": "2026-09-22T19:00", "duree_min": 60, "rpe": 7})
    seance = faux.appels[0][1]["seance"]
    assert CHAMPS <= set(seance)
    assert (seance["sport"], seance["categorie"], seance["impact"], seance["rpe"], seance["source"]) == \
        ("Badminton", "raquette", "eleve", 7, "manuel")


def test_ajustement_semaine(monkeypatch):
    services.importer_et_analyser(lire("course_tapis"), "t.json", analyser=False, rpe=4)
    ctx = {}

    def capturer(contexte, **_):
        ctx.update(contexte)
        raise ConnectionError("pas de LLM")
    monkeypatch.setattr(services._llm, "ajustement_semaine", capturer, raising=False)
    try:
        services.ajuster_semaine()
    except Exception:
        pass
    seance = ctx["realise"][0]
    assert CHAMPS <= set(seance) and seance["sport"] == "Course sur tapis" and seance["rpe"] == 4


def test_resume_semaines_par_sport():
    services.saisir_seance({"sport_id": "badminton", "debut": "2026-09-15T19:00", "duree_min": 60, "rpe": 7},
                           analyser=False)
    from datetime import date
    r = services.resume_semaines(1, date(2026, 9, 21))[0]
    assert r["seances_par_sport"] == {"Badminton": 1} and r["jours_impact_eleve"] == 1

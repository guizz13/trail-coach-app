"""Messages du coach : cap de la semaine en haut de Semaine, analyse de chaque séance réalisée."""

from datetime import date
from pathlib import Path

import pytest

import db
import services
from test_llm import ANALYSE_ORANGE, FauxLLM, SEMAINE_VIGILANCE, bilan

LUNDI = date(2026, 10, 12)
RESUME = {"titre": "Reprise prudente, tendon d'abord", "phrase": "Trois EF courtes, squash 45 min max.",
          "focus": ["Achille : 0 impact consécutif", "Squash ≤ 45 min", "2 muscu dont 1 Pull", "un de trop"]}


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 14))     # mercredi


def valider_un_bilan(monkeypatch, resume=RESUME):
    rep = {**bilan(SEMAINE_VIGILANCE), **({"resume_semaine": resume} if resume else {})}
    monkeypatch.setattr(services, "_llm", FauxLLM(bilan_hebdo=rep))
    r = services.bilan_hebdo({"semaine_debut": LUNDI.isoformat(), "ressenti": 7})
    services.valider_semaine(r["analyse_id"])
    return r["analyse_id"]


def test_sans_plan():
    assert services.cap_semaine(LUNDI) == {"plan": False, "lundi": "2026-10-12"}


def test_proposition_non_validee_pas_de_cap(monkeypatch):
    monkeypatch.setattr(services, "_llm", FauxLLM(bilan_hebdo={**bilan(SEMAINE_VIGILANCE), "resume_semaine": RESUME}))
    services.bilan_hebdo({"semaine_debut": LUNDI.isoformat(), "ressenti": 7})
    assert services.cap_semaine(LUNDI)["plan"] is False


def test_cap_du_plan_valide(monkeypatch):
    valider_un_bilan(monkeypatch)
    cap = services.cap_semaine(date(2026, 10, 15))                    # n'importe quel jour de la semaine
    assert cap["plan"] and cap["titre"] == RESUME["titre"] and cap["phrase"] == RESUME["phrase"]
    assert cap["focus"] == RESUME["focus"][:3] and cap["message_coach"] == "Tiens la Z2."
    assert cap["ajuste_le"] is None
    assert services.tableau_de_bord(date(2026, 10, 14))["cap_semaine"]["titre"] == RESUME["titre"]


def test_ancien_bilan_sans_resume(monkeypatch):
    valider_un_bilan(monkeypatch, resume=None)
    cap = services.cap_semaine(LUNDI)
    assert cap["titre"] is None and cap["phrase"] == "tenir" and cap["focus"] == []      # l'objectif est une phrase


def test_ajustement_applique_prend_la_place(monkeypatch):
    bilan_id = valider_un_bilan(monkeypatch)
    db.inserer("analyses_llm", {"type_appel": "ajustement_semaine", "semaine_debut": LUNDI.isoformat(),
                                "reponse_json": {"message_coach": "On allège jeudi."}, "valide_par_user": 0,
                                "cree_le": "2026-10-13T20:00:00+02:00"})
    assert services.cap_semaine(LUNDI)["ajuste_le"] is None             # proposé, pas appliqué
    db.inserer("analyses_llm", {"type_appel": "ajustement_semaine", "semaine_debut": LUNDI.isoformat(),
                                "reponse_json": {"message_coach": "On allège jeudi."}, "valide_par_user": 1,
                                "cree_le": "2026-10-13T20:05:00+02:00"})
    cap = services.cap_semaine(LUNDI)
    assert cap["phrase"] == cap["message_coach"] == "On allège jeudi." and cap["ajuste_le"] == "2026-10-13"
    assert cap["message_bilan"] == "Tiens la Z2." and cap["analyse_id"] == bilan_id


def test_prompt_resume_semaine():
    prompt = (Path(__file__).parent.parent / "prompts" / "system_prompt_coach.md").read_text(encoding="utf-8")
    section = prompt[prompt.index("### 10.2"):prompt.index("### 10.3")]
    assert '"resume_semaine"' in section and '"titre" 6 mots max' in section


def test_analyse_de_la_seance_la_plus_recente(monkeypatch):
    from conftest import lire
    monkeypatch.setattr(services, "_llm", FauxLLM(analyse_seance={**ANALYSE_ORANGE, "ajustements": []}))
    sid = services.importer_et_analyser(lire("course_tapis"), "t.json")["seance"]["id"]
    assert services.analyse_coach(sid)["texte"] == "EF bien tenue."
    assert db.analyses_seance(sid)[0]["seance_id"] == sid                  # rattachée à la séance
    # Réanalyse : la plus récente est affichée ; un échec n'efface pas la précédente
    monkeypatch.setattr(services, "_llm", FauxLLM(analyse_seance={**ANALYSE_ORANGE, "ajustements": [], "analyse": "Relecture."}))
    services.analyser_seance(sid)
    db.inserer("analyses_llm", {"type_appel": "analyse_seance", "seance_id": sid,
                                "reponse_json": {"erreur": {"type": "ConnectionError"}}})
    a = services.analyse_coach(sid)
    assert a["texte"] == "Relecture."
    seance = next(s for s in services.historique() if s["id"] == sid)
    assert seance["analyse_coach"]["texte"] == "Relecture."


def test_sans_analyse():
    sid = services.saisir_seance({"sport_id": "muscu", "debut": "2026-10-13T07:00", "duree_min": 50, "rpe": 6},
                                 analyser=False)["seance"]["id"]
    assert services.analyse_coach(sid) is None



# ---- v7 : garde-fou sur le cap -------------------------------------------------------------------------
def test_titre_trop_long_devient_la_phrase(monkeypatch, caplog):
    long_ = "Reprise prudente avec trois EF courtes et squash limité à 45 minutes"
    with caplog.at_level("WARNING", logger="sensei"):
        valider_un_bilan(monkeypatch, resume={"titre": long_, "focus": []})
        cap = services.cap_semaine(LUNDI)
    assert cap["titre"] == "Reprise prudente avec trois EF courtes" and cap["phrase"] == long_
    assert "trop long" in caplog.text


def test_phrase_trop_longue_coupee_aux_mots():
    titre, phrase = services._cap_borne("Cap court", " ".join(f"mot{i}" for i in range(25)))
    assert titre == "Cap court" and phrase.split()[-1] == "mot19…" and len(phrase.split()) == 20

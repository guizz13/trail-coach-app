"""Type et contenu d'une séance de musculation cohérents (Samedi 10 : « Push » décrit comme « Pull A »)."""

from datetime import date

import pytest

import db
import services
from test_llm import FauxLLM, bilan, seance


@pytest.mark.parametrize("type_,detail,attendu", [
    ("muscu_push", "Pull A : tractions 4x6-8, rowing 4x8", "muscu_pull"),
    ("muscu_pull", "Push B — développé couché, dips", "muscu_push"),
    ("muscu_push", "Jambes : squat, fentes", "muscu_jambes"),
    ("muscu_push", "Push A : développé couché", "muscu_push"),
    ("muscu_push", "Développé couché, élévations", "muscu_push"),      # pas d'indice : inchangé
    ("EF", "Pull A", "EF"),                                            # hors musculation : inchangé
    ("muscu_pull", None, "muscu_pull"),
])
def test_type_coherent(type_, detail, attendu):
    assert services.type_coherent(type_, detail) == attendu


def test_validation_du_plan_corrige_et_logge(monkeypatch, caplog):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 4))
    semaine = [seance("lundi", "muscu_pull"), seance("mardi", "EF", duree=45), seance("jeudi", "muscu_push"),
               {**seance("samedi", "muscu_push"), "detail": "Pull A : tractions 4x6-8, rowing"}]
    monkeypatch.setattr(services, "_llm", FauxLLM(bilan_hebdo=bilan(semaine)))
    r = services.bilan_hebdo({"semaine_debut": "2026-10-05", "ressenti": 7})
    with caplog.at_level("WARNING", logger="sensei"):
        services.valider_semaine(r["analyse_id"])
    samedi = [p for p in db.planifiees_entre("2026-10-10", "2026-10-10")]
    assert samedi[0]["type"] == "muscu_pull" and "incohérent" in caplog.text


def test_recalcul_admin_corrige_le_plan_existant():
    pid = db.inserer("seances_planifiees", {"date_seance": "2026-10-10", "creneau": "matin", "type": "muscu_push",
                                            "detail": "Pull A : tractions 4x6-8, rowing 4x8"})
    r = services.recalculer_tout()
    assert db.planifiee(pid)["type"] == "muscu_pull"
    assert r["types_corriges"] == [{"seance": "2026-10-10 muscu_push", "type": "muscu_pull"}]


def test_prompt():
    from pathlib import Path
    prompt = (Path(__file__).parent.parent / "prompts" / "system_prompt_coach.md").read_text(encoding="utf-8")
    regle = "Le type de chaque séance de musculation correspond exactement à son contenu."
    assert regle in prompt[prompt.index("### 10.2"):prompt.index("### 10.3")]
    assert regle in prompt[prompt.index("### 10.4"):prompt.index("## 11.")]

"""Préparer en étapes : saisie enrichie, VFC, pré-remplissage, proposition en attente, « Ajuster »."""

from datetime import date

import pytest

import db
import services
from test_api import anonyme, client  # noqa: F401 (fixtures)
from test_llm import FauxLLM, SEMAINE_VIGILANCE, bilan, seance

LUNDI = "2026-10-12"


@pytest.fixture(autouse=True)
def date_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 11))     # dimanche


class Coach(FauxLLM):
    def ajustement_semaine(self, contexte, **_):
        return self._repondre("ajustement_semaine", contexte=contexte)


SAISIE = {
    "semaine_debut": LUNDI, "ressenti": 6, "sommeil": 5, "fatigue_pro": 8, "vfc_ms": "52",
    "douleur_max": 2,
    "squash": [{"jour": "mercredi", "creneau": "soir"}],
    "contraintes": [{"jour": "jeudi", "contraintes": ["deplacement", "indispo_soir"]}],
    "sortie_longue": {"jour": "dimanche", "duree_max_min": 150},
    "autres_sports": [{"jour": "samedi", "sport_id": "badminton"}],
    "notes": "Genou un peu raide le matin.",
}


def test_saisie_enregistree():
    services.enregistrer_imperatifs(SAISIE)
    imp = db.imperatifs(LUNDI)
    assert (imp["fatigue_pro"], imp["vfc_ms"], imp["douleur_max"]) == (8, 52.0, 2)
    assert imp["contraintes"] == [{"jour": "jeudi", "contraintes": ["deplacement", "indispo_soir"]}]
    assert imp["sortie_longue"] == {"jour": "dimanche", "duree_max_min": 150}
    assert imp["autres_sports"] == [{"jour": "samedi", "sport_id": "badminton"}]


def test_rien_de_change_garde_la_sante():
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille G"], "protocole": "kiné"})
    services.enregistrer_imperatifs(SAISIE)                      # pas de clé « sante »
    assert services.sante_profil()["niveau"] == "vigilance"
    services.enregistrer_imperatifs({**SAISIE, "sante": {"niveau": "100"}})
    assert services.sante_profil()["niveau"] == "100"


@pytest.mark.parametrize("champ,valeur", [("fatigue_pro", 11), ("douleur_max", -1), ("vfc_ms", 400),
                                          ("notes", "x" * 201), ("autres_sports", [{"jour": "samedi", "sport_id": "kite"}]),
                                          ("squash", [{"jour": "funday", "creneau": "soir"}]),
                                          ("sortie_longue", {"jour": "mardi"})])
def test_saisie_invalide(champ, valeur):
    with pytest.raises(ValueError):
        services.enregistrer_imperatifs({**SAISIE, champ: valeur})


def test_tendance_vfc():
    for i, v in enumerate((60, 62, 58, 60)):
        db.sauver_imperatifs(f"2026-09-{14 + 7 * i:02d}", {"vfc_ms": v})
    t = services.tendance_vfc(date(2026, 10, 12), 52)
    assert t == {"valeur_ms": 52, "moyenne_4_semaines_ms": 60.0, "ecart_pct": -13.3, "tendance": "baisse",
                 "semaines_de_reference": 4}
    assert services.tendance_vfc(date(2026, 10, 12), 61)["tendance"] == "stable"
    assert services.tendance_vfc(date(2026, 9, 14), 61)["tendance"] is None          # aucun historique
    assert services.vfc_moyenne_4_semaines(date(2026, 10, 12)) == 60.0


def test_contexte_llm(monkeypatch):
    db.sauver_imperatifs("2026-10-05", {"vfc_ms": 60})
    faux = FauxLLM(bilan_hebdo=bilan(SEMAINE_VIGILANCE))
    monkeypatch.setattr(services, "_llm", faux)
    services.bilan_hebdo(SAISIE)
    imp = faux.appels[0][1]["imperatifs"]
    assert imp["fatigue_pro"] == 8 and imp["douleur_max_semaine_ecoulee"] == 2
    assert imp["vfc"]["tendance"] == "baisse" and imp["vfc"]["moyenne_4_semaines_ms"] == 60
    assert imp["contraintes"] == [{"jour": "jeudi", "contraintes": ["Déplacement", "Indispo soir"]}]
    assert imp["autres_sports_prevus"][0] == {"jour": "samedi", "sport_id": "badminton", "sport": "Badminton",
                                              "categorie": "raquette", "impact": "eleve"}
    assert imp["sortie_longue"]["jour"] == "dimanche" and imp["notes"].startswith("Genou")


def test_prompt_vfc():
    from pathlib import Path
    prompt = (Path(__file__).parent.parent / "prompts" / "system_prompt_coach.md").read_text(encoding="utf-8")
    section = prompt[prompt.index("### 10.2"):prompt.index("### 10.3")]
    assert "Tu ne conclus jamais sur une seule valeur." in section


def test_donnees_preparer_pre_remplissage():
    services.enregistrer_imperatifs({**SAISIE, "semaine_debut": "2026-10-05"})          # semaine précédente
    db.inserer("seances_planifiees", {"date_seance": "2026-10-08", "creneau": "matin", "type": "EF", "duree_min": 40})
    db.inserer("evenements", {"type": "squash_competition", "titre": "Open", "date_evt": "2026-10-17"})
    d = services.donnees_preparer()
    assert d["semaine_debut"] == LUNDI and d["imperatifs"] is None
    assert d["imperatifs_precedents"]["squash_jours"] == [{"jour": "mercredi", "creneau": "soir"}]
    assert d["sans_donnees"] == ["EF 40 min"]
    assert [e["titre"] for e in d["competitions"]] == ["Open"]
    assert d["bilan_semaine"]["lundi"] == "2026-10-05" and d["proposition"] is None


def test_proposition_en_attente_puis_validee(monkeypatch):
    monkeypatch.setattr(services, "_llm", FauxLLM(bilan_hebdo=bilan(SEMAINE_VIGILANCE)))
    r = services.bilan_hebdo(SAISIE)
    p = services.donnees_preparer(LUNDI)["proposition"]
    assert p["analyse_id"] == r["analyse_id"] and p["regles"]["bloquantes"] == []
    assert db.planifiees_entre(LUNDI, "2026-10-18") == []                # rien d'écrit avant « Valider »
    services.valider_semaine(r["analyse_id"])
    assert services.donnees_preparer(LUNDI)["proposition"] is None
    assert len(db.planifiees_entre(LUNDI, "2026-10-18")) == 8


def test_ajuster_la_proposition(monkeypatch):
    coach = Coach(bilan_hebdo=bilan(SEMAINE_VIGILANCE),
                  ajustement_semaine={"jours": [{"date": "2026-10-13", "seances": [seance("mardi", "natation", duree=45)]}],
                                      "changements": ["Vélo de mardi remplacé par natation"], "message_coach": "Natation mardi."})
    monkeypatch.setattr(services, "_llm", coach)
    r = services.bilan_hebdo(SAISIE)
    t = services.lancer_ajustement_proposition(r["analyse_id"], "Pas de vélo mardi, piscine plutôt")
    assert t["statut"] == "termine" and t["resultat"]["ok"]
    ctx = coach.appels[-1][1]["contexte"]
    assert ctx["demande_athlete"].startswith("Pas de vélo") and ctx["proposition_non_validee"]
    assert len(ctx["jours_restants"]) == 7
    seances = services.donnees_preparer(LUNDI)["proposition"]["reponse"]["semaine_suivante"]["seances"]
    mardi = [s["type"] for s in seances if s["jour"] == "mardi"]
    assert mardi == ["natation"] and len(seances) == 7
    assert db.planifiees_entre(LUNDI, "2026-10-18") == []                # toujours pas écrit


def test_ajustement_refuse_s_il_casse_les_regles(monkeypatch):
    sans_muscu = {"jours": [{"date": "2026-10-16", "seances": []}, {"date": "2026-10-12", "seances": []}],
                  "changements": [], "message_coach": "x"}
    coach = Coach(bilan_hebdo=bilan(SEMAINE_VIGILANCE), ajustement_semaine=sans_muscu)
    monkeypatch.setattr(services, "_llm", coach)
    r = services.bilan_hebdo(SAISIE)
    res = services.ajuster_proposition(r["analyse_id"], "moins de muscu")
    assert not res["ok"] and any("musculation" in v for v in res["violations"])
    assert len([a for a, _ in coach.appels if a == "ajustement_semaine"]) == 2      # un nouvel essai
    jeudi = [s["type"] for s in services.donnees_preparer(LUNDI)["proposition"]["reponse"]["semaine_suivante"]["seances"]]
    assert "muscu_push" in jeudi                                        # proposition inchangée


def test_routes(client, monkeypatch):
    assert client.get("/dimanche").headers["location"] == "/preparer"
    assert client.get("/preparer").status_code == 200
    d = client.get("/api/preparer?semaine=2026-10-14").json()
    assert d["semaine_debut"] == LUNDI and len(d["semaines_possibles"]) == 3

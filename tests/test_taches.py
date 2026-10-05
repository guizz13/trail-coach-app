"""Tâches IA persistantes : l'appel LLM vit côté serveur, la page peut changer."""

import json
import threading
import time

import pytest

import db
import llm_client
import services
import taches
from conftest import lire
from test_api import anonyme, client  # noqa: F401 (fixtures)
from test_llm import ANALYSE_ORANGE, FauxLLM, SEMAINE_VIGILANCE, bilan


def nb_appels_factures():
    return llm_client.cout_du_mois().nb_appels


def test_bilan_en_tache_puis_resultat(client, monkeypatch):
    monkeypatch.setattr(services, "_llm", FauxLLM(bilan_hebdo=bilan(SEMAINE_VIGILANCE)))
    t = client.post("/api/bilan", json={"semaine_debut": "2026-10-12", "ressenti": 7, "sommeil": 7}).json()
    assert t["statut"] == "termine" and t["cle"] == "bilan_hebdo:2026-10-12"
    assert t["resultat"]["reponse"]["message_coach"] == "Tiens la Z2."
    assert [x["id"] for x in client.get("/api/taches?actives=1").json()] == [t["id"]]      # terminée, pas vue
    assert client.post(f"/api/taches/{t['id']}/vue").json()["vue"] is True
    assert client.get("/api/taches?actives=1").json() == []
    assert nb_appels_factures() == 1


def test_saisie_invalide_refusee_sans_tache(client):
    assert client.post("/api/bilan", json={"ressenti": 12}).status_code == 422
    assert db.fetch_all("SELECT * FROM taches_ia") == []


def test_double_tap_une_seule_tache(client, monkeypatch):
    faux = FauxLLM(bilan_hebdo=bilan(SEMAINE_VIGILANCE))
    monkeypatch.setattr(services, "_llm", faux)
    # Une génération est déjà en cours pour cette semaine
    db.inserer("taches_ia", {"id": "deja", "type": "bilan_hebdo", "cle": "bilan_hebdo:2026-10-12",
                             "statut": "en_cours", "cree_le": taches._maintenant()})
    t = client.post("/api/bilan", json={"semaine_debut": "2026-10-12", "ressenti": 7}).json()
    assert t["id"] == "deja" and t["statut"] == "en_cours"
    assert faux.appels == [] and nb_appels_factures() == 0


def test_redemarrage_pendant_une_tache():
    db.inserer("taches_ia", {"id": "x", "type": "bilan_hebdo", "cle": "bilan_hebdo:2026-10-12",
                             "statut": "en_cours", "cree_le": taches._maintenant()})
    assert taches.interrompre_au_demarrage() == 1
    t = taches.lire("x")
    assert t["statut"] == "erreur" and "redémarrage" in t["erreur"]
    assert [x["id"] for x in taches.actives()] == ["x"]           # bandeau rouge « Réessayer »


def test_au_demarrage_de_l_application(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("COACH_PASSWORD", "x")
    db.inserer("taches_ia", {"id": "y", "type": "analyse_seance", "cle": "analyse_seance:1",
                             "statut": "en_cours", "cree_le": taches._maintenant()})
    import main
    with TestClient(main.app):
        pass
    assert taches.lire("y")["statut"] == "erreur"


def test_tache_perdue_expire():
    db.inserer("taches_ia", {"id": "vieille", "type": "bilan_hebdo", "cle": "bilan_hebdo:2026-10-12",
                             "statut": "en_cours", "cree_le": "2026-01-01T08:00:00+01:00"})
    assert taches.lire("vieille")["statut"] == "erreur"


def test_relancer(client, monkeypatch):
    t = client.post("/api/bilan", json={"semaine_debut": "2026-10-12", "ressenti": 7}).json()
    assert t["statut"] == "erreur"                                   # pas de LLM
    monkeypatch.setattr(services, "_llm", FauxLLM(bilan_hebdo=bilan(SEMAINE_VIGILANCE)))
    t2 = client.post(f"/api/taches/{t['id']}/relancer").json()
    assert t2["id"] != t["id"] and t2["statut"] == "termine"
    assert taches.lire(t["id"])["vue"] is True


def test_import_verdict_immediat_analyse_en_tache(client, monkeypatch):
    monkeypatch.setattr(services, "_llm", FauxLLM(analyse_seance={**ANALYSE_ORANGE, "ajustements": []}))
    r = client.post("/api/import", files={"fichier": ("t.json", lire("course_tapis"))}).json()
    assert r["verdict"] == "hors_plan" and r["analyse_llm"] is None          # sans attendre le coach
    t = r["tache"]
    assert t["cle"] == f"analyse_seance:{r['seance']['id']}" and t["statut"] == "termine"
    assert t["resultat"]["analyse_llm"]["analyse"] == "EF bien tenue."
    # Sans analyse demandée : pas de tâche
    r = client.post("/api/import", files={"fichier": ("v.json", lire("velo"))},
                    data={"options": json.dumps({"analyser": False})}).json()
    assert "tache" not in r


def test_analyser_plus_tard(client, monkeypatch):
    sid = client.post("/api/import", files={"fichier": ("v.json", lire("velo"))},
                      data={"options": json.dumps({"analyser": False})}).json()["seance"]["id"]
    monkeypatch.setattr(services, "_llm", FauxLLM(analyse_seance={**ANALYSE_ORANGE, "ajustements": []}))
    t = client.post(f"/api/seances_realisees/{sid}/analyser").json()
    assert t["statut"] == "termine" and db.analyses_seance(sid)[0]["type_appel"] == "analyse_seance"


def test_reconstruction_rejouee_si_en_cours(monkeypatch):
    """Deux événements ajoutés pendant une reconstruction : une seule relance, après la première."""
    monkeypatch.setattr(taches, "SYNCHRONE", False)
    debut, fin = threading.Event(), threading.Event()
    appels = []

    def lente(p):
        appels.append(p)
        debut.set()
        fin.wait(5)
        return {"reponse": {"ok": True}}
    t1 = taches.lancer("reconstruction_evenements", "reconstruction_evenements", {"n": 1}, lente, rejouer_si_en_cours=True)
    debut.wait(5)
    t2 = taches.lancer("reconstruction_evenements", "reconstruction_evenements", {"n": 2}, lente, rejouer_si_en_cours=True)
    t3 = taches.lancer("reconstruction_evenements", "reconstruction_evenements", {"n": 3}, lente, rejouer_si_en_cours=True)
    assert t1["id"] == t2["id"] == t3["id"] and t1["statut"] == "en_cours"
    fin.set()
    for _ in range(100):
        if len(appels) == 2 and taches.derniere("reconstruction_evenements")["statut"] == "termine":
            break
        time.sleep(0.05)
    assert [a["n"] for a in appels] == [1, 3]
    assert taches.lire(t1["id"])["vue"] is True                       # remplacée par la relance


def test_vrai_fond_puis_changement_d_onglet(client, monkeypatch):
    """Tâche réellement en arrière-plan : la page peut partir, l'état reste lisible côté serveur."""
    monkeypatch.setattr(taches, "SYNCHRONE", False)
    libere = threading.Event()

    class Lent(FauxLLM):
        def bilan_hebdo(self, **ctx):
            libere.wait(5)
            return super().bilan_hebdo(**ctx)
    monkeypatch.setattr(services, "_llm", Lent(bilan_hebdo=bilan(SEMAINE_VIGILANCE)))
    t = client.post("/api/bilan", json={"semaine_debut": "2026-10-12", "ressenti": 7}).json()
    assert t["statut"] == "en_cours"
    # « Changement d'onglet » : une autre page interroge les tâches actives
    assert [x["statut"] for x in client.get("/api/taches?actives=1").json()] == ["en_cours"]
    assert client.post("/api/bilan", json={"semaine_debut": "2026-10-12", "ressenti": 7}).json()["id"] == t["id"]
    libere.set()
    for _ in range(100):
        if client.get(f"/api/taches/{t['id']}").json()["statut"] != "en_cours":
            break
        time.sleep(0.05)
    assert client.get(f"/api/taches/{t['id']}").json()["statut"] == "termine"
    assert nb_appels_factures() == 1                                 # un seul appel facturé

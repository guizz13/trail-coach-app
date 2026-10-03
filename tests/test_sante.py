"""Section 6 du correctif v4 : statut santé structuré, pastille courte, phase de prépa normalisée."""

import sqlite3
import subprocess

import pytest

import db
import services


def test_libelle_court():
    assert services.sante_libelle_court({"niveau": "100", "zones": []}) == {"texte": "Santé 100 %", "couleur": "vert"}
    v = services.sante_libelle_court({"niveau": "vigilance", "zones": ["Achille G", "Achille D"]})
    assert v == {"texte": "Vigilance · Achille D+G", "couleur": "orange"}
    b = services.sante_libelle_court({"niveau": "blessure", "zones": ["Fascia G", "Genou D", "Dos"]})
    assert b == {"texte": "Blessure · 3 zones", "couleur": "rouge"}
    assert services.sante_libelle_court({"niveau": "vigilance", "zones": ["Hanche"]})["texte"] == "Vigilance · Hanche"


def test_enregistrer_sante_et_texte_llm():
    s = services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille D", "Inconnue"], "note": "gêne au réveil",
                                    "protocole": "course 30 min max, +5 min/sem si 0 douleur J+1"})
    assert s["zones"] == ["Achille D"]
    assert services.texte_sante_llm(s) == ("niveau: vigilance | zones: Achille D | note: gêne au réveil | "
                                           "protocole kiné: course 30 min max, +5 min/sem si 0 douleur J+1")
    with pytest.raises(ValueError):
        services.enregistrer_sante({"niveau": "moyen"})


def test_migration_du_texte_libre(tmp_path, monkeypatch):
    ancien = subprocess.run(["git", "show", "31f6211:backend/schema.sql"], capture_output=True, text=True).stdout
    tmp_path = tmp_path / "ancienne_base"          # base distincte de celle créée par la fixture
    tmp_path.mkdir()
    c = sqlite3.connect(tmp_path / "coach.db")
    c.executescript(ancien)
    c.execute("UPDATE profil SET statut_sante = 'vigilance:achille gauche et droit, tendinopathie' WHERE id = 1")
    c.commit()
    c.close()
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    db.init_db()
    assert services.sante_profil() == {"niveau": "vigilance", "zones": ["Achille G", "Achille D"],
                                       "note": "achille gauche et droit, tendinopathie", "protocole": None}


@pytest.mark.parametrize("brut,code,detail", [
    ("BUILD", "BUILD", None),
    ("affûtage", "AFFUTAGE", "affûtage"),
    ("Reprise post-Achille semaine 2/4", "BASE", "Reprise post-Achille semaine 2/4"),
    ("phase de pic", "PIC", "phase de pic"),
    ("transition", "LIBRE", "transition"),
])
def test_phase_normalisee(brut, code, detail):
    pp = services.normaliser_position_prepa({"phase": brut, "semaine": "2/4"})
    assert pp["phase"] == code and pp.get("detail") == detail and pp["semaine"] == "2/4"


def test_dashboard_expose_la_pastille():
    services.enregistrer_sante({"niveau": "blessure", "zones": ["Mollet D"]})
    d = services.tableau_de_bord()
    assert d["sante"]["texte"] == "Blessure · Mollet D" and d["sante"]["couleur"] == "rouge"

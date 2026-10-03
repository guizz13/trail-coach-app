"""Liaison, verdicts et impact par catégorie du catalogue."""

from datetime import date

import pytest

import db
import metrics
import services


def prevoir(jour, type_, creneau="soir", duree=60):
    return db.inserer("seances_planifiees", {"date_seance": jour, "creneau": creneau, "type": type_,
                                             "duree_min": duree, "statut": "prevu", "origine": "manuel"})


def saisir(sport, debut, duree=60, rpe=7):
    return services.saisir_seance({"sport_id": sport, "debut": debut, "duree_min": duree, "rpe": rpe},
                                  analyser=False)["seance"]["id"]


def lie_a(planifiee_id):
    return db.planifiee(planifiee_id)["seance_realisee_id"]


@pytest.fixture(autouse=True)
def jour_fixe(monkeypatch):
    monkeypatch.setattr(services, "aujourdhui", lambda: date(2026, 10, 4))


def test_categories_des_types_prevus():
    c = services.categorie_planifiee
    assert [c("EF"), c("sortie_longue"), c("muscu_push"), c("Pull A"), c("squash"), c("velo")] == \
        ["course", "course", "force", "force", "raquette", "porte"]
    assert [c("badminton"), c("Badminton"), c("natation"), c("Yoga"), c("repos")] == \
        ["raquette", "raquette", "porte", "mobilite", None]


def test_badminton_lie_au_squash_avec_substitution():
    p = prevoir("2026-10-01", "squash")
    sid = saisir("badminton", "2026-10-01T19:00")
    assert lie_a(p) == sid
    d = services.detail_seance(sid)
    assert d["substitution"] == "Substitution : badminton au lieu de squash"
    assert services.detail_seance(saisir("squash", "2026-10-02T19:00"))["substitution"] is None


def test_pas_de_liaison_entre_categories():
    p = prevoir("2026-10-01", "EF", "matin", 45)
    saisir("badminton", "2026-10-01T08:00")
    assert lie_a(p) is None


def test_course_trail_liee_a_une_ef_sans_substitution():
    p = prevoir("2026-10-01", "EF", "matin", 45)
    sid = saisir("trail", "2026-10-01T08:00", 45, 3)
    assert lie_a(p) == sid and services.detail_seance(sid)["substitution"] is None


def test_sport_a_preciser_jamais_lie():
    p = prevoir("2026-10-01", "squash")
    sid = saisir("squash", "2026-10-01T19:00")
    db.maj("seances_realisees", sid, {"sport_a_preciser": 1})
    services.recalculer_tout()
    assert lie_a(p) is None


def _eval(sport, prevu=None, sante=None, **kw):
    r = {"sport_id": sport, "duree_min": 60, "temps_zones_pct": {"z2": 40, "z3": 30, "z4": 30}, **kw}
    return metrics.evaluer_seance(r, prevu, sante)


def test_zones_seulement_pour_les_sports_de_course():
    assert _eval("trail", {"type": "EF", "duree_min": 60})[0] == "orange"
    assert _eval("badminton", {"type": "squash", "duree_min": 60})[0] == "vert"
    assert _eval("velo_route", {"type": "velo", "duree_min": 60})[0] == "vert"


def test_ecarts_de_duree_par_categorie():
    long_ = {"type": "squash", "duree_min": 40}
    assert _eval("padel", long_)[0] == "vert"                                    # raquette : plus long, jamais un écart
    assert _eval("padel", {"type": "squash", "duree_min": 120})[0] == "orange"   # < 60 %
    assert _eval("crossfit", {"type": "muscu_push", "duree_min": 40})[0] == "vert"
    assert _eval("natation", {"type": "velo", "duree_min": 40})[0] == "orange"   # porté : ± 25 %


def test_mobilite_hors_plan_neutre():
    v, signaux = _eval("yoga", None, douleur=5)
    assert v == "hors_plan" and all(x.niveau == "info" for x in signaux)


BLESSURE = {"niveau": "blessure", "zones": ["Achille G"]}


def test_impact_eleve_en_blessure_rouge():
    v, signaux = _eval("badminton", None, BLESSURE)
    assert v == "rouge" and signaux[0].nom == "impact_en_blessure"
    assert _eval("course_route", None, BLESSURE)[1][0].nom == "course_en_blessure"
    assert _eval("natation", None, BLESSURE)[0] == "hors_plan"                   # impact faible
    assert _eval("badminton", None, {"niveau": "blessure", "zones": ["Épaule"]})[0] == "hors_plan"


def seance(jour, type_, creneau="matin", duree=60):
    return {"jour": jour, "type": type_, "creneau": creneau, "duree_min": duree}


SEMAINE = [seance("lundi", "muscu_pull"), seance("mardi", "EF", duree=45), seance("jeudi", "muscu_push"),
           seance("samedi", "badminton", "soir", 75), seance("dimanche", "EF", duree=60)]


def test_vigilance_badminton_samedi_course_dimanche_rejete():
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Achille G"], "protocole": "kiné"})
    b = services.verifier_regles(SEMAINE, lundi=date(2026, 10, 5))["bloquantes"]
    assert any("deux jours de suite" in x and "badminton samedi" in x and "dimanche" in x for x in b)
    services.enregistrer_sante({"niveau": "100"})
    assert services.verifier_regles(SEMAINE, lundi=date(2026, 10, 5))["bloquantes"] == []


def test_vigilance_compte_la_veille_du_lundi():
    services.enregistrer_sante({"niveau": "vigilance", "zones": ["Mollet D"], "protocole": "kiné"})
    saisir("football", "2026-10-04T10:00")
    semaine = [seance("lundi", "EF", duree=40), seance("mardi", "muscu_pull"), seance("jeudi", "muscu_push")]
    b = services.verifier_regles(semaine, lundi=date(2026, 10, 5))["bloquantes"]
    assert any("football dimanche" in x for x in b)


def test_blessure_impact_eleve_prevu_rejete():
    services.enregistrer_sante({"niveau": "blessure", "zones": ["Achille D"]})
    semaine = [seance("lundi", "muscu_pull"), seance("mercredi", "padel", "soir"), seance("jeudi", "muscu_push")]
    b = services.verifier_regles(semaine, lundi=date(2026, 10, 5))["bloquantes"]
    assert any("padel" in x and "interdit" in x for x in b)

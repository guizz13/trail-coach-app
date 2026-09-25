"""
API HTTP et pages du coach.

Lancement (depuis la racine du projet) :
    COACH_PASSWORD=... uvicorn backend.main:app --host 0.0.0.0 --port 8000

Toutes les routes sont protégées par mot de passe (COACH_PASSWORD), sauf /login.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

# Les modules métier s'importent à plat (import db, import metrics…)
BACKEND = Path(__file__).parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("COACH_DATA_DIR", str(BACKEND.parent / "data"))

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import db  # noqa: E402
import services  # noqa: E402

FRONTEND = BACKEND.parent / "frontend"
TAILLE_MAX_FICHIER = 25 * 1024 * 1024

# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------
COOKIE = "coach_session"
DUREE_SESSION_S = 30 * 24 * 3600
ROUTES_PUBLIQUES = {"/login"}
ECHECS_MAX = 5
FENETRE_ECHECS_S = 15 * 60
_echecs: dict[str, list[float]] = {}


def _mot_de_passe() -> str:
    mdp = os.getenv("COACH_PASSWORD")
    if not mdp:
        raise RuntimeError("COACH_PASSWORD non défini : l'application refuse de démarrer sans mot de passe.")
    return mdp


def _cle() -> bytes:
    # Dérivée du mot de passe : le changer invalide toutes les sessions
    return hashlib.sha256(f"coach-session-v1:{_mot_de_passe()}".encode()).digest()


def _jeton(expire: int) -> str:
    sig = hmac.new(_cle(), str(expire).encode(), hashlib.sha256).hexdigest()
    return f"{expire}.{sig}"


def _jeton_valide(jeton: Optional[str]) -> bool:
    if not jeton or "." not in jeton:
        return False
    expire, _, sig = jeton.partition(".")
    if not expire.isdigit() or int(expire) < time.time():
        return False
    attendu = hmac.new(_cle(), expire.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, attendu)


def _mdp_correct(saisi: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(saisi.encode()).digest(),
        hashlib.sha256(_mot_de_passe().encode()).digest(),
    )


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _trop_d_echecs(ip: str) -> bool:
    maintenant = time.time()
    _echecs[ip] = [t for t in _echecs.get(ip, []) if maintenant - t < FENETRE_ECHECS_S]
    return len(_echecs[ip]) >= ECHECS_MAX


def _https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _suite_sure(suite: Optional[str]) -> str:
    """Évite les redirections ouvertes : chemin local uniquement."""
    if suite and suite.startswith("/") and not suite.startswith("//") and "\\" not in suite:
        return suite
    return "/"


@asynccontextmanager
async def _cycle_de_vie(_: FastAPI):
    _mot_de_passe()
    db.init_db()
    yield


app = FastAPI(title="Coach Hybride", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=_cycle_de_vie)


@app.middleware("http")
async def _authentification(request: Request, call_next):
    if request.url.path in ROUTES_PUBLIQUES or _jeton_valide(request.cookies.get(COOKIE)):
        reponse = await call_next(request)
        if request.url.path.startswith("/static/"):
            # Revalidation systématique (ETag) : une mise à jour du JS/CSS est vue aussitôt
            reponse.headers["Cache-Control"] = "no-cache"
        return reponse
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Authentification requise."}, status_code=401)
    return RedirectResponse(f"/login?suite={quote(request.url.path)}", status_code=303)


PAGE_LOGIN = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coach — connexion</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f4f5f7;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}}
form{{background:#fff;padding:24px;border-radius:12px;box-shadow:0 1px 4px #0002;width:min(320px,90vw)}}
h1{{font-size:1.2rem;margin:0 0 16px}}
input,button{{width:100%;box-sizing:border-box;padding:12px;font-size:1rem;border-radius:8px}}
input{{border:1px solid #ccc;margin-bottom:12px}}
button{{border:0;background:#1f6feb;color:#fff;font-weight:600}}
.err{{color:#c62828;margin:0 0 12px}}
@media (prefers-color-scheme:dark){{body{{background:#111}}form{{background:#1c1c1e;color:#eee}}input{{background:#2c2c2e;color:#eee;border-color:#444}}}}
</style></head><body>
<form method="post" action="/login">
<h1>Coach Hybride</h1>
{erreur}
<input type="hidden" name="suite" value="{suite}">
<input type="password" name="password" placeholder="Mot de passe" autocomplete="current-password" autofocus required>
<button type="submit">Entrer</button>
</form></body></html>"""


def _page_login(suite: str, erreur: str = "", status: int = 200) -> HTMLResponse:
    import html
    bloc = f'<p class="err">{html.escape(erreur)}</p>' if erreur else ""
    return HTMLResponse(PAGE_LOGIN.format(erreur=bloc, suite=html.escape(suite, quote=True)),
                        status_code=status)


@app.get("/login", response_class=HTMLResponse)
def login_page(suite: str = "/"):
    return _page_login(_suite_sure(suite))


@app.post("/login")
def login(request: Request, password: str = Form(...), suite: str = Form("/")):
    suite = _suite_sure(suite)
    ip = _ip(request)
    if _trop_d_echecs(ip):
        return _page_login(suite, "Trop de tentatives. Réessayer dans 15 minutes.", 429)
    if not _mdp_correct(password):
        _echecs.setdefault(ip, []).append(time.time())
        time.sleep(0.5)
        return _page_login(suite, "Mot de passe incorrect.", 401)
    _echecs.pop(ip, None)
    rep = RedirectResponse(suite, status_code=303)
    rep.set_cookie(COOKIE, _jeton(int(time.time()) + DUREE_SESSION_S), max_age=DUREE_SESSION_S,
                   httponly=True, samesite="lax", secure=_https(request), path="/")
    return rep


@app.post("/logout")
def logout():
    rep = RedirectResponse("/login", status_code=303)
    rep.delete_cookie(COOKIE, path="/")
    return rep


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
PAGES = {"/": "index.html", "/import": "import.html", "/dimanche": "dimanche.html",
         "/evenements": "evenements.html", "/historique": "historique.html"}


def _servir(fichier: str):
    return lambda: FileResponse(FRONTEND / fichier, headers={"Cache-Control": "no-cache"})


for _chemin, _fichier in PAGES.items():
    app.add_api_route(_chemin, _servir(_fichier), methods=["GET"], include_in_schema=False)

app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")


# ---------------------------------------------------------------------------
# API — erreurs
# ---------------------------------------------------------------------------
@app.exception_handler(services.ErreurImport)
def _erreur_import(_: Request, e: services.ErreurImport):
    return JSONResponse({"detail": str(e)}, status_code=422)


@app.exception_handler(ValueError)
def _erreur_valeur(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=422)


def _lire(f: UploadFile) -> bytes:
    contenu = f.file.read(TAILLE_MAX_FICHIER + 1)
    if len(contenu) > TAILLE_MAX_FICHIER:
        raise HTTPException(413, f"{f.filename} : fichier trop volumineux.")
    return contenu


def _ou_404(x, quoi: str = "Ressource"):
    if x is None:
        raise HTTPException(404, f"{quoi} introuvable.")
    return x


# ---------------------------------------------------------------------------
# API — dashboard & profil
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def api_dashboard():
    return services.tableau_de_bord()


@app.get("/api/semaine")
def api_semaine(lundi: str):
    from datetime import date
    return services.semaine(services.lundi_de(date.fromisoformat(lundi)))


@app.patch("/api/profil")
def api_profil(valeurs: dict = Body(...)):
    autorises = {"mode_actif", "statut_sante", "notes_sante", "poids_kg"}
    maj = {k: v for k, v in valeurs.items() if k in autorises}
    if "mode_actif" in maj and maj["mode_actif"] not in ("BASE", "RACE_PREP"):
        raise ValueError("Mode invalide.")
    db.maj_profil(**maj)
    return db.profil()


# ---------------------------------------------------------------------------
# API — import
# ---------------------------------------------------------------------------
@app.post("/api/import/apercu")
def api_apercu(fichiers: List[UploadFile] = File(...)):
    resultats = []
    for f in fichiers:
        try:
            resultats.append(services.apercu_import(_lire(f), f.filename or "fichier.json"))
        except services.ErreurImport as e:
            resultats.append({"nom": f.filename, "erreur": str(e)})
    return resultats


@app.post("/api/import")
def api_import(fichier: UploadFile = File(...), options: str = Form("{}")):
    try:
        opts = json.loads(options or "{}")
    except json.JSONDecodeError:
        raise HTTPException(422, "Options invalides (JSON attendu).")
    return services.importer_et_analyser(
        _lire(fichier), fichier.filename or "fichier.json",
        muscu_detail=opts.get("muscu_detail"),
        famille=opts.get("famille") or None,
        sous_type=opts.get("sous_type") or None,
        analyser=opts.get("analyser", True) is not False,
    )


# Protégée comme toute l'API par la session (COACH_PASSWORD) : voir _authentification
@app.post("/api/admin/recalculate")
def api_admin_recalculer():
    return services.recalculer_verdicts()


@app.post("/api/analyses/{id_}/decision")
def api_decision(id_: int, corps: dict = Body(...)):
    return services.decider_ajustements(id_, bool(corps.get("accepter")))


# ---------------------------------------------------------------------------
# API — dimanche (bilan hebdo)
# ---------------------------------------------------------------------------
@app.get("/api/dimanche")
def api_dimanche():
    lundi = services.semaine_a_planifier()
    return {"semaine_debut": lundi.isoformat(), "imperatifs": db.imperatifs(lundi.isoformat()),
            "profil": db.profil(), "jours": services.JOURS}


@app.post("/api/bilan")
def api_bilan(imperatifs: dict = Body(...)):
    return services.bilan_hebdo(imperatifs)


@app.post("/api/bilan/{id_}/verifier")
def api_bilan_verifier(id_: int, corps: dict = Body(...)):
    a = _ou_404(db.analyse(id_), "Bilan")
    jour_repos = ((a["reponse_json"] or {}).get("semaine_suivante") or {}).get("jour_repos")
    return services.verifier_regles(corps.get("seances") or [], jour_repos)


@app.post("/api/bilan/{id_}/valider")
def api_bilan_valider(id_: int, corps: dict = Body(default={})):
    return services.valider_semaine(id_, corps.get("seances"))


# ---------------------------------------------------------------------------
# API — historique
# ---------------------------------------------------------------------------
@app.get("/api/seances")
def api_seances(famille: Optional[str] = None, du: Optional[str] = None, au: Optional[str] = None):
    return services.historique(famille, du, au)


@app.get("/api/seances/{id_}")
def api_seance(id_: int):
    return _ou_404(services.detail_seance(id_), "Séance")


@app.get("/api/graphiques")
def api_graphiques():
    return services.graphiques()


@app.get("/api/muscu/charges")
def api_charges_muscu():
    return services.charges_muscu()


@app.post("/api/poids")
def api_poids(valeurs: dict = Body(...)):
    from datetime import date
    d = valeurs.get("date_mesure") or services.aujourdhui().isoformat()
    date.fromisoformat(d)
    poids = services._nombre(valeurs.get("poids_kg"))
    if not poids or not 30 < poids < 200:
        raise ValueError("Poids invalide.")
    db.sauver_poids(d, poids, services._nombre(valeurs.get("masse_grasse_pct")))
    db.maj_profil(poids_kg=poids)
    return db.poids_liste()


# ---------------------------------------------------------------------------
# API — séances planifiées (édition manuelle)
# ---------------------------------------------------------------------------
@app.post("/api/planifiees")
def api_planifiee_creer(p: dict = Body(...)):
    v = services.valider_planifiee(p)
    return db.planifiee(db.inserer("seances_planifiees", {**v, "origine": "manuel"}))


@app.put("/api/planifiees/{id_}")
def api_planifiee_maj(id_: int, p: dict = Body(...)):
    actuelle = _ou_404(db.planifiee(id_), "Séance planifiée")
    v = services.valider_planifiee({**actuelle, "statut": None, **p})
    v["version"] = actuelle["version"] + 1
    v.setdefault("statut", "modifie" if actuelle["statut"] == "prevu" else actuelle["statut"])
    db.maj("seances_planifiees", id_, v)
    return db.planifiee(id_)


@app.delete("/api/planifiees/{id_}")
def api_planifiee_supprimer(id_: int):
    _ou_404(db.planifiee(id_), "Séance planifiée")
    db.supprimer("seances_planifiees", id_)
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — événements
# ---------------------------------------------------------------------------
@app.get("/api/evenements")
def api_evenements():
    return {"evenements": db.evenements(depuis=services.aujourdhui().isoformat()),
            "plan_prepa": db.plan_prepa(),
            "profil": db.profil()}


@app.post("/api/evenements")
def api_evenement_creer(e: dict = Body(...)):
    id_ = db.inserer("evenements", services.valider_evenement(e))
    return {"evenement": db.evenement(id_), "reconstruction": services.reconstruire(id_)}


@app.put("/api/evenements/{id_}")
def api_evenement_maj(id_: int, e: dict = Body(...)):
    _ou_404(db.evenement(id_), "Événement")
    db.maj("evenements", id_, services.valider_evenement(e))
    return {"evenement": db.evenement(id_), "reconstruction": services.reconstruire(id_)}


@app.delete("/api/evenements/{id_}")
def api_evenement_supprimer(id_: int):
    _ou_404(db.evenement(id_), "Événement")
    with db.connexion() as c:
        # analyses_llm référence l'événement sans ON DELETE : on détache la trace
        c.execute("UPDATE analyses_llm SET evenement_id = NULL WHERE evenement_id = ?", (id_,))
        c.execute("DELETE FROM evenements WHERE id = ?", (id_,))
    return {"ok": True, "reconstruction": services.reconstruire()}


@app.post("/api/reconstruire")
def api_reconstruire():
    return services.reconstruire()

"""API FastAPI de carnet et service de l'interface compilée (Svelte)."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config
from .auth import COOKIE, Sessions
from .db import Base
from .normalisation import configurer_emojis
from .modele import GROUPES, GROUPE_VERIFIES, LIBELLES_SOURCES, TYPES
from .service import Carnet, ErreurCarnet

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s : %(message)s")
log = logging.getLogger("carnet")

OUVERTS = {"/api/connexion", "/api/session", "/api/deconnexion"}
etat: dict = {}


def _purge_quotidienne(carnet: Carnet, arret: threading.Event) -> None:
    while not arret.is_set():
        try:
            n = carnet.purger()
            if n:
                log.info("%d archive(s) supprimée(s)", n)
        except Exception:
            log.exception("Purge des archives impossible")
        arret.wait(6 * 3600)


@asynccontextmanager
async def cycle(app: FastAPI):
    cfg = config.charger()
    configurer_emojis(cfg.emoji_groupes)
    base = Base(cfg.db_path, cfg.db_key)
    carnet = Carnet(cfg, base)
    arret = threading.Event()
    threading.Thread(target=_purge_quotidienne, args=(carnet, arret), daemon=True).start()
    etat.update(cfg=cfg, base=base, carnet=carnet,
                sessions=Sessions(cfg.password, cfg.db_key, cfg.session_jours,
                                  base.etat("generation_session", 0)))
    log.info("carnet %s prêt (données : %s)", __version__, cfg.data)
    yield
    arret.set()
    base.fermer()


app = FastAPI(title="carnet", version=__version__, lifespan=cycle, docs_url=None, redoc_url=None)


def carnet() -> Carnet:
    return etat["carnet"]


@app.middleware("http")
async def garde(request: Request, call_next):
    chemin = request.url.path
    if chemin.startswith("/api/"):
        # Toute écriture porte un en-tête que seul le code de carnet envoie : une page d'un autre
        # service (même hôte, autre port) ne peut pas le poser sans autorisation CORS.
        if request.method not in ("GET", "HEAD") and request.headers.get("x-carnet") != "1":
            return JSONResponse({"detail": "Requête refusée."}, status_code=403)
        if chemin not in OUVERTS and not etat["sessions"].valide(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Connexion requise."}, status_code=401)
    reponse = await call_next(request)
    if chemin.startswith("/api/"):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.exception_handler(ErreurCarnet)
async def erreur_carnet(_: Request, exc: ErreurCarnet):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ------------------------------------------------------------------ ouverts

@app.get("/health")
def sante():
    return {"ok": True, "version": __version__}


@app.get("/status")
def statut_public():
    """Compteurs seulement (aucune donnée personnelle) : lus par Home Assistant."""
    return carnet().statut()


class Connexion(BaseModel):
    mot_de_passe: str


@app.post("/api/connexion")
async def connexion(corps: Connexion):
    sessions: Sessions = etat["sessions"]
    attente = sessions.attente()
    if not sessions.verifier_mot_de_passe(corps.mot_de_passe):
        await asyncio.sleep(attente)  # freine les essais sans bloquer le serveur
        raise HTTPException(401, "Mot de passe incorrect.")
    reponse = JSONResponse({"connecte": True})
    reponse.set_cookie(COOKIE, sessions.creer(), max_age=sessions.duree, httponly=True,
                       samesite="strict", path="/")
    return reponse


@app.get("/api/session")
def session(request: Request):
    return {"connecte": etat["sessions"].valide(request.cookies.get(COOKIE))}


@app.post("/api/deconnexion")
def deconnexion():
    # Invalide tous les cookies déjà émis (y compris un cookie copié ailleurs)
    sessions: Sessions = etat["sessions"]
    sessions.generation += 1
    etat["base"].ecrire_etat("generation_session", sessions.generation)
    reponse = JSONResponse({"connecte": False})
    reponse.delete_cookie(COOKIE, path="/")
    return reponse


# ------------------------------------------------------------------ référentiel

@app.get("/api/config")
def referentiel():
    return {"groupes": GROUPES, "groupe_verifies": GROUPE_VERIFIES, "types": TYPES,
            "sources": LIBELLES_SOURCES, "version": __version__,
            "archive_jours": etat["cfg"].archive_jours, "alerte_jours": etat["cfg"].alerte_jours}


@app.get("/api/statut")
def statut():
    return carnet().statut()


# ------------------------------------------------------------------ dépôt et import

@app.get("/api/depot")
def depot():
    return carnet().depot()


@app.post("/api/depot")
async def deposer(fichiers: list[UploadFile] = File(...)):
    res = []
    for f in fichiers:
        contenu = await f.read()
        if len(contenu) > 50 * 1024 * 1024:
            raise ErreurCarnet(f"{f.filename} dépasse 50 Mo.")
        res.append(carnet().deposer(f.filename or "export.vcf", contenu))
    return res


class Import(BaseModel):
    nom: str
    source: str


@app.post("/api/importer")
def importer(corps: Import):
    return carnet().importer(corps.nom, corps.source)


# ------------------------------------------------------------------ contacts et révision

@app.get("/api/contacts")
def contacts():
    return carnet().liste()


@app.get("/api/file")
def file_revision():
    return carnet().file()


@app.get("/api/personnes/{pid}")
def personne(pid: str):
    return carnet().dossier(pid)


class Enregistrement(BaseModel):
    fiche: dict
    valider: bool = False


@app.put("/api/personnes/{pid}")
def enregistrer(pid: str, corps: Enregistrement):
    return carnet().enregistrer(pid, corps.fiche, corps.valider)


@app.post("/api/personnes/{pid}/rouvrir")
def rouvrir(pid: str):
    return carnet().rouvrir(pid)


@app.post("/api/personnes/{pid}/repartir")
def repartir(pid: str):
    return carnet().repartir(pid)


class Detachement(BaseModel):
    source_id: int


@app.post("/api/personnes/{pid}/detacher")
def detacher(pid: str, corps: Detachement):
    return carnet().detacher(pid, corps.source_id)


class Fusion(BaseModel):
    autre: str


@app.post("/api/personnes/{pid}/fusionner")
def fusionner(pid: str, corps: Fusion):
    return carnet().fusionner(pid, corps.autre)


@app.get("/api/photos/{source_id}")
def photo(source_id: int):
    p = carnet().photo(source_id)
    if not p:
        raise HTTPException(404, "Pas de photo.")
    return Response(p[0], media_type=p[1], headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------------ revue

@app.get("/api/revue")
def revue():
    return carnet().revue()


class Retouche(BaseModel):
    anniversaire: str | None = None
    societe: str | None = None
    ajouter: list[str] = []
    retirer: list[str] = []


class Societes(BaseModel):
    variantes: list[str]
    nom: str = ""


@app.post("/api/societes/uniformiser")
def uniformiser(corps: Societes):
    return carnet().uniformiser_societes(corps.variantes, corps.nom)


@app.post("/api/societes/ignorer")
def ignorer(corps: Societes):
    return carnet().ignorer_societes(corps.variantes)


@app.post("/api/personnes/{pid}/retoucher")
def retoucher(pid: str, corps: Retouche):
    return carnet().retoucher(pid, corps.anniversaire, corps.societe, corps.ajouter, corps.retirer)


# ------------------------------------------------------------------ export, kit, archives

@app.post("/api/export")
def exporter():
    return carnet().exporter()


@app.get("/api/exports")
def exports():
    return carnet().exports()


@app.get("/api/exports/{nom}")
def telecharger(nom: str):
    chemin = etat["cfg"].export / Path(nom).name
    if not chemin.is_file():
        raise HTTPException(404, "Export introuvable.")
    return FileResponse(chemin, media_type="text/vcard", filename=chemin.name)


@app.get("/api/kit")
def kit():
    return carnet().apercu_kit()


@app.post("/api/kit")
def envoyer_kit():
    return carnet().envoyer_kit()


@app.get("/api/archives")
def archives():
    return carnet().archives()


# ------------------------------------------------------------------ interface

STATIC = Path(os.environ.get("CARNET_STATIC", str(Path(__file__).parent / "static")))
if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{chemin:path}", include_in_schema=False)
def interface(chemin: str):
    if chemin.startswith("api/"):
        raise HTTPException(404, "Route inconnue.")
    fichier = STATIC / chemin
    if chemin and fichier.is_file() and STATIC in fichier.resolve().parents:
        return FileResponse(fichier)
    index = STATIC / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Interface non compilée."}, status_code=503)

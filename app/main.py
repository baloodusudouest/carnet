"""API FastAPI de carnet et service de l'interface compilée (Svelte)."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config
from .auth import COOKIE, Sessions
from .db import Base
from .normalisation import configurer_emojis
from .modele import GROUPE_VERIFIES, LIBELLES_SOURCES, TYPES, groupes_tous, regles_groupes
from .carddav import ErreurICloud
from .liens import ErreurLien
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


def _veille_nocturne(carnet: Carnet, cfg, arret: threading.Event) -> None:
    """Veille iCloud chaque nuit à l'heure CARNET_VEILLE_HEURE (03:00 par défaut, heure locale)."""
    from datetime import datetime, timedelta
    h, _, m = (cfg.veille_heure or "03:00").partition(":")
    while not arret.is_set():
        maintenant = datetime.now().astimezone()
        prochaine = maintenant.replace(hour=int(h), minute=int(m or 0), second=0, microsecond=0)
        if prochaine <= maintenant:
            prochaine += timedelta(days=1)
        if arret.wait((prochaine - maintenant).total_seconds()):
            return
        try:
            carnet.nuit()
        except Exception:  # noqa: BLE001 — opération déjà en cours : la veille attend la nuit suivante
            log.exception("Veille iCloud non lancée")


@asynccontextmanager
async def cycle(app: FastAPI):
    cfg = config.charger()
    configurer_emojis(cfg.emoji_groupes)
    base = Base(cfg.db_path, cfg.db_key)
    carnet = Carnet(cfg, base)
    arret = threading.Event()
    threading.Thread(target=_purge_quotidienne, args=(carnet, arret), daemon=True).start()
    if cfg.veille_heure:
        threading.Thread(target=_veille_nocturne, args=(carnet, cfg, arret), daemon=True).start()
    etat.update(cfg=cfg, base=base, carnet=carnet,
                sessions=Sessions(cfg.password, cfg.db_key, cfg.session_jours,
                                  base.etat("generation_session", 0)))
    log.info("carnet %s prêt (données : %s)", __version__, cfg.data)
    yield
    arret.set()
    base.fermer()


app = FastAPI(title="carnet", version=__version__, lifespan=cycle, docs_url=None, redoc_url=None)
# Pages, scripts et réponses JSON compressés (les images, déjà compressées, passent telles quelles)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)


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
    if chemin.startswith("/ha/"):
        # Home Assistant : jeton dédié (dates de naissance), jamais le cookie de l'interface
        jeton = etat["cfg"].ha_token
        if not jeton:
            return JSONResponse({"detail": "CARNET_HA_TOKEN n'est pas défini dans la stack."}, status_code=503)
        if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {jeton}"):
            return JSONResponse({"detail": "Jeton refusé."}, status_code=401)
    reponse = await call_next(request)
    if chemin.startswith(("/api/", "/ha/")):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.exception_handler(ErreurCarnet)
async def erreur_carnet(_: Request, exc: ErreurCarnet):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ErreurLien)
async def erreur_lien(_: Request, exc: ErreurLien):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ErreurICloud)
async def erreur_icloud(_: Request, exc: ErreurICloud):
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
    return {"groupes": groupes_tous(), "regles": regles_groupes(), "groupe_verifies": GROUPE_VERIFIES, "types": TYPES,
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


class JetonLinkedIn(BaseModel):
    jeton: str


@app.post("/api/linkedin")
def linkedin_api(corps: JetonLinkedIn):
    return carnet().linkedin_api(corps.jeton)


@app.get("/api/linkedin/etat")
def linkedin_etat():
    cfg = etat["cfg"]
    return {"oauth": bool(cfg.linkedin_client_id and cfg.linkedin_client_secret), "retour": cfg.linkedin_redirect,
            "en_attente": bool(getattr(carnet(), "_jeton_linkedin", None))}


@app.post("/api/linkedin/reessayer")
def linkedin_reessayer():
    return carnet().linkedin_reessayer()


@app.post("/api/linkedin/autorisation")
def linkedin_autorisation():
    return carnet().linkedin_autorisation()


class RetourLinkedIn(BaseModel):
    adresse: str


@app.post("/api/linkedin/code")
def linkedin_code(corps: RetourLinkedIn):
    return carnet().linkedin_code(corps.adresse)


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


@app.post("/api/personnes/{pid}/ecarter")
def ecarter(pid: str):
    return carnet().ecarter(pid)


@app.post("/api/personnes/{pid}/restaurer")
def restaurer(pid: str):
    return carnet().restaurer(pid)


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


# Vignettes d'avatars : calculées une fois, gardées en mémoire (clé : contenu + taille)
_vignettes: dict[tuple[str, int], tuple[bytes, str]] = {}


def reponse_image(request: Request, image: tuple[bytes, str], taille: int | None) -> Response:
    """Image (réduite si `taille` est demandée), avec ETag : le navigateur garde sa copie et
    redemande seulement si la photo a changé (une photo HD remplace la vignette au même lien)."""
    import hashlib
    from . import portraits
    empreinte = hashlib.sha1(image[0]).hexdigest()
    if taille:
        taille = max(32, min(int(taille), 400))
        cle = (empreinte, taille)
        if cle not in _vignettes:
            try:
                _vignettes[cle] = portraits.vignette(image[0], taille)
            except Exception:  # noqa: BLE001 — format illisible : l'original est servi
                _vignettes[cle] = image
            if len(_vignettes) > 2000:
                _vignettes.pop(next(iter(_vignettes)))
        image = _vignettes[cle]
        empreinte = f"{empreinte}-{taille}"
    etag = f'"{empreinte}"'
    entetes = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=entetes)
    return Response(image[0], media_type=image[1], headers=entetes)


@app.get("/api/photos/{source_id}")
def photo(source_id: int, request: Request, taille: int | None = None):
    p = carnet().photo(source_id)
    if not p:
        raise HTTPException(404, "Pas de photo.")
    return reponse_image(request, p, taille)


# ------------------------------------------------------------------ revue

@app.get("/api/revue")
def revue():
    return carnet().revue()


class Retouche(BaseModel):
    anniversaire: str | None = None
    societe: str | None = None
    ajouter: list[str] = []
    retirer: list[str] = []
    telephone: str | None = None
    type_telephone: str | None = None
    types: dict[str, str] = {}
    types_sites: dict[str, str] = {}
    natures: dict[str, str] = {}


class Societes(BaseModel):
    variantes: list[str]
    nom: str = ""


@app.post("/api/societes/uniformiser")
def uniformiser(corps: Societes):
    return carnet().uniformiser_societes(corps.variantes, corps.nom)


@app.post("/api/societes/ignorer")
def ignorer(corps: Societes):
    return carnet().ignorer_societes(corps.variantes)


class Paire(BaseModel):
    a: str
    b: str


@app.post("/api/doublons/ignorer")
def ignorer_doublon(corps: Paire):
    return carnet().ignorer_doublon(corps.a, corps.b)


@app.post("/api/personnes/{pid}/retoucher")
def retoucher(pid: str, corps: Retouche):
    return carnet().retoucher(pid, corps.anniversaire, corps.societe, corps.ajouter, corps.retirer,
                              corps.telephone, corps.type_telephone, corps.types, corps.types_sites, corps.natures)


# ------------------------------------------------------------------ groupes

class Groupe(BaseModel):
    nom: str
    regle: str | None = None


class ModifGroupe(BaseModel):
    ancien: str
    nom: str
    regle: str | None = None


class SuppressionGroupe(BaseModel):
    nom: str
    vers: str | None = None


@app.get("/api/groupes")
def groupes():
    return carnet().groupes()


@app.post("/api/groupes")
def creer_groupe(corps: Groupe):
    return carnet().creer_groupe(corps.nom, corps.regle)


@app.post("/api/groupes/modifier")
def modifier_groupe(corps: ModifGroupe):
    return carnet().modifier_groupe(corps.ancien, corps.nom, corps.regle)


@app.post("/api/groupes/supprimer")
def supprimer_groupe(corps: SuppressionGroupe):
    return carnet().supprimer_groupe(corps.nom, corps.vers)


# ------------------------------------------------------------------ Home Assistant (jeton)

@app.get("/ha/personnes")
def ha_personnes():
    """Noms proposés dans la carte de réservation (nom Immich des contacts liés, proches)."""
    return carnet().ha_personnes()


@app.get("/ha/invite")
def ha_invite(nom: str):
    """Journal de naissance : date de naissance de l'invité écrit dans la réservation."""
    return carnet().ha_invite(nom)


# ------------------------------------------------------------------ iCloud (V2)

@app.get("/api/icloud")
def icloud_etat():
    return carnet().icloud_etat()


@app.post("/api/icloud/simulation")
def icloud_simuler():
    return carnet().icloud_simuler()


@app.get("/api/icloud/brute/{pid}")
def icloud_brute(pid: str):
    texte, nom = carnet().icloud_brute(pid)
    return Response(texte.encode("utf-8"), media_type="text/vcard; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@app.get("/api/liaisons")
def liaisons(rafraichir: bool = False):
    return carnet().liaisons(rafraichir)


class Liaison(BaseModel):
    pid: str
    immich: str | None = None
    treemich: str | None = None


class Liaisons(BaseModel):
    liaisons: list[Liaison]


@app.post("/api/liaisons/valider")
def valider_liaisons(corps: Liaisons):
    return carnet().valider_liaisons([l.model_dump() for l in corps.liaisons])


class Refus(BaseModel):
    pid: str
    immich: str


@app.post("/api/liaisons/refuser")
def refuser_liaison(corps: Refus):
    return carnet().refuser_liaison(corps.pid, corps.immich)


class CorrectionNom(BaseModel):
    pid: str
    garder: str


@app.post("/api/liaisons/nom")
def corriger_nom(corps: CorrectionNom):
    return carnet().corriger_nom(corps.pid, corps.garder)


class RenommageImmich(BaseModel):
    id: str
    nom: str


@app.post("/api/immich/renommer")
def renommer_immich(corps: RenommageImmich):
    return carnet().renommer_immich(corps.id, corps.nom)


class Deliaison(BaseModel):
    pid: str


@app.post("/api/liaisons/delier")
def delier(corps: Deliaison):
    return carnet().delier(corps.pid)


@app.post("/api/liaisons/actualiser")
def actualiser_liens():
    return carnet().actualiser_liens()


class Tranche(BaseModel):
    choix: str


@app.post("/api/personnes/{pid}/relations")
def trancher_relations(pid: str, corps: Tranche):
    return carnet().trancher_relations(pid, corps.choix)


@app.get("/api/immich/visage/{immich_id}")
def visage_immich(immich_id: str, request: Request, taille: int | None = None):
    try:
        image = carnet().visage_immich(immich_id)
    except Exception:  # noqa: BLE001 — pas de visage : l'interface affiche une initiale
        image = None
    if not image:
        raise HTTPException(404, "Pas de visage.")
    return reponse_image(request, image, taille)


@app.get("/api/portraits")
def portraits_hd():
    return carnet().photos_hd()


@app.post("/api/portraits/recherche")
def chercher_portraits():
    return carnet().chercher_portraits()


class ChoixPortrait(BaseModel):
    pid: str
    asset: str | None = None


@app.post("/api/portraits/choix")
def choisir_portrait(corps: ChoixPortrait):
    if not corps.asset:
        return carnet().portrait_auto(corps.pid)
    return carnet().choisir_portrait(corps.pid, corps.asset)


@app.get("/api/portraits/apercu/{pid}/{asset}")
def apercu_portrait(pid: str, asset: str):
    try:
        image = carnet().apercu_portrait(pid, asset)
    except Exception:  # noqa: BLE001 — l'interface affiche un cadre vide
        image = None
    if not image:
        raise HTTPException(404, "Pas d'aperçu.")
    return Response(image[0], media_type=image[1], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/affiches")
def affiches():
    return carnet().affiches()


class GroupesAffiches(BaseModel):
    groupes: list[str]


@app.post("/api/affiches/groupes")
def affiches_groupes(corps: GroupesAffiches):
    return carnet().affiches_groupes(corps.groupes)


@app.post("/api/affiches/preparation")
def preparer_affiches():
    return carnet().preparer_affiches()


class ChoixAffiche(BaseModel):
    pid: str
    asset: str | None = None


@app.post("/api/affiches/choix")
def choisir_affiche(corps: ChoixAffiche):
    return carnet().choisir_affiche(corps.pid, corps.asset)


@app.get("/api/affiches/proposition/{pid}/{asset}")
def apercu_proposition(pid: str, asset: str, grand: bool = False):
    try:
        image = carnet().apercu_proposition(pid, asset, grand)
    except Exception:  # noqa: BLE001
        image = None
    if not image:
        raise HTTPException(404, "Pas d'aperçu.")
    return Response(image[0], media_type=image[1], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/naissances")
def naissances():
    return carnet().naissances_plan()


@app.post("/api/naissances/simulation")
def naissances_simuler():
    return carnet().naissances_simuler()


class EcritureNaissances(BaseModel):
    cible: str
    remplacer: bool = False
    essai: str | None = None
    confirme: bool = False


@app.post("/api/naissances/ecriture")
def naissances_ecrire(corps: EcritureNaissances):
    return carnet().naissances_ecrire(corps.cible, corps.remplacer, corps.essai, corps.confirme)


@app.get("/api/sauvegardes")
def sauvegardes():
    return carnet().sauvegardes()


@app.post("/api/sauvegardes")
def sauvegarder():
    return carnet().sauvegarder()


@app.post("/api/sauvegardes/forcer")
def forcer_sauvegarde():
    return carnet().forcer_synology()


@app.get("/api/sauvegardes/{nom}")
def telecharger_sauvegarde(nom: str):
    chemin = etat["cfg"].archives / "sauvegardes" / Path(nom).name
    if not chemin.is_file():
        raise HTTPException(404, "Sauvegarde introuvable.")
    return FileResponse(chemin, media_type="text/vcard", filename=chemin.name)


@app.post("/api/icloud/veille")
def icloud_veille():
    return carnet().veiller()


class ModeVeille(BaseModel):
    revision: bool


@app.post("/api/icloud/veille/mode")
def icloud_veille_mode(corps: ModeVeille):
    return carnet().veille_mode(corps.revision)


class Ecriture(BaseModel):
    essai: bool = False
    confirme: bool = False


@app.post("/api/icloud/ecriture")
def icloud_ecrire(corps: Ecriture):
    if not corps.essai and not corps.confirme:
        raise HTTPException(400, "Coche la confirmation avant d'écrire dans iCloud.")
    return carnet().icloud_ecrire(corps.essai)


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
    if chemin.startswith(("api/", "ha/")):
        raise HTTPException(404, "Route inconnue.")
    fichier = STATIC / chemin
    if chemin and fichier.is_file() and STATIC in fichier.resolve().parents:
        return FileResponse(fichier)
    index = STATIC / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Interface non compilée."}, status_code=503)

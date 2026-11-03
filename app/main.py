"""Application FastAPI de carnet 2 : interface (3 onglets), API et adresses Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import (__version__, actions, completude, icloud, liaisons, linkedin, nuit, photos, reprise, reseaux, sorties,
               telegram, traiter, vcard)
from .auth import COOKIE, DUREE, Sessions
from .carddav import ErreurICloud
from .carnet import Carnet, ErreurCarnet, Occupe
from .config import charger
from .liens import ErreurLien
from .modele import groupes_tous, nom_affiche

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("carnet")

ETAT: dict = {}


def carnet() -> Carnet:
    return ETAT["carnet"]


def demarrage(c: Carnet) -> None:
    """Au démarrage : première lecture d'iCloud (référence), reprise unique de la 1.3,
    puis données d'Immich et de Treemich en mémoire."""
    try:
        if c.cfg.icloud_user and not c.base.lire("reference"):
            with c.ecriture(attendre=60):
                c.tache = {"nom": "demarrage", "etat": "en_cours", "message": "Première lecture d'iCloud…"}
                icloud.relire(c, "démarrage")
        if reprise.a_faire(c):
            c.tache = {"nom": "demarrage", "etat": "en_cours", "message": "Reprise des choix de la 1.3…"}
            reprise.reprendre(c)
        if c.cfg.immich_cle or c.cfg.treemich_email:
            c.tache = {"nom": "demarrage", "etat": "en_cours", "message": "Lecture d'Immich et de Treemich…"}
            liaisons.donnees(c)
        reseaux.purger(c)
        c.tache = {"nom": "demarrage", "etat": "termine", "message": "Prêt."}
    except Exception as exc:  # noqa: BLE001
        log.exception("Démarrage")
        c.tache = {"nom": "demarrage", "etat": "erreur", "message": str(exc)}
        c.base.noter("veille", f"Démarrage : {exc}")


@asynccontextmanager
async def cycle(app: FastAPI):
    if "carnet" not in ETAT:
        c = Carnet(charger())
        ETAT["carnet"] = c
        threading.Thread(target=demarrage, args=(c,), daemon=True).start()
        nuit.demarrer(c)
    c = carnet()
    ETAT["sessions"] = Sessions(c.cfg.password, c.base.lire("session_generation", 0))
    yield


app = FastAPI(title="carnet", version=__version__, lifespan=cycle, docs_url=None, redoc_url=None)


# ================================================================ sécurité

@app.middleware("http")
async def garde(request: Request, appel):
    chemin = request.url.path
    if chemin.startswith("/ha/"):
        jeton = carnet().cfg.ha_token
        attendu = f"Bearer {jeton}"
        if not jeton or request.headers.get("authorization", "") != attendu:
            return JSONResponse({"detail": "Jeton Home Assistant manquant ou invalide."}, status_code=401)
    elif chemin.startswith("/api/") and chemin not in ("/api/connexion", "/api/session"):
        if not ETAT["sessions"].valide(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Connexion nécessaire."}, status_code=401)
    reponse = await appel(request)
    if chemin.startswith(("/api/", "/ha/")):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.exception_handler(ErreurCarnet)
async def _erreur(_: Request, exc: ErreurCarnet):
    return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, Occupe) else 400)


@app.exception_handler(ErreurICloud)
async def _erreur_icloud(_: Request, exc: ErreurICloud):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(ErreurLien)
async def _erreur_lien(_: Request, exc: ErreurLien):
    return JSONResponse({"detail": str(exc)}, status_code=502)


def _fond(nom: str, travail, *args) -> dict:
    """Opération longue lancée à part ; son avancement se lit dans /api/accueil (tache)."""
    c = carnet()
    if c.tache.get("etat") == "en_cours":
        raise Occupe(f"Une opération est déjà en cours : {c.tache.get('message')}")
    c.tache = {"nom": nom, "etat": "en_cours", "message": "En cours…"}

    def lancer():
        try:
            res = travail(*args)
            if c.tache.get("nom") == nom and c.tache.get("etat") == "en_cours":
                c.tache = {"nom": nom, "etat": "termine", "message": (res or {}).get("message", "Terminé.")
                           if isinstance(res, dict) else "Terminé."}
        except Exception as exc:  # noqa: BLE001
            log.warning("%s : %s", nom, exc)
            c.tache = {"nom": nom, "etat": "erreur", "message": str(exc)}
    threading.Thread(target=lancer, daemon=True).start()
    return {"lance": True}


# ================================================================ public

@app.get("/health")
def sante():
    return {"ok": True, "version": __version__}


@app.get("/status")
def status():
    return sorties.statut(carnet())


# ================================================================ connexion

@app.get("/api/session")
def session(request: Request):
    return {"connecte": ETAT["sessions"].valide(request.cookies.get(COOKIE)), "version": __version__}


@app.post("/api/connexion")
async def connexion(corps: dict = Body(...)):
    s = ETAT["sessions"]
    await asyncio.sleep(s.attente())
    if not s.verifier_mot_de_passe(str(corps.get("mot_de_passe", ""))):
        raise HTTPException(401, "Mot de passe incorrect.")
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, s.creer(), max_age=DUREE, httponly=True, samesite="strict")
    return r


@app.post("/api/deconnexion")
def deconnexion():
    c, s = carnet(), ETAT["sessions"]
    s.generation += 1
    c.base.ecrire("session_generation", s.generation)
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE)
    return r


# ================================================================ accueil et « À traiter »

@app.get("/api/accueil")
def accueil():
    c = carnet()
    reseaux.purger_si_besoin(c)
    return {"version": __version__, "a_traiter": traiter.compte(c), "tache": c.tache,
            "contacts": len(c.fiches()), "reference": bool(c.base.lire("reference")),
            "icloud": bool(c.cfg.icloud_user), "nuit": c.base.lire("nuit"), "lecture": c.base.lire("derniere_lecture")}


@app.get("/api/a-traiter")
def a_traiter():
    return traiter.liste(carnet())


@app.post("/api/a-traiter-lot")
def repondre_lot(corps: dict = Body(...)):
    return actions.repondre_lot(carnet(), [str(i) for i in corps.get("ids") or []], str(corps.get("action", "")))


@app.post("/api/a-traiter/{ident:path}")
def repondre(ident: str, corps: dict = Body(...)):
    return actions.repondre(carnet(), ident, str(corps.get("action", "")), corps.get("valeur"))


# ================================================================ contacts

def _resume(uid: str, f: dict, liens: dict, en_attente: dict, audit: dict | None = None) -> dict:
    tel = (f.get("telephones") or [{}])[0]
    audit = audit or {}
    return {"uid": uid, "nom": nom_affiche(f), "prenom": f.get("prenom", ""), "nom_famille": f.get("nom", ""),
            "societe": f.get("societe", ""), "fonction": f.get("fonction", ""), "groupes": f.get("groupes", []),
            "a_photo": f.get("a_photo", False), "immich": bool(liens.get(uid, {}).get("immich")),
            "treemich": bool(liens.get(uid, {}).get("treemich")), "telephone": tel.get("affichage") or tel.get("valeur", ""),
            "valeur_tel": tel.get("valeur", ""), "courriel": (f.get("courriels") or [{}])[0].get("valeur", ""),
            "anniversaire": f.get("anniversaire", ""), "a_traiter": en_attente.get(uid, 0),
            "manques": audit.get("manques", []), "statut": audit.get("statut"), "plateformes": audit.get("plateformes", ["icloud"]),
            "score": audit.get("score", 0)}


@app.get("/api/contacts")
def contacts():
    c = carnet()

    def calcul():
        liens = c.liaisons()
        compte: dict[str, int] = {}
        for p in traiter.liste(c):
            if p.get("uid"):
                compte[p["uid"]] = compte.get(p["uid"], 0) + 1
        audit = completude.resume(c)
        liste = [_resume(u, f, liens, compte, audit.get(u)) for u, f in c.fiches().items()]
        return sorted(liste, key=lambda x: (x["nom_famille"] or x["nom"]).casefold())
    return c.memo("contacts", calcul)


@app.get("/api/groupes")
def groupes():
    c = carnet()
    noms = {l["nom"] for l in c.base.tous("SELECT nom FROM groupes")} | set(groupes_tous())
    compte = {n: 0 for n in noms}
    for f in c.fiches().values():
        for g in f.get("groupes", []):
            compte[g] = compte.get(g, 0) + 1
    return [{"nom": n, "nombre": compte[n]} for n in sorted(compte, key=str.casefold)]


@app.get("/api/contacts/{uid}")
def contact(uid: str):
    c = carnet()
    f = c.fiche(uid)
    lien = c.liaison(uid)
    noms = {(s, p["id"]): p["nom"] for s in ("immich", "treemich")
            for p in (c.memo_present("liens", liaisons.DUREE_CACHE) or {}).get(s, [])}
    portrait = c.base.un("SELECT candidats, asset, manuel FROM portraits WHERE uid = ?", (uid,))
    affiche = c.base.un("SELECT immich, posee, le, source FROM affiches WHERE uid = ?", (uid,))
    lk = c.base.un("SELECT url, donnees FROM linkedin WHERE uid = ?", (uid,))
    points = [p for p in traiter.liste(c) if p.get("uid") == uid]
    etag = (c.base.un("SELECT etag FROM fiches WHERE uid = ?", (uid,)) or {"etag": ""})["etag"]
    return {"uid": uid, "etag": etag, "fiche": f, "nom": nom_affiche(f),
            "liaisons": {s: {"id": lien[s], "nom": noms.get((s, lien[s])), "statut": lien.get(s + "_statut")}
                         for s in ("immich", "treemich") if lien.get(s)},
            "portraits": {"candidats": json.loads(portrait["candidats"]), "asset": portrait["asset"]} if portrait else None,
            "affiche": dict(affiche) if affiche else None,
            "linkedin": {"url": lk["url"], **json.loads(lk["donnees"])} if lk else None,
            "a_traiter": points, "groupes_connus": [g["nom"] for g in groupes()],
            "completude": completude.resume(c).get(uid, {}), "criteres": completude.CRITERES}


@app.get("/api/completude")
def compteurs_completude():
    c = carnet()
    return {"criteres": completude.CRITERES, "compteurs": completude.compteurs(c)}


@app.post("/api/contacts/{uid}/valider")
def valider_fiche(uid: str, corps: dict = Body(default={})):
    return completude.valider(carnet(), uid, corps.get("etag"))


@app.post("/api/contacts/{uid}/devalider")
def devalider_fiche(uid: str):
    return completude.devalider(carnet(), uid)


@app.post("/api/contacts/{uid}/profil")
def ajouter_profil(uid: str, corps: dict = Body(...)):
    return reseaux.ajouter_profil(carnet(), uid, str(corps.get("service", "")), str(corps.get("valeur", "")),
                                  corps.get("etag") or None)


@app.post("/api/contacts/{uid}/delier-reseau")
def delier_reseau(uid: str, corps: dict = Body(...)):
    return reseaux.delier(carnet(), uid, str(corps.get("service", "")), corps.get("etag") or None)


@app.post("/api/analyse")
def analyse(corps: dict = Body(default={})):
    c = carnet()
    zero = bool(corps.get("remettre_a_zero")) and corps.get("confirmation") == "REMETTRE"
    return _fond("analyse", lambda: completude.analyse_globale(c, zero) and {"message": "Analyse globale terminée."})


@app.get("/api/telegram")
def telegram_etat():
    return telegram.etat(carnet())


@app.post("/api/telegram/code")
def telegram_code(corps: dict = Body(...)):
    return telegram.demander_code(carnet(), str(corps.get("telephone", "")))


@app.post("/api/telegram/import")
def telegram_import(corps: dict = Body(...)):
    return telegram.importer(carnet(), str(corps.get("code", "")), str(corps.get("mot_de_passe", "")))


@app.post("/api/telegram/abandon")
def telegram_abandon():
    telegram.abandonner(carnet())
    return {"ok": True}


@app.post("/api/contacts/{uid}/apercu")
def apercu(uid: str, corps: dict = Body(...)):
    return actions.apercu(carnet(), uid, corps.get("fiche") or {})


@app.put("/api/contacts/{uid}")
def valider(uid: str, corps: dict = Body(...)):
    if not corps.get("etag"):
        raise ErreurCarnet("Version de la fiche absente : recharge la page.")
    return actions.valider(carnet(), uid, corps.get("fiche") or {}, etag_vu=str(corps["etag"]), regler_revue=True)


@app.post("/api/annuler/{jeton}")
def annuler(jeton: str):
    return actions.annuler(carnet(), jeton)


@app.get("/api/contacts/{uid}/photo")
def photo(uid: str, cote: int = 160):
    v = photos.vignette(carnet(), uid, max(48, min(cote, 640)))
    if not v:
        return Response(status_code=404)
    return Response(v[0], media_type=v[1], headers={"Cache-Control": "private, max-age=600"})


# ---------------------------------------------------------------- liaisons

@app.get("/api/contacts/{uid}/proches")
def proches(uid: str):
    return liaisons.proches(carnet(), uid)


@app.post("/api/contacts/{uid}/lier")
def lier(uid: str, corps: dict = Body(...)):
    liaisons.lier(carnet(), uid, str(corps.get("service")), str(corps.get("id")))
    return {"ok": True}


@app.post("/api/contacts/{uid}/delier")
def delier(uid: str, corps: dict = Body(...)):
    liaisons.delier(carnet(), uid, str(corps.get("service")))
    return {"ok": True}


@app.post("/api/liens/rafraichir")
def rafraichir_liens():
    c = carnet()
    return _fond("liens", lambda: liaisons.donnees(c, rafraichir=True) and {"message": "Immich et Treemich relus."})


# ---------------------------------------------------------------- photos

@app.get("/api/contacts/{uid}/portraits")
def portraits(uid: str, rafraichir: bool = False):
    return photos.candidats(carnet(), uid, rafraichir)


@app.get("/api/immich/{asset}/apercu")
def apercu_immich(asset: str):
    contenu = photos.apercu_candidat(carnet(), asset)
    if not contenu:
        return Response(status_code=404)
    return Response(contenu, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/contacts/{uid}/portrait")
def poser_portrait(uid: str, corps: dict = Body(...)):
    return photos.poser(carnet(), uid, str(corps.get("asset")))


@app.post("/api/contacts/{uid}/affiche")
def preparer_affiche(uid: str, corps: dict = Body(default={})):
    return photos.preparer_affiche(carnet(), uid, corps.get("asset"))


@app.get("/api/contacts/{uid}/affiche")
def image_affiche(uid: str):
    c = carnet()
    nom = nom_affiche(c.fiche(uid))
    contenu = photos.image_affiche(c, uid)
    sur = "".join(ch for ch in nom if ch not in '/\\:*?"<>|') or "contact"
    return Response(contenu, media_type="image/jpeg",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{__import__('urllib.parse').parse.quote(sur)}.jpg"})


@app.post("/api/contacts/{uid}/affiche/posee")
def affiche_posee(uid: str, corps: dict = Body(...)):
    photos.marquer_posee(carnet(), uid, bool(corps.get("posee")))
    return {"ok": True}


@app.get("/api/affiches")
def affiches():
    return photos.affiches(carnet())


@app.get("/api/contacts/{uid}/logos")
def logos_(uid: str):
    return photos.chercher_logos(carnet(), uid)


@app.get("/api/contacts/{uid}/logos/{n}")
def logo(uid: str, n: int):
    return Response(photos.apercu_logo(carnet(), uid, n), media_type="image/png")


@app.post("/api/contacts/{uid}/logos/{n}")
def choisir_logo(uid: str, n: int, corps: dict = Body(...)):
    return photos.choisir_logo(carnet(), uid, n, str(corps.get("sorte", "photo")))


# ---------------------------------------------------------------- fusion

@app.get("/api/fusion")
def proposition(a: str, b: str):
    return actions.proposition_fusion(carnet(), a, b)


@app.post("/api/fusion")
def fusion(corps: dict = Body(...)):
    return actions.fusionner(carnet(), str(corps.get("garder")), str(corps.get("absorber")), corps.get("fiche") or {})


# ================================================================ état

@app.get("/api/etat")
def etat():
    c = carnet()
    return {"version": __version__, "statut": sorties.statut(c), "lecture": c.base.lire("derniere_lecture"),
            "nuit": c.base.lire("nuit"), "reference": c.base.lire("reference"), "reprise": c.base.lire("reprise"),
            "synology": c.base.lire("synology"), "kit": c.base.lire("dernier_envoi_kit"),
            "sauvegardes": icloud.liste_sauvegardes(c)[:60], "journal": c.base.journal(limite=80),
            "linkedin": {"sans_contact": linkedin.sans_contact(c), "api": bool(c.cfg.linkedin_client_id),
                         "en_attente": bool(c.__dict__.get("_jeton_linkedin"))},
            "services": {"icloud": bool(c.cfg.icloud_user), "immich": bool(c.cfg.immich_cle),
                         "treemich": bool(c.cfg.treemich_email), "synology": bool(c.cfg.synology_url),
                         "kit": bool(c.cfg.kit_config and c.cfg.kit_config.is_dir()), "ha": bool(c.cfg.ha_token),
                         "nuit": c.cfg.veille_heure if c.cfg.nuit_active else None},
            "reseaux": reseaux.bilan(c), "telegram": telegram.etat(c), "tache": c.tache}


@app.post("/api/icloud/relire")
def relire(corps: dict = Body(default={})):
    c = carnet()

    def travail():
        with c.ecriture(attendre=30):
            b = icloud.relire_quand_meme(c) if corps.get("forcer") else icloud.relire(c, "manuel")
        return {"message": f"iCloud relu : {b['contacts']} fiches, {b['revision']} à relire."}
    return _fond("relecture", travail)


@app.post("/api/nuit")
def nuit_maintenant():
    c = carnet()
    return _fond("nuit", lambda: nuit.passer(c, "manuel") and {"message": c.tache.get("message")})


@app.get("/api/sauvegardes/{nom}")
def sauvegarde(nom: str):
    return icloud.contenu_sauvegarde(carnet(), nom)


@app.post("/api/sauvegardes/{nom}/restaurer")
def restaurer(nom: str, corps: dict = Body(...)):
    c = carnet()
    with c.ecriture(attendre=10):
        return icloud.restaurer(c, nom, [str(u) for u in corps.get("uids") or []])


@app.post("/api/synology")
def synology(corps: dict = Body(default={})):
    c = carnet()
    with c.ecriture(attendre=10):   # jamais en même temps que la copie de nuit
        return sorties.copier_synology(c, forcer=bool(corps.get("forcer")))


@app.post("/api/kit")
def kit():
    return sorties.envoyer_kit(carnet())


IMPORT_MAX = 100 * 1024 * 1024


@app.post("/api/import")
async def importer(request: Request, nom: str = ""):
    """Fichier envoyé tel quel dans le corps (pas de formulaire) : lu en mémoire seulement,
    jamais écrit sur le disque, 100 Mo au plus."""
    c = carnet()
    morceaux, taille = [], 0
    async for m in request.stream():
        taille += len(m)
        if taille > IMPORT_MAX:
            raise ErreurCarnet("Fichier trop gros (100 Mo au plus) : pour Instagram, ne demande que « Abonnés et abonnements ».")
        morceaux.append(m)
    brut = b"".join(morceaux)
    del morceaux
    fichier_nom = nom.rsplit("/", 1)[-1][:120] or "fichier"
    nom = fichier_nom.lower()
    # Export Instagram : archive .zip ou JSON d'abonnements ; l'archive n'est jamais gardée
    if nom.endswith(".zip") or brut[:2] == b"PK" or (nom.endswith(".json") and b"string_list_data" in brut[:200000]):
        return reseaux.importer_instagram(c, brut, nom)
    contenu = brut.decode("utf-8-sig", errors="replace")
    if "First Name" in contenu[:4000] and ("Connected On" in contenu or "linkedin" in contenu.lower()):
        return {"source": "linkedin", **linkedin.importer(c, contenu)}
    if "BEGIN:VCARD" not in contenu.upper():
        raise ErreurCarnet("Fichier non reconnu : dépose un .vcf ou le Connections.csv de LinkedIn.")
    lues, avertissements = vcard.lire(contenu, c.cfg.region)
    ajoutees = 0
    with c.base.transaction() as cx:
        for lue in lues:
            f = dict(lue.fiche, photo=None)
            if traiter.ajouter(cx, "import", None, traiter.empreinte(f), {"fiche": f, "fichier": fichier_nom}):
                ajoutees += 1
    c.oublier()
    c.base.noter("import", f"Import de {fichier_nom} : {len(lues)} fiche(s), {ajoutees} à traiter")
    return {"source": "vcf", "lues": len(lues), "a_traiter": ajoutees, "avertissements": avertissements[:20]}


@app.post("/api/linkedin/autorisation")
def linkedin_autorisation():
    return linkedin.autorisation(carnet())


@app.post("/api/linkedin/code")
def linkedin_code(corps: dict = Body(...)):
    return linkedin.code(carnet(), str(corps.get("adresse", "")))


@app.post("/api/linkedin/reessayer")
def linkedin_reessayer():
    return linkedin.api(carnet(), "")


@app.post("/api/linkedin/rattacher")
def linkedin_rattacher(corps: dict = Body(...)):
    linkedin.rattacher(carnet(), str(corps.get("url")), corps.get("uid") or None)
    return {"ok": True}


# ================================================================ Home Assistant (Bearer)

@app.get("/ha/contacts")
def ha_contacts():
    return sorties.ha_contacts(carnet())


@app.get("/ha/personnes")
def ha_personnes():
    return sorties.ha_personnes(carnet())


@app.get("/ha/anniversaires")
def ha_anniversaires():
    return sorties.ha_anniversaires(carnet())


@app.get("/ha/invite")
def ha_invite(nom: str = ""):
    try:
        return sorties.ha_invite(carnet(), nom)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/ha/portraits/candidats")
def ha_candidats(immich: str = "", nombre: int = 3):
    return sorties.ha_candidats(carnet(), immich, nombre)


@app.get("/ha/portrait")
def ha_portrait(immich: str = "", cadre: str | None = None, asset: str | None = None):
    trouve = sorties.ha_portrait(carnet(), immich, cadre, asset)
    if not trouve:
        raise HTTPException(404, "Pas de portrait HD pour cette personne.")
    contenu, type_, visage = trouve
    entetes = {"X-Visage": ",".join(f"{v:.4f}" for v in visage)} if visage else {}
    return Response(contenu, media_type=type_, headers=entetes)


# ================================================================ interface

@app.get("/{chemin:path}")
def interface(chemin: str):
    statique = carnet().cfg.static
    fichier = (statique / chemin).resolve() if chemin else None
    if fichier and fichier.is_file() and statique.resolve() in fichier.parents:
        return FileResponse(fichier)
    index = statique / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Interface non compilée."}, status_code=404)


__all__ = ["app", "Path"]

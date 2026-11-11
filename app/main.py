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

from .temps import maintenant
from . import (__version__, actions, attentes, completude, famille, galerie, icloud, liaisons, linkedin, nuit, photos, reseaux, sorties,
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
    """Au démarrage : première lecture d'iCloud (référence), puis données d'Immich et de
    Treemich en mémoire."""
    try:
        if c.cfg.icloud_user and not c.base.lire("reference"):
            with c.ecriture(attendre=60):
                c.tache = {"nom": "demarrage", "etat": "en_cours", "message": "Première lecture d'iCloud…"}
                icloud.relire(c, "démarrage")
        # La reprise des choix de la 1.3 a été retirée en 2.6.5. Si l'ancienne base est là et que
        # la reprise n'a jamais eu lieu, on le dit une fois plutôt que de perdre ces choix en silence.
        if c.fiches():
            attentes.semer(c)   # passage à la 2.8 sur une base déjà lue
        if (c.cfg.state / "carnet.db").is_file() and not c.base.lire("reprise") \
                and not c.base.lire("reprise_signalee"):
            c.base.noter("reprise", "La base de la 1.3 est présente mais ses choix n'ont jamais été repris. "
                                    "Pour les reprendre : CARNET_VERSION=2.6.4 dans la stack, un démarrage, "
                                    "puis retour à cette version.")
            c.base.ecrire("reprise_signalee", True)
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
            "icloud": bool(c.cfg.icloud_user), "nuit": c.base.lire("nuit"), "lecture": c.base.lire("derniere_lecture"),
            "lecture_seule": c.cfg.lecture_seule}


@app.get("/api/a-traiter")
def a_traiter():
    return traiter.liste(carnet())


@app.post("/api/a-traiter-lot/apercu")
def apercu_lot(corps: dict = Body(...)):
    return actions.apercu_lot(carnet(), [str(i) for i in corps.get("ids") or []], str(corps.get("action", "")))


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
            "score": audit.get("score", 0), "total": audit.get("total", 0), "decede": audit.get("decede", False),
            "sans_union": audit.get("sans_union", False)}


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
        sans = famille.sans_union_declaree(c)
        liste = [_resume(u, f, liens, compte, {**audit.get(u, {}), "sans_union": u in sans}) for u, f in c.fiches().items()]
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
            "completude": completude.resume(c).get(uid, {}), "criteres": completude.CRITERES,
            "fete": dict(zip(("date", "origine"), attentes.fete_de(f))),
            "deces": {"date": attentes.decedes(c).get(uid), "decede": uid in attentes.decedes(c),
                      "coche": bool(c.base.un("SELECT 1 FROM deces WHERE uid = ? AND origine = 'main'", (uid,)))},
            "google_logo": galerie.recherche_google(f)}


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


@app.post("/api/contacts/{uid}/logo-depose")
async def deposer_logo(uid: str, request: Request, url: str = ""):
    """Logo fourni à la main. Corps = le fichier image tel quel (glissé, collé ou choisi), ou
    paramètre « url » quand le navigateur n'a donné qu'une adresse."""
    c = carnet()
    if url:
        return galerie.deposer_logo(c, uid, url=url)
    morceaux, taille = [], 0
    async for m in request.stream():
        taille += len(m)
        if taille > galerie.POIDS_MAX:
            raise ErreurCarnet("Image trop lourde (3 Mo au plus).")
        morceaux.append(m)
    contenu = b"".join(morceaux)
    if contenu[:5] == b"data:" or contenu[:4] in (b"http", b"HTTP"):      # adresse envoyée dans le corps
        return galerie.deposer_logo(c, uid, url=contenu.decode("utf-8", "replace"))
    return galerie.deposer_logo(c, uid, contenu=contenu)


# ---------------------------------------------------------------- onglet Photos (2.8)

@app.get("/api/photos")
def photos_files():
    return galerie.files(carnet())


def _uids(corps: dict) -> list[str]:
    return [str(u) for u in corps.get("uids") or []]


@app.post("/api/photos/portraits")
def photos_portraits(corps: dict = Body(...)):
    c = carnet()
    return _fond("photos", lambda: _bilan_lot(galerie.poser_portraits(c, _uids(corps)), "portrait(s) posé(s)"))


@app.post("/api/photos/affiches")
def photos_affiches(corps: dict = Body(...)):
    c = carnet()
    return _fond("photos", lambda: _bilan_lot(galerie.preparer_affiches(c, _uids(corps)), "affiche(s) préparée(s)"))


@app.post("/api/photos/posees")
def photos_posees(corps: dict = Body(...)):
    return galerie.marquer_posees(carnet(), _uids(corps))


@app.post("/api/photos/logos/chercher")
def photos_logos_chercher(corps: dict = Body(...)):
    return galerie.chercher_logos(carnet(), _uids(corps))


@app.post("/api/photos/logos/poser")
def photos_logos_poser(corps: dict = Body(...)):
    c = carnet()
    return _fond("photos", lambda: _bilan_lot(galerie.poser_logos(c, list(corps.get("choix") or [])), "logo(s) posé(s)"))


def _bilan_lot(r: dict, quoi: str) -> dict:
    message = f"{r['faits']} {quoi}"
    if r["restants"]:
        message += f", {r['restants']} en attente du lot suivant"
    if r["erreurs"]:
        message += f" ; {len(r['erreurs'])} refus : " + " ; ".join(r["erreurs"][:3])
    return {**r, "message": message + "."}


# ---------------------------------------------------------------- réglages et manques (2.8)

@app.get("/api/attentes")
def attentes_tableau():
    return attentes.tableau(carnet())


@app.post("/api/attentes/apercu")
def attentes_apercu(corps: dict = Body(...)):
    return attentes.apercu(carnet(), str(corps.get("groupe", "")), str(corps.get("info", "")), bool(corps.get("attendue")))


@app.post("/api/attentes")
def attentes_regler(corps: dict = Body(...)):
    c = carnet()
    r = attentes.regler(c, str(corps.get("groupe", "")), str(corps.get("info", "")), bool(corps.get("attendue")))
    return {**r, "tableau": attentes.tableau(c)}


@app.get("/api/manques")
def manques():
    c = carnet()
    return {"lignes": attentes.lignes(c), "total": attentes.total(c)}


@app.get("/api/exceptions")
def exceptions():
    return attentes.liste_exceptions(carnet())


@app.post("/api/contacts/{uid}/exception")
def excepter(uid: str, corps: dict = Body(...)):
    return attentes.excepter(carnet(), uid, str(corps.get("info", "")), bool(corps.get("oui", True)))


@app.post("/api/contacts/{uid}/decede")
def decede(uid: str, corps: dict = Body(...)):
    return famille.marquer_decede(carnet(), uid, bool(corps.get("oui", True)))


@app.get("/api/automatique")
def automatique():
    c = carnet()
    return {**famille.apercu(c), "journal": famille.journal(c), "lecture_seule": c.cfg.lecture_seule}


@app.post("/api/automatique/{quoi}")
def automatique_regler(quoi: str, corps: dict = Body(...)):
    return famille.regler(carnet(), quoi, bool(corps.get("actif")))


@app.post("/api/automatique/defaire/{ident}")
def automatique_defaire(ident: int):
    return famille.defaire(carnet(), ident)


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
    return {"version": __version__, "lecture_seule": c.cfg.lecture_seule,
            "statut": sorties.statut(c), "lecture": c.base.lire("derniere_lecture"),
            "nuit": c.base.lire("nuit"), "reference": c.base.lire("reference"), "reprise": c.base.lire("reprise"),
            "synology": c.base.lire("synology"), "kit": c.base.lire("dernier_envoi_kit"),
            "sauvegardes": icloud.liste_sauvegardes(c)[:60], "journal": c.base.journal(limite=80),
            "linkedin": {"sans_contact": linkedin.sans_contact(c), "api": bool(c.cfg.linkedin_client_id),
                         "en_attente": bool(c.__dict__.get("_jeton_linkedin"))},
            "services": {"icloud": bool(c.cfg.icloud_user), "immich": bool(c.cfg.immich_cle),
                         "treemich": bool(c.cfg.treemich_email), "synology": bool(c.cfg.synology_url),
                         "kit": bool(c.cfg.kit_config and c.cfg.kit_config.is_dir()), "ha": bool(c.cfg.ha_token),
                         "nuit": c.cfg.veille_heure if c.cfg.nuit_active else None},
            "reseaux": reseaux.bilan(c), "telegram": telegram.etat(c), "tache": c.tache, "sante": sante(c)}


def sante(c) -> dict:
    """Chaque service : ok, erreur (avec le message) ou off (non configuré). D'après les dernières
    opérations, sans rien interroger de plus."""
    nuit_ = c.base.lire("nuit") or {}
    syno = c.base.lire("synology") or {}
    liens = c.memo_present("liens", liaisons.DUREE_CACHE) or {}
    erreurs = liens.get("erreurs", [])

    def un(configure, erreur=""):
        return {"etat": "off" if not configure else "erreur" if erreur else "ok", "message": erreur or ""}
    return {
        "icloud": un(c.cfg.icloud_user, nuit_.get("erreur_lecture") or ""),
        "immich": un(c.cfg.immich_cle, next((e for e in erreurs if "treemich" not in e.lower()), "")),
        "treemich": un(c.cfg.treemich_email, next((e for e in erreurs if "treemich" in e.lower()), "")),
        "synology": un(c.cfg.synology_url, syno.get("erreur") or ""),
        "kit": un(c.cfg.kit_config and c.cfg.kit_config.is_dir()),
        "ha": un(c.cfg.ha_token),
        "telegram": un(c.cfg.telegram_api_id and c.cfg.telegram_api_hash),
        "linkedin": un(c.cfg.linkedin_client_id),
    }


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


@app.get("/api/sauvegardes/{nom}/fichier")
def sauvegarde_fichier(nom: str):
    """La sauvegarde telle quelle (.vcf), pour la garder ailleurs ou l'ouvrir dans Contacts."""
    chemin = icloud._fichier(carnet(), nom)
    return FileResponse(chemin, media_type="text/vcard", filename=chemin.name)


@app.get("/api/logo-reseau/{service}")
def logo_reseau(service: str):
    png = reseaux.logo(carnet(), service)
    if not png:
        raise HTTPException(404, "Pas de logo")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=604800"})


@app.get("/api/export.vcf")
def export_vcf():
    """Toutes les fiches, cartes iCloud telles qu'à la dernière lecture (photos comprises)."""
    c = carnet()
    cartes = [l["texte"].strip() for l in c.base.tous("SELECT texte FROM fiches ORDER BY uid") if l["texte"]]
    corps = ("\r\n".join(cartes) + "\r\n").encode("utf-8")
    nom = f"carnet-{maintenant().strftime('%Y-%m-%d')}.vcf"
    c.base.noter("export", f"Export du carnet : {len(cartes)} fiche(s)")
    return Response(corps, media_type="text/vcard", headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@app.post("/api/sauvegardes/{nom}/restaurer")
def restaurer(nom: str, corps: dict = Body(...)):
    c = carnet()
    with c.ecriture(attendre=10):
        return icloud.restaurer(c, nom, [str(u) for u in corps.get("uids") or []])


@app.post("/api/synology")
def synology(corps: dict = Body(default={})):
    """Copie lancée à part ; son avancement (fiche par fiche) se lit dans /api/accueil (tache)."""
    c = carnet()
    forcer = bool(corps.get("forcer"))

    def avancer(progression, message):
        if c.tache.get("nom") == "synology":
            c.tache = {**c.tache, "progression": round(progression, 3), "message": message}

    def travail():
        with c.ecriture(attendre=10):   # jamais en même temps que la copie de nuit
            b = sorties.copier_synology(c, forcer=forcer, avancer=avancer)
        if b.get("erreur") or b.get("desactivee"):
            raise ErreurCarnet(b.get("erreur") or "Synology Contacts n'est pas configuré.")
        return {"message": f"Synology Contacts à jour : {b['crees']} créée(s), {b['modifies']} mise(s) à jour, "
                           f"{b['supprimes']} retirée(s)" + (f", {len(b['erreurs'])} refusée(s)" if b["erreurs"] else "") + "."}
    return _fond("synology", travail)


@app.post("/api/kit")
def kit():
    return sorties.envoyer_kit(carnet())


IMPORT_MAX = 100 * 1024 * 1024


@app.post("/api/import")
async def importer(request: Request, nom: str = "", source: str = "", apercu: bool = False):
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
    # Export Facebook ou Instagram (.zip, .json ou .html) ; l'archive n'est jamais gardée.
    # Le contenu reconnu l'emporte ; sinon, le réseau annoncé par le bouton utilisé.
    source = reseaux.source_export(brut, nom) or (source if source in ("facebook", "instagram") else None)
    if apercu:
        return _apercu_import(c, brut, nom, source)
    if source == "facebook":
        return reseaux.importer_facebook(c, brut, nom)
    if source == "instagram":
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


def _apercu_import(c: Carnet, brut: bytes, nom: str, source: str | None) -> dict:
    """Import unique (2.8) : ce que carnet a reconnu et ce qu'il ferait, sans rien faire."""
    if source == "facebook":
        return {"source": "facebook", "reconnu": "Export Facebook", "nombre": len(reseaux.lire_facebook(brut, nom)),
                "suite": "Les personnes sont rapprochées de tes fiches ; celles qui correspondent arrivent dans « À traiter »."}
    if source == "instagram":
        return {"source": "instagram", "reconnu": "Export Instagram", "nombre": len(reseaux.lire_instagram(brut, nom)),
                "suite": "Les comptes sont rapprochés de tes fiches ; ceux qui correspondent arrivent dans « À traiter »."}
    contenu = brut.decode("utf-8-sig", errors="replace")
    if "First Name" in contenu[:4000] and ("Connected On" in contenu or "linkedin" in contenu.lower()):
        lignes = [l for l in contenu.splitlines() if l.strip()]
        debut = next((i for i, l in enumerate(lignes) if l.startswith("First Name")), 0)
        return {"source": "linkedin", "reconnu": "Relations LinkedIn (Connections.csv)", "nombre": max(0, len(lignes) - debut - 1),
                "suite": "Les changements de poste ou de société de tes contacts arrivent dans « À traiter »."}
    if "BEGIN:VCARD" in contenu.upper():
        lues, _ = vcard.lire(contenu, c.cfg.region)
        return {"source": "vcf", "reconnu": "Cartes de contacts (.vcf)", "nombre": len(lues),
                "suite": "Chaque fiche arrive dans « À traiter » : tu choisis de la créer dans iCloud, de la réunir ou de l'ignorer."}
    raise ErreurCarnet("Fichier non reconnu. carnet lit : les cartes .vcf, le Connections.csv de LinkedIn, "
                       "les exports Facebook et Instagram (.zip, .json ou .html).")


@app.post("/api/linkedin/autorisation")
def linkedin_autorisation():
    return linkedin.autorisation(carnet())


@app.post("/api/linkedin/code")
def linkedin_code(corps: dict = Body(...)):
    return linkedin.code(carnet(), str(corps.get("adresse", "")))


@app.post("/api/linkedin/reessayer")
def linkedin_reessayer():
    return linkedin.api(carnet(), "")


@app.get("/api/reseaux/{service}/non-lies")
def reseau_non_lies(service: str):
    return reseaux.non_lies(carnet(), service)


@app.post("/api/reseaux/{service}/rattacher")
def reseau_rattacher(service: str, corps: dict = Body(...)):
    return reseaux.rattacher(carnet(), service, str(corps.get("ext_id", "")), str(corps.get("uid", "")))


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


@app.get("/ha/fetes")
def ha_fetes():
    return sorties.ha_fetes(carnet())


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

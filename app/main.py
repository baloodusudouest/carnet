"""Application FastAPI de carnet 2 : interface (6 onglets), API, adresses Home Assistant et sauvegarde des réglages."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .base import connecter
from .temps import maintenant
from . import maison
from . import (__version__, actions, attentes, completude, connexion, famille, galerie, groupes as groupes_, icloud, liaisons, linkedin, nuit, photos, reseaux, sorties,
               telegram, traiter, vcard)
from .auth import COMMUN, COOKIE, DUREE, Sessions, en_https
from .carddav import ErreurICloud
from .carnet import Carnet, ErreurCarnet, Occupe
from .config import charger
from . import millesime as millesime_
from . import genres
from . import alimentation, coffre, evenements, journaux, personnes
from . import reglages as reglages_
from .liens import ErreurLien
from .modele import groupes_tous, nom_affiche
from .normalisation import cle_texte

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
        # 2.28 : chiffrement de la base (SQLCipher, CARNET_DB_KEY)
        if c.base.chiffrement:
            c.base.noter("base", f"Base chiffrée au démarrage ({c.base.chiffrement['tables']} tables) ; copie en clair "
                                 f"gardée 14 jours pour un retour à la 2.27 : {c.base.chiffrement['copie_claire']}")
        elif not c.base.chiffree and not c.base.lire("base_en_clair_signalee"):
            c.base.noter("base", "La base n'est pas chiffrée : pose CARNET_DB_KEY dans la stack pour la chiffrer "
                                 "(allergies et alimentation y sont rangées).")
            c.base.ecrire("base_en_clair_signalee", True)
        icloud.reanalyser(c)    # passage à la 2.8 : champs nouveaux déjà présents dans les cartes
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


# 2.32 (socle 0.9.0) : tâches suivies dans /health (maison.TACHES). « nuit » est déclarée par nuit.declarer ;
# les opérations lancées à la main sont des tâches « à la demande » (jamais d'orange dans l'Anneau).
TACHES_DEMANDE = ("analyse", "liens", "photos", "synchro", "relecture", "synology", "import")


def declarer_taches(c: Carnet) -> None:
    nuit.declarer(c)
    for nom in TACHES_DEMANDE:
        maison.TACHES.declarer(nom, type="demande")


def lancer_copie(c: Carnet) -> asyncio.Task | None:
    """Copie cohérente de carnet2.db chaque nuit (maison.HEURES_COPIE, heure de Paris) vers <state>/copies.
    Base chiffrée (CARNET_DB_KEY) : la copie s'ouvre avec la même clé (socle 0.9.1, `ouvrir`) et reste chiffrée."""
    cle = c.cfg.db_key if c.base.chiffree else ""

    def ouvrir(chemin, lecture_seule=False):
        return connecter(Path(chemin), cle, timeout=30)

    return asyncio.create_task(maison.planifier_copie("carnet", [c.cfg.db_path], c.cfg.state / "copies",
                                                      maison.HEURES_COPIE["carnet"], ouvrir=ouvrir))


@asynccontextmanager
async def cycle(app: FastAPI):
    if "carnet" not in ETAT:
        c = Carnet(charger())
        ETAT["carnet"] = c
        threading.Thread(target=demarrage, args=(c,), daemon=True).start()
        nuit.demarrer(c)
    c = carnet()
    declarer_taches(c)
    ETAT["sessions"] = Sessions(c.cfg.password, c.base.lire("session_generation", 0))
    copie = lancer_copie(c)
    try:
        yield
    finally:
        if copie is not None:            # arrêt propre de la boucle de copie
            copie.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await copie


app = FastAPI(title="carnet", version=__version__, lifespan=cycle, docs_url=None, redoc_url=None)


# ================================================================ sécurité

def _jeton_ha(request: Request) -> bool:
    """Jeton de Home Assistant (CARNET_HA_TOKEN) comparé en temps constant, en octets ; vide : fermé."""
    jeton = carnet().cfg.ha_token
    attendu = f"Bearer {jeton}"
    return bool(jeton) and hmac.compare_digest(request.headers.get("authorization", "").encode(), attendu.encode())


@app.middleware("http")
async def garde(request: Request, appel):
    chemin = request.url.path
    def ouvert() -> bool:
        # 2.26 : le jeton commun MAISON_JETON seul (les anciens jetons par paire ne sont plus lus) ; vide : fermé
        return maison.jeton_valide(maison.jeton_propose(request.headers), maison.jetons())

    if chemin.startswith("/ha/"):
        if not _jeton_ha(request):
            return JSONResponse({"detail": "Jeton Home Assistant manquant ou invalide."}, status_code=401)
    elif chemin.startswith("/sillage/"):
        # 2.15 : Sillage lit la liste des personnes liées à Immich (jeton commun)
        if not ouvert():
            return JSONResponse({"detail": "Jeton de Sillage manquant ou invalide."}, status_code=401)
    elif chemin.startswith("/gazette/"):
        # 2.20 : Gazette lit noms et dates de naissance (jeton commun)
        if not ouvert():
            return JSONResponse({"detail": "Jeton de Gazette manquant ou invalide."}, status_code=401)
    elif chemin.startswith("/douze-points/"):
        # 2.22.1 : Douze points lit prénoms et noms, rien d'autre (jeton commun)
        if not ouvert():
            return JSONResponse({"detail": "Jeton de Douze points manquant ou invalide."}, status_code=401)
    elif chemin.startswith(("/evenements/", "/compteurs/")):
        # 3.1 : adresse commune des événements envoyés par les applis (jeton commun)
        if not ouvert():
            return JSONResponse({"detail": "Jeton commun manquant ou invalide."}, status_code=401)
    # /externe/… (2.26 : sauvegarde pour l'Anneau) : pas de session, la route vérifie le jeton commun.
    # Sans session : seulement l'envoi du mot de passe et la question « suis-je connecté ? ».
    # La lecture de /api/connexion (l'état des services, 2.9) exige une session comme le reste.
    elif chemin.startswith("/api/") and not (chemin == "/api/session"
                                             or (chemin == "/api/connexion" and request.method == "POST")):
        if not ETAT["sessions"].connecte(request.cookies):
            return JSONResponse({"detail": "Connexion nécessaire."}, status_code=401)
    reponse = await appel(request)
    if chemin.startswith(("/api/", "/ha/", "/sillage/", "/gazette/", "/douze-points/", "/externe/", "/evenements/", "/compteurs/")):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.exception_handler(ErreurCarnet)
async def _erreur(_: Request, exc: ErreurCarnet):
    return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, Occupe) else 400)


@app.exception_handler(journaux.Introuvable)
async def _introuvable(_: Request, exc: journaux.Introuvable):
    """2.33 : personne ou pépite inconnue (fiche complète)."""
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(journaux.PepiteChangee)
async def _pepite_changee(_: Request, exc: journaux.PepiteChangee):
    """2.33 : la pépite a changé depuis sa lecture (écritures concurrentes carnet / Gazette)."""
    return JSONResponse({"detail": str(exc)}, status_code=409)


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
            if nom == nuit.TACHE:        # la nuit lancée à la main se suit elle-même (nuit.passer_suivie)
                res = travail(*args)
            else:
                with maison.TACHES.tour(nom):    # 2.32 : tâche à la demande suivie dans /health
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
def sante(request: Request):
    # 2.32 : + version_socle, taches, copie_base (socle 0.9.0) ; messages d'erreur des tâches seulement avec
    # le jeton commun MAISON_JETON ou une session
    sessions = ETAT.get("sessions")
    return {"ok": True, "version": __version__,
            **maison.sante(request, jeton_commun=maison.jetons(),
                           session_ok=bool(sessions and sessions.connecte(request.cookies)))}


@app.get("/status")
def status(request: Request):
    """Compteurs pour le paquet Home Assistant (lus sans jeton). Sans session ni jeton de Home Assistant :
    mêmes champs, mais les messages d'erreur d'iCloud et de Synology sont remplacés par un texte neutre (M14)."""
    complet = ETAT["sessions"].connecte(request.cookies) or _jeton_ha(request)
    return sorties.statut(carnet(), complet=complet)


# ================================================================ connexion

@app.get("/api/session")
def session(request: Request):
    return {"connecte": ETAT["sessions"].connecte(request.cookies), "version": __version__}


@app.post("/api/connexion")
async def ouvrir_session(request: Request, corps: dict = Body(...)):
    s = ETAT["sessions"]
    await asyncio.sleep(s.attente())
    if not s.verifier_mot_de_passe(str(corps.get("mot_de_passe", ""))):
        raise HTTPException(401, "Mot de passe incorrect.")
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, s.creer(), max_age=DUREE, httponly=True, samesite="strict", secure=en_https(request))
    return r


@app.post("/api/deconnexion")
def deconnexion():
    c, s = carnet(), ETAT["sessions"]
    s.generation += 1
    c.base.ecrire("session_generation", s.generation)
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE)
    r.delete_cookie(COMMUN)      # « Se déconnecter » ferme aussi la connexion commune
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


def _associes(c: Carnet, uid: str, f: dict) -> list[dict | None]:
    """2.19 : pour chaque nom associé de la fiche (conjoint, parent, frère…), la fiche qui porte ce nom, si une seule
    le porte. Sinon None : le nom reste du texte."""
    return genres.cibles(c, uid, f)


ANNUAIRE = maison.Annuaire()


def adresse_de(nom: str, request: Request) -> str:
    """2.25 : adresse d'une autre appli pour le navigateur, lue dans l'annuaire de l'Anneau (privée si la page
    vient de Tailscale). 2.26 : plus de variable de repli ; l'Anneau ne la connaît pas : vide."""
    return ANNUAIRE.adresse(nom, prive=maison.est_prive(request.headers.get("host", "")))


@app.get("/api/contacts/{uid}")
def contact(uid: str, request: Request):
    c = carnet()
    f = c.fiche(uid)
    lien = c.liaison(uid)
    noms = {(s, p["id"]): p["nom"] for s in ("immich", "treemich")
            for p in (c.memo_present("liens", liaisons.DUREE_CACHE) or {}).get(s, [])}
    portrait = c.base.un("SELECT candidats, asset, manuel FROM portraits WHERE uid = ?", (uid,))
    affiche = c.base.un("SELECT immich, posee, le, source FROM affiches WHERE uid = ?", (uid,))
    lk = c.base.un("SELECT url, donnees FROM linkedin WHERE uid = ?", (uid,))
    # 2.22.3 : la question du genre n'est pas répétée en tête de fiche, le champ Genre est juste dessous
    points = [p for p in traiter.liste(c) if p.get("uid") == uid and p["motif"] != "genre"]
    etag = (c.base.un("SELECT etag FROM fiches WHERE uid = ?", (uid,)) or {"etag": ""})["etag"]
    return {"uid": uid, "etag": etag, "fiche": f, "nom": nom_affiche(f), "associes": _associes(c, uid, f),
            "liaisons": {s: {"id": lien[s], "nom": noms.get((s, lien[s])), "statut": lien.get(s + "_statut")}
                         for s in ("immich", "treemich") if lien.get(s)},
            "portraits": {"candidats": json.loads(portrait["candidats"]), "asset": portrait["asset"]} if portrait else None,
            "affiche": dict(affiche) if affiche else None,
            "linkedin": {"url": lk["url"], **json.loads(lk["donnees"])} if lk else None,
            "a_traiter": points, "groupes_connus": [g["nom"] for g in groupes()],
            "completude": completude.resume(c).get(uid, {}), "criteres": completude.CRITERES,
            "fete": {**dict(zip(("date", "origine"), attentes.fete_de(f))),
                     "attendue": "fete" in attentes.attendues(f, attentes.par_groupe(c))},
            "deces": {"date": attentes.decedes(c).get(uid), "decede": uid in attentes.decedes(c),
                      "coche": bool(c.base.un("SELECT 1 FROM deces WHERE uid = ? AND origine = 'main'", (uid,)))},
            "genre": genres.fiche(c, uid),     # 2.22
            # 3.5 : pourquoi la date de mariage ou de décès ne part pas vers Treemich, et le conjoint nommé sur la fiche
            "famille": {"raisons": famille.raisons_de(c, uid), "conjoint": famille.conjoint_nomme(c, uid)},
            "personne_id": personnes.de(c, uid),           # 2.28 : identifiant maison stable
            "alimentation": alimentation.fiche(c, uid),     # 2.28 : allergies, intolérances, non aimés, plaisirs
            "journaux": journaux.fiche(c, uid),             # 2.29 : « Pour les journaux » (Gazette)
            # 3.1 : événements envoyés par les applis (séjours, Gazette, Douze points…) et photos scandale de Gazette
            "evenements": evenements.de_personne(c, personnes.de(c, uid)),
            "photos_scandale": evenements.compteur(c, personnes.de(c, uid), "gazette", "photos_scandale"),
            "pepites": len(journaux.pepites(c, personnes.de(c, uid))),
            "google_logo": galerie.recherche_google(f),
            # 2.15 : le chemin de vie de la personne, si la fiche est liée à Immich et que Sillage a une adresse
            "sillage": (f"{sillage}/#/chemin/{c.liaisons().get(uid, {}).get('immich')}"
                        if (sillage := adresse_de("Sillage", request))
                        and c.liaisons().get(uid, {}).get("immich") else "")}


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
    c = carnet()
    avant = c.fiche(uid)
    res = actions.valider(c, uid, corps.get("fiche") or {}, etag_vu=str(corps["etag"]), regler_revue=True)
    # 2.8.3 : une date de mariage ou de décès saisie ici part vers Treemich sans attendre la nuit,
    # si l'accord est allumé — après le délai d'« Annuler », pour ne rien propager d'une saisie annulée
    apres = c.fiches().get(uid, {})
    # 3.5 : conjoint choisi sous la date de mariage : « conjoint » sur les deux cartes, couple dans Treemich, date
    # accordée — après le délai d'« Annuler », pour ne rien propager d'une saisie annulée
    conjoint = str(corps.get("conjoint") or "")
    if conjoint and apres.get("mariage") and conjoint != uid and conjoint in c.fiches() and not c.cfg.lecture_seule:
        def unir():
            try:
                bilan = famille.lier_conjoint(c, uid, conjoint)
                c.base.noter("automatique", bilan["message"])
            except Exception as exc:  # noqa: BLE001 — Treemich muet, refus… : dit dans le journal, la fiche le redit
                c.base.noter("automatique", f"Conjoint de {nom_affiche(apres)} : {exc}")
        threading.Timer(icloud.DELAI_ANNULER + 2, unir).start()
        res["famille"] = (f"Conjoint : {nom_affiche(c.fiches()[conjoint])}. « conjoint » est écrit sur les deux fiches, "
                          "puis le couple et la date partent vers Treemich dans quelques secondes (résultat dans Réglages › Journal).")
        res["raisons"] = []
        return res
    if any((apres.get(k) or "") and (apres.get(k) or "") != (avant.get(k) or "") for k in ("mariage", "deces")):
        if famille.actif(c, "famille") and not c.cfg.lecture_seule:
            def accorder():
                try:
                    bilan = famille.accorder_maintenant(c)
                    c.base.noter("automatique", bilan["message"])
                except Exception as exc:  # noqa: BLE001 — occupé, Treemich muet… : la nuit reprendra
                    c.base.noter("automatique", f"Dates de famille non accordées tout de suite ({exc}) : la nuit reprendra.")
            threading.Timer(icloud.DELAI_ANNULER + 2, accorder).start()
            res["famille"] = "Date de famille : elle part vers Treemich dans quelques secondes."
        else:
            res["famille"] = ("Date de famille enregistrée dans iCloud seulement : "
                              + ("carnet est en lecture seule." if c.cfg.lecture_seule
                                 else "l'accord avec Treemich est éteint (Connexion › Treemich)."))
        # 3.5 : la raison d'un blocage, tout de suite sur la fiche (pas de conjoint dans l'arbre, date sans année…)
        res["raisons"] = famille.raisons_de(c, uid)
    return res


@app.post("/api/contacts/{uid}/supprimer")
def supprimer_fiche(uid: str, corps: dict = Body(...)):
    """Suppression d'une fiche, depuis son écran de modification. « confirmation » doit valoir vrai."""
    return actions.supprimer(carnet(), uid, corps.get("etag") or None, corps.get("confirmation"))


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
    couleur = corps.get("couleur")
    return photos.preparer_affiche(carnet(), uid, corps.get("asset"),
                                   couleur=int(couleur) if str(couleur).isdigit() else None)


@app.get("/api/contacts/{uid}/propositions")
def propositions(uid: str, rafraichir: bool = False):
    """2.10 : 5 propositions de photo et 5 d'affiche (visages d'Immich, sinon logo de la société)."""
    return photos.propositions(carnet(), uid, rafraichir)


@app.get("/api/contacts/{uid}/propositions/{sorte}/{cle}")
def apercu_proposition(uid: str, sorte: str, cle: str):
    if sorte not in ("photo", "affiche"):
        raise HTTPException(404, "Proposition inconnue.")
    return Response(photos.apercu_proposition(carnet(), uid, sorte, cle), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=300"})


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
    # M13 (audit du 17/11/2026) : téléchargement, décodage de l'image et SQLite dans un fil à part,
    # pour que le reste de l'appli continue de répondre pendant ce temps.
    if url:
        return await asyncio.to_thread(galerie.deposer_logo, c, uid, url=url)
    morceaux, taille = [], 0
    async for m in request.stream():
        taille += len(m)
        if taille > galerie.POIDS_MAX:
            raise ErreurCarnet("Image trop lourde (3 Mo au plus).")
        morceaux.append(m)
    contenu = b"".join(morceaux)
    if contenu[:5] == b"data:" or contenu[:4] in (b"http", b"HTTP"):      # adresse envoyée dans le corps
        return await asyncio.to_thread(galerie.deposer_logo, c, uid, url=contenu.decode("utf-8", "replace"))
    return await asyncio.to_thread(galerie.deposer_logo, c, uid, contenu=contenu)


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


@app.post("/api/photos/propositions")
def photos_propositions(corps: dict = Body(...)):
    """2.11 : relit Immich pour les contacts cochés. Lecture seule : rien n'est écrit ailleurs que chez carnet."""
    c = carnet()
    if corps.get("tous"):                       # 2.12 : tout le monde, d'une traite
        return _fond("photos", lambda: _bilan_lot(galerie.chercher_toutes(c), "contact(s) relu(s) dans Immich"))
    return _fond("photos", lambda: _bilan_lot(galerie.chercher_propositions(c, _uids(corps)), "contact(s) relu(s) dans Immich"))


@app.post("/api/photos/portraits/choix")
def photos_portraits_choix(corps: dict = Body(...)):
    c = carnet()
    c.exiger_ecriture("iCloud")
    return _fond("photos", lambda: _bilan_lot(galerie.poser_choix(c, list(corps.get("choix") or [])), "photo(s) posée(s)"))


@app.post("/api/photos/affiches/choix")
def photos_affiches_choix(corps: dict = Body(...)):
    c = carnet()
    c.exiger_ecriture("Immich")
    return _fond("photos", lambda: _bilan_lot(galerie.preparer_choix(c, list(corps.get("choix") or [])), "affiche(s) préparée(s)"))


@app.post("/api/photos/posees")
def photos_posees(corps: dict = Body(...)):
    return galerie.marquer_posees(carnet(), _uids(corps))


@app.get("/api/photos/logos/connu/{uid}")
def photos_logo_connu(uid: str):
    """Logo déjà gardé pour la société de cette fiche (aperçu)."""
    c = carnet()
    contenu = galerie.logo_connu(c, galerie.cle_societe(c.fiche(uid)))
    if not contenu:
        raise HTTPException(404, "Pas de logo gardé pour cette société.")
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(contenu))
    sortie = io.BytesIO()
    img.convert("RGBA").save(sortie, "PNG")
    return Response(sortie.getvalue(), media_type="image/png")


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


# ---------------------------------------------------------------- Connexion et Groupes (2.9)

@app.get("/api/connexion")
def connexion_etat():
    c = carnet()
    return {"services": connexion.etat(c, sante(c), reseaux.bilan(c)), "lecture_seule": c.cfg.lecture_seule,
            "nuit": c.cfg.veille_heure if c.cfg.nuit_active else None}


@app.post("/api/connexion/{service}/verifier")
def connexion_verifier(service: str):
    return connexion.verifier(carnet(), service)


@app.post("/api/connexion/{service}/synchroniser")
def connexion_synchroniser(service: str):
    c = carnet()

    def travail():
        # 3.3 : un geste réussi sert d'essai à la fiche « Connexion » du service (contrat 3). Un échec n'est pas
        # noté : il peut venir de carnet lui-même (lecture seule, groupe Urgence vide…) ; son message s'affiche.
        fiche = FICHE_DE_CLE.get(service)
        res = connexion.synchroniser(c, service)
        if fiche:
            SERVICES.noter(fiche, True, (res or {}).get("message") if isinstance(res, dict) else None)
        return res
    return _fond("synchro", travail)


@app.post("/api/connexion/{service}/nuit")
def connexion_nuit(service: str, corps: dict = Body(...)):
    return connexion.regler_nuit(carnet(), service, bool(corps.get("actif")))


# ================================================================ fiches « Connexion » (3.3, contrat 3, socle 0.11.0)
# Une fiche par service extérieur (écran commun du socle et fiche « État » de l'Anneau) : ce que carnet y lit, ce qu'il
# y écrit, la variable qui le relie, un essai LÉGER (une lecture courte : rien d'écrit, rien de réveillé) et au plus un
# geste qui écrit, porté par la route existante POST /api/connexion/{clé}/synchroniser. « Vérifier » de l'écran de
# travail (relire et comparer), les interrupteurs de nuit, Sauvegardes, Import, réseaux et Attentes restent dans
# l'écran Connexion, sous les fiches. Le dossier de données (/state, /data) n'est pas un service.

def _derniere(cle: str, sans_erreur: bool = False):
    """Date ISO gardée par carnet après sa dernière écriture chez un service (None si jamais)."""
    d = carnet().base.lire(cle) or {}
    if sans_erreur and d.get("erreur"):
        return None
    return d.get("le") if isinstance(d, dict) else None


SYNCHRONISER = {"id": "synchroniser", "nom": "Synchroniser"}
SERVICES = maison.Services(reglages_.ID_APPLI)
SERVICES.ajouter(
    "icloud", "iCloud",
    lit="iCloud est la source : carnet le relit et signale ce qui a changé sur l'iPhone.",
    ecrit="carnet n'y écrit que ce que tu as validé — plus les fêtes, si tu le veux.",
    regle=lambda: bool(carnet().cfg.icloud_user), reglage="CARNET_ICLOUD_USER et CARNET_ICLOUD_PASSWORD",
    essai=lambda: connexion.essai_carddav(carnet().icloud()), geste=SYNCHRONISER,
).ajouter(
    "immich", "Immich",
    lit="Le nom, la date de naissance et la photo de chaque fiche reliée à une personne d'Immich.",
    ecrit="Synchroniser fait les liaisons sûres, complète les naissances d'un côté ou de l'autre et pose les "
          "portraits manquants.",
    regle=lambda: bool(carnet().cfg.immich_cle), reglage="CARNET_IMMICH_CLE",
    essai=lambda: connexion.essai_immich(carnet()), geste=SYNCHRONISER,
).ajouter(
    "treemich", "Treemich",
    lit="Le nom, la naissance, le mariage, le décès et les liens familiaux de chaque fiche reliée à l'arbre.",
    ecrit="Synchroniser remplit le côté vide, sans jamais écraser.",
    regle=lambda: bool(carnet().cfg.treemich_email), reglage="CARNET_TREEMICH_EMAIL et CARNET_TREEMICH_PASSWORD",
    essai=lambda: connexion.essai_treemich(carnet()), geste=SYNCHRONISER,
).ajouter(
    "synology-contacts", "Synology Contacts",
    lit="Les cartes déjà copiées, pour les comparer à iCloud (Vérifier, sans rien écrire).",
    ecrit="Copie à l'identique d'iCloud vers Synology Contacts.",
    regle=lambda: bool(carnet().cfg.synology_url), reglage="CARNET_SYNOLOGY_URL",
    essai=lambda: connexion.essai_carddav(carnet().synology()), geste={"id": "copier", "nom": "Copier maintenant"},
    derniere_ecriture=lambda: _derniere("synology", sans_erreur=True),
).ajouter(
    "home-assistant", "Home Assistant",
    lit="Home Assistant vient lire carnet : contacts, anniversaires et mariages (/ha/anniversaires), "
        "fêtes (/ha/fetes), invités, portraits.",
    ecrit="carnet n'écrit rien dans Home Assistant.",
    regle=lambda: bool(carnet().cfg.ha_token), reglage="CARNET_HA_TOKEN",
).ajouter(
    "kit-urgence", "Kit d'urgence", genre="maison", cible="kit-urgence",
    lit="Rien.",
    ecrit="Les contacts du groupe Urgence sont envoyés au kit d'urgence.",
    regle=lambda: bool(carnet().cfg.kit_config and carnet().cfg.kit_config.is_dir()),
    reglage="CARNET_KIT_CONFIG (volume ${KIT_DATA_DIR}/config)",
    essai=lambda: connexion.essai_kit(carnet()), geste={"id": "envoyer", "nom": "Envoyer au kit"},
    derniere_ecriture=lambda: _derniere("dernier_envoi_kit"),
).ajouter(
    "millesime", "Millésime", genre="maison", cible="millesime",
    lit="Millésime date les scans de photos papier d'Immich par l'âge des visages. carnet vient lire son état "
        "toutes les 10 minutes au plus (jeton commun MAISON_JETON). Les personnes des scans sans date de naissance "
        "sont dans À traiter › Sans anniversaire.",
    ecrit="carnet n'y écrit rien.",
    regle=lambda: bool(carnet().cfg.millesime_jeton), reglage="MAISON_JETON",
    essai=lambda: connexion.essai_millesime(carnet()),
).ajouter(
    "coffre-contacts", "Coffre Contacts",
    lit="Les notes déjà là : leur en-tête et ce que tu y as écrit hors du bloc de carnet, gardé tel quel.",
    ecrit="Écrire les notes du coffre Contacts (SilverBullet).",
    regle=lambda: bool(carnet().cfg.contacts), reglage="CARNET_CONTACTS (volume /contacts)",
    essai=lambda: connexion.essai_coffre(carnet()), geste=SYNCHRONISER,
    derniere_ecriture=lambda: _derniere("coffre_contacts"),
)
# Fiche commune ↔ clé de l'écran de travail (routes /api/connexion/{clé}/…)
FICHE_DE_CLE = {"icloud": "icloud", "immich": "immich", "treemich": "treemich", "synology": "synology-contacts",
                "kit": "kit-urgence", "contacts": "coffre-contacts"}
# Monté APRÈS la garde : le dernier middleware ajouté passe en premier (la garde ne voit pas ces deux routes).
maison.monter_services(app, SERVICES, lambda r: "sessions" in ETAT and ETAT["sessions"].connecte(r.cookies))


@app.get("/api/a-traiter-tuiles")
def a_traiter_tuiles():
    return traiter.tuiles(carnet())


@app.get("/api/sans-anniversaire")
def sans_anniversaire(forcer: bool = False):
    """2.21 : personnes des scans de Millésime sans date de naissance (tuile d'À traiter)."""
    from . import millesime as mil
    c = carnet()
    if forcer:
        mil.lire(c, forcer=True)
    return mil.sans_anniversaire(c)


@app.get("/api/groupes-detail")
def groupes_detail():
    return groupes_.liste(carnet())


@app.get("/api/groupes/{nom}/membres")
def groupe_membres(nom: str):
    return groupes_.membres(carnet(), nom)


@app.post("/api/groupes-creer")
def groupe_creer(corps: dict = Body(...)):
    return groupes_.creer(carnet(), str(corps.get("nom", "")))


@app.post("/api/groupes/{nom}/renommer")
def groupe_renommer(nom: str, corps: dict = Body(...)):
    return groupes_.renommer(carnet(), nom, str(corps.get("nouveau", "")))


@app.post("/api/groupes/{nom}/supprimer")
def groupe_supprimer(nom: str, corps: dict = Body(...)):
    return groupes_.supprimer(carnet(), nom, corps.get("confirmation"))


@app.post("/api/groupes/{nom}/membres")
def groupe_changer(nom: str, corps: dict = Body(...)):
    return groupes_.changer_membres(carnet(), nom, [str(u) for u in corps.get("uids") or []], str(corps.get("action", "")))


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


@app.post("/api/contacts/{uid}/genre")
def genre(uid: str, corps: dict = Body(...)):
    """2.22 : femme, homme, autre, ou vide pour retirer le choix. Reste dans carnet ; écrit dans Treemich s'il y est inconnu."""
    return genres.definir(carnet(), uid, str(corps.get("genre") or ""))


@app.put("/api/contacts/{uid}/journaux")
def changer_journaux(uid: str, corps: dict = Body(...)):
    """2.29 : « Pour les journaux » depuis la fiche (reste dans carnet : permis en lecture seule)."""
    return journaux.definir(carnet(), uid, corps)


# 2.33 : « Fiche complète » pour les journaux — pépite par pépite, avec contrôle de `le` (409 si elle a changé).
# Reste dans carnet (jamais dans iCloud) : permis en lecture seule.

@app.get("/api/contacts/{uid}/fiche-journaux")
def fiche_journaux(uid: str):
    return journaux.fiche_complete_uid(carnet(), uid)


@app.post("/api/contacts/{uid}/fiche-journaux/pepites")
def ajouter_pepite(uid: str, corps: dict = Body(...)):
    c = carnet()
    return journaux.ajouter(c, personnes.de(c, uid), corps, "carnet")


@app.put("/api/contacts/{uid}/fiche-journaux/pepites/{pid}")
def modifier_pepite(uid: str, pid: str, corps: dict = Body(...)):
    c = carnet()
    return journaux.modifier(c, personnes.de(c, uid), pid, corps, "carnet")


@app.delete("/api/contacts/{uid}/fiche-journaux/pepites/{pid}")
def effacer_pepite(uid: str, pid: str, corps: dict | None = Body(default=None), le: str | None = None):
    c = carnet()
    return journaux.effacer(c, personnes.de(c, uid), pid, corps, "carnet", le)


@app.put("/api/contacts/{uid}/alimentation")
def changer_alimentation(uid: str, corps: dict = Body(...)):
    """2.28 : allergies, intolérances, « aucune connue », vérifiée le, aliments non aimés, plaisirs coupables.
    Reste dans carnet (jamais écrit dans iCloud) ; permis en lecture seule."""
    return alimentation.definir(carnet(), uid, corps)


@app.get("/api/personnes/sans-fiche")
def personnes_sans_fiche():
    """2.28 : identifiants maison dont la fiche a été retirée (à rattacher si la carte revient)."""
    return {"personnes": personnes.sans_fiche(carnet())}


@app.post("/api/personnes/{ident}/rattacher")
def rattacher_personne(ident: str, corps: dict = Body(...)):
    return personnes.rattacher(carnet(), ident, str(corps.get("uid") or ""))


@app.post("/api/contacts/{uid}/decede")
def decede(uid: str, corps: dict = Body(...)):
    return famille.marquer_decede(carnet(), uid, bool(corps.get("oui", True)))


@app.get("/api/automatique")
def automatique():
    c = carnet()
    return {**famille.apercu(c), "journal": famille.journal(c), "lecture_seule": c.cfg.lecture_seule}


@app.post("/api/automatique/verifier")
def automatique_verifier():
    """Relit Treemich et compare naissances, mariages et décès avec les fiches. N'écrit rien."""
    return famille.verifier(carnet())


@app.post("/api/automatique/accorder")
def automatique_accorder():
    """Accorde tout de suite mariages et décès avec Treemich (bouton de Réglages)."""
    return famille.accorder_maintenant(carnet())


@app.post("/api/automatique/{quoi}")
def automatique_regler(quoi: str, corps: dict = Body(...)):
    return famille.regler(carnet(), quoi, bool(corps.get("actif")))


@app.post("/api/automatique/defaire/{ident}")
def automatique_defaire(ident: int):
    return famille.defaire(carnet(), ident)


# ---------------------------------------------------------------- réglages d'usage, sauvegarde, restauration (2.26)

LIRE_ANNEAU = None      # tests et démonstration : faux Anneau (fonction (adresse, jeton) → dict) ; None : HTTP


@app.get("/api/reglages")
def reglages_lire():
    c = carnet()
    return {"reglages": reglages_.tout(c), "lecture_seule": c.cfg.lecture_seule,
            "origine_lecture_seule": maison.origine_lecture_seule("CARNET_LECTURE_SEULE")}


@app.put("/api/reglages")
def reglages_ecrire(corps: dict = Body(...)):
    """Change un ou plusieurs réglages ; une valeur de mauvais type : 400, rien n'est changé."""
    valeurs = corps.get("reglages", corps) if isinstance(corps, dict) else corps
    return {"reglages": reglages_.changer(carnet(), valeurs)}


def _anneau(le: str = "") -> dict:
    """Lit les sauvegardes de carnet chez l'Anneau ; message clair (503 / 404) si rien ne vient."""
    import urllib.error
    if not maison.jeton_a_envoyer() and LIRE_ANNEAU is None:
        raise HTTPException(503, "MAISON_JETON n'est pas posé : carnet ne peut pas lire les sauvegardes de l'Anneau.")
    try:
        r = maison.lire_sauvegarde(reglages_.ID_APPLI, le, lire=LIRE_ANNEAU)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, "L'Anneau n'a pas de sauvegarde de carnet" + (f" du {le}." if le else ".")) from exc
        raise HTTPException(503, f"L'Anneau a refusé la demande (erreur {exc.code}).") from exc
    except Exception as exc:  # noqa: BLE001 — Anneau éteint, réseau, réponse illisible
        raise HTTPException(503, f"Anneau injoignable ({exc.__class__.__name__}) : réessaie plus tard.") from exc
    if not isinstance(r, dict):
        raise HTTPException(503, "Réponse de l'Anneau illisible.")
    return r


@app.get("/api/restaurer")
def restaurer_lire(le: str = ""):
    c = carnet()
    if not le:
        return {"dates": list(_anneau().get("dates") or [])}
    s = _anneau(le)
    if not isinstance(s.get("reglages"), dict):
        raise HTTPException(404, f"L'Anneau n'a pas de sauvegarde de carnet du {le}.")
    return {"le": s.get("le", le), "version": s.get("version", ""), "differences": reglages_.differences(c, s["reglages"])}


@app.post("/api/restaurer")
def restaurer_appliquer(corps: dict = Body(...)):
    """Applique les réglages d'une sauvegarde (rien d'autre). Permis en lecture seule : tout reste dans carnet."""
    le = str(corps.get("le") or "").strip()
    if not le:
        raise HTTPException(400, "Choisis la date de la sauvegarde à restaurer.")
    s = _anneau(le)
    if not isinstance(s.get("reglages"), dict):
        raise HTTPException(404, f"L'Anneau n'a pas de sauvegarde de carnet du {le}.")
    return reglages_.restaurer(carnet(), {**s, "le": s.get("le", le)})


@app.get("/externe/sauvegarde")
def externe_sauvegarde(request: Request):
    """Réglages d'usage pour l'Anneau (collecte de nuit) : jeton commun seulement ; sans jeton réglé, porte fermée."""
    if not maison.jeton_valide(maison.jeton_propose(request.headers), maison.jetons()):
        raise HTTPException(404, "Not Found")
    return maison.sauvegarde(reglages_.ID_APPLI, __version__, reglages_.tout(carnet()), exclus=reglages_.EXCLUS)


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
        "millesime": un(c.cfg.millesime_jeton, millesime_.lire(c)["erreur"] if c.cfg.millesime_jeton else ""),
        "linkedin": un(c.cfg.linkedin_client_id),
        "contacts": coffre.sante(c),     # 2.28 : coffre « Contacts »
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
    return _fond("nuit", lambda: nuit.passer_suivie(c, "manuel") and {"message": c.tache.get("message")})


@app.get("/api/sauvegardes/{nom}")
def sauvegarde(nom: str):
    return icloud.contenu_sauvegarde(carnet(), nom)


@app.get("/api/sauvegardes/{nom}/fichier")
def sauvegarde_fichier(nom: str):
    """La sauvegarde telle quelle (.vcf), pour la garder ailleurs ou l'ouvrir dans Contacts."""
    chemin = icloud._fichier(carnet(), nom)
    return FileResponse(chemin, media_type="text/vcard", filename=chemin.name)


ARBRE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="6" fill="#e6f0e2"/>
<path d="M14.6 27v-7.2h2.8V27z" fill="#7a5a3c"/>
<circle cx="16" cy="10.5" r="6.2" fill="#3f7d4a"/><circle cx="10.4" cy="15.2" r="5" fill="#4f9159"/><circle cx="21.6" cy="15.2" r="5" fill="#4f9159"/>
<circle cx="16" cy="16.6" r="4.6" fill="#5ea367"/>
</svg>"""


@app.get("/api/logo-reseau/{service}")
def logo_reseau(service: str):
    if service == "treemich":                   # 2.11.3 : un arbre dessiné par carnet, à la place des lettres « Tr »
        return Response(ARBRE, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=604800"})
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
    # M13 (audit du 17/11/2026) : lecture de l'archive et écriture en base dans un fil à part
    async with maison.TACHES.tour_async("import"):     # 2.32 : tâche à la demande suivie dans /health
        return await asyncio.to_thread(_importer_brut, c, brut, nom, source, apercu)


def _importer_brut(c: Carnet, brut: bytes, nom: str, source: str, apercu: bool) -> dict:
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


# ================================================================ Sillage (Bearer)

@app.get("/sillage/personnes")
def sillage_personnes():
    return sorties.sillage_personnes(carnet())


# ================================================================ Gazette (Bearer)

@app.get("/gazette/personnes")
def gazette_personnes():
    return sorties.gazette_personnes(carnet())


@app.put("/gazette/personnes/{personne_id}/journaux")
def gazette_journaux(personne_id: str, corps: dict = Body(...)):
    """2.29 : Gazette garde ici ce que Julien a écrit sur une personne pour les rumeurs de La Récidive."""
    return journaux.ecrire(carnet(), personne_id, (corps or {}).get("texte"), "gazette")


@app.put("/gazette/personnes/{personne_id}/parus/{cle}")
def gazette_paru(personne_id: str, cle: str, corps: dict = Body(...)):
    """2.30 : Gazette range ici un numéro de La Récidive approuvé (journaux parus de la fiche)."""
    return journaux.ecrire_paru(carnet(), personne_id, cle, corps)


# 2.33 : fiche complète de la personne (pépites), lue et écrite par Gazette (jeton commun)

@app.get("/gazette/personnes/{personne_id}/fiche")
def gazette_fiche(personne_id: str):
    return journaux.fiche_complete(carnet(), personne_id)


@app.post("/gazette/personnes/{personne_id}/fiche/pepites")
def gazette_ajouter_pepite(personne_id: str, corps: dict = Body(...)):
    return journaux.ajouter(carnet(), personne_id, corps, "gazette")


@app.put("/gazette/personnes/{personne_id}/fiche/pepites/{pid}")
def gazette_modifier_pepite(personne_id: str, pid: str, corps: dict = Body(...)):
    return journaux.modifier(carnet(), personne_id, pid, corps, "gazette")


@app.delete("/gazette/personnes/{personne_id}/fiche/pepites/{pid}")
def gazette_effacer_pepite(personne_id: str, pid: str, corps: dict | None = Body(default=None), le: str | None = None):
    return journaux.effacer(carnet(), personne_id, pid, corps, "gazette", le)


@app.post("/gazette/personnes/{personne_id}/fiche/parues")
def gazette_pepites_parues(personne_id: str, corps: dict = Body(...)):
    """Numéro approuvé dans Gazette : {ids, date} — les pépites tirées pour ses textes retenus reçoivent `parue_le`."""
    return journaux.marquer_parues(carnet(), personne_id, corps)


# ================================================================ Événements des applis (3.1, jeton commun)

@app.put("/evenements/{appli}/{cle}")
def evenement_recu(appli: str, cle: str, corps: dict = Body(...)):
    return evenements.recevoir(carnet(), appli, cle, corps)


@app.delete("/evenements/{appli}/{cle}")
def evenement_retire(appli: str, cle: str):
    return evenements.retirer(carnet(), appli, cle)


@app.put("/compteurs/{appli}/{nom}")
def compteur_recu(appli: str, nom: str, corps: dict = Body(...)):
    return evenements.recevoir_compteur(carnet(), appli, nom, corps)


@app.get("/api/evenements/a-rattacher")
def evenements_a_rattacher():
    return {"personnes": evenements.a_rattacher(carnet())}


@app.put("/api/evenements/personnes/{ligne_id}/rattacher")
def evenement_rattacher(ligne_id: int, corps: dict = Body(...)):
    return evenements.rattacher(carnet(), ligne_id, str((corps or {}).get("uid") or ""))


@app.delete("/api/evenements/personnes/{ligne_id}")
def evenement_ecarter(ligne_id: int):
    return evenements.ecarter(carnet(), ligne_id)


# ================================================================ Douze points (Bearer)

@app.get("/douze-points/personnes")
def douze_points_personnes():
    return sorties.douze_points_personnes(carnet())


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


@app.post("/ha/livre-or")
def ha_livre_or(corps: dict = Body(...)):
    """2.31 : Home Assistant envoie chaque mot signé dans le livre d'or (script.livre_dor_signer), et l'existant une
    fois (script.livre_dor_renvoyer_carnet). Reste dans carnet : permis en lecture seule."""
    return journaux.recevoir_livre(carnet(), corps)


@app.delete("/api/livre-or/{mot_id}")
def supprimer_livre(mot_id: int):
    """3.5 : supprime un mot du livre d'or (après confirmation dans l'écran) ; un renvoi de Home Assistant ne le fait pas
    revenir."""
    return journaux.supprimer_livre(carnet(), mot_id)


@app.put("/api/livre-or/{mot_id}/rattacher")
def rattacher_livre(mot_id: int, corps: dict = Body(...)):
    """2.31 : rattache un mot du livre d'or (signataire non reconnu) à une fiche."""
    return journaux.rattacher_livre(carnet(), mot_id, str((corps or {}).get("uid") or ""))


@app.get("/ha/allergies")
def ha_allergies(personne_id: str = "", nom: str = ""):
    """2.28 : indicateur d'allergies (statut et date de vérification seulement)."""
    if not personne_id and not nom:
        raise HTTPException(400, "Donne personne_id ou nom.")
    try:
        return sorties.ha_allergies(carnet(), personne_id, nom)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/ha/aliments")
def ha_aliments(personne_id: str = "", nom: str = ""):
    """3.5 : listes d'alimentation et note d'hôte d'une personne (champs aliments d'une chambre)."""
    if not personne_id and not nom:
        raise HTTPException(400, "Donne personne_id ou nom.")
    try:
        return sorties.ha_aliments(carnet(), personne_id, nom)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/ha/aliments/annuaire")
def ha_aliments_annuaire():
    """3.5 : toutes les personnes dont l'alimentation est renseignée (carte « Fiches invités »)."""
    return sorties.ha_aliments_annuaire(carnet())


@app.post("/ha/aliments/modifier")
def ha_aliments_modifier(corps: dict = Body(...)):
    """3.5 : une modification faite dans une carte de Home Assistant, par ajouts et retraits ; renvoi sans doublon."""
    try:
        return alimentation.modifier_par_ha(carnet(), corps)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.put("/ha/evenements/{cle}")
def ha_evenement(cle: str, corps: dict = Body(...)):
    """3.5 : séjour d'une chambre envoyé par Home Assistant (à la réservation et au départ), rangé comme les
    événements des autres applis (appli « home-assistant », type « sejour »)."""
    corps = dict(corps or {})
    if (corps.get("type") or "sejour") != "sejour":
        raise ErreurCarnet("Home Assistant n'envoie que des séjours.")
    corps["type"] = "sejour"
    return evenements.recevoir(carnet(), "home-assistant", cle, corps)


@app.delete("/ha/evenements/{cle}")
def ha_evenement_retire(cle: str):
    """3.5 : séjour annulé dans Home Assistant."""
    return evenements.retirer(carnet(), "home-assistant", cle)


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

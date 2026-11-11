"""Onglet Photos (carnet 2.8, revu en 2.11) : quatre files, traitées par lots, et le logo déposé à la main.

2.11 : « Portraits » et « Affiches » portent sur TOUS les contacts qui peuvent en recevoir une
(reliés à Immich, ou d'une société dont le logo est gardé), y compris ceux qui ont déjà une photo.
Chaque contact montre ses propositions ; la première est le choix de carnet (visage entier, grand,
personne seule et centrée si possible, sinon le logo). Rien n'est posé sans avoir été coché : une
photo déjà en place n'est jamais remplacée d'office. Le compteur de la tuile ne compte que ce qui manque.

Files (avant la 2.11 : « portraits » = reliées sans photo, « a_preparer » = avec photo sans affiche) :
- portraits  : fiches reliées à Immich, sans photo ;
- logos      : fiches sans photo qui portent une société et ne sont pas reliées à Immich. Le logo
               se choisit **par société** : il est posé sur toutes ses fiches sans photo, et gardé
               pour les fiches à venir. Une fiche qui a déjà une photo la garde : le logo ne
               remplace jamais une photo ;
- a_preparer : fiches avec une photo venue d'Immich, sans affiche iPhone ;
- a_poser    : affiches prêtes dans l'album Immich, pas encore posées sur l'iPhone.

Rien n'est écrit dans iCloud sans que Julien ait vu l'image : les lots ne portent que sur les
fiches qu'il a cochées. La recherche automatique d'un logo ne marche que pour une fiche qui a un
site ou un courriel professionnel (une sur dix d'après l'essai du 11/11/2026) ; le chemin
principal est le logo déposé : glissé depuis une autre fenêtre, collé, ou choisi comme fichier.
"""
from __future__ import annotations

import base64
import json
import io
import ipaddress
import socket
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx
from PIL import Image

from . import logos, photos
from .carnet import Carnet, ErreurCarnet
from .modele import nom_affiche
from .normalisation import cle_texte, domaine_pro
from .temps import iso, maintenant

LOT_MAX = 20                # fiches traitées au plus par envoi (le reste attend le lot suivant)
POIDS_MAX = 3_000_000
COTE_MIN = 48


def _ligne(uid: str, f: dict, **plus) -> dict:
    return {"uid": uid, "nom": nom_affiche(f), "societe": f.get("societe", ""), "groupes": f.get("groupes", []), **plus}


def files(c: Carnet) -> dict:
    fiches, liens = c.fiches(), c.liaisons()
    from . import attentes
    morts = attentes.decedes(c)
    cherches = {l["uid"]: dict(l) for l in c.base.tous("SELECT * FROM logos_cherches")}
    connus = {l["cle"] for l in c.base.tous("SELECT cle FROM logos_societes")}
    portraits_connus = {l["uid"] for l in c.base.tous("SELECT uid FROM portraits WHERE candidats != '[]'")}
    affiches = {l["uid"]: l["posee"] for l in c.base.tous("SELECT uid, posee FROM affiches")}
    res = {"portraits": [], "logos": [], "affiches": [], "a_poser": []}
    cherches_portraits = {l["uid"]: json.loads(l["candidats"]) for l in c.base.tous("SELECT uid, candidats FROM portraits")}
    for uid, f in fiches.items():
        if uid in morts:
            continue
        immich = bool(liens.get(uid, {}).get("immich"))
        logo = not immich and bool(f.get("societe")) and cle_societe(f) in connus
        if not f.get("a_photo") and not immich and f.get("societe"):
            recherche = cherches.get(uid)
            res["logos"].append(_ligne(uid, f, domaine=bool(logos.domaine_de(f, domaine_pro)),
                                       cherche=bool(recherche), trouves=recherche["trouves"] if recherche else 0,
                                       cle=cle_societe(f), connu=cle_societe(f) in connus,
                                       google=recherche_google(f)))
        if immich or logo:
            cands = cherches_portraits.get(uid)
            # « cherche » : la recherche Immich a été faite depuis la 2.11 (un logo gardé est toujours prêt)
            pret = logo or (cands is not None and photos.a_jour(cands))
            commun = {"mode": "immich" if immich else "logo", "cherche": pret,
                      "aucune": immich and cands is not None and photos.a_jour(cands) and not cands}
            res["portraits"].append(_ligne(uid, f, a_photo=bool(f.get("a_photo")), **commun))
            res["affiches"].append(_ligne(uid, f, a_photo=bool(f.get("a_photo")),
                                          affiche=None if uid not in affiches else "posée" if affiches[uid] else "prête",
                                          **commun))
        if uid in affiches and not affiches[uid]:
            res["a_poser"].append(_ligne(uid, f))
    # Ce qui manque d'abord, puis par nom
    res["portraits"].sort(key=lambda x: (x["a_photo"], x["nom"].casefold()))
    res["affiches"].sort(key=lambda x: (x["affiche"] is not None, x["nom"].casefold()))
    for cle in ("logos", "a_poser"):
        res[cle].sort(key=lambda x: x["nom"].casefold())
    nombres = {"logos": len(res["logos"]), "a_poser": len(res["a_poser"]),
               "portraits": sum(1 for x in res["portraits"] if not x["a_photo"]),
               "affiches": sum(1 for x in res["affiches"] if x["affiche"] is None)}
    return {"files": res, "nombres": nombres, "lot_max": LOT_MAX,
            "totaux": {"portraits": len(res["portraits"]), "affiches": len(res["affiches"])}}


def recherche_google(f: dict) -> str:
    """Adresse d'une recherche d'images du logo de la société. Ouverte dans un nouvel onglet par
    Julien : carnet lui-même n'interroge jamais Google."""
    mots = " ".join(x for x in (f.get("societe") or nom_affiche(f), "logo") if x)
    return "https://www.google.com/search?tbm=isch&q=" + quote_plus(mots)


def _par_lot(c: Carnet, uids: list[str], faire) -> dict:
    faits, erreurs = 0, []
    for uid in uids[:LOT_MAX]:
        try:
            if faire(uid) is not False:
                faits += 1
        except ErreurCarnet as exc:
            f = c.fiches().get(uid)
            erreurs.append(f"{nom_affiche(f) if f else 'Fiche'} : {exc}")
    c.oublier()
    return {"faits": faits, "restants": max(0, len(uids) - LOT_MAX), "erreurs": erreurs[:10]}


def poser_portraits(c: Carnet, uids: list[str]) -> dict:
    c.exiger_ecriture("iCloud")

    def un(uid):
        cands = photos.candidats(c, uid)
        if not cands:
            raise ErreurCarnet("aucun portrait utilisable dans Immich.")
        photos.poser(c, uid, cands[0]["asset"], origine="Photos")
    return _par_lot(c, uids, un)


def preparer_affiches(c: Carnet, uids: list[str]) -> dict:
    c.exiger_ecriture("Immich")
    return _par_lot(c, uids, lambda uid: photos.preparer_affiche(c, uid))


# ------------------------------------------------------------ 2.11 : propositions pour tous, pose des choix

def chercher_propositions(c: Carnet, uids: list[str]) -> dict:
    """Relit dans Immich les photos de chaque contact coché (une soixantaine d'appels par contact :
    par lots). N'écrit rien, ni dans iCloud ni dans Immich."""
    def un(uid):
        if not c.liaison(uid).get("immich"):
            return False
        photos.candidats(c, uid, rafraichir=True)
    return _par_lot(c, uids, un)


def _choix(corps: list) -> list[tuple[str, str]]:
    return [(str(x.get("uid")), str(x.get("cle"))) for x in corps if isinstance(x, dict) and x.get("uid") and x.get("cle") is not None]


def poser_choix(c: Carnet, choix: list[dict]) -> dict:
    """Pose, pour chaque contact coché, la photo choisie à l'écran (celle de carnet si l'on n'a rien
    touché). Relié à Immich : le portrait découpé, et le visage de la personne dans Immich suit.
    Sinon : le logo gardé pour la société. Une photo en place est remplacée — c'est pourquoi rien
    n'arrive ici sans avoir été coché."""
    c.exiger_ecriture("iCloud")
    par_uid = dict(_choix(choix))
    refus_immich: list[str] = []

    def un(uid):
        cle = par_uid[uid]
        if c.liaison(uid).get("immich"):
            res = photos.poser(c, uid, cle, origine="Photos")
            if res.get("immich") not in ("ok", "non relié"):
                refus_immich.append(nom_affiche(c.fiche(uid)))
            return
        logo = photos._logo_de(c, uid, int(cle)) if cle.isdigit() else None
        if logo is None:
            raise ErreurCarnet("logo introuvable : relance la recherche.")
        from . import actions
        photo = photos.images.alleger((logos.photo(logo), "image/jpeg"))
        actions.valider(c, uid, c.fiche(uid), photo=photo, origine="Photos", motif="logo en photo",
                        etag_vu=actions._etag(c, uid))
        retenir_logo(c, c.fiche(uid), logo)
    bilan = _par_lot(c, list(par_uid), un)
    if refus_immich:
        bilan["erreurs"] = (bilan["erreurs"] + [f"Visage non mis à jour dans Immich pour : {', '.join(refus_immich[:8])}."])[:10]
    return bilan


def preparer_choix(c: Carnet, choix: list[dict]) -> dict:
    """Prépare l'affiche choisie pour chaque contact coché (photo d'Immich, ou couleur du logo)."""
    c.exiger_ecriture("Immich")
    par_uid = dict(_choix(choix))

    def un(uid):
        cle = par_uid[uid]
        if c.liaison(uid).get("immich"):
            photos.preparer_affiche(c, uid, asset=cle)
        else:
            photos.preparer_affiche(c, uid, couleur=int(cle) if cle.isdigit() else None)
    return _par_lot(c, list(par_uid), un)


def marquer_posees(c: Carnet, uids: list[str]) -> dict:
    return _par_lot(c, uids, lambda uid: photos.marquer_posee(c, uid, True))


def chercher_logos(c: Carnet, uids: list[str]) -> dict:
    """Recherche sur le site de chaque société (aucun service tiers). Ne pose rien : renvoie, par
    fiche, le nombre de logos trouvés ; l'interface les montre et Julien coche."""
    res = []
    for uid in uids[:LOT_MAX]:
        try:
            trouves = photos.chercher_logos(c, uid)
        except ErreurCarnet:
            trouves = []
        c.base.executer("INSERT INTO logos_cherches(uid, le, trouves) VALUES (?,?,?) ON CONFLICT(uid) DO UPDATE SET "
                        "le = excluded.le, trouves = excluded.trouves", (uid, iso(maintenant()), len(trouves)))
        res.append({"uid": uid, "logos": trouves})
    c.oublier()
    return {"resultats": res, "restants": max(0, len(uids) - LOT_MAX)}


def cle_societe(f: dict) -> str:
    return cle_texte(f.get("societe") or "")


def logo_connu(c: Carnet, cle: str) -> bytes | None:
    l = c.base.un("SELECT image FROM logos_societes WHERE cle = ?", (cle,))
    return bytes(l["image"]) if l else None


def retenir_logo(c: Carnet, f: dict, contenu: bytes) -> None:
    """Le logo choisi pour une fiche devient celui de sa société."""
    cle = cle_societe(f)
    if cle:
        c.base.executer("INSERT INTO logos_societes(cle, nom, image, le) VALUES (?,?,?,?) ON CONFLICT(cle) DO UPDATE SET "
                        "nom = excluded.nom, image = excluded.image, le = excluded.le",
                        (cle, f.get("societe") or "", contenu, iso(maintenant())))


def fiches_de_la_societe(c: Carnet, cle: str) -> list[str]:
    """Fiches de cette société qui attendent un logo : sans photo, et pas reliées à Immich (celles-là
    auront un portrait). Une fiche qui a une photo n'est jamais dans la liste."""
    liens, res = c.liaisons(), []
    for uid, f in c.fiches().items():
        if cle and cle_societe(f) == cle and not f.get("a_photo") and not liens.get(uid, {}).get("immich"):
            res.append(uid)
    return sorted(res)


def poser_logos(c: Carnet, choix: list[dict]) -> dict:
    """Pose par société : chaque choix {uid, n} désigne le logo retenu sur une fiche ; il est posé
    sur toutes les fiches sans photo de la même société. Sans logo en attente pour cette fiche,
    c'est le logo déjà gardé pour la société qui sert."""
    c.exiger_ecriture("iCloud")
    a_poser: dict[str, bytes] = {}
    refus: list[str] = []
    for x in choix:
        uid = str(x.get("uid"))
        f = c.fiches().get(uid)
        if not f:
            continue
        cle = cle_societe(f)
        try:
            contenu = photos._logo(c, uid, int(x.get("n", 0)))
        except ErreurCarnet:
            contenu = logo_connu(c, cle)
        if not contenu:
            refus.append(f"{nom_affiche(f)} : dépose d'abord un logo.")
            continue
        retenir_logo(c, f, contenu)
        for cible in (fiches_de_la_societe(c, cle) or [uid]):
            a_poser.setdefault(cible, contenu)

    def un(uid):
        photos.garder_logos(c, uid, [{"url": "société", "octets": a_poser[uid], "largeur": 0, "hauteur": 0}])
        photos.choisir_logo(c, uid, 0, "photo")
    bilan = _par_lot(c, list(a_poser), un)
    bilan["erreurs"] = (refus + bilan["erreurs"])[:10]
    return bilan


# ----------------------------------------------------------------- logo déposé

def _adresse_publique(url: str) -> None:
    """Refuse tout ce qui n'est pas une adresse http(s) publique : carnet tourne sur le réseau de
    la maison et ne doit pas servir à lire ce qui s'y trouve."""
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ErreurCarnet("Adresse d'image non reconnue (http ou https attendu).")
    try:
        adresses = {x[4][0] for x in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))}
    except OSError:
        raise ErreurCarnet("Adresse d'image introuvable.")
    for a in adresses:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global:
            raise ErreurCarnet("Cette adresse désigne le réseau local : carnet ne la lit pas.")


def telecharger_image(url: str, transport: httpx.BaseTransport | None = None, verifier=_adresse_publique) -> bytes:
    """Image désignée par une adresse (glissée depuis le navigateur). « data: » est décodée sur
    place ; sinon téléchargement borné, redirections suivies une à une et contrôlées."""
    url = (url or "").strip()
    if url.startswith("data:"):
        entete, _, donnees = url.partition(",")
        if not entete.startswith("data:image/") or ";base64" not in entete:
            raise ErreurCarnet("Ce qui a été déposé n'est pas une image.")
        try:
            contenu = base64.b64decode(donnees, validate=False)
        except ValueError:
            raise ErreurCarnet("Image illisible.")
        if len(contenu) > POIDS_MAX:
            raise ErreurCarnet("Image trop lourde (3 Mo au plus).")
        return contenu
    with httpx.Client(timeout=10, follow_redirects=False, transport=transport,
                      headers={"User-Agent": logos.UA, "Accept": "image/*,*/*;q=0.5"}) as client:
        for _ in range(4):
            verifier(url)
            try:
                with client.stream("GET", url) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        raise ErreurCarnet(f"Le site a refusé l'image ({r.status_code}) : enregistre-la et dépose le fichier.")
                    morceaux, taille = [], 0
                    for m in r.iter_bytes():
                        taille += len(m)
                        if taille > POIDS_MAX:
                            raise ErreurCarnet("Image trop lourde (3 Mo au plus).")
                        morceaux.append(m)
                    return b"".join(morceaux)
            except httpx.HTTPError:
                raise ErreurCarnet("Image injoignable : enregistre-la et dépose le fichier.")
    raise ErreurCarnet("Trop de redirections pour cette image.")


def deposer_logo(c: Carnet, uid: str, contenu: bytes | None = None, url: str | None = None) -> dict:
    """Logo fourni par Julien (fichier, image collée, ou adresse glissée). Il devient le candidat
    n° 0 de la fiche : l'aperçu et la pose passent par le même chemin qu'un logo trouvé."""
    c.fiche(uid)
    if contenu is None:
        contenu = telecharger_image(url or "", transport=c.transports.get("logos"),
                                    verifier=(lambda u: None) if c.transports.get("logos") else _adresse_publique)
    if not contenu or len(contenu) > POIDS_MAX:
        raise ErreurCarnet("Image vide ou trop lourde (3 Mo au plus).")
    try:
        img = Image.open(io.BytesIO(contenu))
        img.load()
    except Exception:  # noqa: BLE001 — SVG, page web, fichier abîmé…
        raise ErreurCarnet("Image illisible. Les logos au format SVG ne sont pas pris : dépose un PNG ou un JPEG.")
    if min(img.size) < COTE_MIN:
        raise ErreurCarnet(f"Image trop petite ({img.size[0]} × {img.size[1]} px) : il faut au moins {COTE_MIN} px.")
    photos.garder_logos(c, uid, [{"url": "déposé", "octets": contenu, "largeur": img.size[0], "hauteur": img.size[1]}])
    return {"n": 0, "largeur": img.size[0], "hauteur": img.size[1], "petit": min(img.size) < 180}


__all__ = ["files", "poser_portraits", "preparer_affiches", "marquer_posees", "chercher_logos", "poser_logos",
           "deposer_logo", "telecharger_image", "recherche_google"]

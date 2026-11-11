"""Photos des fiches : portraits HD tirés d'Immich, affiches plein écran (album Immich) et logos
de société. Tout se fait à la demande depuis la fiche, sauf la photo d'une fiche liée qui n'en a
pas encore : la nuit la pose seule (jamais en remplacement d'une photo existante)."""
from __future__ import annotations

import io
import json
import logging

from PIL import Image

from . import images, logos, synchro
from .carnet import Carnet, ErreurCarnet
from .liens import ErreurLien
from .modele import nom_affiche
from .normalisation import domaine_pro
from .temps import iso, maintenant

log = logging.getLogger("carnet")
PHOTOS_EXAMINEES = 60     # photos Immich regardées par personne
CANDIDATS = 12            # visages gardés par personne (2.10 : de quoi proposer 5 photos et 5 affiches)
PROPOSITIONS = 5          # propositions montrées pour la photo, et pour l'affiche
VISAGE_MIN = 250          # côté minimal du visage sur la photo d'origine (pixels)
ALBUM = "Affiches de contacts"


def _immich_de(c: Carnet, uid: str) -> str:
    immich_id = c.liaison(uid).get("immich")
    if not immich_id:
        raise ErreurCarnet("Ce contact n'est pas lié à une personne Immich : lie-le d'abord.")
    return immich_id


def candidats(c: Carnet, uid: str, rafraichir: bool = False) -> list[dict]:
    """Les plus grands visages entiers de la personne (Immich a déjà repéré les visages)."""
    ligne = c.base.un("SELECT candidats FROM portraits WHERE uid = ?", (uid,))
    if ligne and not rafraichir:
        return json.loads(ligne["candidats"])
    immich_id = _immich_de(c, uid)
    im = c.immich()
    trouves = []
    try:
        for photo in im.photos_de(immich_id, PHOTOS_EXAMINEES):
            visage = next((v for v in im.visages_photo(photo["id"])
                           if (v.get("person") or {}).get("id") == immich_id), None)
            boite = images.boite_relative(visage) if visage else None
            if not boite or not images.entier(boite):
                continue
            taille = images.taille_reelle(boite, photo["largeur"], photo["hauteur"], visage)
            if taille < VISAGE_MIN:
                continue
            trouves.append({"asset": photo["id"], "boite": list(boite), "taille": taille, "type": photo["type"],
                            "le": (photo["le"] or "")[:10],
                            "ratio": round(visage["imageWidth"] / visage["imageHeight"], 4)
                            if visage.get("imageWidth") and visage.get("imageHeight") else None})
    except ErreurLien as exc:
        raise ErreurCarnet(str(exc))
    finally:
        im.fermer()
    trouves = sorted(trouves, key=lambda x: -x["taille"])[:CANDIDATS]
    c.base.executer("INSERT INTO portraits(uid, candidats, le) VALUES (?,?,?) "
                    "ON CONFLICT(uid) DO UPDATE SET candidats = excluded.candidats, le = excluded.le",
                    (uid, json.dumps(trouves), iso(maintenant())))
    return trouves


def _image_haute(im, cand: dict) -> bytes:
    """Original si Pillow le lit, sinon la version pleine taille d'Immich (HEIC, RAW…)."""
    contenu = None
    if (cand.get("type") or "").lower() in ("image/jpeg", "image/png", "image/webp", "image/tiff"):
        contenu = im.image(cand["asset"], "original")
        if contenu and not images.lisible(contenu):
            contenu = None
    for taille in ("fullsize", "preview"):
        if contenu:
            break
        contenu = im.image(cand["asset"], taille)
    if not contenu:
        raise ErreurCarnet("Photo introuvable dans Immich.")
    return contenu


def portrait(c: Carnet, uid: str, asset: str) -> tuple[bytes, str]:
    """Portrait carré découpé dans la photo choisie (JPEG 512 px, léger pour iCloud)."""
    cand = next((x for x in candidats(c, uid) if x["asset"] == asset), None)
    if not cand:
        raise ErreurCarnet("Cette photo n'est plus proposée : relance la recherche.")
    im = c.immich()
    try:
        contenu = _image_haute(im, cand)
    except ErreurLien as exc:
        raise ErreurCarnet(str(exc))
    finally:
        im.fermer()
    return images.alleger(images.portrait(contenu, cand["boite"]))


def poser(c: Carnet, uid: str, asset: str, origine: str = "manuel") -> dict:
    """Le portrait choisi devient la photo de la fiche dans iCloud."""
    from . import actions
    image = portrait(c, uid, asset)
    res = actions.valider(c, uid, c.fiche(uid), photo=image, origine=origine, motif="photo",
                          etag_vu=actions._etag(c, uid))
    c.base.executer("UPDATE portraits SET asset = ?, manuel = ?, le = ? WHERE uid = ?",
                    (asset, int(origine == "manuel"), iso(maintenant()), uid))
    return res


def apercu_candidat(c: Carnet, asset: str) -> bytes | None:
    im = c.immich()
    try:
        return im.image(asset, "thumbnail")
    except ErreurLien:
        return None
    finally:
        im.fermer()


def photo_fiche(c: Carnet, uid: str) -> tuple[bytes, str] | None:
    """Photo actuelle de la fiche, lue dans la carte iCloud (incluse, ou par son lien)."""
    ligne = c.base.un("SELECT texte FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        return None
    trouvee = synchro.photo(ligne["texte"])
    if not trouvee:
        return None
    if trouvee[0] == "image":
        return trouvee[1]
    dav = c.icloud()
    try:
        donnees = dav.telecharger(trouvee[1])
    finally:
        dav.fermer()
    return (donnees, synchro.type_image(donnees)) if donnees else None


def vignette(c: Carnet, uid: str, cote: int = 160) -> tuple[bytes, str] | None:
    def calcul():
        p = photo_fiche(c, uid)
        if not p:
            return None
        try:
            return images.vignette(p[0], cote)
        except Exception:  # noqa: BLE001 — image illisible
            return None
    etag = (c.base.un("SELECT etag FROM fiches WHERE uid = ?", (uid,)) or {"etag": ""})["etag"]
    return c.memo(f"vignette:{uid}:{etag}:{cote}", calcul, duree=7 * 86400)


# ------------------------------------------------------------ affiches (album Immich)

def _personne(f: dict) -> str:
    """Nom de la personne à écrire sous la société ; vide pour une fiche d'entreprise."""
    return nom_affiche(f) if (f.get("prenom") or f.get("nom")) else ""


def _logo_de(c: Carnet, uid: str, n: int | None = None) -> bytes | None:
    """Logo à utiliser pour la fiche : le candidat n° n s'il est donné, sinon le premier logo en
    attente, sinon celui gardé pour sa société."""
    from . import galerie
    attente = c.logos.get(uid) or []
    if n is not None:
        return attente[n]["octets"] if 0 <= n < len(attente) else None
    return attente[0]["octets"] if attente else galerie.logo_connu(c, galerie.cle_societe(c.fiche(uid)))


def propositions(c: Carnet, uid: str, rafraichir: bool = False) -> dict:
    """Ce que montre la fenêtre ouverte en touchant la photo d'une fiche en modification (2.10) :
    5 propositions de photo et 5 d'affiche. Contact relié à Immich : ses visages. Sinon : le logo
    de sa société (en attente, trouvé sur son site ou gardé) et 5 couleurs tirées de ce logo."""
    from . import galerie
    f = c.fiche(uid)
    if c.liaison(uid).get("immich"):
        cands = candidats(c, uid, rafraichir)
        cadrables = [x for x in cands if x.get("ratio") and images.cadre_affiche(x["boite"], x["ratio"])]
        cadrables.sort(key=lambda x: -images.cadre_affiche(x["boite"], x["ratio"])[1] * x["taille"])
        return {"mode": "immich", "societe": f.get("societe", ""),
                "photos": [{"cle": x["asset"], "le": x["le"]} for x in cands[:PROPOSITIONS]],
                "affiches": [{"cle": x["asset"], "le": x["le"]} for x in cadrables[:PROPOSITIONS]]}
    if not f.get("societe"):
        return {"mode": "rien", "societe": "", "photos": [], "affiches": [],
                "raison": "Ce contact n'est pas relié à Immich et n'a pas de société : relie-le dans le bloc Liaisons, "
                          "ou indique sa société pour utiliser un logo."}
    attente = list(c.logos.get(uid) or [])
    connu = galerie.logo_connu(c, galerie.cle_societe(f))
    if rafraichir and logos.domaine_de(f, domaine_pro):
        try:
            attente = logos.chercher(logos.domaine_de(f, domaine_pro), transport=c.transports.get("logos"))
        except Exception as exc:  # noqa: BLE001 — site injoignable : on garde ce qu'on a
            log.info("Logos introuvables pour %s : %s", uid, exc)
    if connu and all(x["octets"] != connu for x in attente):
        attente.append({"url": "gardé", "octets": connu, "largeur": 0, "hauteur": 0})
    attente = attente[:PROPOSITIONS]
    garder_logos(c, uid, attente)
    photos_ = [{"cle": str(i), "origine": "gardé pour la société" if x["url"] == "gardé" else
                "déposé" if x["url"] == "déposé" else "trouvé sur le site"} for i, x in enumerate(attente)]
    teintes = logos.couleurs(attente[0]["octets"], PROPOSITIONS) if attente else []
    return {"mode": "logo", "societe": f.get("societe", ""), "photos": photos_,
            "affiches": [{"cle": str(i), "couleur": "#%02x%02x%02x" % t} for i, t in enumerate(teintes)],
            "domaine": bool(logos.domaine_de(f, domaine_pro)), "google": galerie.recherche_google(f)}


def apercu_proposition(c: Carnet, uid: str, sorte: str, cle: str) -> bytes:
    """Petite image d'une proposition : la photo carrée telle qu'elle serait posée, ou l'affiche."""
    f = c.fiche(uid)
    if c.liaison(uid).get("immich"):
        cand = next((x for x in candidats(c, uid) if x["asset"] == cle), None)
        if not cand:
            raise ErreurCarnet("Cette photo n'est plus proposée : relance la recherche.")
        im = c.immich()
        try:
            contenu = im.image(cle, "preview")
        except ErreurLien as exc:
            raise ErreurCarnet(str(exc))
        finally:
            im.fermer()
        if not contenu:
            raise ErreurCarnet("Photo introuvable dans Immich.")
        try:
            return images.affiche(contenu, cand["boite"], hauteur=720) if sorte == "affiche" \
                else images.portrait(contenu, cand["boite"])[0]
        except ValueError:
            raise ErreurCarnet("Visage trop serré sur cette photo.")
    if sorte == "affiche":
        logo = _logo_de(c, uid)
        if not logo:
            raise ErreurCarnet("Pas de logo pour cette société.")
        teintes = logos.couleurs(logo, PROPOSITIONS)
        n = int(cle) if cle.isdigit() and int(cle) < len(teintes) else 0
        return logos.affiche(logo, f.get("societe", ""), largeur=354, hauteur=768, couleur=teintes[n], personne=_personne(f))
    logo = _logo_de(c, uid, int(cle) if cle.isdigit() else -1)
    if not logo:
        raise ErreurCarnet("Relance la recherche du logo.")
    return logos.photo(logo, 320)


def preparer_affiche(c: Carnet, uid: str, asset: str | None = None, logo: bytes | None = None,
                     couleur: int | None = None) -> dict:
    """Affiche verticale plein écran, ajoutée à l'album Immich « Affiches de contacts »
    (archivée : absente de la chronologie). Remplace l'affiche précédente du contact.
    2.10 : un contact sans portrait possible (non relié à Immich) reçoit l'affiche du logo de sa
    société : logo en haut, page à la couleur de la société (ou la couleur n° `couleur` des
    propositions), nom de la société, puis nom de la personne."""
    f = c.fiche(uid)
    if logo is None and not asset and not c.liaison(uid).get("immich"):
        logo = _logo_de(c, uid)
        if logo is None:
            raise ErreurCarnet("Pas de logo pour cette société : dépose-en un d'abord (Photos, file Logos).")
    if logo is not None:
        teintes = logos.couleurs(logo, PROPOSITIONS)
        teinte = teintes[couleur] if couleur is not None and 0 <= couleur < len(teintes) else teintes[0]
        contenu = logos.affiche(logo, f.get("societe") or nom_affiche(f), couleur=teinte, personne=_personne(f))
        source = "logo"
        from . import galerie
        galerie.retenir_logo(c, f, logo)               # le logo choisi devient celui de la société
    else:
        cands = candidats(c, uid)
        cand = next((x for x in cands if x["asset"] == asset), None) if asset else None
        cand = cand or next((x for x in cands if x.get("ratio") and images.cadre_affiche(x["boite"], x["ratio"])), None)
        if not cand and asset:
            raise ErreurCarnet("Cette photo n'est plus proposée : relance la recherche.")
        if not cand:
            raise ErreurCarnet("Aucune photo assez large pour une affiche : il faut un visage avec de la place autour.")
        im = c.immich()
        try:
            contenu = images.affiche(_image_haute(im, cand), cand["boite"])
        except ValueError:
            raise ErreurCarnet("Visage trop serré sur cette photo pour une affiche : choisis-en une autre.")
        finally:
            im.fermer()
        source = cand["asset"]
    contenu = images.legender(contenu, nom_affiche(f))
    im = c.immich()
    try:
        album = im.album(ALBUM, c.base.lire("album_affiches"))
        c.base.ecrire("album_affiches", album)
        nouvel = im.envoyer_image(contenu, f"{nom_affiche(f)}.jpg", iso(maintenant()))
        im.ajouter_album(album, [nouvel])
        ancienne = c.base.un("SELECT immich FROM affiches WHERE uid = ?", (uid,))
        if ancienne and ancienne["immich"]:
            try:
                im.supprimer_images([ancienne["immich"]])
            except ErreurLien as exc:
                log.warning("Ancienne affiche non retirée : %s", exc)
    except ErreurLien as exc:
        raise ErreurCarnet(str(exc))
    finally:
        im.fermer()
    c.base.executer("INSERT OR REPLACE INTO affiches(uid, source, immich, posee, le) VALUES (?,?,?,NULL,?)",
                    (uid, source, nouvel, iso(maintenant())))
    c.base.noter("photos", "Affiche préparée dans l'album Immich", {"uid": uid})
    return {"uid": uid, "immich": nouvel}


def image_affiche(c: Carnet, uid: str) -> bytes:
    ligne = c.base.un("SELECT immich FROM affiches WHERE uid = ?", (uid,))
    if not ligne or not ligne["immich"]:
        raise ErreurCarnet("Pas encore d'affiche pour ce contact.")
    im = c.immich()
    try:
        contenu = im.image(ligne["immich"], "original")
    except ErreurLien as exc:
        raise ErreurCarnet(str(exc))
    finally:
        im.fermer()
    if not contenu:
        raise ErreurCarnet("Affiche introuvable dans Immich : prépare-la de nouveau.")
    return contenu


def marquer_posee(c: Carnet, uid: str, posee: bool) -> None:
    c.base.executer("UPDATE affiches SET posee = ? WHERE uid = ?", (iso(maintenant()) if posee else None, uid))


def affiches(c: Carnet) -> list[dict]:
    fiches = c.fiches()
    return [{"uid": l["uid"], "nom": nom_affiche(fiches[l["uid"]]), "posee": l["posee"], "le": l["le"],
             "source": l["source"]}
            for l in c.base.tous("SELECT * FROM affiches") if l["uid"] in fiches]


# ------------------------------------------------------------ logos

def garder_logos(c: Carnet, uid: str, trouves: list[dict]) -> None:
    """Logos en attente d'un choix, gardés en mémoire (au plus 80 fiches : les plus anciennes sortent)."""
    c.logos.pop(uid, None)
    c.logos[uid] = trouves
    while len(c.logos) > 80:
        c.logos.pop(next(iter(c.logos)))


def chercher_logos(c: Carnet, uid: str) -> list[dict]:
    f = c.fiche(uid)
    domaine = logos.domaine_de(f, domaine_pro)
    if not domaine:
        raise ErreurCarnet("Pas de site ni de courriel professionnel dans la fiche : impossible de trouver le logo.")
    trouves = logos.chercher(domaine, transport=c.transports.get("logos"))
    garder_logos(c, uid, trouves)
    return [{"n": i, "url": x["url"], "largeur": x["largeur"], "hauteur": x["hauteur"]} for i, x in enumerate(trouves)]


def _logo(c: Carnet, uid: str, n: int) -> bytes:
    trouves = c.logos.get(uid) or []
    if not 0 <= n < len(trouves):
        raise ErreurCarnet("Relance la recherche du logo.")
    return trouves[n]["octets"]


def apercu_logo(c: Carnet, uid: str, n: int) -> bytes:
    img = Image.open(io.BytesIO(_logo(c, uid, n)))
    img.load()
    sortie = io.BytesIO()
    img.convert("RGBA").save(sortie, "PNG")
    return sortie.getvalue()


def choisir_logo(c: Carnet, uid: str, n: int, sorte: str) -> dict:
    from . import actions
    contenu = _logo(c, uid, n)
    if sorte == "affiche":
        return preparer_affiche(c, uid, logo=contenu)
    photo = images.alleger((logos.photo(contenu), "image/jpeg"))
    res = actions.valider(c, uid, c.fiche(uid), photo=photo, motif="logo en photo", etag_vu=actions._etag(c, uid))
    from . import galerie
    galerie.retenir_logo(c, c.fiche(uid), contenu)   # 2.8.1 : ce logo devient celui de la société
    return res

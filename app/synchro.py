"""Préparation des cartes écrites dans iCloud (V2).

Une carte iCloud existante n'est pas remplacée en bloc : carnet remplace les propriétés qu'il
gère (nom, téléphones, courriels, adresses, sites, notes, photo…) et garde tout le reste
(dates personnalisées, champs propres à Apple…). Les groupes iCloud sont des cartes à part
(X-ADDRESSBOOKSERVER-KIND:group) qui listent leurs membres par UID.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass, field

from .export import echapper, plier

# Propriétés écrites par carnet : remplacées à chaque écriture
GEREES = {"N", "FN", "NICKNAME", "ORG", "TITLE", "BDAY", "TEL", "EMAIL", "ADR", "URL", "X-SOCIALPROFILE",
          "X-ABRELATEDNAMES", "NOTE", "CATEGORIES", "PHOTO", "IMPP", "X-ABSHOWAS"}
# Repères qu'iCloud ajoute à côté de la photo (elle n'est alors pas incluse dans la carte)
PHOTO_ANNEXES = {"X-IMAGETYPE", "X-IMAGEHASH"}
# Propriétés d'enveloppe : réécrites
ENVELOPPE = {"BEGIN", "END", "VERSION", "PRODID", "UID", "REV"}
GROUPE_MEMBRE = "X-ADDRESSBOOKSERVER-MEMBER"
_NOM = re.compile(r"^(?:(?P<groupe>[A-Za-z0-9-]+)\.)?(?P<nom>[A-Za-z0-9-]+)")


def deplier(texte: str) -> list[str]:
    lignes: list[str] = []
    for brute in texte.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if brute[:1] in (" ", "\t") and lignes:
            lignes[-1] += brute[1:]
        elif brute.strip():
            lignes.append(brute)
    return lignes


def _decouper(ligne: str) -> tuple[str | None, str, str]:
    """(groupe, NOM en majuscules, valeur brute)."""
    m = _NOM.match(ligne)
    if not m:
        return None, "", ""
    valeur = ligne.split(":", 1)[1] if ":" in ligne else ""
    return m["groupe"], m["nom"].upper(), valeur


def _devaleur(v: str) -> str:
    return (v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\"))


@dataclass
class Carte:
    href: str
    etag: str
    texte: str
    uid: str = ""
    nom: str = ""
    groupe: bool = False
    membres: list[str] = field(default_factory=list)


def analyser(href: str, etag: str, texte: str) -> Carte:
    c = Carte(href, etag, texte)
    for ligne in deplier(texte):
        _, nom, valeur = _decouper(ligne)
        if nom == "UID":
            c.uid = _devaleur(valeur).replace("urn:uuid:", "").strip()
        elif nom == "FN":
            c.nom = _devaleur(valeur).strip()
        elif nom == "X-ADDRESSBOOKSERVER-KIND" and valeur.strip().lower() == "group":
            c.groupe = True
        elif nom == GROUPE_MEMBRE:
            c.membres.append(valeur.strip().replace("urn:uuid:", ""))
    if not c.uid:  # carte sans UID : son nom de fichier en tient lieu
        c.uid = href.rstrip("/").rsplit("/", 1)[-1].removesuffix(".vcf")
    return c


def _apple(nom: str, valeur: str) -> bool:
    """Profil iMessage / FaceTime (x-apple:) : carnet ne le lit pas, il porte le nom et la photo
    partagés par le contact. Il est toujours gardé."""
    return nom in ("X-SOCIALPROFILE", "IMPP") and "x-apple:" in valeur.lower()


def _conservees(distante: str, gerees: set[str] = GEREES) -> list[str]:
    """Lignes de la carte iCloud que carnet ne gère pas. Un groupe « itemN. » est gardé en
    entier ou retiré en entier (une étiquette X-ABLabel suit sa propriété)."""
    lignes = deplier(distante)
    retires = {g for g, nom, v in map(_decouper, lignes) if g and nom in gerees and not _apple(nom, v)}
    gardees = []
    for ligne in lignes:
        g, nom, valeur = _decouper(ligne)
        if _apple(nom, valeur):
            gardees.append(ligne)
        elif g:
            if g not in retires:
                gardees.append(ligne)
        elif nom not in gerees and nom not in ENVELOPPE:
            gardees.append(ligne)
    return gardees


def _renumeroter(lignes: list[str], depart: int) -> list[str]:
    """Les groupes conservés prennent des numéros après ceux écrits par carnet."""
    correspondance: dict[str, str] = {}
    res = []
    for ligne in lignes:
        g, _, _ = _decouper(ligne)
        if g:
            if g not in correspondance:
                correspondance[g] = f"item{depart + len(correspondance)}"
            ligne = correspondance[g] + ligne[len(g):]
        res.append(ligne)
    return res


def assembler(nouvelle: str, distante: str | None) -> str:
    """Carte écrite dans iCloud : celle de carnet, plus ce que l'iCloud avait en plus.
    Sans photo dans carnet, celle d'iCloud est gardée (jamais de photo perdue en silence)."""
    lignes = [l for l in deplier(nouvelle) if _decouper(l)[1] not in ("CATEGORIES", "END")]
    if distante:
        # Avec une photo écrite par carnet, les repères de l'ancienne image (X-IMAGEHASH…) sont
        # retirés : iCloud les recalcule. Sans photo, tout ce qui concerne celle d'iCloud reste.
        gerees = GEREES | PHOTO_ANNEXES if any(_decouper(l)[1] == "PHOTO" for l in lignes) \
            else GEREES - {"PHOTO"}
        items = [int(m) for l in lignes if (m := (re.match(r"item(\d+)\.", l) or [None, None])[1])]
        lignes += _renumeroter(_conservees(distante, gerees), max(items, default=0) + 1)
    lignes.append("END:VCARD")
    return "\r\n".join(plier(l) for l in lignes) + "\r\n"


def carte_groupe(nom: str, uid: str, membres: list[str], distante: str | None = None) -> str:
    lignes = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//carnet//FR", f"N:{echapper(nom)}", f"FN:{echapper(nom)}",
              "X-ADDRESSBOOKSERVER-KIND:group"]
    if distante:
        lignes += [l for l in _conservees(distante)
                   if _decouper(l)[1] not in ("X-ADDRESSBOOKSERVER-KIND", GROUPE_MEMBRE)]
    lignes += [f"{GROUPE_MEMBRE}:urn:uuid:{m}" for m in sorted(membres)]
    lignes += [f"UID:{uid}", "END:VCARD"]
    return "\r\n".join(plier(l) for l in lignes) + "\r\n"


def empreinte(texte: str) -> str:
    """Signature d'une carte, indépendante de l'ordre des lignes, du pliage et des numéros d'item."""
    lignes = []
    for l in deplier(texte):
        g, nom, _ = _decouper(l)
        if nom in ("PRODID", "REV"):
            continue
        lignes.append(l[len(g) + 1:] if g else l)
    return hashlib.sha256("\n".join(sorted(x.lower() for x in lignes)).encode()).hexdigest()


def type_image(donnees: bytes) -> str:
    if donnees[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if donnees[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if donnees[:4] in (b"GIF8",):
        return "image/gif"
    if donnees[8:12] == b"WEBP":
        return "image/webp"
    if donnees[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic"
    return "image/jpeg"


def photo(texte: str) -> tuple[str, object] | None:
    """Photo d'une carte : ("lien", url) quand iCloud ne donne qu'une adresse à télécharger,
    ("image", (octets, type)) quand elle est incluse dans la carte, None sinon."""
    for ligne in deplier(texte):
        _, nom, valeur = _decouper(ligne)
        if nom != "PHOTO" or not valeur.strip():
            continue
        valeur = valeur.strip()
        if valeur.lower().startswith(("http://", "https://")):
            return "lien", valeur
        if valeur.startswith("data:"):
            valeur = valeur.partition(",")[2]
        try:
            donnees = base64.b64decode(valeur, validate=False)
        except (binascii.Error, ValueError):
            return None
        return ("image", (donnees, type_image(donnees))) if donnees else None
    return None


def a_une_photo(texte: str | None) -> bool:
    """La carte iCloud a une photo, incluse ou seulement signalée (X-IMAGEHASH)."""
    return bool(texte) and any(_decouper(l)[1] in ({"PHOTO"} | PHOTO_ANNEXES) for l in deplier(texte))

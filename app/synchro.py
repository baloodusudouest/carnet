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


# iCloud colle parfois une propriété à la fin de la précédente, sans retour à la ligne
# (« …x-apple:+3361234X-SHARED-PHOTO-DISPLAY-PREF:ALWAYS_ASK ») : elle est remise sur sa ligne
_COLLEES = re.compile(r"(?<=[^\s.])(?=(?:X-SHARED-PHOTO-DISPLAY-PREF|X-ADDRESSBOOKSERVER-[A-Z-]+|X-ADDRESSING-GRAMMAR"
                      r"|VND-\d+-[A-Z0-9-]+)[;:])")
# Une vraie ligne de vCard commence par « NOM: » ou « NOM; » (éventuellement « itemN.NOM »)
_LIGNE = re.compile(r"^(?:[A-Za-z0-9-]+\.)?[A-Za-z0-9-]+[;:]")
# Données internes d'iCloud (prononciation Siri, en JSON sur plusieurs lignes, ce qui rend la
# carte illisible si on la renvoie) : jamais renvoyées, iCloud les recalcule
JETEES = {"X-ADDRESSBOOKSERVER-PHONEME-DATA"}


def deplier(texte: str) -> list[str]:
    lignes: list[str] = []
    for brute in texte.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if brute[:1] in (" ", "\t") and lignes:
            lignes[-1] += brute[1:]
        elif brute.strip():
            lignes.append(brute)
    res: list[str] = []
    for ligne in lignes:
        res.extend(x for x in _COLLEES.split(ligne) if x)
    # Les restes d'une valeur sur plusieurs lignes (JSON d'iCloud) ne sont pas des propriétés
    return [l for l in res if _LIGNE.match(l)]


def nettoyer_texte(texte: str) -> str:
    """Carte iCloud remise en forme lisible : propriétés décollées, données internes retirées."""
    lignes = [l for l in deplier(texte) if _decouper(l)[1] not in JETEES]
    return "\r\n".join(plier(l) for l in lignes) + "\r\n"


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
    brut: str = ""       # texte reçu d'iCloud, tel quel (sauvegarde)


def analyser(href: str, etag: str, texte: str) -> Carte:
    c = Carte(href, etag, nettoyer_texte(texte), brut=texte)
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
        elif nom not in gerees and nom not in ENVELOPPE and nom not in JETEES:
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


# Champs de la fiche → propriétés vCard qui les portent
SITES = {"URL", "X-SOCIALPROFILE"}


def _cle_ligne_site(ligne: str) -> str | None:
    """Clé d'un site écrit sur une ligne URL ou X-SOCIALPROFILE (adresse sans http ni www),
    ou None si carnet ne la lit pas comme un site."""
    from .normalisation import cle_site, site
    entete, _, valeur = ligne.partition(":")
    v = _devaleur(valeur).strip()
    if not v.lower().startswith("http"):
        m = re.search(r";x-user=([^;:]+)", entete, re.I)
        if m and not v:
            v = m.group(1).strip('"')
    s = site(v)
    return cle_site(s) if s else None


PROPRIETES = {
    "prenom": {"N", "FN"}, "nom": {"N", "FN"}, "surnom": {"NICKNAME"}, "societe": {"ORG", "X-ABSHOWAS", "FN"},
    "fonction": {"TITLE"}, "anniversaire": {"BDAY"}, "telephones": {"TEL"}, "courriels": {"EMAIL"},
    "adresses": {"ADR"}, "sites": {"URL", "X-SOCIALPROFILE"}, "noms_associes": {"X-ABRELATEDNAMES"},
    "notes": {"NOTE"}, "photo": {"PHOTO"} | PHOTO_ANNEXES,
    "service": {"ORG"}, "prononciation_prenom": {"X-PHONETIC-FIRST-NAME"},
    "prononciation_nom": {"X-PHONETIC-LAST-NAME"},
}
# Fête, mariage, décès : des X-ABDATE repérés par leur libellé (voir remplacer_dates)
CHAMPS_DATES = ("fete", "mariage", "deces")


def assembler_partiel(nouvelle: str, distante: str, champs: set[str], retypes: set[str] | None = None) -> str:
    """Carte écrite quand seuls certains champs changent : les lignes d'origine d'iCloud restent
    telles quelles pour tout le reste (titre et suffixe du nom, service, boîte postale, étiquettes
    personnalisées, IMPP…). Seules les propriétés des champs modifiés viennent de carnet."""
    props = set().union(*(PROPRIETES.get(ch, set()) for ch in champs)) if champs else set()
    if not props:
        return nettoyer_texte(distante)

    def groupes_de(lignes: list[str]) -> dict[str, str]:
        """itemN → propriété principale du groupe (TEL, EMAIL…), l'étiquette X-ABLabel suit."""
        res = {}
        for l in lignes:
            g, nom, _ = _decouper(l)
            if g and nom not in ("X-ABLABEL", "X-ABADR"):
                res.setdefault(g, nom)
        return res

    dist = deplier(distante)
    gdist = groupes_de(dist)
    neuves = deplier(nouvelle)
    gneuf = groupes_de(neuves)

    def principal_de(l: str, groupes: dict[str, str]) -> str:
        g, nom, _ = _decouper(l)
        return groupes.get(g, nom) if g else nom

    # Sites : comparés un par un. Une ligne URL / X-SOCIALPROFILE d'iCloud dont le site est encore
    # sur la fiche reste telle quelle (paramètres x-user, étiquette personnalisée…) ; seule celle
    # d'un site retiré part, seul un site nouveau est ajouté. Une ligne que carnet ne sait pas
    # lire est toujours gardée.
    sites = "sites" in champs
    cles_neuves = {k for l in neuves if principal_de(l, gneuf) in SITES and (k := _cle_ligne_site(l))} if sites else set()
    retirees: set[str] = set()      # groupes « itemN » ou lignes seules retirées
    cles_gardees: set[str] = set()
    if sites:
        for l in dist:
            g, nom, v = _decouper(l)
            if principal_de(l, gdist) not in SITES or (g and nom == "X-ABLABEL") or _apple(nom, v):
                continue
            k = _cle_ligne_site(l)
            if k is None or (k in cles_neuves and k not in (retypes or set())):
                if k:
                    cles_gardees.add(k)
            else:
                retirees.add(g or l)
    gardees = []
    for l in dist:
        g, nom, v = _decouper(l)
        principal = principal_de(l, gdist)
        if nom == "END" or nom in JETEES:
            continue
        if sites and principal in SITES:
            if (g or l) in retirees:
                continue
        elif principal in props and not _apple(principal, v):
            continue
        gardees.append(l)

    def ajoutee(l: str) -> bool:
        principal = principal_de(l, gneuf)
        if principal not in props:
            return False
        if sites and principal in SITES:
            g = _decouper(l)[0]
            tete = next((x for x in neuves if g and _decouper(x)[0] == g and _decouper(x)[1] != "X-ABLABEL"), l)
            return _cle_ligne_site(tete) not in cles_gardees
        return True
    ajout = [l for l in neuves if ajoutee(l)]
    items = [int(m) for l in gardees if (m := (re.match(r"item(\d+)\.", l) or [None, None])[1])]
    ajout = _renumeroter(ajout, max(items, default=0) + 1)
    lignes = gardees + ajout + ["END:VCARD"]
    return "\r\n".join(plier(l) for l in lignes) + "\r\n"


def remplacer_dates(texte: str, fiche: dict, champs: set[str]) -> str:
    """Réécrit dans la carte les seules dates supplémentaires des champs donnés (fete, mariage,
    deces). Les autres dates de la carte — autre libellé, libellé natif d'Apple — ne bougent pas."""
    from .export import lignes_dates
    from .vcard import champ_date
    champs = {c for c in champs if c in CHAMPS_DATES}
    if not champs:
        return texte
    lignes = deplier(texte)
    libelles = {g: _devaleur(v).strip() for g, nom, v in map(_decouper, lignes) if g and nom == "X-ABLABEL"}
    a_retirer = {g for g, nom, _ in map(_decouper, lignes)
                 if g and nom == "X-ABDATE" and champ_date(libelles.get(g, "")) in champs}
    gardees = [l for l in lignes if _decouper(l)[0] not in a_retirer and _decouper(l)[1] != "END"]
    items = [int(m.group(1)) for l in gardees if (m := re.match(r"item(\d+)\.", l))]
    suivant = max(items, default=0) + 1
    for (propriete, valeur), libelle in lignes_dates(fiche, champs):
        gardees += [f"item{suivant}.{propriete}:{valeur}", f"item{suivant}.X-ABLabel:{libelle}"]
        suivant += 1
    return "\r\n".join(plier(l) for l in gardees + ["END:VCARD"]) + "\r\n"


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


# 2.17.2 : ce que Synology Contacts réécrit ou ne garde pas, sans rien changer au contenu
_SYNOLOGY_NE_GARDE_PAS = ("X-ABDATE", "X-ABLABEL", "X-ABRELATEDNAMES", "X-ABADR", "X-ADDRESSBOOKSERVER-")
_STRUCTURES = ("N", "ORG", "ADR")


def ligne_comme_synology(l: str) -> str | None:
    """Une ligne de carte sous une forme que Synology ne change pas : sans groupe, en minuscules, paramètres triés,
    TYPE répétés réunis en un seul (« TYPE=CELL;TYPE=VOICE » = « TYPE=CELL,VOICE »), sans les « ; » vides de fin
    des valeurs structurées (« ORG:Société; » = « ORG:Société »). None : une ligne que Synology ne garde pas."""
    g, nom, valeur = _decouper(l)
    if nom in ("PRODID", "REV") or nom.startswith(_SYNOLOGY_NE_GARDE_PAS):
        return None
    tete = (l[len(g) + 1:] if g else l).split(":", 1)[0]
    morceaux = tete.split(";")
    types, autres = set(), []
    for p in morceaux[1:]:
        cle, _, v = p.partition("=")
        if cle.strip().lower() == "type":
            types |= {x.strip().lower() for x in v.split(",") if x.strip()}
        elif p.strip():
            autres.append(p.strip().lower())
    params = sorted(autres) + ([f"type={','.join(sorted(types))}"] if types else [])
    if nom in _STRUCTURES:
        valeur = valeur.rstrip(";")
    return ";".join([morceaux[0].lower(), *params]) + ":" + valeur.lower()


def empreinte_synology(texte: str) -> str:
    """2.17.2 : l'empreinte d'une carte pour la comparer à sa copie dans Synology (voir ligne_comme_synology)."""
    lignes = (ligne_comme_synology(l) for l in deplier(texte))
    return hashlib.sha256("\n".join(sorted(x for x in lignes if x is not None)).encode()).hexdigest()


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

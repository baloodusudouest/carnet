"""Lecture des fichiers .vcf exportés par iCloud.com et Google Contacts (vCard 3.0)."""
from __future__ import annotations

import base64
import logging
import re

import vobject

from .. import normalisation as n
from ..modele import GROUPES, fiche_vide
from . import FicheLue

log = logging.getLogger("carnet.vcard")

ETIQUETTES_APPLE = {
    # téléphones, courriels, adresses
    "mobile": "mobile", "iphone": "mobile", "home": "domicile", "work": "travail",
    "main": "principal", "other": "autre", "bureau": "bureau", "office": "bureau",
    "domicile": "domicile", "travail": "travail", "portable": "mobile",
    # noms associés
    "spouse": "conjoint", "partner": "partenaire", "mother": "mère", "father": "père",
    "parent": "parent", "child": "enfant", "son": "enfant", "daughter": "enfant",
    "brother": "frère", "sister": "sœur", "friend": "ami", "assistant": "assistant",
    "manager": "responsable", "conjoint": "conjoint", "mere": "mère", "pere": "père",
    "enfant": "enfant", "frere": "frère", "soeur": "sœur", "ami": "ami",
    # sites
    "homepage": "site", "home page": "site",
}

TYPES_TEL = {"CELL": "mobile", "IPHONE": "mobile", "HOME": "domicile", "WORK": "travail",
             "MAIN": "principal", "OTHER": "autre", "FAX": "autre", "PAGER": "autre"}
TYPES_LIEU = {"HOME": "domicile", "WORK": "travail", "OTHER": "autre"}
CLES_GROUPES = {n.cle_texte(g): g for g in GROUPES}

BLOC = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.S | re.I)


def _etiquette(libelle: str) -> str | None:
    """« _$!<Mobile>!$_ » → « mobile » ; un libellé personnalisé est cherché tel quel."""
    m = re.fullmatch(r"_\$!<(.+?)>!\$_", libelle.strip())
    cle = n.cle_texte(m.group(1) if m else libelle)
    return ETIQUETTES_APPLE.get(cle)


def _types(ligne) -> list[str]:
    types = []
    for valeur in ligne.params.get("TYPE", []):
        types += [t.strip().upper() for t in str(valeur).split(",") if t.strip()]
    return types


def _type_depuis(ligne, libelles: dict, table: dict, defaut: str | None) -> str | None:
    if ligne.group and ligne.group.lower() in libelles:
        trouve = _etiquette(libelles[ligne.group.lower()])
        if trouve:
            return trouve
    for t in _types(ligne):
        if t in table:
            return table[t]
    return defaut


def _texte(valeur) -> str:
    if isinstance(valeur, list):
        valeur = ",".join(str(v) for v in valeur)
    return str(valeur or "").strip()


def _photo(ligne) -> tuple[bytes | None, str | None]:
    valeur = ligne.value
    type_ = (_types(ligne) or ["JPEG"])[0].lower()
    if isinstance(valeur, bytes):
        return valeur, f"image/{'jpeg' if type_ == 'jpg' else type_}"
    texte = str(valeur or "")
    if texte.startswith("data:"):  # vCard 4 : data:image/jpeg;base64,…
        entete, _, donnees = texte.partition(",")
        try:
            return base64.b64decode(donnees), entete[5:].split(";")[0] or "image/jpeg"
        except ValueError:
            return None, None
    return None, None  # lien vers un serveur (Google) : inutilisable hors ligne


def _lire_carte(brut: str, region: str) -> tuple[FicheLue | None, dict | None]:
    """Retourne (fiche, None) pour un contact, (None, groupe) pour une carte de groupe Apple."""
    carte = vobject.readOne(brut, ignoreUnreadable=True)
    lignes = list(carte.getChildren())
    noms = {ligne.name.upper() for ligne in lignes}

    # Carte de groupe iCloud : X-ADDRESSBOOKSERVER-KIND:group + MEMBER:urn:uuid:…
    for ligne in lignes:
        if ligne.name.upper() == "X-ADDRESSBOOKSERVER-KIND" and _texte(ligne.value).lower() == "group":
            membres = [_texte(m.value).replace("urn:uuid:", "") for m in lignes
                       if m.name.upper() == "X-ADDRESSBOOKSERVER-MEMBER"]
            nom = _texte(carte.fn.value) if "FN" in noms else ""
            return None, {"nom": nom, "membres": membres}

    libelles = {ligne.group.lower(): _texte(ligne.value) for ligne in lignes
                if ligne.group and ligne.name.upper() == "X-ABLABEL"}
    f = fiche_vide()
    lue = FicheLue(fiche=f, brut=brut)

    if "N" in noms:
        nn = carte.n.value
        prenom = " ".join(p for p in (_texte(nn.given), _texte(nn.additional)) if p)
        f["prenom"], f["nom"] = prenom, _texte(nn.family)
    if not (f["prenom"] or f["nom"]) and "FN" in noms:
        # Une fiche d'entreprise (FN = société, ou X-ABShowAs:COMPANY) n'a pas de prénom ni de nom
        org = carte.org.value if "ORG" in noms else []
        org = _texte(org[0] if isinstance(org, list) and org else org)
        entreprise = "X-ABSHOWAS" in noms and _texte(carte.contents["x-abshowas"][0].value).upper() == "COMPANY"
        fn = _texte(carte.fn.value)
        if not entreprise and n.cle_texte(fn) != n.cle_texte(org):
            f["prenom"], f["nom"] = n.separer_nom_complet(fn)
    f["prenom"] = n.formater_prenom(f["prenom"])
    f["nom"] = n.formater_nom(f["nom"])

    for ligne in lignes:
        nom = ligne.name.upper()
        try:
            if nom == "NICKNAME":
                f["surnom"] = _texte(ligne.value)
            elif nom == "ORG":
                org = ligne.value if isinstance(ligne.value, list) else [ligne.value]
                f["societe"] = _texte(org[0] if org else "")
            elif nom == "TITLE":
                f["fonction"] = _texte(ligne.value)
            elif nom == "NOTE":
                f["notes"] = _texte(ligne.value)
            elif nom == "BDAY":
                omet = "X-APPLE-OMIT-YEAR" in {k.upper() for k in ligne.params}
                f["anniversaire"] = n.anniversaire(_texte(ligne.value), sans_annee=omet)
            elif nom == "UID":
                lue.uid = _texte(ligne.value).replace("urn:uuid:", "") or None
            elif nom == "TEL":
                # Sans type : mobile ou « autre » selon le numéro lui-même
                t = n.telephone(_texte(ligne.value),
                                _type_depuis(ligne, libelles, TYPES_TEL, None), region)
                if t:
                    f["telephones"].append(t)
            elif nom == "EMAIL":
                c = n.courriel(_texte(ligne.value),
                               _type_depuis(ligne, libelles, TYPES_LIEU, "domicile"))
                if c:
                    f["courriels"].append(c)
            elif nom == "ADR":
                a = ligne.value
                ad = n.adresse(_texte(a.street), _texte(a.code), _texte(a.city), _texte(a.region),
                               _texte(a.country), _type_depuis(ligne, libelles, TYPES_LIEU, "domicile"))
                if ad:
                    f["adresses"].append(ad)
            elif nom == "URL":
                lib = libelles.get((ligne.group or "").lower(), "")
                s = n.site(_texte(ligne.value), _etiquette(lib) if lib else None)
                if s:
                    f["sites"].append(s)
            elif nom == "X-SOCIALPROFILE":
                reseau = (_types(ligne) or [""])[0].lower()
                valeur = _texte(ligne.value)
                if not valeur.startswith("http") and "X-USER" in {k.upper() for k in ligne.params}:
                    valeur = valeur or _texte(ligne.params.get("X-USER", [""])[0])
                s = n.site(valeur, reseau if reseau in ("linkedin", "facebook", "instagram", "tiktok")
                           else ("x" if reseau == "twitter" else None))
                if s:
                    f["sites"].append(s)
            elif nom == "X-ABRELATEDNAMES":
                lib = libelles.get((ligne.group or "").lower(), "")
                r = n.nom_associe(_texte(ligne.value), (_etiquette(lib) if lib else None) or "autre")
                if r:
                    f["noms_associes"].append(r)
            elif nom == "CATEGORIES":
                valeurs = ligne.value if isinstance(ligne.value, list) else _texte(ligne.value).split(",")
                for v in valeurs:
                    groupe = CLES_GROUPES.get(n.cle_texte(str(v)))
                    if groupe:
                        f["groupes"].append(groupe)
            elif nom == "PHOTO" and lue.photo is None:
                lue.photo, lue.photo_type = _photo(ligne)
        except Exception as exc:  # une ligne bizarre ne doit pas faire perdre le contact
            lue.avertissements.append(f"{nom} ignoré : {exc}")
    n.dedoublonner(f)
    return lue, None


def lire(texte: str, region: str = "FR") -> tuple[list[FicheLue], list[str]]:
    """Lit un fichier .vcf entier. Retourne (contacts, avertissements)."""
    fiches, groupes, avertissements = [], [], []
    for i, bloc in enumerate(BLOC.findall(texte.replace("\r\n", "\n")), start=1):
        try:
            lue, groupe = _lire_carte(bloc, region)
        except Exception as exc:
            avertissements.append(f"Carte n° {i} illisible : {exc}")
            continue
        if groupe:
            groupes.append(groupe)
        elif lue:
            fiches.append(lue)
            avertissements += [f"Carte n° {i} : {a}" for a in lue.avertissements]
    # Appartenance aux groupes iCloud (cartes de groupe incluses dans l'export)
    par_uid = {f.uid: f for f in fiches if f.uid}
    for g in groupes:
        groupe = CLES_GROUPES.get(n.cle_texte(g["nom"]))
        if not groupe:
            continue
        for uid in g["membres"]:
            if uid in par_uid and groupe not in par_uid[uid].fiche["groupes"]:
                par_uid[uid].fiche["groupes"].append(groupe)
    return fiches, avertissements

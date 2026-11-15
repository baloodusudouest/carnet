"""Lecture des cartes vCard : celles d'iCloud (CardDAV) et des fichiers .vcf importés à la main."""
from __future__ import annotations

import base64
import logging
import re

from dataclasses import dataclass, field

import vobject

from . import normalisation as n
from .modele import DATES_LIBELLEES, fiche_vide, groupes_reconnus


@dataclass
class FicheLue:
    fiche: dict
    uid: str | None = None
    photo: bytes | None = None
    photo_type: str | None = None
    brut: str = ""
    avertissements: list[str] = field(default_factory=list)

log = logging.getLogger("carnet.vcard")

ETIQUETTES_APPLE = {
    # téléphones, courriels, adresses
    "mobile": "mobile", "iphone": "mobile", "home": "domicile", "work": "travail",
    "main": "principal", "other": "autre", "bureau": "bureau", "office": "bureau",
    "domicile": "domicile", "travail": "travail", "portable": "mobile",
    # noms associés
    "spouse": "conjoint", "partner": "partenaire", "mother": "mère", "father": "père",
    "parent": "parent", "child": "enfant", "son": "fils", "daughter": "fille", "husband": "mari", "wife": "épouse",
    "fils": "fils", "fille": "fille", "mari": "mari", "epouse": "épouse",
    # 2.24 : libellé « école » de l'iPhone (numéros, courriels, adresses, URL)
    "school": "école", "ecole": "école", "autre": "autre",
    "brother": "frère", "sister": "sœur", "friend": "ami", "assistant": "assistant",
    "manager": "responsable", "conjoint": "conjoint", "mere": "mère", "pere": "père",
    "enfant": "enfant", "frere": "frère", "soeur": "sœur", "ami": "ami",
    "frere ou sœur": "frère ou sœur", "frere ou soeur": "frère ou sœur", "sibling": "frère ou sœur",
    # sites
    "homepage": "site", "home page": "site",
}

TYPES_TEL = {"CELL": "mobile", "IPHONE": "mobile", "HOME": "domicile", "WORK": "travail",
             "MAIN": "principal", "OTHER": "autre", "FAX": "fax travail", "PAGER": "pager"}
TYPES_LIEU = {"HOME": "domicile", "WORK": "travail", "OTHER": "autre"}
# 2.24 : messageries instantanées (IMPP). Le préfixe est celui que l'iPhone écrit pour chaque service.
PREFIXES_MESSAGERIE = {"Skype": "skype", "MSN": "msnim", "GoogleTalk": "xmpp", "Facebook": "xmpp", "AIM": "aim",
                       "Yahoo": "ymsgr", "ICQ": "aim", "Jabber": "xmpp"}
RESEAUX_LUS = {"linkedin": "linkedin", "facebook": "facebook", "instagram": "instagram", "tiktok": "tiktok",
               "telegram": "telegram", "whatsapp": "whatsapp", "signal": "signal", "twitter": "x",
               "flickr": "flickr", "myspace": "myspace", "sinaweibo": "sina weibo"}
DATES_APPLE = {"anniversary": "anniversaire (Apple)", "other": "autre"}


def _groupe_connu(nom: str) -> str | None:
    """Nom de groupe lu dans un export → groupe de carnet (intégré ou créé), sinon None."""
    return {n.cle_texte(g): g for g in groupes_reconnus()}.get(n.cle_texte(nom))

BLOC = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.S | re.I)
_CHAMP_DATE = {n.cle_texte(v): k for k, v in DATES_LIBELLEES.items()}


def champ_date(libelle: str) -> str | None:
    """Libellé d'une date supplémentaire → champ de la fiche (« Fête » → fete), sinon None."""
    return _CHAMP_DATE.get(n.cle_texte(libelle))


def date_supplementaire(valeur: str, champ: str) -> str:
    """Valeur d'un X-ABDATE → « AAAA-MM-JJ » ou « --MM-JJ ». L'an 1604 veut dire « sans année »,
    que le paramètre X-APPLE-OMIT-YEAR soit là ou non (l'iPhone le retire en réécrivant la carte).
    La fête n'a jamais d'année."""
    d = n.anniversaire(valeur)
    if len(d) == 10 and (d.startswith("1604-") or champ == "fete"):
        d = "--" + d[5:]
    return d


def _etiquette(libelle: str) -> str | None:
    """« _$!<Mobile>!$_ » → « mobile » ; un libellé personnalisé est cherché tel quel."""
    m = re.fullmatch(r"_\$!<(.+?)>!\$_", libelle.strip())
    cle = n.cle_texte(m.group(1) if m else libelle)
    return ETIQUETTES_APPLE.get(cle)


def _libelle_libre(libelle: str) -> str:
    """Libellé que carnet ne connaît pas : gardé tel quel (« iCloud »), ou le mot d'Apple en minuscules."""
    m = re.fullmatch(r"_\$!<(.+?)>!\$_", libelle.strip())
    return (m.group(1).lower() if m else " ".join(libelle.split()))


def _type_tel(ligne, libelles: dict) -> str | None:
    """2.24 : fax (domicile, travail), pager et Apple Watch sont gardés au lieu de devenir « autre »."""
    types = set(_types(ligne))
    if not (ligne.group and ligne.group.lower() in libelles):
        if "FAX" in types:
            return "fax domicile" if "HOME" in types else "fax travail"
        if "APPLEWATCH" in types:
            return "apple watch"
        if "PAGER" in types:
            return "pager"
    return _type_depuis(ligne, libelles, TYPES_TEL, None)


def _types(ligne) -> list[str]:
    types = []
    for valeur in ligne.params.get("TYPE", []):
        types += [t.strip().upper() for t in str(valeur).split(",") if t.strip()]
    return types


def _type_depuis(ligne, libelles: dict, table: dict, defaut: str | None, libre: bool = False) -> str | None:
    """libre (2.24, courriels et adresses) : un libellé écrit à la main sur l'iPhone est gardé tel quel."""
    if ligne.group and ligne.group.lower() in libelles:
        trouve = _etiquette(libelles[ligne.group.lower()])
        if trouve:
            return trouve
        if libre and _libelle_libre(libelles[ligne.group.lower()]):
            return _libelle_libre(libelles[ligne.group.lower()])
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


def lire_carte(brut: str, region: str = "FR") -> tuple[FicheLue | None, dict | None]:
    """Retourne (fiche, None) pour un contact, (None, groupe) pour une carte de groupe Apple."""
    # vobject coupe la valeur d'un TEL à la première virgule : la pause avant un numéro de poste
    # (« +33 5 53 00 00 00,123 ») est réécrite en « poste » pour être conservée
    protege = re.sub(r"^((?:item\d+\.)?TEL[^:\n]*:)([^\n]*)$",
                     lambda m: m.group(1) + re.sub(r"\s*[,;]+\s*(?=\d)", " poste ", m.group(2)),
                     brut, flags=re.M | re.I)
    carte = vobject.readOne(protege, ignoreUnreadable=True)
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
        # 2.24 : second prénom, titre et suffixe ont leur champ (avant : le second prénom était collé au prénom)
        f["prenom"], f["nom"] = _texte(nn.given), _texte(nn.family)
        f["second_prenom"] = n.formater_prenom(_texte(nn.additional))
        f["titre"], f["suffixe"] = _texte(nn.prefix), _texte(nn.suffix)
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
                f["service"] = " ".join(_texte(org[1]).split()) if len(org) > 1 else ""
            elif nom == "X-PHONETIC-FIRST-NAME":
                f["prononciation_prenom"] = _texte(ligne.value)
            elif nom == "X-PHONETIC-LAST-NAME":
                f["prononciation_nom"] = _texte(ligne.value)
            elif nom == "X-PHONETIC-MIDDLE-NAME":
                f["phonetique_second_prenom"] = _texte(ligne.value)
            elif nom == "X-PHONETIC-ORG":
                f["phonetique_societe"] = _texte(ligne.value)
            elif nom == "X-PRONUNCIATION-FIRST-NAME":
                f["dire_prenom"] = _texte(ligne.value)
            elif nom == "X-PRONUNCIATION-LAST-NAME":
                f["dire_nom"] = _texte(ligne.value)
            elif nom == "X-MAIDENNAME":
                f["nom_naissance"] = _texte(ligne.value)
            elif nom == "X-ACTIVITY-ALERT":
                # Sonnerie et son SMS réglés sur l'iPhone (« type=call,snd=system:Shelter ») : lus, jamais écrits
                v = _texte(ligne.value).replace("\\,", ",")
                son = v.rsplit(":", 1)[-1].strip() if ":" in v else ""
                if "type=call" in v and son:
                    f["sonnerie"] = son
                elif "type=text" in v and son:
                    f["son_sms"] = son
            elif nom == "X-ABDATE":
                # Date supplémentaire : Fête, Mariage et Décès ont leur champ ; les autres (libellé
                # d'Apple ou écrit à la main) vont dans « dates_autres » (2.24)
                lib = libelles.get((ligne.group or "").lower(), "")
                champ = champ_date(lib)
                if champ and not f[champ]:
                    f[champ] = date_supplementaire(_texte(ligne.value), champ)
                elif not champ and ligne.group:
                    d = date_supplementaire(_texte(ligne.value), "")
                    if d:
                        m = re.fullmatch(r"_\$!<(.+?)>!\$_", lib.strip())
                        type_ = DATES_APPLE.get(m.group(1).lower(), m.group(1).lower()) if m else (" ".join(lib.split()) or "autre")
                        f["dates_autres"].append({"valeur": d, "type": type_})
            elif nom == "TITLE":
                f["fonction"] = _texte(ligne.value)
            elif nom == "NOTE":
                f["notes"] = n.note(_texte(ligne.value))
            elif nom == "BDAY":
                omet = "X-APPLE-OMIT-YEAR" in {k.upper() for k in ligne.params}
                f["anniversaire"] = n.anniversaire(_texte(ligne.value), sans_annee=omet)
            elif nom == "UID":
                lue.uid = _texte(ligne.value).replace("urn:uuid:", "") or None
            elif nom == "TEL":
                # Sans type : mobile ou « autre » selon le numéro lui-même
                t = n.telephone(_texte(ligne.value), _type_tel(ligne, libelles), region)
                if t:
                    f["telephones"].append(t)
            elif nom == "EMAIL":
                c = n.courriel(_texte(ligne.value),
                               _type_depuis(ligne, libelles, TYPES_LIEU, "domicile", libre=True))
                if c:
                    f["courriels"].append(c)
                elif (s := n.site(_texte(ligne.value))):  # un lien saisi comme courriel
                    f["sites"].append(s)
            elif nom == "IMPP":
                # 2.24 : messagerie instantanée (service dans X-SERVICE-TYPE). Les profils iMessage / FaceTime
                # et les services écrits en « x-apple: » (QQ, Gadu-Gadu) restent dans la carte sans être lus.
                brut_v = _texte(ligne.value)
                service = _texte((ligne.params.get("X-SERVICE-TYPE") or [""])[0])
                if service and not brut_v.lower().startswith("x-apple:"):
                    from urllib.parse import unquote
                    pseudo = unquote(brut_v.split(":", 1)[1] if ":" in brut_v else brut_v).strip()
                    if pseudo:
                        f["messageries"].append({"valeur": pseudo, "type": service})
                elif (s := n.site(brut_v)):       # un lien web saisi comme messagerie
                    f["sites"].append(s)
            elif nom == "ADR":
                a = ligne.value
                ad = n.adresse(_texte(a.street), _texte(a.code), _texte(a.city), _texte(a.region),
                               _texte(a.country), _type_depuis(ligne, libelles, TYPES_LIEU, "domicile", libre=True))
                if ad:
                    f["adresses"].append(ad)
            elif nom == "URL":
                lib = libelles.get((ligne.group or "").lower(), "")
                connu = _etiquette(lib) if lib else None
                # 2.24 : URL « domicile » ou « travail » (TYPE=HOME / WORK), « école », ou libellé écrit à la main
                lieu = next((TYPES_LIEU[t] for t in _types(ligne) if t in ("HOME", "WORK")), None)
                s = n.site(_texte(ligne.value), connu or lieu)
                if s:
                    if s["type"] == "site" and lib and not connu and _libelle_libre(lib):
                        s["type"] = _libelle_libre(lib)       # aucun réseau reconnu : le libellé de l'iPhone est gardé
                    f["sites"].append(s)
            elif nom == "X-SOCIALPROFILE":
                reseau = (_types(ligne) or [""])[0].lower()
                valeur = _texte(ligne.value)
                if not valeur.startswith("http") and "X-USER" in {k.upper() for k in ligne.params}:
                    valeur = valeur or _texte(ligne.params.get("X-USER", [""])[0])
                s = n.site(valeur, RESEAUX_LUS.get(reseau))
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
                    groupe = _groupe_connu(str(v))
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
            lue, groupe = lire_carte(bloc, region)
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
        groupe = _groupe_connu(g["nom"])
        if not groupe:
            continue
        for uid in g["membres"]:
            if uid in par_uid and groupe not in par_uid[uid].fiche["groupes"]:
                par_uid[uid].fiche["groupes"].append(groupe)
    return fiches, avertissements

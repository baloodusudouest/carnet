"""Écriture des fiches au format vCard 3.0, tel qu'iCloud et l'iPhone le lisent."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from . import images
from .modele import DATES_LIBELLEES, GROUPE_VERIFIES

TEL_224 = {"fax domicile": "type=HOME;type=FAX", "fax travail": "type=WORK;type=FAX", "pager": "type=PAGER",
           "apple watch": "type=APPLEWATCH;type=CELL;type=VOICE"}     # 2.24, comme l'iPhone les écrit
# Libellés d'Apple pour les types que carnet connaît ; tout autre type est écrit comme libellé personnalisé
LIBELLES_LIEU = {"école": "_$!<School>!$_", "autre": "_$!<Other>!$_"}
DATES_APPLE = {"anniversaire (Apple)": "_$!<Anniversary>!$_", "autre": "_$!<Other>!$_"}
TEL = {"mobile": "type=CELL;type=VOICE", "domicile": "type=HOME;type=VOICE",
       "travail": "type=WORK;type=VOICE", "principal": "type=MAIN", "autre": "type=OTHER;type=VOICE"}
LIEU = {"domicile": "type=HOME", "travail": "type=WORK"}
RELATIONS = {"conjoint": "Spouse", "partenaire": "Partner", "mère": "Mother", "père": "Father",
             "parent": "Parent", "enfant": "Child", "frère": "Brother", "sœur": "Sister",
             "fils": "Son", "fille": "Daughter", "mari": "Husband", "épouse": "Wife",
             "ami": "Friend", "assistant": "Assistant", "responsable": "Manager", "autre": "Other"}
LIBELLES_LIBRES = {"frère ou sœur": "frère ou sœur"}
RESEAUX = {"linkedin", "facebook", "instagram", "tiktok", "x", "telegram", "whatsapp", "signal",
           "flickr", "myspace", "sina weibo"}
RESEAUX_ECRITS = {"x": "twitter", "sina weibo": "sinaweibo"}


def echapper(texte: str) -> str:
    return (str(texte).replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def plier(ligne: str) -> str:
    """Coupe à 75 octets (RFC 2425) sans couper un caractère UTF-8."""
    morceaux, courant, taille = [], "", 0
    for c in ligne:
        n = len(c.encode("utf-8"))
        limite = 75 if not morceaux else 74  # la ligne de continuation commence par une espace
        if taille + n > limite:
            morceaux.append(courant)
            courant, taille = "", 0
        courant += c
        taille += n
    morceaux.append(courant)
    return "\r\n ".join(morceaux)


def vcard(fiche: dict, uid: str, photo: tuple[bytes, str] | None = None,
          verifie: bool = False) -> str:
    l: list[str] = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//carnet//FR"]
    item = 0

    def etiquette(propriete: str, valeur: str, libelle: str) -> None:
        nonlocal item
        item += 1
        l.append(f"item{item}.{propriete}:{valeur}")
        l.append(f"item{item}.X-ABLabel:{libelle}")

    prenom, nom, societe = fiche.get("prenom", ""), fiche.get("nom", ""), fiche.get("societe", "")
    # 2.24 : nom ; prénom ; second prénom ; titre ; suffixe, comme l'iPhone
    l.append("N:" + ";".join(echapper(x) for x in (nom, prenom, fiche.get("second_prenom") or "",
                                                  fiche.get("titre") or "", fiche.get("suffixe") or "")))
    complet = " ".join(p for p in (prenom, nom) if p) or societe or fiche.get("surnom", "") or "(sans nom)"
    l.append(f"FN:{echapper(complet)}")
    if not (prenom or nom) and societe:
        l.append("X-ABShowAs:COMPANY")
    if fiche.get("surnom"):
        l.append(f"NICKNAME:{echapper(fiche['surnom'])}")
    if societe or fiche.get("service"):
        l.append(f"ORG:{echapper(societe)};{echapper(fiche.get('service') or '')}")
    if fiche.get("prononciation_prenom"):
        l.append(f"X-PHONETIC-FIRST-NAME:{echapper(fiche['prononciation_prenom'])}")
    if fiche.get("prononciation_nom"):
        l.append(f"X-PHONETIC-LAST-NAME:{echapper(fiche['prononciation_nom'])}")
    for champ, propriete in (("phonetique_second_prenom", "X-PHONETIC-MIDDLE-NAME"), ("phonetique_societe", "X-PHONETIC-ORG"),
                             ("dire_prenom", "X-PRONUNCIATION-FIRST-NAME"), ("dire_nom", "X-PRONUNCIATION-LAST-NAME"),
                             ("nom_naissance", "X-MAIDENNAME")):
        if fiche.get(champ):
            l.append(f"{propriete}:{echapper(fiche[champ])}")
    if fiche.get("fonction"):
        l.append(f"TITLE:{echapper(fiche['fonction'])}")
    annif = fiche.get("anniversaire", "")
    if len(annif) == 10:
        l.append(f"BDAY;VALUE=date:{annif}")
    elif annif.startswith("--"):
        l.append(f"BDAY;X-APPLE-OMIT-YEAR=1604;VALUE=date:1604-{annif[2:]}")

    for i, t in enumerate(fiche.get("telephones", [])):
        # Numéro : pas d'échappement de « ; » ni « , » (attente / pause avant le poste, comme l'iPhone)
        valeur = str(t.get("affichage") or t["valeur"]).replace("\n", " ").replace("\\", "")
        pref = ";type=pref" if i == 0 else ""
        if t.get("type") in TEL:
            l.append(f"TEL;{TEL[t['type']]}{pref}:{valeur}")
        elif t.get("type") in TEL_224:
            l.append(f"TEL;{TEL_224[t['type']]}{pref}:{valeur}")
        elif t.get("type") == "école":
            etiquette(f"TEL{pref}", valeur, LIBELLES_LIEU["école"])
        else:
            etiquette(f"TEL;type=VOICE{pref}", valeur, echapper(t.get("type") or "autre"))
    for i, c in enumerate(fiche.get("courriels", [])):
        pref = ";type=pref" if i == 0 else ""
        if c.get("type") in LIEU:
            l.append(f"EMAIL;type=INTERNET;{LIEU[c['type']]}{pref}:{echapper(c['valeur'])}")
        else:
            etiquette(f"EMAIL;type=INTERNET{pref}", echapper(c["valeur"]),
                      LIBELLES_LIEU.get(c.get("type") or "autre") or echapper(c["type"]))
    for a in fiche.get("adresses", []):
        champs = ";".join(echapper(a.get(k, "")) for k in ("rue", "ville", "region", "cp", "pays"))
        if a.get("type") in LIEU:
            l.append(f"ADR;{LIEU[a['type']]}:;;{champs}")
        else:
            etiquette("ADR", f";;{champs}", LIBELLES_LIEU.get(a.get("type") or "autre") or echapper(a["type"]))
    for s in fiche.get("sites", []):
        if s.get("type") in RESEAUX:
            reseau = RESEAUX_ECRITS.get(s["type"], s["type"])
            l.append(f"X-SOCIALPROFILE;type={reseau}:{echapper(s['valeur'])}")
        elif s.get("type") in LIEU:                 # 2.24 : URL « domicile » ou « travail »
            l.append(f"URL;{LIEU[s['type']]}:{echapper(s['valeur'])}")
        else:
            etiquette("URL", echapper(s["valeur"]), "_$!<HomePage>!$_" if s.get("type") in ("site", None, "")
                      else LIBELLES_LIEU.get(s["type"]) or echapper(s["type"]))
    for r in fiche.get("noms_associes", []):
        # 2.22 : Apple n'a pas de libellé neutre pour la fratrie : « frère ou sœur » est un libellé personnalisé
        etiquette("X-ABRELATEDNAMES", echapper(r["valeur"]), LIBELLES_LIBRES.get(r.get("type"))
                  or f"_$!<{RELATIONS.get(r.get('type', 'autre'), 'Other')}>!$_")
    for ligne_date, libelle in lignes_dates(fiche) + lignes_dates_autres(fiche):
        etiquette(*ligne_date, libelle)
    for propriete, valeur, libelle in lignes_messageries(fiche):
        etiquette(propriete, valeur, libelle)
    if fiche.get("notes"):
        l.append(f"NOTE:{echapper(fiche['notes'])}")
    groupes = list(fiche.get("groupes", [])) + ([GROUPE_VERIFIES] if verifie else [])
    if groupes:
        l.append("CATEGORIES:" + ",".join(echapper(g) for g in groupes))
    if photo and photo[0]:
        photo = images.alleger(photo)   # iCloud refuse les fiches trop lourdes (~120 Ko)
        type_ = (photo[1] or "image/jpeg").split("/")[-1].upper().replace("JPG", "JPEG")
        l.append(f"PHOTO;ENCODING=b;TYPE={type_}:" + base64.b64encode(photo[0]).decode("ascii"))
    l.append(f"UID:{uid}")
    l.append("END:VCARD")
    return "\r\n".join(plier(x) for x in l) + "\r\n"


def lignes_dates(fiche: dict, champs=None) -> list[tuple[tuple[str, str], str]]:
    """Dates supplémentaires à écrire : [((propriété, valeur), libellé)]. Une date sans année
    s'écrit comme le fait l'iPhone : an 1604 et paramètre X-APPLE-OMIT-YEAR."""
    res = []
    for champ, libelle in DATES_LIBELLEES.items():
        d = fiche.get(champ) or ""
        if champs is not None and champ not in champs:
            continue
        if len(d) == 10:
            res.append((("X-ABDATE", d), libelle))
        elif d.startswith("--") and len(d) == 7:
            res.append((("X-ABDATE;X-APPLE-OMIT-YEAR=1604", f"1604-{d[2:]}"), libelle))
    return res


def lignes_dates_autres(fiche: dict) -> list[tuple[tuple[str, str], str]]:
    """2.24 : dates libres de la fiche (libellé d'Apple ou écrit à la main), dans la forme de lignes_dates."""
    res = []
    for d in fiche.get("dates_autres") or []:
        v, libelle = d.get("valeur") or "", DATES_APPLE.get(d.get("type") or "autre") or echapper(d["type"])
        if len(v) == 10:
            res.append((("X-ABDATE", v), libelle))
        elif v.startswith("--") and len(v) == 7:
            res.append((("X-ABDATE;X-APPLE-OMIT-YEAR=1604", f"1604-{v[2:]}"), libelle))
    return res


ANCIENNES_MESSAGERIES = {"MSN": "X-MSN", "AIM": "X-AIM", "Yahoo": "X-YAHOO", "ICQ": "X-ICQ", "Jabber": "X-JABBER"}


def lignes_messageries(fiche: dict) -> list[tuple[str, str, str]]:
    """2.24 : [(propriété, valeur, libellé)] des messageries instantanées, comme l'iPhone les écrit : la ligne
    IMPP, précédée pour cinq services de leur ancienne propriété (X-MSN, X-AIM…) que l'iPhone tient encore."""
    from urllib.parse import quote
    from .vcard import PREFIXES_MESSAGERIE
    res = []
    for m in fiche.get("messageries") or []:
        service, pseudo = m.get("type") or "Skype", (m.get("valeur") or "").strip()
        if not pseudo:
            continue
        if service in ANCIENNES_MESSAGERIES:
            res.append((ANCIENNES_MESSAGERIES[service], echapper(pseudo), echapper(service)))
        prefixe = PREFIXES_MESSAGERIE.get(service, "im")
        res.append((f"IMPP;X-SERVICE-TYPE={service}", f"{prefixe}:{quote(pseudo, safe='@._-+')}", echapper(service)))
    return res


def ecrire_atomique(chemin: Path, texte: str) -> None:
    """Écrit à côté puis renomme : le kit ne lit jamais un fichier à moitié écrit."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=".carnet-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(texte)
        os.chmod(tmp, 0o644)
        os.replace(tmp, chemin)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

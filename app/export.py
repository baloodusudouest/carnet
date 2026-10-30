"""Écriture des fiches au format vCard 3.0, tel qu'iCloud et l'iPhone le lisent."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from .modele import GROUPE_VERIFIES

TEL = {"mobile": "type=CELL;type=VOICE", "domicile": "type=HOME;type=VOICE",
       "travail": "type=WORK;type=VOICE", "principal": "type=MAIN", "autre": "type=OTHER;type=VOICE"}
LIEU = {"domicile": "type=HOME", "travail": "type=WORK"}
RELATIONS = {"conjoint": "Spouse", "partenaire": "Partner", "mère": "Mother", "père": "Father",
             "parent": "Parent", "enfant": "Child", "frère": "Brother", "sœur": "Sister",
             "ami": "Friend", "assistant": "Assistant", "responsable": "Manager", "autre": "Other"}
RESEAUX = {"linkedin", "facebook", "instagram", "tiktok", "x", "telegram", "whatsapp", "signal"}


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
    l.append(f"N:{echapper(nom)};{echapper(prenom)};;;")
    complet = " ".join(p for p in (prenom, nom) if p) or societe or fiche.get("surnom", "") or "(sans nom)"
    l.append(f"FN:{echapper(complet)}")
    if not (prenom or nom) and societe:
        l.append("X-ABShowAs:COMPANY")
    if fiche.get("surnom"):
        l.append(f"NICKNAME:{echapper(fiche['surnom'])}")
    if societe:
        l.append(f"ORG:{echapper(societe)};")
    if fiche.get("fonction"):
        l.append(f"TITLE:{echapper(fiche['fonction'])}")
    annif = fiche.get("anniversaire", "")
    if len(annif) == 10:
        l.append(f"BDAY;VALUE=date:{annif}")
    elif annif.startswith("--"):
        l.append(f"BDAY;X-APPLE-OMIT-YEAR=1604;VALUE=date:1604-{annif[2:]}")

    for i, t in enumerate(fiche.get("telephones", [])):
        valeur = echapper(t.get("affichage") or t["valeur"])
        pref = ";type=pref" if i == 0 else ""
        if t.get("type") in TEL:
            l.append(f"TEL;{TEL[t['type']]}{pref}:{valeur}")
        else:
            etiquette(f"TEL;type=VOICE{pref}", valeur, echapper(t.get("type") or "autre"))
    for i, c in enumerate(fiche.get("courriels", [])):
        pref = ";type=pref" if i == 0 else ""
        if c.get("type") in LIEU:
            l.append(f"EMAIL;type=INTERNET;{LIEU[c['type']]}{pref}:{echapper(c['valeur'])}")
        else:
            etiquette(f"EMAIL;type=INTERNET{pref}", echapper(c["valeur"]), "_$!<Other>!$_")
    for a in fiche.get("adresses", []):
        champs = ";".join(echapper(a.get(k, "")) for k in ("rue", "ville", "region", "cp", "pays"))
        if a.get("type") in LIEU:
            l.append(f"ADR;{LIEU[a['type']]}:;;{champs}")
        else:
            etiquette("ADR", f";;{champs}", "_$!<Other>!$_")
    for s in fiche.get("sites", []):
        if s.get("type") in RESEAUX:
            reseau = "twitter" if s["type"] == "x" else s["type"]
            l.append(f"X-SOCIALPROFILE;type={reseau}:{echapper(s['valeur'])}")
        else:
            etiquette("URL", echapper(s["valeur"]), "_$!<HomePage>!$_" if s.get("type") == "site"
                      else "_$!<Other>!$_")
    for r in fiche.get("noms_associes", []):
        etiquette("X-ABRELATEDNAMES", echapper(r["valeur"]),
                  f"_$!<{RELATIONS.get(r.get('type', 'autre'), 'Other')}>!$_")
    if fiche.get("notes"):
        l.append(f"NOTE:{echapper(fiche['notes'])}")
    groupes = list(fiche.get("groupes", [])) + ([GROUPE_VERIFIES] if verifie else [])
    if groupes:
        l.append("CATEGORIES:" + ",".join(echapper(g) for g in groupes))
    if photo and photo[0]:
        type_ = (photo[1] or "image/jpeg").split("/")[-1].upper().replace("JPG", "JPEG")
        l.append(f"PHOTO;ENCODING=b;TYPE={type_}:" + base64.b64encode(photo[0]).decode("ascii"))
    l.append(f"UID:{uid}")
    l.append("END:VCARD")
    return "\r\n".join(plier(x) for x in l) + "\r\n"


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

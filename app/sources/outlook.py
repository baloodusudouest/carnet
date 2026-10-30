"""Lecture de l'export CSV d'Outlook.com (Contacts > Gérer > Exporter les contacts).

En-têtes anglais, identiques quelle que soit la langue du compte :
First Name, Middle Name, Last Name, …, E-mail Address, Mobile Phone, Birthday, Notes…
"""
from __future__ import annotations

import csv
import io
import re

from .. import normalisation as n
from ..modele import GROUPES_RECONNUS, fiche_vide
from . import FicheLue

TELEPHONES = [
    ("Mobile Phone", "mobile"), ("Home Phone", "domicile"), ("Home Phone 2", "domicile"),
    ("Business Phone", "travail"), ("Business Phone 2", "travail"),
    ("Company Main Phone", "principal"), ("Primary Phone", "principal"),
    ("Other Phone", "autre"), ("Car Phone", "autre"), ("Radio Phone", "autre"),
    ("Callback", "autre"), ("Assistant's Phone", "autre"),
]
COURRIELS = [("E-mail Address", "domicile"), ("E-mail 2 Address", "domicile"),
             ("E-mail 3 Address", "domicile")]
ADRESSES = [("Home", "domicile"), ("Business", "travail"), ("Other", "autre")]
CLES_GROUPES = {n.cle_texte(g): g for g in GROUPES_RECONNUS}


def _ordre_des_dates(lignes: list[dict]) -> tuple[str, bool]:
    """Devine si le fichier écrit les dates J/M ou M/J en regardant toutes les dates.
    Retourne (ordre, certain)."""
    jm = mj = False
    for v in lignes:
        for colonne in ("Birthday", "Anniversary"):
            mo = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/\d{2,4}\s*", v.get(colonne) or "")
            if mo:
                x, y = int(mo.group(1)), int(mo.group(2))
                jm |= x > 12
                mj |= y > 12
    if jm and not mj:
        return "jm", True
    if mj and not jm:
        return "mj", True
    return "mj", False  # format américain par défaut d'Outlook


def lire(texte: str, region: str = "FR") -> tuple[list[FicheLue], list[str]]:
    lecteur = csv.DictReader(io.StringIO(texte))
    if not lecteur.fieldnames or "First Name" not in lecteur.fieldnames:
        return [], ["Ce fichier ne ressemble pas à un export Outlook (colonne « First Name » absente)."]
    lignes = [{k: (val or "").strip() for k, val in ligne.items() if k} for ligne in lecteur]
    ordre, certain = _ordre_des_dates(lignes)
    fiches, avertissements = [], []
    if not certain and any("/" in v.get("Birthday", "") for v in lignes):
        avertissements.append("Dates d'anniversaire lues au format mois/jour (format d'Outlook) : "
                              "vérifie-les pendant la révision.")
    for i, v in enumerate(lignes, start=2):
        f = fiche_vide()
        prenom = " ".join(p for p in (v.get("First Name", ""), v.get("Middle Name", "")) if p)
        f["prenom"] = n.formater_prenom(prenom)
        f["nom"] = n.formater_nom(v.get("Last Name", ""))
        f["surnom"] = v.get("Nickname", "")
        f["societe"] = v.get("Company", "")
        f["fonction"] = v.get("Job Title", "")
        f["notes"] = n.note(v.get("Notes", ""))
        f["anniversaire"] = n.anniversaire(v.get("Birthday", ""), ordre=ordre)
        for colonne, type_ in TELEPHONES:
            t = n.telephone(v.get(colonne, ""), type_, region)
            if t:
                f["telephones"].append(t)
        for colonne, type_ in COURRIELS:
            c = n.courriel(v.get(colonne, ""), type_)
            if c:
                f["courriels"].append(c)
        for prefixe, type_ in ADRESSES:
            rue = "\n".join(x for x in (v.get(f"{prefixe} Street", ""), v.get(f"{prefixe} Street 2", ""),
                                        v.get(f"{prefixe} Street 3", "")) if x)
            a = n.adresse(rue, v.get(f"{prefixe} Postal Code", ""), v.get(f"{prefixe} City", ""),
                          v.get(f"{prefixe} State", ""), v.get(f"{prefixe} Country/Region", ""), type_)
            if a:
                f["adresses"].append(a)
        for colonne in ("Personal Web Page", "Web Page"):
            s = n.site(v.get(colonne, ""))
            if s:
                f["sites"].append(s)
        if v.get("Spouse"):
            f["noms_associes"].append({"valeur": v["Spouse"], "type": "conjoint"})
        if v.get("Manager's Name"):
            f["noms_associes"].append({"valeur": v["Manager's Name"], "type": "responsable"})
        if v.get("Assistant's Name"):
            f["noms_associes"].append({"valeur": v["Assistant's Name"], "type": "assistant"})
        for categorie in re.split(r"[;,]", v.get("Categories", "")):
            groupe = CLES_GROUPES.get(n.cle_texte(categorie))
            if groupe and groupe not in f["groupes"]:
                f["groupes"].append(groupe)
        n.dedoublonner(f)
        if not any((f["prenom"], f["nom"], f["societe"], f["telephones"], f["courriels"])):
            avertissements.append(f"Ligne {i} vide, ignorée.")
            continue
        brut = ",".join(f'"{c}"' for c in v.values() if c)
        fiches.append(FicheLue(fiche=f, brut=brut))
    return fiches, avertissements

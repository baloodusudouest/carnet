"""Lecture de Connections.csv (archive « Télécharger mes données » de LinkedIn).

Le fichier commence par quelques lignes « Notes: … » avant l'en-tête :
First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ces fiches enrichissent les contacts existants ; elles n'en créent jamais.
"""
from __future__ import annotations

import csv
import io
import re

from .. import normalisation as n
from ..modele import fiche_vide
from . import FicheLue


def lire(texte: str, region: str = "FR") -> tuple[list[FicheLue], list[str]]:
    lignes = texte.splitlines()
    debut = next((i for i, l in enumerate(lignes) if l.lstrip('"').startswith("First Name")), None)
    if debut is None:
        return [], ["En-tête « First Name,Last Name,URL… » introuvable : est-ce bien Connections.csv ?"]
    fiches = []
    for v in csv.DictReader(io.StringIO("\n".join(lignes[debut:]))):
        v = {k: (val or "").strip() for k, val in v.items() if k}
        f = fiche_vide()
        f["prenom"] = n.formater_prenom(v.get("First Name", ""))
        f["nom"] = n.formater_nom(v.get("Last Name", ""))
        f["societe"] = v.get("Company", "")
        f["fonction"] = v.get("Position", "")
        c = n.courriel(v.get("Email Address", ""), "travail")
        if c:
            f["courriels"].append(c)
        s = n.site(v.get("URL", ""), "linkedin")
        if s:
            f["sites"].append(s)
        if f["prenom"] or f["nom"]:
            fiches.append(FicheLue(fiche=f, uid=uid_profil(v.get("URL", "")), brut=",".join(v.values())))
    return fiches, []


def uid_profil(url: str) -> str | None:
    """Identifiant stable d'une relation : l'adresse de son profil (« linkedin.com/in/claire-martin »),
    sans protocole, sous-domaine ni paramètres. Un réimport retrouve ainsi la même relation."""
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", url or "", re.I)
    return f"linkedin.com/in/{m.group(1).lower()}" if m else None

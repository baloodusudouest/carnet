"""Lecture des exports déposés : vCard (iCloud, Gmail), CSV Outlook, CSV LinkedIn.

Chaque lecteur renvoie une liste de FicheLue : fiche normalisée + photo + texte d'origine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FicheLue:
    fiche: dict
    uid: str | None = None
    photo: bytes | None = None
    photo_type: str | None = None
    brut: str = ""
    avertissements: list[str] = field(default_factory=list)


def lire_texte(chemin: Path) -> str:
    """UTF-8 (avec ou sans BOM), sinon Windows-1252 (anciens exports Outlook)."""
    donnees = chemin.read_bytes()
    for codage in ("utf-8-sig", "cp1252"):
        try:
            return donnees.decode(codage)
        except UnicodeDecodeError:
            continue
    return donnees.decode("utf-8", errors="replace")


def detecter_source(chemin: Path) -> str | None:
    """Devine la source d'un fichier déposé, d'après son contenu puis son nom."""
    nom = chemin.name.lower()
    suffixe = chemin.suffix.lower()
    if suffixe in (".vcf", ".vcard"):
        debut = lire_texte(chemin)[:4000]
        if "PRODID:-//Apple" in debut or "icloud" in nom or "X-ABADR" in debut:
            return "icloud"
        if "gmail" in nom or "google" in nom or "PRODID:-//Google" in debut:
            return "gmail"
        if "outlook" in nom:
            return "outlook"
        return "icloud" if "X-ABLabel" in debut else None
    if suffixe == ".csv":
        debut = lire_texte(chemin)[:3000]
        if "Connected On" in debut or "Date de connexion" in debut or "linkedin" in nom:
            return "linkedin"
        if "E-mail Address" in debut or "Mobile Phone" in debut or "outlook" in nom:
            return "outlook"
    return None

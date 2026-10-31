"""Anniversaires pour Home Assistant (calendrier « Anniversaires », rempli chaque nuit).

`analyser` lit une date de naissance telle qu'elle peut venir d'une vCard iCloud ou de carnet :
  1985-03-04, 19850304, 1985-03-04T00:00:00Z (date seule, sans décalage de fuseau),
  --0304 ou --03-04 (année inconnue), année 1604 d'Apple ou année < 1900 avec
  X-APPLE-OMIT-YEAR (année inconnue). Une date invalide ou illisible renvoie None.
`assembler` trie (mois, jour, nom) et retire les doublons (même nom, même date).
"""
from __future__ import annotations

from datetime import date

from .normalisation import anniversaire as _normaliser

ANNEE_MIN = 1900   # en dessous, avec X-APPLE-OMIT-YEAR, l'année est un bouche-trou d'Apple


def analyser(brut: str | None, sans_annee: bool = False) -> tuple[int, int, int | None] | None:
    """(jour, mois, annee) ; annee vaut None si elle est inconnue. None si la date est illisible."""
    t = (brut or "").strip()
    if not t:
        return None
    # « 1985-03-04T00:00:00Z » : la date écrite, telle quelle (jamais convertie de fuseau)
    t = t.split("T")[0].strip()
    valeur = _normaliser(t, sans_annee=False)
    if not valeur:
        return None
    if valeur.startswith("--"):
        mois, jour, annee = int(valeur[2:4]), int(valeur[5:7]), None
    else:
        annee, mois, jour = int(valeur[:4]), int(valeur[5:7]), int(valeur[8:10])
        if sans_annee and annee < ANNEE_MIN:
            annee = None
    try:
        date(annee or 2000, mois, jour)   # 2000 est bissextile : le 29 février sans année reste valable
    except ValueError:
        return None
    return jour, mois, annee


def assembler(entrees: list[dict]) -> list[dict]:
    """Entrées {nom, jour, mois, annee, immich} → triées par mois, jour, nom, sans doublon."""
    vues: set[tuple] = set()
    res = []
    for e in sorted(entrees, key=lambda e: (e["mois"], e["jour"], e["nom"].casefold())):
        cle = (e["nom"], e["jour"], e["mois"], e["annee"])
        if cle in vues:
            continue
        vues.add(cle)
        res.append(e)
    return res

"""2.22.3 : genre probable d'un prénom, pour proposer (jamais enregistrer seul) le genre d'un contact.

S'appuie sur la bibliothèque gender-guesser (liste de prénoms par pays, licence GPLv3, données sous
GNU FDL) : elle est installée à côté de carnet, rien n'en est copié ici. Si elle manque, carnet ne
propose rien et tout le reste marche.

Seuls les prénoms sans ambiguïté donnent une proposition : Camille, Dominique, Claude ou Stéphane
n'en donnent pas.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache

_GENRE = {"female": "femme", "male": "homme"}
_PLUTOT = {"mostly_female": "femme", "mostly_male": "homme"}


@lru_cache(maxsize=1)
def _detecteur():
    try:
        import gender_guesser.detector as g
        return g.Detector(case_sensitive=False)
    except Exception:          # bibliothèque absente ou fichier illisible : pas de proposition
        return None


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def _un(d, prenom: str) -> str:
    en_france, ailleurs = d.get_gender(prenom, "france"), d.get_gender(prenom)
    if en_france in _GENRE:
        return _GENRE[en_france]
    # « plutôt féminin » en France et féminin sans réserve tous pays confondus (Marie) : proposé
    if en_france in _PLUTOT and _GENRE.get(ailleurs) == _PLUTOT[en_france]:
        return _PLUTOT[en_france]
    return ""


@lru_cache(maxsize=4096)
def genre(prenom: str) -> str:
    """« femme », « homme », ou « » quand le prénom est mixte, inconnu ou absent."""
    d = _detecteur()
    p = " ".join((prenom or "").split())
    if d is None or not p:
        return ""
    premier = p.split(" ")[0]
    for essai in (premier, _sans_accents(premier), premier.split("-")[0], _sans_accents(premier.split("-")[0])):
        if essai:
            trouve = _un(d, essai.capitalize() if essai.isupper() else essai)
            if trouve:
                return trouve
            if d.get_gender(essai, "france") != "unknown":      # connu mais mixte : on ne cherche pas plus loin
                return ""
    return ""

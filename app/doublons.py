"""Détection des doublons entre fiches source.

Règles (spec, « Détection des doublons ») :
- même mobile (E.164)                       → doublon certain
- même courriel                             → doublon certain
- même numéro fixe + noms compatibles       → doublon probable (un fixe est souvent partagé en famille)
- noms très proches (RapidFuzz, accents et ordre ignorés)          → doublon probable
- noms proches + même date de naissance ou même société            → doublon probable
- même nom de famille + un autre mot commun (société, ville…)       → doublon possible (Revue)
  ex. « Docteur Chossat PSV Villeneuve » / « Isabelle CHOSSAT, PSV Villeneuve sur Lot »
Deux dates de naissance complètes et différentes affaiblissent un rapprochement par le nom.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz, process

from .normalisation import cle_courriel, cle_texte

SEUIL = 80
# Doublons possibles, montrés dans la Revue mais jamais réunis automatiquement à l'import
SEUIL_REVUE = 70
SCORE_FAMILLE = 75

# Mots qui ne distinguent personne : titres, formes juridiques, mots de liaison
MOTS_VIDES = {
    "docteur", "dr", "doc", "madame", "mme", "mlle", "monsieur", "mr", "maitre", "me",
    "pr", "professeur", "prof", "sarl", "sas", "sasu", "eurl", "sci", "scp", "selarl", "ste",
    "societe", "cabinet", "et", "de", "du", "des", "la", "le", "les", "sur", "sous", "en", "au",
    "aux", "chez", "pour", "par", "the", "and", "of",
}


def _mots(texte: str) -> set[str]:
    return {m for m in cle_texte(texte).split() if len(m) >= 3 and m not in MOTS_VIDES}


@dataclass
class Signature:
    id: int
    nom: str
    mobiles: set[str]
    fixes: set[str]
    courriels: set[str]
    anniversaire: str
    societe: str
    prenom: str = ""
    famille: frozenset = frozenset()   # mots du nom de famille
    mots: frozenset = frozenset()      # mots du prénom, du nom et de la société


def signature(id_: int, fiche: dict) -> Signature:
    nom = cle_texte(f"{fiche.get('prenom', '')} {fiche.get('nom', '')}")
    if not nom:
        nom = cle_texte(fiche.get("societe", ""))
    tels = [t for t in fiche.get("telephones", []) if t.get("valide")]
    return Signature(
        id=id_, nom=nom,
        mobiles={t["valeur"] for t in tels if t.get("mobile")},
        fixes={t["valeur"] for t in tels if not t.get("mobile")},
        courriels={cle_courriel(c) for c in fiche.get("courriels", [])},
        anniversaire=fiche.get("anniversaire", ""),
        societe=cle_texte(fiche.get("societe", "")),
        prenom=" ".join(sorted(_mots(fiche.get("prenom", "")))),
        famille=frozenset(_mots(fiche.get("nom", ""))),
        mots=frozenset(_mots(f"{fiche.get('prenom', '')} {fiche.get('nom', '')} {fiche.get('societe', '')}")),
    )


def _prenoms_differents(a: Signature, b: Signature) -> bool:
    if not a.prenom or not b.prenom:
        return False
    if a.prenom.startswith(b.prenom) or b.prenom.startswith(a.prenom):  # Isa / Isabelle
        return False
    return fuzz.ratio(a.prenom, b.prenom) < 80


def meme_famille_et_structure(a: Signature, b: Signature) -> bool:
    """Le nom de famille de l'un se retrouve chez l'autre, et ils partagent un autre mot
    (société, ville…), sans prénoms contraires."""
    noms = (a.famille & b.mots) | (b.famille & a.mots)
    return bool(noms) and len(a.mots & b.mots) >= 2 and not _prenoms_differents(a, b)


def comparer(a: Signature, b: Signature, sim_nom: float | None = None) -> tuple[int, list[str]]:
    """Score de 0 à 100 et raisons lisibles."""
    raisons, score = [], 0
    if a.mobiles & b.mobiles:
        score, raisons = 100, raisons + ["même mobile"]
    if a.courriels & b.courriels:
        score, raisons = 100, raisons + ["même courriel"]
    if sim_nom is None:
        sim_nom = fuzz.token_sort_ratio(a.nom, b.nom) if a.nom and b.nom else 0.0
    meme_annif = bool(a.anniversaire) and a.anniversaire == b.anniversaire
    annifs_contraires = (len(a.anniversaire) == 10 and len(b.anniversaire) == 10
                         and a.anniversaire != b.anniversaire)
    meme_societe = bool(a.societe) and a.societe == b.societe
    if a.fixes & b.fixes and (sim_nom >= 60 or not a.nom or not b.nom):
        score = max(score, 90)
        raisons.append("même numéro fixe")
    if sim_nom >= 88:
        par_nom = 85 if (sim_nom >= 95 or meme_annif or meme_societe) else 70
        if annifs_contraires:
            par_nom -= 30
        if par_nom > 0:
            raisons.append("même nom" if sim_nom >= 99.5 else f"noms proches ({sim_nom:.0f} %)")
            score = max(score, par_nom)
    if score < SCORE_FAMILLE and meme_famille_et_structure(a, b):
        score = SCORE_FAMILLE
        raisons.append("même nom de famille et mots communs")
    if meme_annif and score:
        raisons.append("même date de naissance")
    if meme_societe and score:
        raisons.append("même société")
    return score, raisons


def rapprochements(sigs: list[Signature], interdits: set[tuple[int, int]] | None = None,
                   seuil: int = SEUIL) -> list[tuple[int, int, int, list[str]]]:
    """Toutes les paires (id_a < id_b) au-dessus du seuil, sauf celles déclarées distinctes."""
    interdits = interdits or set()
    candidats: set[tuple[int, int]] = set()
    index: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sigs):
        for cle in s.mobiles | s.fixes | {"@" + c for c in s.courriels}:
            index[cle].append(i)
    for positions in index.values():
        for x in range(len(positions)):
            for y in range(x + 1, len(positions)):
                candidats.add((positions[x], positions[y]))
    # Même nom de famille retrouvé dans l'autre fiche (mots rares seulement)
    par_mot: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sigs):
        for m in s.mots:
            par_mot[m].append(i)
    for i, s in enumerate(sigs):
        for m in s.famille:
            if len(par_mot[m]) <= 50:
                candidats.update((min(i, j), max(i, j)) for j in par_mot[m] if j != i)
    sims: dict[tuple[int, int], float] = {}
    avec_nom = [i for i, s in enumerate(sigs) if len(s.nom) >= 3]
    if len(avec_nom) > 1:
        noms = [sigs[i].nom for i in avec_nom]
        matrice = process.cdist(noms, noms, scorer=fuzz.token_sort_ratio, score_cutoff=88,
                                dtype=np.float32, workers=1)
        xs, ys = np.nonzero(matrice)
        for x, y in zip(xs.tolist(), ys.tolist()):
            if x < y:
                cle = (avec_nom[x], avec_nom[y])
                candidats.add(cle)
                sims[cle] = float(matrice[x, y])
    resultat = []
    for x, y in candidats:
        a, b = sigs[x], sigs[y]
        paire = (min(a.id, b.id), max(a.id, b.id))
        if paire in interdits or a.id == b.id:
            continue
        score, raisons = comparer(a, b, sims.get((x, y)))
        if score >= seuil:
            resultat.append((paire[0], paire[1], score, raisons))
    return sorted(resultat)

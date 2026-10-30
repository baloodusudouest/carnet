"""Détection des doublons entre fiches source.

Règles (spec, « Détection des doublons ») :
- même mobile (E.164)                       → doublon certain
- même courriel                             → doublon certain
- même numéro fixe + noms compatibles       → doublon probable (un fixe est souvent partagé en famille)
- noms très proches (RapidFuzz, accents et ordre ignorés)          → doublon probable
- noms proches + même date de naissance ou même société            → doublon probable
Deux dates de naissance complètes et différentes affaiblissent un rapprochement par le nom.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz, process

from .normalisation import cle_courriel, cle_texte

SEUIL = 80


@dataclass
class Signature:
    id: int
    nom: str
    mobiles: set[str]
    fixes: set[str]
    courriels: set[str]
    anniversaire: str
    societe: str


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
    )


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

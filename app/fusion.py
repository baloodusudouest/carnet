"""Proposition de fiche fusionnée à partir des fiches source d'une personne.

Valeurs uniques : la première non vide selon iCloud > Gmail > Outlook > LinkedIn.
Valeurs multiples : réunion sans doublon (même clé), le type venant de la première source.
LinkedIn n'apporte que ce qui manque : société, fonction, profil, courriel.
"""
from __future__ import annotations

from .modele import CHAMPS_MULTIPLES, PRIORITE_SOURCES, completer, fiche_vide
from .normalisation import CLES, note, regle_proches


def _ordre(source: dict) -> tuple[int, int]:
    rang = PRIORITE_SOURCES.index(source["source"]) if source["source"] in PRIORITE_SOURCES else 99
    return rang, source["id"]


def proposer(sources: list[dict]) -> dict:
    """sources : [{"id", "source", "donnees", "a_photo"}]."""
    fiche = fiche_vide()
    rangees = sorted(sources, key=_ordre)
    for champ in ("prenom", "nom", "surnom", "societe", "fonction", "anniversaire"):
        for s in rangees:
            valeur = s["donnees"].get(champ, "")
            # Une année connue l'emporte sur un anniversaire sans année
            if champ == "anniversaire" and fiche[champ].startswith("--") and len(valeur) == 10 \
                    and valeur[5:] == fiche[champ][2:]:
                fiche[champ] = valeur
            if valeur and not fiche[champ]:
                fiche[champ] = valeur
    notes = []
    for s in rangees:
        texte = note(s["donnees"].get("notes"))
        if texte and texte not in notes:
            notes.append(texte)
    fiche["notes"] = "\n\n".join(notes)
    for champ in CHAMPS_MULTIPLES:
        vues = set()
        for s in rangees:
            for item in s["donnees"].get(champ, []):
                cle = CLES[champ](item)
                if not cle:  # clé vide : la valeur est gardée telle quelle
                    fiche[champ].append(dict(item))
                elif cle not in vues:
                    vues.add(cle)
                    fiche[champ].append(dict(item))
    groupes = set()
    for s in rangees:
        groupes.update(s["donnees"].get("groupes", []))
    fiche["groupes"] = sorted(groupes)
    fiche["photo"] = next((s["id"] for s in rangees if s.get("a_photo")), None)
    return regle_proches(completer(fiche))


def reunir(base: dict, ajout: dict) -> dict:
    """Fusion manuelle : garde tout ce qui a été retenu dans `base`, complète les champs
    vides avec `ajout`, ajoute ses valeurs multiples absentes, réunit groupes et notes."""
    f = completer(base)
    a = completer(ajout)
    for champ in ("prenom", "nom", "surnom", "societe", "fonction", "anniversaire"):
        if not f[champ] and a[champ]:
            f[champ] = a[champ]
    if f["photo"] is None:
        f["photo"] = a["photo"]
    f["notes"], a["notes"] = note(f["notes"]), note(a["notes"])
    if a["notes"] and a["notes"] not in f["notes"]:
        f["notes"] = "\n\n".join(x for x in (f["notes"], a["notes"]) if x)
    for champ in CHAMPS_MULTIPLES:
        cles = {CLES[champ](x) for x in f[champ]}
        for item in a[champ]:
            if CLES[champ](item) not in cles:
                f[champ].append(dict(item))
    f["groupes"] = sorted(set(f["groupes"]) | set(a["groupes"]))
    return f


def retirer_source(fiche: dict, detachee: dict, restantes: list[dict]) -> dict:
    """Après « Pas la même personne » : retire de la fiche les valeurs qui ne venaient que de
    la fiche détachée. Ce qui a été saisi à la main ou existe ailleurs reste."""
    f = completer(fiche)
    d = detachee["donnees"]
    if f["photo"] == detachee["id"]:
        f["photo"] = None
    for champ in ("prenom", "nom", "surnom", "societe", "fonction", "anniversaire"):
        valeur = d.get(champ, "")
        if valeur and f[champ] == valeur and not any(r["donnees"].get(champ) == valeur for r in restantes):
            f[champ] = ""
    for champ in CHAMPS_MULTIPLES:
        venues = {CLES[champ](x) for x in d.get(champ, [])}
        ailleurs = {CLES[champ](x) for r in restantes for x in r["donnees"].get(champ, [])}
        f[champ] = [x for x in f[champ] if CLES[champ](x) not in venues - ailleurs]
    return f

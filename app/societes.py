"""Sociétés écrites de plusieurs façons (carnet 2.8.2).

« aquitaineenergie », « aquitaineÉnergie », « AQUITAINEENERGIE », « Aquitaine Énergie SA » : carnet les rapproche et
propose, dans « À traiter », de choisir une seule écriture. Rien n'est écrit sans ce choix.

Deux niveaux de rapprochement :
- *sûr* : seules les majuscules et les accents diffèrent ;
- *proposé* : diffèrent aussi les espaces, traits d'union, points, ou une forme juridique
  (SA, SAS, SARL…). Ce sont peut-être deux sociétés : à Julien de le dire.
"""
from __future__ import annotations

import re

from . import traiter
from .carnet import Carnet, ErreurCarnet
from .normalisation import cle_texte

FORMES = {"sa", "sas", "sasu", "sarl", "eurl", "sci", "snc", "scop", "selarl", "scp", "gie", "gmbh", "ag", "ltd", "inc",
          "llc", "plc", "bv", "nv", "spa", "srl", "corp", "co", "cie"}
LOT = 20   # fiches écrites au plus par réponse ; le point reste tant qu'il en reste


def cle_large(nom: str) -> str:
    """Clé de rapprochement : sans accents ni casse, sans ponctuation ni espaces, sans forme
    juridique en fin de nom."""
    mots = re.findall(r"[a-z0-9]+", cle_texte(nom or "").replace("&", " et "))
    while len(mots) > 1 and mots[-1] in FORMES:
        mots.pop()
    # « S.A. » découpé en « s », « a »
    while len(mots) > 2 and len(mots[-1]) == 1 and len(mots[-2]) == 1 and mots[-2] + mots[-1] in FORMES:
        mots = mots[:-2]
    return "".join(mots)


def groupes(c: Carnet) -> dict[str, dict[str, list[str]]]:
    """clé large → {écriture exacte: [uid…]} pour toutes les fiches qui portent une société."""
    res: dict[str, dict[str, list[str]]] = {}
    for uid, f in c.fiches().items():
        nom = " ".join((f.get("societe") or "").split())
        cle = cle_large(nom)
        if len(cle) >= 2:
            res.setdefault(cle, {}).setdefault(nom, []).append(uid)
    return res


def points(c: Carnet) -> list[dict]:
    """Un point par société écrite de plusieurs façons."""
    res = []
    for cle, ecritures in groupes(c).items():
        if len(ecritures) < 2:
            continue
        variantes = sorted(({"nom": n, "nombre": len(u)} for n, u in ecritures.items()), key=lambda v: (-v["nombre"], v["nom"]))
        uid = sorted(ecritures[variantes[0]["nom"]])[0]
        res.append({"motif": "societe", "uid": uid, "cle": f"{cle}|{traiter.empreinte(sorted(ecritures))}",
                    "donnees": {"cle": cle, "variantes": variantes, "fiches": sum(v["nombre"] for v in variantes),
                                "sur": len({cle_texte(n) for n in ecritures}) == 1}})
    return res


def harmoniser(c: Carnet, cle: str, nom: str) -> dict:
    """Écrit `nom` sur toutes les fiches du groupe qui s'écrivent autrement, par lots."""
    from . import actions
    nom = " ".join((nom or "").split())
    if not nom:
        raise ErreurCarnet("Choisis l'écriture à garder.")
    if cle_large(nom) != cle:
        raise ErreurCarnet("Cette écriture désigne une autre société : choisis une des écritures proposées, "
                           "ou une variante du même nom.")
    c.exiger_ecriture("iCloud")
    a_changer = sorted(u for n, uids in groupes(c).get(cle, {}).items() if n != nom for u in uids)
    faits, erreurs = 0, []
    for uid in a_changer[:LOT]:
        f = c.fiche(uid)
        f["societe"] = nom
        try:
            actions.valider(c, uid, f, origine="À traiter", motif="nom de société", etag_vu=actions._etag(c, uid))
            faits += 1
        except ErreurCarnet as exc:
            erreurs.append(str(exc))
    restants = max(0, len(a_changer) - LOT) + len(erreurs)
    c.oublier()
    message = f"« {nom} » écrit sur {faits} fiche(s)"
    if restants:
        message += f" ; {restants} restent à faire : le point revient, réponds-y de nouveau"
    if erreurs:
        message += f" ({erreurs[0]})"
    return {"ok": True, "faits": faits, "restants": restants, "uid": a_changer[0] if faits else None, "message": message + "."}


__all__ = ["cle_large", "groupes", "points", "harmoniser"]

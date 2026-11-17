"""Alimentation d'une personne (2.28) : allergies, intolérances, « aucune connue », date de
vérification, aliments non aimés, plaisirs coupables.

Rangée par identifiant maison (app/personnes.py), dans la base de carnet seulement : jamais écrite
dans iCloud, ni dans Synology Contacts, ni dans le kit d'urgence. Home Assistant n'en reçoit qu'un
indicateur (`statut`) : « inconnu » (rien de dit : demander), « aucune » (aucune allergie ni intolérance
connue), « a_connaitre » (au moins une allergie ou intolérance). Une absence d'information n'est jamais
lue comme « rien à signaler ».
"""
from __future__ import annotations

import json
import re

from . import personnes
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

LISTES = ("allergies", "intolerances", "non_aimes", "plaisirs")
LIBELLES = {"allergies": "Allergies", "intolerances": "Intolérances", "non_aimes": "Aliments non aimés",
            "plaisirs": "Plaisirs coupables"}
STATUTS = {"inconnu": "Inconnu : à demander", "aucune": "Aucune allergie ni intolérance connue",
           "a_connaitre": "Allergies ou intolérances à connaître"}
MAX_ELEMENTS = 30
MAX_LONGUEUR = 80
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _propre(valeur) -> list[str]:
    """Liste nettoyée : texte « a, b ; c » ou liste ; doublons retirés (sans casse), ordre gardé."""
    if valeur is None:
        return []
    if isinstance(valeur, str):
        valeur = re.split(r"[,;\n]", valeur)
    if not isinstance(valeur, list):
        raise ErreurCarnet("Une liste d'aliments est attendue.")
    res, vus = [], set()
    for v in valeur:
        if not isinstance(v, str):
            raise ErreurCarnet("Chaque aliment doit être un texte.")
        v = " ".join(v.split())
        if not v:
            continue
        if len(v) > MAX_LONGUEUR:
            raise ErreurCarnet(f"« {v[:30]}… » est trop long ({MAX_LONGUEUR} caractères au plus).")
        if v.casefold() not in vus:
            vus.add(v.casefold())
            res.append(v)
    if len(res) > MAX_ELEMENTS:
        raise ErreurCarnet(f"{MAX_ELEMENTS} éléments au plus par liste.")
    return res


def statut(a: dict | None) -> str:
    if not a:
        return "inconnu"
    if a["allergies"] or a["intolerances"]:
        return "a_connaitre"
    return "aucune" if a["aucune"] else "inconnu"


def _ligne(l) -> dict:
    a = {k: json.loads(l[k]) for k in LISTES}
    a.update(aucune=bool(l["aucune"]), verifiee_le=l["verifiee_le"], le=l["le"])
    return a


def toutes(c: Carnet) -> dict[str, dict]:
    """identifiant maison → alimentation."""
    return c.memo("alimentation", lambda: {l["personne"]: _ligne(l) for l in c.base.tous("SELECT * FROM alimentation")})


def de_personne(c: Carnet, ident: str) -> dict | None:
    return toutes(c).get(ident)


def fiche(c: Carnet, uid: str) -> dict:
    """Ce que montre la fiche de carnet."""
    ident = personnes.de(c, uid)
    a = de_personne(c, ident)
    vide = {k: [] for k in LISTES} | {"aucune": False, "verifiee_le": None, "le": None}
    return {"personne_id": ident, **(a or vide), "statut": statut(a), "statut_libelle": STATUTS[statut(a)],
            "libelles": LIBELLES}


def definir(c: Carnet, uid: str, corps: dict) -> dict:
    """Enregistre l'alimentation d'une fiche. `verifiee` vrai : vérifiée aujourd'hui ; `verifiee_le` :
    date donnée (AAAA-MM-JJ). « Aucune connue » et une allergie ou intolérance ne vont pas ensemble.
    Tout vide et rien de coché : la ligne est retirée (retour à « inconnu »). Reste dans carnet : permis
    en lecture seule (rien ne sort de carnet)."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Données d'alimentation attendues.")
    ident = personnes.de(c, uid)
    listes = {k: _propre(corps.get(k)) for k in LISTES}
    aucune = bool(corps.get("aucune"))
    if aucune and (listes["allergies"] or listes["intolerances"]):
        raise ErreurCarnet("« Aucune connue » ne peut pas aller avec une allergie ou une intolérance.")
    verifiee = corps.get("verifiee_le")
    if corps.get("verifiee") is True:
        verifiee = iso(maintenant())[:10]
    elif verifiee in ("", None):
        verifiee = (de_personne(c, ident) or {}).get("verifiee_le")
    elif not (isinstance(verifiee, str) and DATE.match(verifiee)):
        raise ErreurCarnet("Date de vérification attendue au format AAAA-MM-JJ.")
    le = iso(maintenant())
    if not aucune and not any(listes.values()):
        c.base.executer("DELETE FROM alimentation WHERE personne = ?", (ident,))
    else:
        c.base.executer(
            "INSERT INTO alimentation(personne, allergies, intolerances, aucune, verifiee_le, non_aimes, plaisirs, le) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(personne) DO UPDATE SET allergies = excluded.allergies, "
            "intolerances = excluded.intolerances, aucune = excluded.aucune, verifiee_le = excluded.verifiee_le, "
            "non_aimes = excluded.non_aimes, plaisirs = excluded.plaisirs, le = excluded.le",
            (ident, *(json.dumps(listes[k], ensure_ascii=False) for k in ("allergies", "intolerances")), int(aucune),
             verifiee, *(json.dumps(listes[k], ensure_ascii=False) for k in ("non_aimes", "plaisirs")), le))
    # Le journal ne porte jamais le contenu : seulement qu'une fiche a été changée
    c.base.noter("alimentation", "Alimentation d'une fiche mise à jour", {"uid": uid})
    return fiche(c, uid)


def indicateur(c: Carnet, ident: str | None) -> dict:
    """Ce que reçoit Home Assistant : le statut et la date de vérification, rien d'autre."""
    a = de_personne(c, ident) if ident else None
    return {"allergies": statut(a), "allergies_verifiees_le": (a or {}).get("verifiee_le")}

"""Alimentation d'une personne (2.28) : allergies, intolérances, « aucune connue », date de
vérification, aliments non aimés, plaisirs coupables ; 3.5 : note d'hôte.

Rangée par identifiant maison (app/personnes.py), dans la base de carnet seulement : jamais écrite
dans iCloud, ni dans Synology Contacts, ni dans le kit d'urgence. Le journal n'en porte jamais le contenu.

Statut (`statut`) : « inconnu » (rien de dit : demander), « aucune » (aucune allergie ni intolérance
connue), « a_connaitre » (au moins une allergie ou intolérance). Une absence d'information n'est jamais
lue comme « rien à signaler ».

3.5 (plan du 17/11/2026, étapes 3 et 4, choix de Julien du 23/11/2026) : Home Assistant reçoit les listes
complètes et la note d'hôte des personnes qu'il demande (`pour_ha`, /ha/aliments) pour les champs aliments de la
chambre, et l'annuaire de toutes les personnes renseignées (`annuaire`, carte « Fiches invités »). Il renvoie les
modifications faites dans ses cartes par ajouts et retraits explicites (`modifier_par_ha`), jamais le texte entier :
une allergie ou une intolérance n'est retirée qu'avec `confirme: true`, et une modification déjà reçue (même
identifiant d'opération, renvoi de la file d'attente) n'est pas appliquée deux fois.
"""
from __future__ import annotations

import json
import re

from . import personnes
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

LISTES = ("allergies", "intolerances", "non_aimes", "plaisirs")
SANTE = ("allergies", "intolerances")
LIBELLES = {"allergies": "Allergies", "intolerances": "Intolérances", "non_aimes": "Aliments non aimés",
            "plaisirs": "Plaisirs coupables", "note": "Note d'hôte"}
STATUTS = {"inconnu": "Inconnu : à demander", "aucune": "Aucune allergie ni intolérance connue",
           "a_connaitre": "Allergies ou intolérances à connaître"}
MAX_ELEMENTS = 30
MAX_LONGUEUR = 80
MAX_NOTE = 500
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OPERATION = re.compile(r"^[A-Za-z0-9_.:-]{6,64}$")
GARDE_OPERATIONS = 90     # jours pendant lesquels un identifiant d'opération reçu est gardé


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


def _note(valeur) -> str:
    if valeur is None:
        return ""
    if not isinstance(valeur, str):
        raise ErreurCarnet("La note d'hôte doit être un texte.")
    texte = "\n".join(" ".join(l.split()) for l in valeur.replace("\r", "").split("\n")).strip()
    if len(texte) > MAX_NOTE:
        raise ErreurCarnet(f"Note d'hôte trop longue ({MAX_NOTE} caractères au plus).")
    return texte


def statut(a: dict | None) -> str:
    if not a:
        return "inconnu"
    if a["allergies"] or a["intolerances"]:
        return "a_connaitre"
    return "aucune" if a["aucune"] else "inconnu"


def _ligne(l) -> dict:
    a = {k: json.loads(l[k]) for k in LISTES}
    a.update(aucune=bool(l["aucune"]), verifiee_le=l["verifiee_le"], le=l["le"],
             note=(l["note"] if "note" in l.keys() else "") or "")
    return a


def toutes(c: Carnet) -> dict[str, dict]:
    """identifiant maison → alimentation."""
    return c.memo("alimentation", lambda: {l["personne"]: _ligne(l) for l in c.base.tous("SELECT * FROM alimentation")})


def de_personne(c: Carnet, ident: str) -> dict | None:
    return toutes(c).get(ident)


VIDE = {**{k: [] for k in LISTES}, "aucune": False, "verifiee_le": None, "le": None, "note": ""}


def fiche(c: Carnet, uid: str) -> dict:
    """Ce que montre la fiche de carnet."""
    ident = personnes.de(c, uid)
    a = de_personne(c, ident)
    return {"personne_id": ident, **(a or VIDE), "statut": statut(a), "statut_libelle": STATUTS[statut(a)],
            "libelles": LIBELLES}


def _ecrire(c: Carnet, ident: str, listes: dict, aucune: bool, verifiee, note: str) -> None:
    """Enregistre (ou retire, si tout est vide) la ligne d'alimentation d'une personne."""
    le = iso(maintenant())
    if not aucune and not any(listes.values()) and not note:
        c.base.executer("DELETE FROM alimentation WHERE personne = ?", (ident,))
        return
    c.base.executer(
        "INSERT INTO alimentation(personne, allergies, intolerances, aucune, verifiee_le, non_aimes, plaisirs, note, le) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(personne) DO UPDATE SET allergies = excluded.allergies, "
        "intolerances = excluded.intolerances, aucune = excluded.aucune, verifiee_le = excluded.verifiee_le, "
        "non_aimes = excluded.non_aimes, plaisirs = excluded.plaisirs, note = excluded.note, le = excluded.le",
        (ident, *(json.dumps(listes[k], ensure_ascii=False) for k in ("allergies", "intolerances")), int(aucune),
         verifiee, *(json.dumps(listes[k], ensure_ascii=False) for k in ("non_aimes", "plaisirs")), note, le))


def definir(c: Carnet, uid: str, corps: dict) -> dict:
    """Enregistre l'alimentation d'une fiche. `verifiee` vrai : vérifiée aujourd'hui ; `verifiee_le` :
    date donnée (AAAA-MM-JJ). « Aucune connue » et une allergie ou intolérance ne vont pas ensemble.
    `note` absente : la note d'hôte reste telle quelle. Tout vide et rien de coché : la ligne est retirée
    (retour à « inconnu »). Reste dans carnet : permis en lecture seule (rien ne sort de carnet)."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Données d'alimentation attendues.")
    ident = personnes.de(c, uid)
    avant = de_personne(c, ident) or VIDE
    listes = {k: _propre(corps.get(k)) for k in LISTES}
    aucune = bool(corps.get("aucune"))
    if aucune and (listes["allergies"] or listes["intolerances"]):
        raise ErreurCarnet("« Aucune connue » ne peut pas aller avec une allergie ou une intolérance.")
    verifiee = corps.get("verifiee_le")
    if corps.get("verifiee") is True:
        verifiee = iso(maintenant())[:10]
    elif verifiee in ("", None):
        verifiee = avant.get("verifiee_le")
    elif not (isinstance(verifiee, str) and DATE.match(verifiee)):
        raise ErreurCarnet("Date de vérification attendue au format AAAA-MM-JJ.")
    note = _note(corps["note"]) if "note" in corps else avant.get("note", "")
    _ecrire(c, ident, listes, aucune, verifiee, note)
    # Le journal ne porte jamais le contenu : seulement qu'une fiche a été changée
    c.base.noter("alimentation", "Alimentation d'une fiche mise à jour", {"uid": uid})
    return fiche(c, uid)


def indicateur(c: Carnet, ident: str | None) -> dict:
    """Le statut et la date de vérification (2.28, /ha/invite et /ha/allergies)."""
    a = de_personne(c, ident) if ident else None
    return {"allergies": statut(a), "allergies_verifiees_le": (a or {}).get("verifiee_le")}


# ---------------------------------------------------------------- 3.5 : Home Assistant

def pour_ha(c: Carnet, ident: str | None) -> dict:
    """Listes, note d'hôte, statut et date de vérification d'une personne (vide : statut « inconnu »)."""
    a = de_personne(c, ident) if ident else None
    a = a or VIDE
    return {**{k: list(a[k]) for k in LISTES}, "note": a.get("note", ""), "aucune": bool(a["aucune"]),
            "statut": statut(a if a is not VIDE else None), "verifiee_le": a.get("verifiee_le"), "le": a.get("le")}


def annuaire(c: Carnet) -> list[dict]:
    """Toutes les personnes dont l'alimentation est renseignée, avec leur nom (carte « Fiches invités »)."""
    from .sorties import contacts_ha
    noms = {p["personne_id"]: p for p in contacts_ha(c) if p.get("personne_id")}
    res = []
    for ident in toutes(c):
        uid = personnes.uid_de(c, ident)
        actuel = personnes.ids(c).get(uid) if uid else None
        p = noms.get(actuel or ident)
        if not p:
            continue        # fiche retirée d'iCloud : la ligne attend son rattachement dans carnet
        res.append({"personne_id": p["personne_id"], "nom": p["nom"], "prenom": p["prenom"], **pour_ha(c, ident)})
    return sorted(res, key=lambda x: x["nom"].casefold())


def _identifiant(c: Carnet, personne_id: str) -> str:
    uid = personnes.uid_de(c, (personne_id or "").strip())
    ident = personnes.ids(c).get(uid) if uid else None
    if not ident:
        raise LookupError("Personne inconnue de carnet (identifiant maison).")
    return ident


def modifier_par_ha(c: Carnet, corps: dict) -> dict:
    """Une modification faite dans une carte de Home Assistant : {operation, personne_id, ajouts: {liste: [..]},
    retraits: {liste: [..]}, note (texte, absente : inchangée), aucune (vrai/faux, absente : inchangée),
    verifiee (vrai : vérifiée aujourd'hui), confirme (vrai : retrait d'allergie ou d'intolérance voulu)}.
    Renvoie {deja, personne_id, ...pour_ha}. Permis en lecture seule : rien ne sort de carnet."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    operation = str(corps.get("operation") or "")
    if not OPERATION.fullmatch(operation):
        raise ErreurCarnet("Identifiant d'opération attendu (6 à 64 lettres, chiffres, « - », « _ », « . », « : »).")
    ident = _identifiant(c, str(corps.get("personne_id") or ""))
    if c.base.un("SELECT 1 FROM alimentation_operations WHERE id = ?", (operation,)):
        return {"deja": True, "personne_id": ident, **pour_ha(c, ident)}
    ajouts = corps.get("ajouts") or {}
    retraits = corps.get("retraits") or {}
    if not isinstance(ajouts, dict) or not isinstance(retraits, dict):
        raise ErreurCarnet("« ajouts » et « retraits » : un objet par liste est attendu.")
    inconnues = (set(ajouts) | set(retraits)) - set(LISTES)
    if inconnues:
        raise ErreurCarnet(f"Liste inconnue : {', '.join(sorted(inconnues))}.")
    ajouts = {k: _propre(v) for k, v in ajouts.items()}
    retraits = {k: _propre(v) for k, v in retraits.items()}
    if any(retraits.get(k) for k in SANTE) and corps.get("confirme") is not True:
        raise ErreurCarnet("Retirer une allergie ou une intolérance demande une confirmation (confirme: true).")
    avant = de_personne(c, ident) or VIDE
    listes = {}
    for k in LISTES:
        retires = {x.casefold() for x in retraits.get(k, [])}
        l = [x for x in avant[k] if x.casefold() not in retires]
        presents = {x.casefold() for x in l}
        l += [x for x in ajouts.get(k, []) if x.casefold() not in presents]
        if len(l) > MAX_ELEMENTS:
            raise ErreurCarnet(f"{MAX_ELEMENTS} éléments au plus par liste.")
        listes[k] = l
    aucune = bool(corps["aucune"]) if "aucune" in corps and corps["aucune"] is not None else bool(avant["aucune"])
    if listes["allergies"] or listes["intolerances"]:
        aucune = False          # une allergie connue l'emporte sur « aucune connue »
    note = _note(corps["note"]) if corps.get("note") is not None else avant.get("note", "")
    verifiee = iso(maintenant())[:10] if corps.get("verifiee") is True else avant.get("verifiee_le")
    _ecrire(c, ident, listes, aucune, verifiee, note)
    c.base.executer("INSERT OR IGNORE INTO alimentation_operations(id, personne, le) VALUES (?, ?, ?)",
                    (operation, ident, iso(maintenant())))
    c.base.executer("DELETE FROM alimentation_operations WHERE le < date('now', ?)", (f"-{GARDE_OPERATIONS} days",))
    c.oublier()
    # Le journal ne porte jamais le contenu
    c.base.noter("alimentation", "Alimentation modifiée depuis Home Assistant", {"personne_id": ident})
    return {"deja": False, "personne_id": ident, **pour_ha(c, ident)}

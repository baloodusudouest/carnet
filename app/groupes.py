"""Section Groupes (carnet 2.9) : voir les groupes, ajouter ou retirer des contacts par lot, créer,
renommer et supprimer un groupe.

Un groupe est une carte de groupe dans iCloud ; l'appartenance est portée par cette carte, pas par
les fiches. Supprimer un groupe retire la carte de groupe : aucune fiche n'est supprimée.
Les groupes d'origine de carnet (Famille, Amis, Urgence…) portent des règles (proches, urgence,
kit) : ils ne se renomment pas et ne se suppriment pas.
"""
from __future__ import annotations

import json
import secrets
import time

from . import icloud, synchro
from .carddav import Conflit
from .carnet import Carnet, ErreurCarnet
from .modele import GROUPES, nom_affiche
from .normalisation import cle_texte

LOT = 20


def _cartes(c: Carnet, nom: str) -> list[dict]:
    return [dict(l) for l in c.base.tous("SELECT * FROM groupes WHERE nom = ? ORDER BY uid", (nom,))]


def _noms(c: Carnet) -> set[str]:
    noms = {l["nom"] for l in c.base.tous("SELECT nom FROM groupes")} | set(GROUPES)
    for f in c.fiches().values():
        noms.update(f.get("groupes") or [])
    return noms


def liste(c: Carnet) -> list[dict]:
    from . import attentes
    nombre: dict[str, int] = {}
    for f in c.fiches().values():
        for g in f.get("groupes") or []:
            nombre[g] = nombre.get(g, 0) + 1
    dans_icloud = {l["nom"] for l in c.base.tous("SELECT nom FROM groupes")}
    tableau = attentes.par_groupe(c)
    return [{"nom": n, "nombre": nombre.get(n, 0), "integre": n in GROUPES, "dans_icloud": n in dans_icloud,
             "attentes": len(tableau.get(n, set()))} for n in sorted(_noms(c), key=str.casefold)]


def membres(c: Carnet, nom: str) -> list[dict]:
    res = [{"uid": u, "nom": nom_affiche(f), "societe": f.get("societe", ""), "a_photo": f.get("a_photo", False),
            "groupes": f.get("groupes", [])} for u, f in c.fiches().items() if nom in (f.get("groupes") or [])]
    return sorted(res, key=lambda x: x["nom"].casefold())


def _propre(nom: str) -> str:
    nom = " ".join((nom or "").split())
    if not nom or len(nom) > 60:
        raise ErreurCarnet("Donne un nom au groupe (60 caractères au plus).")
    return nom


def _libre(c: Carnet, nom: str, sauf: str | None = None) -> None:
    if any(cle_texte(n) == cle_texte(nom) and n != sauf for n in _noms(c)):
        raise ErreurCarnet(f"Un groupe « {nom} » existe déjà.")


def creer(c: Carnet, nom: str) -> dict:
    """Groupe vide créé dans iCloud."""
    nom = _propre(nom)
    _libre(c, nom)
    c.exiger_ecriture("iCloud")
    with c.ecriture(attendre=5):
        icloud.sauvegarde_du_jour(c)
        dav = c.icloud()
        try:
            guid = icloud._uid_groupe(nom)
            href = dav.href_nouveau(guid)
            texte = synchro.carte_groupe(nom, guid, [])
            etag = dav.ecrire(href, texte, None) or dav.etag(href) or ""
        finally:
            dav.fermer()
        c.base.executer("INSERT OR REPLACE INTO groupes(uid, href, etag, nom, texte, membres) VALUES (?,?,?,?,?,?)",
                        (guid, href, etag, nom, texte, "[]"))
    c.base.noter("ecriture", f"Groupes : « {nom} » créé dans iCloud")
    c.oublier()
    return {"ok": True, "nom": nom}


def _modifiable(nom: str) -> None:
    if nom in GROUPES:
        raise ErreurCarnet(f"« {nom} » est un groupe d'origine de carnet (ses règles en dépendent) : il ne se renomme pas "
                           "et ne se supprime pas.")


def _dans_les_fiches(cx, ancien: str, nouveau: str | None) -> int:
    """Remplace (ou retire) un nom de groupe dans les fiches gardées en base."""
    n = 0
    for l in cx.execute("SELECT uid, fiche FROM fiches").fetchall():
        f = json.loads(l["fiche"])
        if ancien in (f.get("groupes") or []):
            f["groupes"] = sorted((set(f["groupes"]) - {ancien}) | ({nouveau} if nouveau else set()))
            cx.execute("UPDATE fiches SET fiche = ? WHERE uid = ?", (json.dumps(f, ensure_ascii=False), l["uid"]))
            n += 1
    return n


def renommer(c: Carnet, nom: str, nouveau: str) -> dict:
    nouveau = _propre(nouveau)
    _modifiable(nom)
    cartes = _cartes(c, nom)
    if not cartes:
        raise ErreurCarnet("Ce groupe n'existe pas dans iCloud.")
    _libre(c, nouveau, sauf=nom)
    if nouveau == nom:
        return {"ok": True, "nom": nom, "fiches": 0}
    c.exiger_ecriture("iCloud")
    with c.ecriture(attendre=5):
        icloud.sauvegarde_du_jour(c)
        dav = c.icloud()
        try:
            for g in cartes:
                texte = synchro.carte_groupe(nouveau, g["uid"], json.loads(g["membres"]), g["texte"])
                try:
                    etag = dav.ecrire(g["href"], texte, g["etag"] or dav.etag(g["href"])) or dav.etag(g["href"]) or ""
                except Conflit:
                    raise ErreurCarnet(f"Le groupe « {nom} » change en ce moment dans iCloud : relis iCloud, puis réessaie.")
                c.base.executer("UPDATE groupes SET nom = ?, texte = ?, etag = ? WHERE uid = ?", (nouveau, texte, etag, g["uid"]))
        finally:
            dav.fermer()
        with c.base.transaction() as cx:
            fiches = _dans_les_fiches(cx, nom, nouveau)
            cx.execute("UPDATE OR REPLACE attentes SET groupe = ? WHERE groupe = ?", (nouveau, nom))
    c.base.noter("ecriture", f"Groupes : « {nom} » renommé « {nouveau} » dans iCloud ({fiches} fiche(s))")
    c.oublier()
    return {"ok": True, "nom": nouveau, "fiches": fiches}


def supprimer(c: Carnet, nom: str, confirmation) -> dict:
    """Retire le groupe d'iCloud. Toujours confirmé ; aucune fiche n'est supprimée. « Annuler »
    le remet avec ses membres pendant 10 secondes."""
    if confirmation is not True:
        raise ErreurCarnet("Suppression non confirmée : rien n'a été supprimé.")
    _modifiable(nom)
    cartes = _cartes(c, nom)
    if not cartes:
        raise ErreurCarnet("Ce groupe n'existe pas dans iCloud.")
    c.exiger_ecriture("iCloud")
    attentes_ = [dict(l) for l in c.base.tous("SELECT * FROM attentes WHERE groupe = ?", (nom,))]
    with c.ecriture(attendre=5):
        icloud.sauvegarde_du_jour(c)
        dav = c.icloud()
        try:
            for g in cartes:
                try:
                    dav.supprimer(g["href"], g["etag"] or dav.etag(g["href"]))
                except Conflit:
                    raise ErreurCarnet(f"Le groupe « {nom} » change en ce moment dans iCloud : relis iCloud, puis réessaie.")
                c.base.executer("DELETE FROM groupes WHERE uid = ?", (g["uid"],))
        finally:
            dav.fermer()
        with c.base.transaction() as cx:
            fiches = _dans_les_fiches(cx, nom, None)
            cx.execute("DELETE FROM attentes WHERE groupe = ?", (nom,))
    jeton = secrets.token_urlsafe(12)
    c.annulations[jeton] = {"groupe": True, "nom": nom, "cartes": cartes, "attentes": attentes_,
                            "jusqua": time.monotonic() + icloud.DELAI_ANNULER}
    c.base.noter("ecriture", f"Groupes : « {nom} » retiré d'iCloud ({fiches} fiche(s) en sortent, aucune n'est supprimée)")
    c.oublier()
    return {"ok": True, "jeton": jeton, "nom": nom, "fiches": fiches}


def remettre(c: Carnet, a: dict) -> dict:
    """Annulation d'une suppression de groupe : les cartes de groupe reviennent avec leurs membres."""
    c.exiger_ecriture("iCloud")
    dav = c.icloud()
    try:
        for g in a["cartes"]:
            etag = dav.ecrire(g["href"], g["texte"], None) or dav.etag(g["href"]) or ""
            c.base.executer("INSERT OR REPLACE INTO groupes(uid, href, etag, nom, texte, membres) VALUES (?,?,?,?,?,?)",
                            (g["uid"], g["href"], etag, g["nom"], g["texte"], g["membres"]))
    finally:
        dav.fermer()
    with c.base.transaction() as cx:
        vivants = {l["uid"] for l in cx.execute("SELECT uid FROM fiches").fetchall()}
        for g in a["cartes"]:
            for uid in json.loads(g["membres"]):
                if uid in vivants:
                    f = json.loads(cx.execute("SELECT fiche FROM fiches WHERE uid = ?", (uid,)).fetchone()["fiche"])
                    f["groupes"] = sorted(set(f.get("groupes") or []) | {a["nom"]})
                    cx.execute("UPDATE fiches SET fiche = ? WHERE uid = ?", (json.dumps(f, ensure_ascii=False), uid))
        for l in a["attentes"]:
            cx.execute("INSERT OR IGNORE INTO attentes(groupe, info) VALUES (?, ?)", (l["groupe"], l["info"]))
    c.base.noter("ecriture", f"Groupes : suppression de « {a['nom']} » annulée")
    c.oublier()
    return {"ok": True}


def changer_membres(c: Carnet, nom: str, uids: list[str], action: str) -> dict:
    """Ajoute des contacts à un groupe, ou les en retire, par lots de 20."""
    from . import actions
    if action not in ("ajouter", "retirer"):
        raise ErreurCarnet("Action inconnue.")
    if nom not in _noms(c):
        raise ErreurCarnet("Ce groupe n'existe pas.")
    c.exiger_ecriture("iCloud")
    faits, erreurs = 0, []
    for uid in uids[:LOT]:
        try:
            f = c.fiche(uid)
            avant = set(f.get("groupes") or [])
            apres = avant | {nom} if action == "ajouter" else avant - {nom}
            if apres == avant:
                continue
            f["groupes"] = sorted(apres)
            actions.valider(c, uid, f, origine="Groupes", motif=f"groupe « {nom} »", etag_vu=actions._etag(c, uid))
            faits += 1
        except ErreurCarnet as exc:
            erreurs.append(str(exc))
    c.oublier()
    return {"faits": faits, "restants": max(0, len(uids) - LOT), "erreurs": erreurs[:5]}


__all__ = ["liste", "membres", "creer", "renommer", "supprimer", "remettre", "changer_membres"]

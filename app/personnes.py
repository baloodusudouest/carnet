"""Identifiant maison stable d'une personne (2.28).

L'UID d'une carte iCloud change quand la carte est fusionnée, supprimée puis recréée : il ne peut pas
servir de clé commune entre carnet, Home Assistant, Gazette, Douze points et le coffre Contacts.
Chaque fiche reçoit donc un identifiant propre à carnet (« p- » + 10 caractères hexadécimaux), créé
la première fois que carnet la voit et jamais réutilisé. L'UID iCloud n'en est qu'un attribut.

- Fiche retirée (suppression confirmée, sur l'iPhone ou dans carnet) : l'identifiant reste, sans fiche
  (uid vide, ancien_uid gardé) ; son alimentation est gardée. « Annuler » la rattache.
- Fusion : l'identifiant de la fiche gardée reste ; celui de la fiche absorbée pointe vers lui
  (`remplacee_par`), et son alimentation passe à la fiche gardée si celle-ci n'en a pas.
- Rattacher : un identifiant sans fiche peut être rattaché à une fiche qui n'a pas encore d'histoire
  (carte recréée sur l'iPhone) ; la fiche prend alors cet identifiant.
"""
from __future__ import annotations

import secrets

from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant


def _nouvel_id(existants: set[str]) -> str:
    while True:
        ident = "p-" + secrets.token_hex(5)
        if ident not in existants:
            return ident


def ids(c: Carnet) -> dict[str, str]:
    """uid → identifiant maison, pour toutes les fiches lues. Les fiches nouvelles en reçoivent un."""
    def calcul():
        connus = {l["uid"]: l["id"] for l in c.base.tous("SELECT id, uid FROM personnes WHERE uid IS NOT NULL")}
        manquants = [u for u in c.fiches() if u not in connus]
        if manquants:
            existants = {l["id"] for l in c.base.tous("SELECT id FROM personnes")}
            le = iso(maintenant())
            with c.base.transaction() as cx:
                for uid in manquants:
                    ident = _nouvel_id(existants)
                    existants.add(ident)
                    cx.execute("INSERT INTO personnes(id, uid, cree_le) VALUES (?, ?, ?)", (ident, uid, le))
                    connus[uid] = ident
        return connus
    return c.memo("personnes", calcul)


def de(c: Carnet, uid: str) -> str:
    """Identifiant maison d'une fiche (créé s'il manque). ErreurCarnet si la fiche n'existe pas."""
    c.fiche(uid)
    return ids(c)[uid]


def uid_de(c: Carnet, ident: str) -> str | None:
    """Fiche actuelle d'un identifiant, en suivant les fusions. None si la personne n'a plus de fiche."""
    vus = set()
    while ident and ident not in vus:
        vus.add(ident)
        l = c.base.un("SELECT uid, remplacee_par FROM personnes WHERE id = ?", (ident,))
        if not l:
            return None
        if l["uid"]:
            return l["uid"]
        ident = l["remplacee_par"]
    return None


def detacher(cx, uid: str) -> None:
    """Dans une transaction : la fiche est retirée, l'identifiant reste (sans fiche)."""
    cx.execute("UPDATE personnes SET ancien_uid = uid, uid = NULL, retiree_le = ? WHERE uid = ?",
               (iso(maintenant()), uid))


def rattacher_ancien(cx, uid: str) -> None:
    """Dans une transaction : « Annuler » une suppression remet l'identifiant sur sa fiche."""
    cx.execute("DELETE FROM personnes WHERE uid = ? AND id NOT IN (SELECT personne FROM alimentation)", (uid,))
    cx.execute("UPDATE personnes SET uid = ancien_uid, retiree_le = NULL WHERE ancien_uid = ? AND uid IS NULL "
               "AND remplacee_par IS NULL", (uid,))


def fusionner(cx, garder: str, absorber: str) -> None:
    """Dans une transaction : l'identifiant de la fiche absorbée pointe vers celui de la fiche gardée.
    Son alimentation passe à la fiche gardée si celle-ci n'en a pas (sinon elle reste, consultable)."""
    g = cx.execute("SELECT id FROM personnes WHERE uid = ?", (garder,)).fetchone()
    a = cx.execute("SELECT id FROM personnes WHERE uid = ?", (absorber,)).fetchone()
    if not a:
        return
    if not g:
        # La fiche gardée n'a pas encore d'identifiant : elle prend celui de la fiche absorbée
        cx.execute("UPDATE personnes SET uid = ? WHERE id = ?", (garder, a[0]))
        return
    if not cx.execute("SELECT 1 FROM alimentation WHERE personne = ?", (g[0],)).fetchone():
        cx.execute("UPDATE alimentation SET personne = ? WHERE personne = ?", (g[0], a[0]))
    cx.execute("UPDATE personnes SET ancien_uid = uid, uid = NULL, remplacee_par = ?, retiree_le = ? WHERE id = ?",
               (g[0], iso(maintenant()), a[0]))


def sans_fiche(c: Carnet) -> list[dict]:
    """Identifiants dont la fiche a été retirée (hors fusions), à rattacher si la carte revient."""
    return [{"id": l["id"], "ancien_uid": l["ancien_uid"], "retiree_le": l["retiree_le"],
             "alimentation": bool(l["a"])}
            for l in c.base.tous("SELECT p.id, p.ancien_uid, p.retiree_le, a.personne AS a FROM personnes p "
                                 "LEFT JOIN alimentation a ON a.personne = p.id "
                                 "WHERE p.uid IS NULL AND p.remplacee_par IS NULL ORDER BY p.retiree_le DESC")]


def rattacher(c: Carnet, ident: str, uid: str) -> dict:
    """Rattache un identifiant sans fiche à une fiche (carte recréée). La fiche ne doit avoir aucune
    alimentation à elle : son identifiant provisoire est alors remplacé par l'ancien."""
    c.fiche(uid)
    l = c.base.un("SELECT uid, remplacee_par FROM personnes WHERE id = ?", (ident,))
    if not l:
        raise ErreurCarnet("Identifiant inconnu.")
    if l["uid"] or l["remplacee_par"]:
        raise ErreurCarnet("Cet identifiant a déjà une fiche : rien à rattacher.")
    actuel = ids(c).get(uid)
    if actuel and c.base.un("SELECT 1 FROM alimentation WHERE personne = ?", (actuel,)):
        raise ErreurCarnet("Cette fiche a déjà ses propres informations d'alimentation : rattachement refusé "
                           "pour ne rien mélanger.")
    with c.base.transaction() as cx:
        if actuel:
            cx.execute("DELETE FROM personnes WHERE id = ?", (actuel,))
        cx.execute("UPDATE personnes SET uid = ?, retiree_le = NULL WHERE id = ?", (uid, ident))
    c.oublier("personnes")
    c.base.noter("ecriture", "Identifiant maison rattaché à une fiche", {"uid": uid})
    return {"ok": True, "id": ident}

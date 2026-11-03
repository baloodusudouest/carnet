"""Décisions de Julien : valider une fiche, répondre à un point « À traiter », fusionner.

Chaque écriture vers iCloud prend le verrou commun (jamais deux écrivains) et passe par
icloud.ecrire, qui garde tout ce que carnet ne gère pas et refuse d'écraser une carte changée
sur l'iPhone.
"""
from __future__ import annotations

import json

from . import fiches as F, icloud, liaisons, traiter
from .carnet import Carnet, ErreurCarnet
from .modele import nom_affiche
from .normalisation import ValeurInvalide


def apercu(c: Carnet, uid: str, fiche: dict) -> dict:
    """Ce qui partirait dans iCloud si on validait cette fiche (rien n'est écrit)."""
    try:
        propre = F.preparer(fiche, c.cfg.region)
    except ValeurInvalide as exc:
        raise ErreurCarnet(str(exc))
    return {"fiche": propre, "champs": F.differences(c.fiche(uid), propre)}


def valider(c: Carnet, uid: str, fiche: dict, photo: tuple[bytes, str] | None = None,
            origine: str = "manuel", motif: str = "modification", etag_vu: str | None = None,
            forcer: set[str] | None = None) -> dict:
    """etag_vu : version de la carte que l'interface a affichée (refus si elle a changé depuis)."""
    try:
        propre = F.preparer(fiche, c.cfg.region)
    except ValeurInvalide as exc:
        raise ErreurCarnet(str(exc))
    with c.ecriture(attendre=5):
        res = icloud.ecrire(c, uid, propre, photo, origine=origine, motif=motif, etag_vu=etag_vu, forcer=forcer)
        # Validée depuis la version affichée : les points iPhone et conflit de cette fiche sont réglés.
        # Sous le verrou, pour ne jamais effacer un point arrivé par une lecture pendant ce temps.
        if etag_vu is not None:
            with c.base.transaction() as cx:
                cx.execute("DELETE FROM a_traiter WHERE uid = ? AND motif IN ('iphone_modifiee', 'iphone_nouvelle', 'conflit')", (uid,))
            c.oublier()
    return res


def _etag(c: Carnet, uid: str) -> str:
    l = c.base.un("SELECT etag FROM fiches WHERE uid = ?", (uid,))
    return l["etag"] if l else ""


def annuler(c: Carnet, jeton: str) -> dict:
    with c.ecriture(attendre=5):
        return icloud.annuler(c, jeton)


def repondre(c: Carnet, ident: str, action: str, valeur=None) -> dict:
    """Réponse à un point de la boîte « À traiter »."""
    p = traiter.trouver(c, ident)
    motif, cle, uid, d = p["motif"], p["cle"], p["uid"], p["donnees"]
    if action == "ignorer":
        traiter.ignorer(c, motif, cle)
        return {"ok": True}

    if motif in ("iphone_modifiee", "iphone_nouvelle"):
        if action == "garder":
            traiter.retirer(c, motif, cle)
            return {"ok": True}
        if action == "revenir" and motif == "iphone_modifiee":
            # La version d'avant revient dans iCloud ; la carte actuelle est contrôlée (If-Match)
            with c.ecriture(attendre=5):
                res = icloud.remettre(c, uid, d["texte_avant"], d["avant"].get("groupes", []),
                                      "À traiter : fiche remise comme avant la modification sur l'iPhone")
            traiter.retirer(c, motif, cle)
            return res
    if motif == "iphone_supprimee":
        if action == "confirmer":
            with c.base.transaction() as cx:
                for table in ("liaisons", "portraits", "affiches", "en_attente"):
                    cx.execute(f"DELETE FROM {table} WHERE uid = ?", (uid,))
                cx.execute("UPDATE linkedin SET uid = NULL WHERE uid = ?", (uid,))
                cx.execute("DELETE FROM a_traiter WHERE motif = ? AND cle = ?", (motif, cle))
            c.oublier()
            return {"ok": True}
        if action == "recreer":
            with c.ecriture(attendre=5):
                res = icloud.recreer(c, d["texte"], d["href"], (d.get("fiche") or {}).get("groupes", []))
            traiter.retirer(c, motif, cle)
            return res
    if motif == "conflit":
        if action == "garder":    # la version de l'iPhone reste
            traiter.retirer(c, motif, cle)
            return {"ok": True}
        if action == "reprendre":  # ma version, écrite par-dessus celle de l'iPhone (que je viens de voir)
            with c.ecriture(attendre=5):
                icloud.relire(c, "avant reprise d'un conflit")
                res = icloud.ecrire(c, uid, F.preparer(d["voulue"], c.cfg.region), origine="À traiter",
                                    motif="version reprise après conflit")
                with c.base.transaction() as cx:
                    cx.execute("DELETE FROM a_traiter WHERE uid = ? AND motif IN ('iphone_modifiee', 'conflit')", (uid,))
                c.oublier()
            return res
    if motif == "forme" and action == "appliquer":
        champs = {"nom": {"prenom", "nom"}, "telephone": {"telephones"}}
        forcer = set().union(*(champs.get(e["champ"], set()) for e in d["ecarts"]))
        res = valider(c, uid, c.fiche(uid), origine="À traiter", motif="mise en forme", etag_vu=_etag(c, uid), forcer=forcer)
        traiter.ignorer(c, motif, cle)
        return res
    if motif == "emoji" and action == "appliquer":
        f = c.fiche(uid)
        f["groupes"] = sorted(set(f.get("groupes", [])) | {d["groupe"]})
        res = valider(c, uid, f, origine="À traiter", motif=f"groupe « {d['groupe']} »", etag_vu=_etag(c, uid))
        return res
    if motif == "liaison":
        if action == "lier":
            liaisons.lier(c, uid, "immich", d["immich"]["id"])
            return {"ok": True}
        if action == "pas_lui":
            liaisons.refuser(c, uid, "immich", d["immich"]["id"])
            return {"ok": True}
    if motif == "date" and action == "choisir":
        date = str(valeur or "")
        f = c.fiche(uid)
        res = {"ok": True}
        if f.get("anniversaire", "") != date:
            f["anniversaire"] = date
            res = valider(c, uid, f, origine="À traiter", motif="date de naissance", etag_vu=_etag(c, uid))
        res["services"] = liaisons.ecrire_partout(c, uid, date)
        traiter.ignorer(c, motif, cle)
        return res
    if motif == "nom" and action == "renommer":
        liaisons.renommer(c, uid, d["service"])
        traiter.ignorer(c, motif, cle)
        return {"ok": True}
    if motif == "relations" and action == "ajouter":
        f = c.fiche(uid)
        f["noms_associes"] = list(f.get("noms_associes", [])) + [dict(x) for x in d["ajouts"]]
        res = valider(c, uid, f, origine="À traiter", motif="liens familiaux", etag_vu=_etag(c, uid))
        traiter.ignorer(c, motif, cle)
        return res
    if motif == "linkedin" and action == "appliquer":
        f = c.fiche(uid)
        for champ, v in d["changements"].items():
            if champ == "courriel":
                if v and v not in {x["valeur"] for x in f.get("courriels", [])}:
                    f["courriels"] = list(f.get("courriels", [])) + [{"valeur": v, "type": "travail"}]
            else:
                f[champ] = v
        res = valider(c, uid, f, origine="LinkedIn", motif="poste ou société", etag_vu=_etag(c, uid))
        traiter.retirer(c, motif, cle)
        return res
    if motif == "import":
        if action == "creer":
            try:
                propre = F.preparer(d["fiche"], c.cfg.region)
            except ValeurInvalide as exc:
                raise ErreurCarnet(str(exc))
            with c.ecriture(attendre=5):
                res = icloud.creer(c, propre, origine="import")
            traiter.retirer(c, motif, cle)
            return res
        if action == "reunir" and valeur:
            f = F.proposer_fusion(c.fiche(str(valeur)), d["fiche"])
            res = valider(c, str(valeur), f, origine="import", motif="fiche importée réunie")
            traiter.retirer(c, motif, cle)
            return res
    if motif == "doublon" and action == "distincts":
        traiter.ignorer(c, motif, cle)
        return {"ok": True}
    raise ErreurCarnet("Action inconnue pour ce point.")


def fusionner(c: Carnet, garder: str, absorber: str, fiche: dict) -> dict:
    """Réunit deux fiches : `garder` reçoit la fiche choisie, `absorber` est retirée d'iCloud.
    Liaisons, portrait, affiche et relation LinkedIn de la fiche retirée passent à celle gardée."""
    if garder == absorber:
        raise ErreurCarnet("Choisis deux fiches différentes.")
    c.fiche(absorber)
    try:
        propre = F.preparer(fiche, c.cfg.region)
    except ValeurInvalide as exc:
        raise ErreurCarnet(str(exc))
    with c.ecriture(attendre=5):
        res = icloud.ecrire(c, garder, propre, origine="fusion", motif="fiche réunie")
        icloud.supprimer(c, absorber, origine="fusion")
    with c.base.transaction() as cx:
        for service in ("immich", "treemich"):
            a = cx.execute("SELECT * FROM liaisons WHERE uid = ? AND service = ?", (absorber, service)).fetchone()
            g = cx.execute("SELECT 1 FROM liaisons WHERE uid = ? AND service = ?", (garder, service)).fetchone()
            if a and not g:
                cx.execute("UPDATE liaisons SET uid = ? WHERE uid = ? AND service = ?", (garder, absorber, service))
        cx.execute("DELETE FROM liaisons WHERE uid = ?", (absorber,))
        cx.execute("UPDATE OR IGNORE refus SET uid = ? WHERE uid = ?", (garder, absorber))
        for table in ("portraits", "affiches"):
            if not cx.execute(f"SELECT 1 FROM {table} WHERE uid = ?", (garder,)).fetchone():
                cx.execute(f"UPDATE {table} SET uid = ? WHERE uid = ?", (garder, absorber))
            cx.execute(f"DELETE FROM {table} WHERE uid = ?", (absorber,))
        cx.execute("UPDATE linkedin SET uid = ? WHERE uid = ?", (garder, absorber))
        cx.execute("DELETE FROM en_attente WHERE uid = ?", (absorber,))
        cx.execute("DELETE FROM a_traiter WHERE uid = ?", (absorber,))
        cx.execute("DELETE FROM a_traiter WHERE motif = 'doublon' AND cle = ?", (F.cle_paire(garder, absorber),))
    c.oublier()
    c.base.noter("ecriture", "Deux fiches réunies en une", {"garder": garder, "absorber": absorber})
    return res


def proposition_fusion(c: Carnet, a: str, b: str) -> dict:
    fa, fb = c.fiche(a), c.fiche(b)
    return {"a": {"uid": a, "nom": nom_affiche(fa), "fiche": fa}, "b": {"uid": b, "nom": nom_affiche(fb), "fiche": fb},
            "proposee": F.proposer_fusion(fa, fb)}


__all__ = ["apercu", "valider", "annuler", "repondre", "fusionner", "json"]

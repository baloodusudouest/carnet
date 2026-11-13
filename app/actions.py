"""Décisions de Julien : valider une fiche, répondre à un point « À traiter », fusionner.

Chaque écriture vers iCloud prend le verrou commun (jamais deux écrivains) et passe par
icloud.ecrire, qui garde tout ce que carnet ne gère pas et refuse d'écraser une carte changée
sur l'iPhone.
"""
from __future__ import annotations

import json

from . import fiches as F, icloud, liaisons, traiter
from .carddav import ErreurICloud
from .carnet import Carnet, ErreurCarnet
from .modele import nom_affiche
from .normalisation import ValeurInvalide


def apercu(c: Carnet, uid: str, fiche: dict) -> dict:
    """Ce qui partirait dans iCloud si on validait cette fiche (rien n'est écrit)."""
    try:
        propre = F.preparer(fiche, c.cfg.region, avant=c.fiche(uid))
    except ValeurInvalide as exc:
        raise ErreurCarnet(str(exc))
    champs = F.differences(c.fiche(uid), propre)
    return {"fiche": propre, "champs": champs, "notes": _notes_de_saisie(fiche, propre, champs)}


def _notes_de_saisie(saisie: dict, propre: dict, champs: list) -> list[str]:
    """2.17.4 : ce que la mise en forme a écarté ou rendu identique, pour ne pas laisser « Aucun changement » sans
    explication (un courriel sans « @ » disparaissait sans un mot)."""
    notes = []
    gardes = {(x.get("valeur") or "").strip().lower() for x in propre.get("courriels") or []}
    for x in saisie.get("courriels") or []:
        v = (x.get("valeur") or "").strip()
        if v and v.lower().removeprefix("mailto:") not in gardes:
            notes.append(f"Courriel « {v} » non reconnu (il faut une adresse du type nom@domaine.fr) : il ne sera pas écrit.")
    gardes = {(x.get("valeur") or "").strip().lower() for x in propre.get("sites") or []}
    for x in saisie.get("sites") or []:
        v = (x.get("valeur") or "").strip()
        if v and not any(v.lower().rstrip("/") in g or g in v.lower() for g in gardes):
            notes.append(f"Site « {v} » non reconnu : il ne sera pas écrit.")
    if not champs:
        notes.append("Ta saisie revient au même que la fiche actuelle une fois mise en forme : numéros au format "
                     "international (+33 6 …), courriels et sites tels quels. Rien à écrire.")
    return notes


REVUE = ("iphone_modifiee", "iphone_nouvelle", "conflit")


def en_revue(c: Carnet, uid: str) -> bool:
    """La fiche attend ta relecture : modifiée ou créée sur l'iPhone, ou en conflit."""
    return bool(c.base.un(f"SELECT 1 FROM a_traiter WHERE uid = ? AND motif IN {REVUE}", (uid,)))


def valider(c: Carnet, uid: str, fiche: dict, photo: tuple[bytes, str] | None = None,
            origine: str = "manuel", motif: str = "modification", etag_vu: str | None = None,
            forcer: set[str] | None = None, regler_revue: bool = False) -> dict:
    """etag_vu : version de la carte que l'interface a affichée (refus si elle a changé depuis).
    regler_revue : seulement pour une modification faite par toi dans l'éditeur de la fiche, à
    partir de la version affichée ; elle règle les points iPhone et conflit de la fiche. Les autres
    écritures (À traiter, réseaux, photo…) laissent ces points en place : « Revenir » reste
    possible et la nuit continue d'ignorer la fiche."""
    try:
        propre = F.preparer(fiche, c.cfg.region, avant=c.fiche(uid) if origine == "manuel" else None)
    except ValeurInvalide as exc:
        raise ErreurCarnet(str(exc))
    with c.ecriture(attendre=5):
        res = icloud.ecrire(c, uid, propre, photo, origine=origine, motif=motif, etag_vu=etag_vu, forcer=forcer)
        # Sous le verrou, pour ne jamais effacer un point arrivé par une lecture pendant ce temps
        if regler_revue and etag_vu is not None:
            with c.base.transaction() as cx:
                cx.execute(f"DELETE FROM a_traiter WHERE uid = ? AND motif IN {REVUE}", (uid,))
            c.oublier()
    return res


def _etag(c: Carnet, uid: str) -> str:
    l = c.base.un("SELECT etag FROM fiches WHERE uid = ?", (uid,))
    return l["etag"] if l else ""


def annuler(c: Carnet, jeton: str) -> dict:
    with c.ecriture(attendre=5):
        return icloud.annuler(c, jeton)


# Ce que carnet sait d'une fiche en dehors de sa carte iCloud : retiré avec elle, remis si on annule
TABLES_D_UNE_FICHE = ("liaisons", "portraits", "affiches", "en_attente", "validations", "exceptions", "deces", "logos_cherches")


def supprimer(c: Carnet, uid: str, etag_vu: str | None, confirmation: bool) -> dict:
    """Suppression d'une fiche demandée par Julien depuis la fiche (2.8). Toujours confirmée : sans
    `confirmation`, rien n'est fait. La carte est retirée d'iCloud, donc de l'iPhone. « Annuler »
    la remet pendant 10 secondes ; ensuite, la sauvegarde du jour permet de la remettre (État)."""
    if confirmation is not True:
        raise ErreurCarnet("Suppression non confirmée : rien n'a été supprimé.")
    f = c.fiche(uid)
    ligne = c.base.un("SELECT href, etag, texte FROM fiches WHERE uid = ?", (uid,))
    if not etag_vu or etag_vu != ligne["etag"]:
        raise ErreurCarnet("La fiche a changé depuis son affichage : recharge-la avant de la supprimer.")
    import secrets
    import time
    memoire = {t: [dict(l) for l in c.base.tous(f"SELECT * FROM {t} WHERE uid = ?", (uid,))] for t in TABLES_D_UNE_FICHE}
    with c.ecriture(attendre=5):
        icloud.supprimer(c, uid, origine="fiche")
        with c.base.transaction() as cx:
            for table in TABLES_D_UNE_FICHE:
                cx.execute(f"DELETE FROM {table} WHERE uid = ?", (uid,))
            cx.execute("UPDATE linkedin SET uid = NULL WHERE uid = ?", (uid,))
        c.logos.pop(uid, None)
        c.oublier()
    jeton = secrets.token_urlsafe(12)
    c.annulations[jeton] = {"supprimee": True, "uid": uid, "texte": ligne["texte"], "href": ligne["href"],
                            "groupes": sorted(f.get("groupes", [])), "memoire": memoire,
                            "jusqua": time.monotonic() + icloud.DELAI_ANNULER}
    return {"ok": True, "jeton": jeton, "nom": nom_affiche(f)}


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
        champs = {"nom": {"prenom", "nom"}, "telephone": {"telephones"}, "anniversaire": {"anniversaire"}}
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
    if motif == "reseau":
        from . import reseaux
        if action in ("lier", "lier_numero"):
            return reseaux.lier(c, uid, d["service"], d["ext_id"], d.get("pseudo", ""), d.get("telephone", ""),
                                ajouter_numero=action == "lier_numero")
        if action == "pas_lui":
            reseaux.refuser(c, uid, d["service"], d["ext_id"])
            return {"ok": True}
    if motif in ("mariage", "mariage_different"):
        from . import famille
        if action == "sans" and motif == "mariage":
            return famille.sans_union(c, d["a"], d["b"])
        if action == "ecrire":
            reliees = famille._reliees(c)
            res = famille.ecrire_partout(c, "mariage", str(valeur or ""), [reliees[t] for t in (d["a"], d["b"]) if t in reliees],
                                         a=d["a"], b=d["b"])
            return res
    if motif == "deces_different" and action == "ecrire":
        from . import famille
        return famille.ecrire_partout(c, "deces", str(valeur or ""), [uid], treemich=d["treemich"])
    if motif == "societe" and action == "choisir":
        from . import societes
        return societes.harmoniser(c, d["cle"], str(valeur or ""))
    if motif == "doublon" and action == "distincts":
        traiter.ignorer(c, motif, cle)
        return {"ok": True}
    raise ErreurCarnet("Action inconnue pour ce point.")


ACTIONS_LOT = ("ignorer", "lier", "pas_lui", "garder", "appliquer")
ACTIONS_LOT_QUI_ECRIVENT = ("lier", "appliquer")


def _plafond_lot(c: Carnet) -> int:
    return max(3, len(c.fiches()) // 20)


def apercu_lot(c: Carnet, idents: list[str], action: str) -> dict:
    """Ce que ferait repondre_lot, sans rien faire : combien de points, combien d'écritures
    dans iCloud, combien remis au lot suivant. Affiché avant « Confirmer »."""
    if action not in ACTIONS_LOT:
        raise ErreurCarnet("Action groupée inconnue.")
    ecrit = action in ACTIONS_LOT_QUI_ECRIVENT
    plafond = _plafond_lot(c)
    n = len(idents)
    return {"action": action, "points": n, "ecrit": ecrit, "plafond": plafond,
            "a_ecrire": min(n, plafond) if ecrit else 0, "reportes": max(0, n - plafond) if ecrit else 0,
            "lecture_seule": c.cfg.lecture_seule}


def repondre_lot(c: Carnet, idents: list[str], action: str) -> dict:
    """Même réponse à plusieurs points. Les écritures dans iCloud sont plafonnées comme le
    coupe-circuit (5 % des fiches, 3 au moins) : au-delà, le reste attend un autre lot."""
    if action not in ACTIONS_LOT:
        raise ErreurCarnet("Action groupée inconnue.")
    if action in ACTIONS_LOT_QUI_ECRIVENT:
        c.exiger_ecriture("iCloud")
    plafond = _plafond_lot(c)
    bilan = {"faits": 0, "erreurs": [], "reportes": 0}
    ecritures = 0
    for ident in idents:
        ecrit = action in ACTIONS_LOT_QUI_ECRIVENT
        if ecrit and ecritures >= plafond:
            bilan["reportes"] += 1
            continue
        try:
            res = repondre(c, ident, action)
            bilan["faits"] += 1
            if ecrit and (res or {}).get("jeton"):
                ecritures += 1
        except (ErreurCarnet, ErreurICloud) as exc:   # une carte refusée n'arrête pas le lot
            bilan["erreurs"].append(str(exc))
    return bilan


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
        for (service,) in cx.execute("SELECT service FROM liaisons WHERE uid = ?", (absorber,)).fetchall():
            a = cx.execute("SELECT * FROM liaisons WHERE uid = ? AND service = ?", (absorber, service)).fetchone()
            g = cx.execute("SELECT 1 FROM liaisons WHERE uid = ? AND service = ?", (garder, service)).fetchone()
            if a and not g:
                cx.execute("UPDATE liaisons SET uid = ? WHERE uid = ? AND service = ?", (garder, absorber, service))
        cx.execute("DELETE FROM liaisons WHERE uid = ?", (absorber,))
        cx.execute("UPDATE OR IGNORE refus SET uid = ? WHERE uid = ?", (garder, absorber))
        cx.execute("DELETE FROM validations WHERE uid = ?", (absorber,))
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

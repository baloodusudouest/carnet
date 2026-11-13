"""Section Connexion (carnet 2.9) : un service par icône. Pour chacun : son état, « Vérifier »
(relire et comparer, sans rien écrire), « Synchroniser » (écrire ce qui est sûr — ce qui manque
d'un seul côté, jamais écraser — et envoyer toute différence dans « À traiter »), et un
interrupteur « la nuit ».

carnet ne remplace aucun de ces outils : il vérifie qu'ils disent la même chose.
"""
from __future__ import annotations

from . import attentes, famille, liaisons, sorties, traiter
from .carnet import Carnet, ErreurCarnet
from .fiches import date_lisible
from .modele import nom_affiche

# clé → (nom, ce que fait la synchronisation de nuit ; None : pas de nuit pour ce service)
SERVICES = {
    "icloud": ("iCloud", "Écrire les fêtes sur les fiches"),
    "immich": ("Immich", "Relier les personnes sûres, compléter naissances et portraits"),
    "treemich": ("Treemich", "Accorder mariages et décès"),
    "synology": ("Copies", "Copier vers Synology Contacts"),
    "sauvegardes": ("Sauvegardes", None),
    "import": ("Import", None),
    "linkedin": ("LinkedIn", None),
    "telegram": ("Telegram", None),
    "facebook": ("Facebook", None),
    "instagram": ("Instagram", None),
    "ha": ("Home Assistant", None),
    "kit": ("Kit d'urgence", "Envoyer les contacts d'urgence"),
}
_ANCIENS = {"icloud": "fetes", "treemich": "famille"}       # interrupteurs de la 2.8, gardés tels quels


def nuit_active(c: Carnet, service: str) -> bool:
    if service in _ANCIENS:
        return famille.actif(c, _ANCIENS[service])
    return bool(c.base.lire(f"nuit_{service}", True))        # Immich, Copies, Kit : comme avant la 2.9


def regler_nuit(c: Carnet, service: str, oui: bool) -> dict:
    if service not in SERVICES or SERVICES[service][1] is None:
        raise ErreurCarnet("Ce service n'a pas de synchronisation de nuit.")
    if service in _ANCIENS:
        return famille.regler(c, _ANCIENS[service], oui)
    c.base.ecrire(f"nuit_{service}", bool(oui))
    c.base.noter("automatique", f"{SERVICES[service][0]} : synchronisation de nuit {'allumée' if oui else 'éteinte'}")
    return {"ok": True, "actif": bool(oui)}


def _differences(c: Carnet) -> dict[str, int]:
    """Points d'« À traiter » par service."""
    res = {"icloud": 0, "immich": 0, "treemich": 0, "linkedin": 0, "telegram": 0, "facebook": 0, "instagram": 0}
    for p in traiter.liste(c):
        if p["tuile"] in ("icloud", "immich", "treemich"):
            res[p["tuile"]] += 1
        elif p["motif"] == "reseau" and p["donnees"].get("service") in res:
            res[p["donnees"]["service"]] += 1
        elif p["motif"] == "linkedin":
            res["linkedin"] += 1
    return res


def etat(c: Carnet, sante: dict, reseaux_: dict) -> list[dict]:
    """Une ligne par icône : voyant, résumé, différences en attente, interrupteur de nuit."""
    diff = _differences(c)
    lecture, nuit_, syno = c.base.lire("derniere_lecture") or {}, c.base.lire("nuit") or {}, c.base.lire("synology") or {}
    d = c.memo_present("liens", liaisons.DUREE_CACHE) or {}
    liens = c.liaisons()
    reliees = {s: sum(1 for v in liens.values() if v.get(s)) for s in ("immich", "treemich")}
    from . import icloud
    sauvegardes = icloud.liste_sauvegardes(c)
    resume = {
        "icloud": f"{len(c.fiches())} fiches", "immich": f"{reliees['immich']} fiche(s) reliée(s)",
        "treemich": f"{reliees['treemich']} fiche(s) reliée(s)",
        "synology": "jamais copié" if not syno else f"{sum(syno.get(k, 0) for k in ('crees', 'modifies', 'supprimes'))} changement(s) à la dernière copie",
        "sauvegardes": f"{len(sauvegardes)} copie(s) d'iCloud", "import": "Cartes, LinkedIn, Facebook, Instagram",
        "ha": "Contacts, anniversaires, mariages, fêtes", "kit": "Groupe Urgence",
    }
    le = {"icloud": lecture.get("le"), "immich": d.get("le"), "treemich": d.get("le"), "synology": syno.get("le"),
          "sauvegardes": sauvegardes[0].get("le") if sauvegardes else None, "kit": c.base.lire("dernier_envoi_kit")}
    res = []
    for cle, (nom, nuit_quoi) in SERVICES.items():
        s = sante.get(cle) or {"etat": "ok", "message": ""}
        r = reseaux_.get(cle)
        res.append({"cle": cle, "nom": nom, "voyant": s["etat"], "message": s.get("message", ""),
                    "resume": resume.get(cle) or (f"{r['liees']} fiche(s) liée(s)" if r else ""),
                    "le": le.get(cle) or (r or {}).get("importe_le"), "differences": diff.get(cle, 0),
                    "nuit": None if nuit_quoi is None else {"actif": nuit_active(c, cle), "quoi": nuit_quoi},
                    "verifiable": cle in ("icloud", "immich", "treemich", "synology"),
                    "synchronisable": cle in ("icloud", "immich", "treemich", "synology", "kit")})
    if nuit_.get("erreur") and res:
        res[0]["message"] = res[0]["message"] or nuit_["erreur"]
    return res


# ----------------------------------------------------------------- vérifier (n'écrit rien)

def _rapport_immich(c: Carnet, d: dict) -> dict:
    """Immich : nom, date de naissance, photo de la fiche, et ce qui n'est pas relié."""
    if not d.get("immich"):
        return {"ok": False, "raison": next((e for e in d.get("erreurs", []) if "treemich" not in e.lower()), "Immich n'a pas répondu.")}
    fiches, liens = c.fiches(), c.liaisons()
    im = {p["id"]: p for p in d["immich"]}
    reliees = {u: v["immich"] for u, v in liens.items() if v.get("immich") in im and u in fiches}
    a_traiter = {(p["motif"], p["uid"]) for p in traiter.liste(c)}
    noms = {r["uid"]: r for r in liaisons.renommages(c, d) if r["service"] == "immich"}
    lignes = {"nom": [0, 0, 0], "naissance": [0, 0, 0], "photo": [0, 0, 0]}     # identiques, vides, écarts
    ecarts = []

    def ecart(libelle, etat, uid, carnet, autre, suite):
        ecarts.append({"libelle": libelle, "etat_libelle": etat, "uid": uid, "nom": nom_affiche(fiches[uid]),
                       "carnet": carnet, "autre": autre, "suite": suite})
    for uid, pid in sorted(reliees.items(), key=lambda x: nom_affiche(fiches[x[0]]).casefold()):
        f = fiches[uid]
        if uid in noms:
            lignes["nom"][2] += 1
            ecart("Nom", "Différents", uid, noms[uid]["voulu"], noms[uid]["actuel"], "Un point t'attend dans « À traiter » : renommer dans Immich, ou ignorer.")
        else:
            lignes["nom"][0] += 1
        etat = famille._comparer(f.get("anniversaire") or "", (im[pid].get("naissance") or "")[:10])
        lignes["naissance"][{"identique": 0, "vide": 1}.get(etat, 2)] += 1
        if etat not in ("identique", "vide"):
            suite = ("Un point t'attend dans « À traiter »." if ("date", uid) in a_traiter
                     else "Synchroniser complète la fiche." if etat == "treemich_seul"
                     else "Synchroniser l'écrit dans Immich." if etat == "carnet_seul" and len(f.get("anniversaire") or "") == 10
                     else "Rien n'est fait d'office : complète la date du côté où elle manque.")
            ecart("Naissance", {"carnet_seul": "Dans carnet seulement", "treemich_seul": "Dans Immich seulement",
                                "different": "Différentes", "incomplet": "Incomplètes d'un côté"}[etat], uid,
                  date_lisible(f.get("anniversaire") or ""), date_lisible((im[pid].get("naissance") or "")[:10]), suite)
        if f.get("a_photo"):
            lignes["photo"][0] += 1
        else:
            lignes["photo"][2] += 1
            ecart("Photo", "Fiche sans photo", uid, "", "portrait disponible", "Synchroniser pose le portrait (20 fiches au plus par passage).")
    propositions = len(liaisons.propositions(c, d))
    sures = len(liaisons.sures(c, d))
    attendues = sum(1 for b in attentes.tout(c).values() if "immich" in b["manques"])
    nommees = sum(1 for p in d["immich"] if (p.get("nom") or "").strip())
    notes = [f"{len(reliees)} fiche(s) reliée(s) à une personne d'Immich.",
             f"{max(0, nommees - len(set(reliees.values())))} personne(s) nommée(s) dans Immich n'ont pas de fiche reliée."]
    if sures:
        notes.append(f"{sures} liaison(s) sûre(s) : Synchroniser les fait.")
    if propositions:
        notes.append(f"{propositions} liaison(s) proposée(s) t'attendent dans « À traiter ».")
    if attendues:
        notes.append(f"{attendues} fiche(s) dont le groupe attend Immich n'y sont pas reliées (tuile « Contact incomplet »).")
    return {"ok": True, "le": d.get("le"), "notes": notes, "ecarts": ecarts,
            "lignes": [{"libelle": l, "sur": len(reliees), "identiques": v[0], "vides": v[1], "ecarts": v[2]}
                       for l, v in (("Nom", lignes["nom"]), ("Naissance", lignes["naissance"]), ("Photo", lignes["photo"]))]}


def _rapport_treemich(c: Carnet, d: dict) -> dict:
    v = famille.verifier(c, rafraichir=False)
    if not v.get("treemich"):
        return {"ok": False, "raison": v.get("raison") or "Treemich n'a pas répondu."}
    fiches = c.fiches()
    noms = [r for r in liaisons.renommages(c, d) if r["service"] == "treemich"]
    liens_fam = liaisons.relations(c, d)
    ecarts = [{"libelle": "Nom", "etat_libelle": "Différents", "uid": r["uid"], "nom": nom_affiche(fiches[r["uid"]]),
               "carnet": r["voulu"], "autre": r["actuel"], "suite": "Un point t'attend dans « À traiter » : renommer dans Treemich, ou ignorer."}
              for r in noms]
    ecarts += [{**e, "autre": e["treemich"]} for e in v["ecarts"]]
    ecarts += [{"libelle": "Liens familiaux", "etat_libelle": "Dans Treemich seulement", "uid": r["uid"], "nom": nom_affiche(fiches[r["uid"]]),
                "carnet": "", "autre": ", ".join(a["valeur"] for a in r["ajouts"][:4]),
                "suite": "Un point t'attend dans « À traiter » : ajouter à la fiche, ou ignorer."} for r in liens_fam]
    lignes = [{"libelle": "Nom", "sur": v["personnes"], "identiques": v["personnes"] - len(noms), "vides": 0, "ecarts": len(noms)}]
    lignes += [{k: l[k] for k in ("libelle", "sur", "identiques", "vides", "ecarts")} for l in v["bilan"]]
    lignes.append({"libelle": "Liens familiaux", "sur": v["personnes"], "identiques": v["personnes"] - len(liens_fam), "vides": 0, "ecarts": len(liens_fam)})
    attendues = sum(1 for b in attentes.tout(c).values() if "treemich" in b["manques"])
    notes = [f"{v['personnes']} fiche(s) reliée(s) à l'arbre, {v['couples']} couple(s).",
             f"{v['sans_fiche']} personne(s) de l'arbre n'ont pas de fiche reliée."]
    if attendues:
        notes.append(f"{attendues} fiche(s) dont le groupe attend Treemich n'y sont pas reliées (tuile « Contact incomplet »).")
    notes += famille.pourquoi_rien(c, d)[:6]
    if v["liste_couples"]:
        notes.append("Dans Treemich, la date de mariage n'est pas dans « Life events » : elle est sur le lien du couple "
                     "(Profile › Relatives › crayon du conjoint › Marriage anniversary).")
    return {"ok": True, "le": d.get("le"), "notes": notes, "ecarts": ecarts, "lignes": lignes, "couples": v["liste_couples"]}


def verifier(c: Carnet, service: str) -> dict:
    """Relit le service et compare. N'écrit rien, nulle part."""
    if service == "icloud":
        from . import icloud
        with c.ecriture(attendre=30):
            b = icloud.relire(c, "vérification")
        points = [p for p in traiter.liste(c) if p["tuile"] == "icloud"]
        return {"ok": True, "le": (c.base.lire("derniere_lecture") or {}).get("le"), "lignes": [], "ecarts": [],
                "notes": [f"iCloud relu : {b['contacts']} fiches.",
                          f"{len(points)} changement(s) fait(s) sur l'iPhone t'attendent dans « À traiter »." if points
                          else "Aucun changement fait sur l'iPhone n'attend ta réponse.",
                          f"{len(famille.fetes_a_ecrire(c))} fête(s) ne sont pas encore écrites sur les fiches."]}
    if service == "synology":
        return sorties.apercu_synology(c)
    if service not in ("immich", "treemich"):
        raise ErreurCarnet("Ce service ne se vérifie pas.")
    d = liaisons.donnees(c, rafraichir=True)
    return _rapport_immich(c, d) if service == "immich" else _rapport_treemich(c, d)


# ----------------------------------------------------------------- synchroniser (écrit le sûr)

def synchroniser(c: Carnet, service: str) -> dict:
    """Écrit ce qui est sûr pour ce service et laisse toute différence à « À traiter ». Demandé par
    Julien : l'interrupteur de nuit n'entre pas en compte. Renvoie {message, …}."""
    from . import icloud, nuit
    if service == "synology":
        b = sorties.copier_synology(c)
        if b.get("desactivee"):
            raise ErreurCarnet("Synology Contacts n'est pas configuré.")
        if b.get("erreur"):
            raise ErreurCarnet(b["erreur"])
        return {**b, "message": f"Copie Synology : {b.get('crees', 0)} créée(s), {b.get('modifies', 0)} modifiée(s), {b.get('supprimes', 0)} retirée(s)."}
    if service == "kit":
        b = sorties.envoyer_kit(c)
        return {**b, "message": "Contacts d'urgence envoyés au kit."}
    if service not in ("icloud", "immich", "treemich"):
        raise ErreurCarnet("Ce service ne se synchronise pas.")
    c.exiger_ecriture(SERVICES[service][0])
    bilan = {"ecrites": 0, "reportees": 0, "liaisons": 0, "details": [], "treemich": 0, "immich": 0}
    if service == "treemich":
        b = famille.accorder_maintenant(c, forcer=True)
        d = liaisons.donnees(c)
        b["immich"] = 0
        _naissances_vers(c, d, "treemich", b)
        points = sum(1 for p in traiter.liste(c) if p["tuile"] == "treemich")
        return {**b, "message": f"Treemich : {b['ecrites']} fiche(s) écrite(s) dans iCloud, {b['treemich']} écriture(s) dans Treemich"
                                + (f" ; {points} différence(s) dans « À traiter »" if points else "")
                                + (" ; " + b["details"][0] if b["details"] else "") + "."}
    with c.ecriture(attendre=30):
        if service == "icloud":
            lecture = icloud.relire(c, "synchronisation")
            famille._ecrire_cartes(c, famille.fetes_a_ecrire(c), bilan, nuit.PLAFOND, "fête")
            points = sum(1 for p in traiter.liste(c) if p["tuile"] == "icloud")
            return {**bilan, "message": f"iCloud relu ({lecture['contacts']} fiches) ; {bilan['ecrites']} fête(s) écrite(s)"
                                        + (f", {bilan['reportees']} au prochain passage" if bilan["reportees"] else "")
                                        + (f" ; {points} changement(s) de l'iPhone dans « À traiter »" if points else "") + "."}
        d = liaisons.donnees(c, rafraichir=True)
        for e in d["erreurs"]:
            bilan["details"].append(e)
        for s in liaisons.sures(c, d):
            liaisons.lier(c, s["uid"], "immich", s["immich"], statut="auto")
            bilan["liaisons"] += 1
        nuit._ecritures_sures(c, d, bilan)
    _naissances_vers(c, d, "immich", bilan)
    c.oublier()
    points = sum(1 for p in traiter.liste(c) if p["tuile"] == "immich")
    return {**bilan, "message": f"Immich : {bilan['liaisons']} liaison(s) sûre(s), {bilan['ecrites']} fiche(s) complétée(s) (naissance, portrait), "
                                f"{bilan['immich']} naissance(s) écrite(s) dans Immich"
                                + (f", {bilan['reportees']} au prochain passage" if bilan["reportees"] else "")
                                + (f" ; {points} différence(s) dans « À traiter »" if points else "")
                                + (" ; " + bilan["details"][0] if bilan["details"] else "") + "."}


def _naissances_vers(c: Carnet, d: dict, service: str, bilan: dict) -> None:
    """Remplir : la fiche a une date de naissance complète, le service n'en a aucune → elle y est
    écrite. Jamais si le service porte déjà une date, même partielle."""
    from .liens import ErreurLien
    fiches, liens = c.fiches(), c.liaisons()
    im = {p["id"]: p for p in d.get("immich", [])}
    for uid, lien in liens.items():
        f, ext = fiches.get(uid), lien.get(service)
        date = (f or {}).get("anniversaire") or ""
        if not ext or len(date) != 10 or date.startswith("1900"):
            continue
        try:
            if service == "immich":
                if ext not in im or (im[ext].get("naissance") or ""):
                    continue
                client = c.immich()
                try:
                    client.maj_naissance(ext, date)
                finally:
                    client.fermer()
            else:
                if not famille._treemich_parle(d) or ext not in d["naissances_treemich"] or d["naissances_treemich"][ext]:
                    continue
                c.treemich().maj_naissance(ext, date)
            liaisons._maj_cache(c, service, ext, naissance=date)
            c.base.executer("INSERT INTO automatiques(le, service, sujet, cible, avant, apres) VALUES (?,?,?,?,?,?)",
                            (famille.iso(famille.maintenant()), service, "naissance", ext, None, date))
            bilan[service] = bilan.get(service, 0) + 1
        except (ErreurLien, ErreurCarnet) as exc:
            bilan["details"].append(str(exc))
            break


__all__ = ["SERVICES", "etat", "verifier", "synchroniser", "nuit_active", "regler_nuit"]

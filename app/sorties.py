"""Ce que carnet donne aux autres : kit d'urgence, copie Synology Contacts, Home Assistant.

Home Assistant : `/ha/contacts` (nouvelle adresse unique) et les adresses de la 1.3
(`/ha/personnes`, `/ha/anniversaires`, `/ha/invite`, `/ha/portraits/candidats`, `/ha/portrait`),
gardées à l'identique pour que rien ne casse. Aucun nom ni aucune date dans les journaux.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from . import anniversaires, export, images, synchro
from .carddav import Conflit, ErreurICloud
from .carnet import Carnet, ErreurCarnet
from .liaisons import DUREE_CACHE
from .modele import GROUPE_URGENCE, nom_affiche
from .normalisation import GROUPES_PROCHES, cle_texte
from .temps import iso, maintenant

log = logging.getLogger("carnet")
KIT_VCF = "contacts-urgence.vcf"
SEUIL_SYNOLOGY = 0.05


# ================================================================ kit d'urgence

def envoyer_kit(c: Carnet) -> dict:
    """Groupe « Urgence » → contacts-urgence.vcf dans le dossier du kit, puis régénération."""
    c.exiger_ecriture("le kit d'urgence")
    dossier = c.cfg.kit_config
    if not dossier or not dossier.is_dir():
        raise ErreurCarnet("Dossier du kit introuvable : vérifie le volume ${KIT_DATA_DIR}/config dans la stack.")
    lignes = [l for l in c.base.tous("SELECT uid, texte, fiche FROM fiches")
              if GROUPE_URGENCE in json.loads(l["fiche"]).get("groupes", [])]
    if not lignes:
        raise ErreurCarnet("Aucun contact dans le groupe Urgence.")
    # Cartes nettoyées (sans données internes d'iCloud), photos réduites pour la liseuse
    textes = []
    for l in lignes:
        f = json.loads(l["fiche"])
        textes.append(export.vcard(f, l["uid"], None))
    export.ecrire_atomique(dossier / KIT_VCF, "".join(textes))
    res = {"nb": len(lignes), "fichier": KIT_VCF, "regeneration": None, "le": iso(maintenant())}
    if c.cfg.kit_token:
        try:
            with c.http("kit") as client:
                r = client.post(f"{c.cfg.kit_url}/generer", timeout=300,
                                headers={"Authorization": f"Bearer {c.cfg.kit_token}"})
            res["regeneration"] = "ok" if r.status_code < 300 else f"erreur HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            res["regeneration"] = f"kit injoignable ({exc.__class__.__name__})"
    else:
        res["regeneration"] = "non demandée (KIT_API_TOKEN absent)"
    c.base.ecrire("dernier_envoi_kit", res)
    c.base.noter("kit", f"Kit d'urgence : {res['nb']} contact(s) envoyés, régénération {res['regeneration']}")
    return res


# ================================================================ Synology Contacts (miroir d'iCloud)

def copier_synology(c: Carnet, forcer: bool = False, avancer=None) -> dict:
    """Synology Contacts à l'identique d'iCloud (cartes et groupes). Arrêt sans rien écrire si plus
    de 5 % des fiches déjà copiées changeraient d'un coup — sauf la première fois après la 1.3,
    dont la copie portait des identifiants « carnet-… » : elle est remplacée entièrement.
    avancer(progression 0…1, message) : suivi de la copie (bouton à anneau)."""
    avancer = avancer or (lambda *_: None)
    if not c.cfg.synology_url:
        return {"desactivee": True}
    c.exiger_ecriture("Synology Contacts")
    dav = c.synology()
    bilan = {"le": iso(maintenant()), "crees": 0, "modifies": 0, "supprimes": 0, "erreurs": [], "ok": True}
    try:
        avancer(0.02, "Lecture de Synology Contacts…")
        distantes = {x.uid: x for x in (synchro.analyser(b.href, b.etag, b.texte) for b in dav.lister())}
        voulues = {l["uid"]: l["texte"] for l in c.base.tous("SELECT uid, texte FROM fiches")}
        voulues.update({l["uid"]: l["texte"] for l in c.base.tous("SELECT uid, texte FROM groupes")})
        actions = []
        for uid, texte in voulues.items():
            d = distantes.get(uid)
            if d is None:
                actions.append(("creer", uid, texte, None, dav.href_nouveau(uid)))
            elif synchro.empreinte(d.texte) != synchro.empreinte(texte):
                actions.append(("modifier", uid, texte, d.etag, d.href))
        for uid, d in distantes.items():
            if uid not in voulues:
                actions.append(("supprimer", uid, None, d.etag, d.href))
        ancienne_copie = distantes and all(u.startswith("carnet-") for u in distantes)
        touches = sum(1 for a in actions if a[0] != "creer")
        if distantes and not (forcer or ancienne_copie) and touches > max(5, SEUIL_SYNOLOGY * len(distantes)):
            raise ErreurCarnet(f"Copie Synology bloquée : {touches} fiches sur {len(distantes)} changeraient d'un coup "
                               "(plus de 5 %). Vérifie, puis « Forcer la copie » si c'est voulu.")
        total = len(actions)
        avancer(0.08, f"{total} fiche(s) à copier…" if total else "Déjà à jour.")
        for n, (action, uid, texte, etag, href) in enumerate(actions, 1):
            if n % 5 == 0 or n == total:
                avancer(0.08 + 0.92 * n / total, f"{n} / {total} fiche(s) copiée(s)")
            try:
                if action == "supprimer":
                    dav.supprimer(href, etag)
                    bilan["supprimes"] += 1
                else:
                    dav.ecrire(href, texte, etag)
                    bilan["crees" if action == "creer" else "modifies"] += 1
            except (Conflit, ErreurICloud) as exc:
                bilan["erreurs"].append(str(exc))
                if "refuse la connexion" in str(exc):
                    break
    except (ErreurICloud, ErreurCarnet) as exc:
        bilan.update(ok=False, erreur=str(exc))
    finally:
        dav.fermer()
    c.base.ecrire("synology", bilan)
    c.base.noter("synology", f"Synology Contacts : {bilan['crees']} créée(s), {bilan['modifies']} mise(s) à jour, "
                 f"{bilan['supprimes']} retirée(s)" + (f" — {bilan.get('erreur')}" if bilan.get("erreur") else ""),
                 {k: bilan[k] for k in ("crees", "modifies", "supprimes")})
    return bilan


# ================================================================ Home Assistant

def _noms_immich(c: Carnet) -> dict[str, str]:
    d = c.memo_present("liens", DUREE_CACHE)
    return {p["id"]: p["nom"] for p in (d or {}).get("immich", [])}


def contacts_ha(c: Carnet) -> list[dict]:
    """Toutes les fiches, avec le nom donné à HA : celui d'Immich quand la fiche est liée."""
    noms = _noms_immich(c)
    liens = c.liaisons()
    res = []
    for uid, f in c.fiches().items():
        lien = liens.get(uid, {})
        lue = anniversaires.analyser(f.get("anniversaire"))
        res.append({"carnet_id": uid, "nom": noms.get(lien.get("immich")) or nom_affiche(f), "nom_carnet": nom_affiche(f),
                    "prenom": f.get("prenom", ""), "immich_id": lien.get("immich"), "treemich_id": lien.get("treemich"),
                    "groupes": f.get("groupes", []), "proche": bool(set(f.get("groupes", [])) & GROUPES_PROCHES),
                    "naissance": f.get("anniversaire") or None,
                    "jour": lue[0] if lue else None, "mois": lue[1] if lue else None, "annee": lue[2] if lue else None})
    return sorted(res, key=lambda p: p["nom"].casefold())


def ha_contacts(c: Carnet) -> dict:
    liste = contacts_ha(c)
    log.info("HA contacts : %d fiche(s) renvoyée(s)", len(liste))
    return {"genere_le": iso(maintenant()), "nombre": len(liste),
            "contacts": [{k: p[k] for k in ("carnet_id", "nom", "prenom", "immich_id", "treemich_id", "groupes", "proche",
                                            "naissance", "jour", "mois", "annee")} for p in liste]}


def ha_personnes(c: Carnet) -> dict:
    """1.3 : fiches liées à Immich et proches (liste de la carte de réservation)."""
    return {"personnes": [{"nom": p["nom"], "immich": bool(p["immich_id"])} for p in contacts_ha(c)
                          if p["immich_id"] or p["proche"]]}


def ha_anniversaires(c: Carnet) -> dict:
    """Naissances, et depuis la 2.8 les mariages (clé « mariages »). Une personne décédée n'est
    plus annoncée ; un couple divorcé non plus."""
    from . import attentes, famille
    morts, divorces = attentes.decedes(c), famille.divorces(c)
    personnes = [p for p in contacts_ha(c) if p["carnet_id"] not in morts]
    entrees = [{"nom": p["nom"], "jour": p["jour"], "mois": p["mois"], "annee": p["annee"], "immich": bool(p["immich_id"])}
               for p in personnes if p["jour"]]
    liste = anniversaires.assembler(entrees)
    fiches = c.fiches()
    mariages = []
    for p in personnes:
        lue = anniversaires.analyser(fiches[p["carnet_id"]].get("mariage"))
        if lue and p["carnet_id"] not in divorces:
            mariages.append({"nom": p["nom"], "jour": lue[0], "mois": lue[1], "annee": lue[2], "immich": bool(p["immich_id"])})
    mariages = anniversaires.assembler(mariages)
    log.info("HA anniversaires : %d naissance(s), %d mariage(s)", len(liste), len(mariages))
    return {"genere_le": iso(maintenant()), "nombre": len(liste), "anniversaires": liste, "mariages": mariages}


def ha_fetes(c: Carnet) -> dict:
    """Fêtes des contacts dont un groupe attend la fête (case du tableau des attentes). La date
    est celle de la carte, sinon celle du calendrier : l'annonce n'attend pas l'écriture dans iCloud."""
    from . import attentes
    morts, tableau, fiches = attentes.decedes(c), attentes.par_groupe(c), c.fiches()
    entrees = []
    for p in contacts_ha(c):
        f = fiches[p["carnet_id"]]
        if p["carnet_id"] in morts or "fete" not in attentes.attendues(f, tableau):
            continue
        lue = anniversaires.analyser(attentes.fete_de(f)[0])
        if lue:
            entrees.append({"nom": p["nom"], "prenom": p["prenom"], "jour": lue[0], "mois": lue[1], "annee": None,
                            "immich": bool(p["immich_id"])})
    liste = anniversaires.assembler(entrees)
    log.info("HA fêtes : %d entrée(s)", len(liste))
    return {"genere_le": iso(maintenant()), "nombre": len(liste), "fetes": liste}


def ha_invite(c: Carnet, nom: str) -> dict:
    """Nom (ou identifiant Immich) → fiche de l'invité. 404 inconnu, 409 plusieurs."""
    brut = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\s*(?:→|->)\s*\d{4}-\d{2}-\d{2}\)\s*$", "", (nom or "").strip())
    personnes = [p for p in contacts_ha(c) if p["immich_id"] or p["proche"]]
    uuid_ = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", brut.lower())
    if uuid_:
        trouves = [p for p in personnes if p["immich_id"] == uuid_.group(0)]
    else:
        cle = cle_texte(brut)
        trouves = [p for p in personnes if cle in (cle_texte(p["nom"]), cle_texte(p["nom_carnet"]))]
    if not trouves:
        raise LookupError(f"« {brut} » n'est ni un proche ni un contact lié à Immich dans carnet.")
    if len(trouves) > 1:
        raise ValueError(f"Plusieurs personnes s'appellent « {brut} » : mets l'identifiant Immich dans le champ.")
    p = trouves[0]
    annif = p["naissance"] or ""
    return {"nom": p["nom"], "prenom": p["prenom"], "naissance": annif or None, "annee_connue": len(annif) == 10,
            "immich_id": p["immich_id"], "treemich_id": p["treemich_id"], "groupes": p["groupes"], "carnet_id": p["carnet_id"]}


def _uid_immich(c: Carnet, immich_id: str) -> str | None:
    return next((u for u, v in c.liaisons().items() if v.get("immich") == immich_id), None)


def ha_candidats(c: Carnet, immich_id: str, nombre: int = 3) -> dict:
    uid = _uid_immich(c, (immich_id or "").strip().lower())
    if not uid:
        return {"candidats": [], "actuel": None}
    ligne = c.base.un("SELECT candidats, asset FROM portraits WHERE uid = ?", (uid,))
    cands = json.loads(ligne["candidats"]) if ligne else []
    return {"candidats": [{"asset": x["asset"], "score": x["taille"], "le": x.get("le")} for x in cands[:max(1, min(nombre, 6))]],
            "actuel": ligne["asset"] if ligne else None}


def ha_portrait(c: Carnet, immich_id: str, cadre: str | None, asset: str | None) -> tuple[bytes, str, tuple | None] | None:
    """Portrait centré sur le visage pour les cadres et cartes de HA (None : HA prend la vignette Immich)."""
    uid = _uid_immich(c, (immich_id or "").strip().lower())
    if not uid:
        return None
    ligne = c.base.un("SELECT candidats, asset FROM portraits WHERE uid = ?", (uid,))
    cands = json.loads(ligne["candidats"]) if ligne else []
    voulu = asset or (ligne["asset"] if ligne else None)
    cand = next((x for x in cands if x["asset"] == voulu), None)
    if not cand:
        return None

    centre = bool(asset) or cadre == "centre"

    def calcul():
        im = c.immich()
        try:
            contenu = im.image(cand["asset"], "preview")
        finally:
            im.fermer()
        if not contenu:
            return None
        boite = tuple(cand["boite"])
        if centre:
            return images.portrait_centre(contenu, boite)
        ratio = cand.get("ratio") or images.ratio_image(contenu)
        return images.portrait(contenu, boite)[0], images.visage_dans_portrait(boite, ratio)
    trouve = c.memo(f"portrait:{cand['asset']}:{centre}", calcul, duree=86400)
    return (trouve[0], "image/jpeg", trouve[1]) if trouve else None


# ================================================================ /status (compteurs seulement)

def statut(c: Carnet) -> dict:
    from . import traiter
    lecture = c.base.lire("derniere_lecture") or {}
    nuit = c.base.lire("nuit") or {}
    syno = c.base.lire("synology") or {}
    compte = traiter.compte(c)
    sauvegardes = [j for j in c.base.journal("sauvegarde", 1)]
    total = len(c.fiches())
    par = compte["par_motif"]
    return {
        "version": __import__("app").__version__,
        "total": total, "verifies": total - compte["total"], "a_traiter": compte["total"], "par_motif": par,
        # Champs lus par le paquet Home Assistant de la 1.3 (inchangé)
        "a_reviser": compte["total"], "doublons_a_reviser": par.get("doublon", 0),
        "a_revoir": par.get("iphone_modifiee", 0) + par.get("iphone_nouvelle", 0) + par.get("iphone_supprimee", 0),
        "linkedin_sans_contact": (c.base.un("SELECT count(*) AS n FROM linkedin WHERE uid IS NULL AND detachee = 0") or {"n": 0})["n"],
        "archives_bientot": 0, "contacts_archives_bientot": 0, "prochaine_suppression": None,
        "reference": bool(c.base.lire("reference")),
        "veille": {"le": lecture.get("le"), "ok": lecture.get("ok", False) and not nuit.get("erreur_lecture"),
                   "erreur": nuit.get("erreur_lecture"), "revision": lecture.get("revision", 0),
                   "nouveaux": lecture.get("nouveaux", 0), "modifies": lecture.get("modifies", 0),
                   "supprimes": lecture.get("supprimes", 0)} if lecture or nuit else None,
        "synchro": {"mode": "auto" if c.cfg.nuit_active else "arret", "le": nuit.get("le"), "ok": not nuit.get("erreur"),
                    "crees": 0, "modifies": nuit.get("ecrites", 0), "groupes": 0, "suppressions_en_attente": 0,
                    "en_revision": compte["total"], "alerte": nuit.get("alerte"), "erreur": nuit.get("erreur")} if nuit else None,
        "sauvegarde": {"le": sauvegardes[0]["le"] if sauvegardes else None, "ok": not (syno.get("erreur")),
                       "erreur": syno.get("erreur"), "contacts": total,
                       "synology": {k: syno.get(k) for k in ("crees", "modifies", "supprimes")} if syno else None},
        "dernier_envoi_kit": c.base.lire("dernier_envoi_kit"),
        "completude": __import__("app.completude", fromlist=["compteurs"]).compteurs(c),
        "tache": {k: c.tache.get(k) for k in ("nom", "etat", "message")},
    }

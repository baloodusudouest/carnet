"""iCloud, la source maître : lecture (veille), écriture d'une fiche, groupes, annulation,
sauvegardes et restauration.

Règles :
- la première lecture complète sert de référence : rien n'est signalé, rien n'est écrit ;
- ensuite, toute fiche modifiée, créée ou supprimée sur l'iPhone va dans « À traiter » ;
- lecture incomplète, ou plus de 5 % des fiches disparues d'un coup : arrêt, rien n'est changé ;
- toute écriture se fait avec If-Match : une carte changée sur l'iPhone entre-temps n'est jamais
  écrasée (conflit → « À traiter ») ;
- une sauvegarde complète est faite avant la première écriture de la journée.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from datetime import timedelta
from pathlib import Path

from . import export, fiches as F, images, synchro, traiter
from .carddav import Conflit, ErreurICloud
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

SEUIL_DISPARUES = 0.05      # au-delà : coupe-circuit
TAILLE_MAX = 110_000        # octets : iCloud refuse une carte trop lourde (~120 Ko)
DELAI_ANNULER = 10          # secondes pendant lesquelles « Annuler » reste possible
GARDE_JOURS = 30            # sauvegardes quotidiennes gardées 30 jours…
GARDE_MOIS = 12             # …puis une par mois pendant un an
VOLUME_MAX = 2_000_000_000  # octets : au-delà, les plus anciennes partent d'abord


# ================================================================ lecture

def _uid_groupe(nom: str) -> str:
    return f"carnet-groupe-{uuid.uuid5(uuid.NAMESPACE_URL, 'carnet:' + nom)}"


def relire(c: Carnet, origine: str = "manuel") -> dict:
    """Lit tout iCloud et met la base à jour. À appeler avec le verrou d'écriture."""
    dav = c.icloud()
    try:
        brutes = dav.lister()   # lève ErreurICloud si la lecture est incomplète
    finally:
        dav.fermer()
    cartes = [synchro.analyser(b.href, b.etag, b.texte) for b in brutes]
    contacts = {x.uid: x for x in cartes if not x.groupe}
    groupes = {x.uid: x for x in cartes if x.groupe}
    appartenance: dict[str, list[str]] = {}
    for g in groupes.values():
        for m in g.membres:
            appartenance.setdefault(m, []).append(g.nom)

    reference = c.base.lire("reference")
    stockees = {l["uid"]: l for l in c.base.tous("SELECT * FROM fiches")}
    disparues = [u for u in stockees if u not in contacts]
    if reference and stockees and len(disparues) > max(3, SEUIL_DISPARUES * len(stockees)):
        raise ErreurCarnet(f"Lecture d'iCloud arrêtée : {len(disparues)} fiches sur {len(stockees)} auraient disparu "
                           "d'un coup (plus de 5 %). Rien n'a été modifié. Vérifie sur l'iPhone, puis « Relire quand même ».")
    return _appliquer(c, contacts, groupes, appartenance, stockees, disparues, bool(reference), origine)


def relire_quand_meme(c: Carnet) -> dict:
    """Après vérification : la lecture est acceptée même avec beaucoup de fiches disparues."""
    dav = c.icloud()
    try:
        brutes = dav.lister()
    finally:
        dav.fermer()
    cartes = [synchro.analyser(b.href, b.etag, b.texte) for b in brutes]
    contacts = {x.uid: x for x in cartes if not x.groupe}
    groupes = {x.uid: x for x in cartes if x.groupe}
    appartenance: dict[str, list[str]] = {}
    for g in groupes.values():
        for m in g.membres:
            appartenance.setdefault(m, []).append(g.nom)
    stockees = {l["uid"]: l for l in c.base.tous("SELECT * FROM fiches")}
    disparues = [u for u in stockees if u not in contacts]
    return _appliquer(c, contacts, groupes, appartenance, stockees, disparues, True, "manuel (forcé)")


def _appliquer(c: Carnet, contacts, groupes, appartenance, stockees, disparues, signaler: bool, origine: str) -> dict:
    quand = iso(maintenant())
    bilan = {"le": quand, "ok": True, "erreur": None, "contacts": len(contacts), "nouveaux": 0, "modifies": 0,
             "supprimes": 0, "revision": 0, "reference": not signaler, "origine": origine}
    region = c.cfg.region
    with c.base.transaction() as cx:
        cx.execute("DELETE FROM groupes")
        for g in groupes.values():
            cx.execute("INSERT INTO groupes(uid, href, etag, nom, texte, membres) VALUES (?,?,?,?,?,?)",
                       (g.uid, g.href, g.etag, g.nom, g.texte, json.dumps(g.membres)))
        for uid, carte in contacts.items():
            ancienne = stockees.get(uid)
            gr = appartenance.get(uid, [])
            if ancienne and ancienne["etag"] == carte.etag and ancienne["texte"] == carte.texte:
                fiche = json.loads(ancienne["fiche"])
                a_photo = bool(ancienne["photo"])
                if sorted(fiche.get("groupes", [])) == sorted(set(gr)):
                    continue
                avant = dict(fiche)
                fiche["groupes"] = sorted(set(gr))
            else:
                fiche, a_photo = F.lire(carte.texte, gr, region)
                avant = json.loads(ancienne["fiche"]) if ancienne else None
            cx.execute("INSERT INTO fiches(uid, href, etag, texte, fiche, photo, lu_le) VALUES (?,?,?,?,?,?,?) "
                       "ON CONFLICT(uid) DO UPDATE SET href=excluded.href, etag=excluded.etag, texte=excluded.texte, "
                       "fiche=excluded.fiche, photo=excluded.photo, lu_le=excluded.lu_le",
                       (uid, carte.href, carte.etag, carte.texte, json.dumps(fiche, ensure_ascii=False), int(a_photo), quand))
            if not signaler:
                continue
            if ancienne is None:
                bilan["nouveaux"] += 1
                traiter.ajouter(cx, "iphone_nouvelle", uid, uid, {"fiche": fiche})
                bilan["revision"] += 1
                continue
            diff = F.differences(avant, fiche, photo=bool(a_photo) != bool(ancienne["photo"]))
            if not diff:
                continue
            bilan["modifies"] += 1
            bilan["revision"] += 1
            existant = cx.execute("SELECT donnees FROM a_traiter WHERE motif = 'iphone_modifiee' AND cle = ?", (uid,)).fetchone()
            premier = json.loads(existant["donnees"]) if existant else {"avant": avant, "texte_avant": ancienne["texte"]}
            premier["apres"] = fiche
            premier["champs"] = F.differences(premier["avant"], fiche, photo=bool(a_photo) != bool(ancienne["photo"]))
            if premier["champs"]:
                traiter.ajouter(cx, "iphone_modifiee", uid, uid, premier, remplacer=True)
            else:   # revenue à l'état d'avant : plus rien à relire
                cx.execute("DELETE FROM a_traiter WHERE motif = 'iphone_modifiee' AND cle = ?", (uid,))
        for uid in disparues:
            ancienne = stockees[uid]
            cx.execute("DELETE FROM fiches WHERE uid = ?", (uid,))
            cx.execute("DELETE FROM a_traiter WHERE uid = ? AND motif NOT IN ('iphone_supprimee')", (uid,))
            if signaler:
                bilan["supprimes"] += 1
                bilan["revision"] += 1
                traiter.ajouter(cx, "iphone_supprimee", uid, uid,
                                {"fiche": json.loads(ancienne["fiche"]), "texte": ancienne["texte"], "href": ancienne["href"]},
                                remplacer=True)
    if not signaler:
        c.base.ecrire("reference", {"le": quand, "contacts": len(contacts)})
    c.base.ecrire("derniere_lecture", bilan)
    c.oublier()
    c.base.noter("veille", f"Lecture d'iCloud ({origine}) : {len(contacts)} fiches"
                 + (" — référence enregistrée" if not signaler else
                    f", {bilan['nouveaux']} nouvelle(s), {bilan['modifies']} modifiée(s), {bilan['supprimes']} supprimée(s)"),
                 {k: bilan[k] for k in ("contacts", "nouveaux", "modifies", "supprimes")})
    return bilan


def _relire_une(c: Carnet, dav, uid: str, href: str) -> tuple[str, str] | None:
    """Relit une carte après écriture : texte et ETag exacts, gardés comme nouvelle référence."""
    brute = dav.lire_une(href)
    if not brute:
        return None
    return brute.etag, brute.texte


# ================================================================ écriture

def _groupes_actuels(c: Carnet) -> dict[str, dict]:
    return {l["nom"]: {"uid": l["uid"], "href": l["href"], "etag": l["etag"], "texte": l["texte"],
                       "membres": json.loads(l["membres"])} for l in c.base.tous("SELECT * FROM groupes")}


def carte(c: Carnet, uid: str, fiche: dict, photo: tuple[bytes, str] | None, texte_distant: str | None) -> str:
    """Carte complète à écrire : la fiche de carnet + tout ce qu'iCloud avait en plus.
    Contrôle de taille : la photo est réduite si besoin, sinon l'écriture est refusée."""
    nouvelle = export.vcard(fiche, uid, photo)
    texte = synchro.assembler(nouvelle, texte_distant)
    if len(texte.encode()) > TAILLE_MAX and photo:
        nouvelle = export.vcard(fiche, uid, images.alleger(photo, 50_000))
        texte = synchro.assembler(nouvelle, texte_distant)
    if len(texte.encode()) > TAILLE_MAX:
        raise ErreurCarnet(f"Fiche trop lourde pour iCloud ({len(texte.encode()) // 1000} Ko) : "
                           "réduis les notes ou retire la photo.")
    return texte


def sauvegarde_du_jour(c: Carnet, motif: str = "jour") -> str | None:
    """Copie complète d'iCloud (d'après la dernière lecture) avant la première écriture du jour."""
    jour = maintenant().strftime("%Y-%m-%d")
    dossier = c.cfg.sauvegardes
    if motif == "jour" and any(dossier.glob(f"icloud-{jour}*.vcf")):
        return None
    return sauvegarder(c, motif)


def sauvegarder(c: Carnet, motif: str = "nuit") -> str:
    quand = maintenant()
    dossier = c.cfg.sauvegardes
    dossier.mkdir(parents=True, exist_ok=True)
    nom = f"icloud-{quand:%Y-%m-%d_%H%M%S}-{motif}.vcf"
    textes = [l["texte"] for l in c.base.tous("SELECT texte FROM fiches ORDER BY uid")]
    textes += [l["texte"] for l in c.base.tous("SELECT texte FROM groupes ORDER BY uid")]
    export.ecrire_atomique(dossier / nom, "".join(t if t.endswith("\n") else t + "\r\n" for t in textes))
    c.base.noter("sauvegarde", f"Sauvegarde d'iCloud : {len(textes)} cartes ({nom})", {"fichier": nom, "cartes": len(textes)})
    purger(c)
    return nom


def purger(c: Carnet) -> int:
    """30 jours de sauvegardes, puis la première de chaque mois pendant un an, 2 Go au plus."""
    dossier = c.cfg.sauvegardes
    fichiers = sorted(dossier.glob("icloud-*.vcf"))
    if not fichiers:
        return 0
    aujourd = maintenant().date()
    garder, mois_vus = set(), set()
    for f in fichiers:
        m = re.match(r"icloud-(\d{4})-(\d{2})-(\d{2})", f.name)
        if not m:
            continue
        jour = aujourd.replace(year=int(m[1]), month=int(m[2]), day=int(m[3]))
        age = (aujourd - jour).days
        if age <= GARDE_JOURS:
            garder.add(f)
        elif age <= 366 and (m[1], m[2]) not in mois_vus:
            garder.add(f)
            mois_vus.add((m[1], m[2]))
    retires = 0
    for f in fichiers:
        if f not in garder:
            f.unlink(missing_ok=True)
            retires += 1
    restants = sorted((f for f in fichiers if f.exists()), key=lambda f: f.name)
    total = sum(f.stat().st_size for f in restants)
    while restants and total > VOLUME_MAX and len(restants) > 1:
        f = restants.pop(0)
        total -= f.stat().st_size
        f.unlink(missing_ok=True)
        retires += 1
    return retires


def ecrire(c: Carnet, uid: str, fiche: dict, photo: tuple[bytes, str] | None = None,
           origine: str = "manuel", motif: str = "modification") -> dict:
    """Écrit une fiche existante dans iCloud (verrou d'écriture déjà pris).
    Renvoie {etag, jeton} ; jeton sert à « Annuler » pendant 10 s."""
    ligne = c.base.un("SELECT * FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        raise ErreurCarnet("Ce contact n'existe plus dans iCloud : relis iCloud avant de le modifier.")
    sauvegarde_du_jour(c)
    avant = json.loads(ligne["fiche"])
    texte = carte(c, uid, fiche, photo, ligne["texte"])
    dav = c.icloud()
    try:
        try:
            nouvel_etag = dav.ecrire(ligne["href"], texte, ligne["etag"])
        except Conflit:
            _signaler_conflit(c, dav, uid, ligne, fiche)
            raise ErreurCarnet("Ce contact vient d'être modifié sur l'iPhone : rien n'a été écrasé. "
                               "Les deux versions t'attendent dans « À traiter ».")
        relue = _relire_une(c, dav, uid, ligne["href"])
        etag, texte_final = relue if relue else (nouvel_etag or dav.etag(ligne["href"]) or "", texte)
        groupes_avant = sorted(avant.get("groupes", []))
        modifs_groupes = _ecrire_groupes(c, dav, uid, groupes_avant, sorted(set(fiche.get("groupes", []))))
    finally:
        dav.fermer()
    lue, a_photo = F.lire(texte_final, fiche.get("groupes", []), c.cfg.region)
    with c.base.transaction() as cx:
        cx.execute("UPDATE fiches SET etag = ?, texte = ?, fiche = ?, photo = ?, lu_le = ? WHERE uid = ?",
                   (etag, texte_final, json.dumps(lue, ensure_ascii=False), int(a_photo), iso(maintenant()), uid))
    c.oublier()
    diff = F.differences(avant, lue, photo=bool(photo))
    c.base.noter("ecriture", f"{origine} : {motif} écrite dans iCloud ({len(diff)} champ(s), {modifs_groupes} groupe(s))",
                 {"uid": uid, "champs": [d["champ"] for d in diff], "origine": origine})
    jeton = secrets.token_urlsafe(12)
    c.annulations[jeton] = {"uid": uid, "texte": ligne["texte"], "etag": etag, "groupes": groupes_avant,
                            "jusqua": time.monotonic() + DELAI_ANNULER}
    return {"uid": uid, "etag": etag, "jeton": jeton, "champs": diff, "groupes": modifs_groupes}


def creer(c: Carnet, fiche: dict, photo: tuple[bytes, str] | None = None, origine: str = "manuel") -> dict:
    """Nouvelle fiche dans iCloud (import, recréation)."""
    uid = str(uuid.uuid4()).upper()
    sauvegarde_du_jour(c)
    dav = c.icloud()
    try:
        href = dav.href_nouveau(uid)
        texte = carte(c, uid, fiche, photo, None)
        dav.ecrire(href, texte, None)
        relue = _relire_une(c, dav, uid, href)
        etag, texte_final = relue if relue else (dav.etag(href) or "", texte)
        _ecrire_groupes(c, dav, uid, [], sorted(set(fiche.get("groupes", []))))
    finally:
        dav.fermer()
    lue, a_photo = F.lire(texte_final, fiche.get("groupes", []), c.cfg.region)
    with c.base.transaction() as cx:
        cx.execute("INSERT INTO fiches(uid, href, etag, texte, fiche, photo, lu_le) VALUES (?,?,?,?,?,?,?)",
                   (uid, href, etag, texte_final, json.dumps(lue, ensure_ascii=False), int(a_photo), iso(maintenant())))
    c.oublier()
    c.base.noter("ecriture", f"{origine} : fiche créée dans iCloud", {"uid": uid, "origine": origine})
    return {"uid": uid, "etag": etag}


def recreer(c: Carnet, texte: str, href: str) -> dict:
    """Remet dans iCloud une carte supprimée sur l'iPhone, à l'identique (même UID)."""
    carte_ = synchro.analyser(href, "", texte)
    sauvegarde_du_jour(c)
    dav = c.icloud()
    try:
        dav.ecrire(href, texte, None)
        relue = _relire_une(c, dav, carte_.uid, href)
        etag, texte_final = relue if relue else (dav.etag(href) or "", texte)
    finally:
        dav.fermer()
    fiche, a_photo = F.lire(texte_final, [], c.cfg.region)
    with c.base.transaction() as cx:
        cx.execute("INSERT OR REPLACE INTO fiches(uid, href, etag, texte, fiche, photo, lu_le) VALUES (?,?,?,?,?,?,?)",
                   (carte_.uid, href, etag, texte_final, json.dumps(fiche, ensure_ascii=False), int(a_photo), iso(maintenant())))
    c.oublier()
    c.base.noter("ecriture", "Fiche supprimée sur l'iPhone recréée dans iCloud", {"uid": carte_.uid})
    return {"uid": carte_.uid}


def supprimer(c: Carnet, uid: str, origine: str = "fusion") -> None:
    """Suppression d'une carte : seulement à la demande (fusion), jamais la nuit."""
    ligne = c.base.un("SELECT * FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        return
    sauvegarde_du_jour(c)
    avant = json.loads(ligne["fiche"])
    dav = c.icloud()
    try:
        _ecrire_groupes(c, dav, uid, sorted(avant.get("groupes", [])), [])
        try:
            dav.supprimer(ligne["href"], ligne["etag"])
        except Conflit:
            raise ErreurCarnet("Ce contact vient d'être modifié sur l'iPhone : il n'a pas été supprimé. Relis iCloud.")
    finally:
        dav.fermer()
    with c.base.transaction() as cx:
        cx.execute("DELETE FROM fiches WHERE uid = ?", (uid,))
        cx.execute("DELETE FROM a_traiter WHERE uid = ?", (uid,))
    c.oublier()
    c.base.noter("ecriture", f"{origine} : fiche retirée d'iCloud", {"uid": uid, "origine": origine})


def _signaler_conflit(c: Carnet, dav, uid: str, ligne, fiche_voulue: dict) -> None:
    relue = dav.lire_une(ligne["href"])
    iphone = F.lire(relue.texte, json.loads(ligne["fiche"]).get("groupes", []), c.cfg.region)[0] if relue else None
    with c.base.transaction() as cx:
        traiter.ajouter(cx, "conflit", uid, uid, {"voulue": fiche_voulue, "iphone": iphone}, remplacer=True)
    c.base.noter("ecriture", "Conflit : carte modifiée sur l'iPhone, rien n'a été écrasé", {"uid": uid})


def _ecrire_groupes(c: Carnet, dav, uid: str, avant: list[str], apres: list[str]) -> int:
    """Met à jour les cartes de groupe d'iCloud (ajout ou retrait de ce membre). Retourne le
    nombre de cartes de groupe écrites."""
    ajoutes, retires = set(apres) - set(avant), set(avant) - set(apres)
    if not (ajoutes or retires):
        return 0
    actuels = _groupes_actuels(c)
    ecrites = 0
    for nom in sorted(ajoutes | retires):
        for essai in range(2):
            g = actuels.get(nom)
            membres = set(g["membres"]) if g else set()
            if nom in ajoutes:
                membres.add(uid)
            else:
                membres.discard(uid)
            if g is None:
                if nom in retires:
                    break
                guid = _uid_groupe(nom)
                href = dav.href_nouveau(guid)
                texte = synchro.carte_groupe(nom, guid, sorted(membres))
                dav.ecrire(href, texte, None)
                etag = dav.etag(href) or ""
                g = {"uid": guid, "href": href}
            else:
                texte = synchro.carte_groupe(nom, g["uid"], sorted(membres), g["texte"])
                try:
                    etag = dav.ecrire(g["href"], texte, g["etag"]) or dav.etag(g["href"]) or ""
                except Conflit:
                    if essai:
                        raise ErreurCarnet(f"Le groupe « {nom} » change en ce moment dans iCloud : réessaie.")
                    relue = dav.lire_une(g["href"])
                    if relue:
                        x = synchro.analyser(relue.href, relue.etag, relue.texte)
                        actuels[nom] = {**g, "etag": x.etag, "texte": x.texte, "membres": x.membres}
                    continue
            with c.base.transaction() as cx:
                cx.execute("INSERT OR REPLACE INTO groupes(uid, href, etag, nom, texte, membres) VALUES (?,?,?,?,?,?)",
                           (g["uid"], g["href"], etag, nom, texte, json.dumps(sorted(membres))))
            actuels[nom] = {"uid": g["uid"], "href": g["href"], "etag": etag, "texte": texte, "membres": sorted(membres)}
            ecrites += 1
            break
    return ecrites


def remettre(c: Carnet, uid: str, texte_avant: str, groupes_avant: list[str], motif: str) -> dict:
    """Remet une carte exactement comme elle était (photo comprise), groupes compris.
    La carte actuelle est contrôlée par If-Match : un changement sur l'iPhone n'est pas écrasé."""
    ligne = c.base.un("SELECT * FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        raise ErreurCarnet("Ce contact n'existe plus dans iCloud.")
    sauvegarde_du_jour(c)
    dav = c.icloud()
    try:
        try:
            dav.ecrire(ligne["href"], texte_avant, ligne["etag"])
        except Conflit:
            raise ErreurCarnet("La fiche vient d'être modifiée sur l'iPhone : rien n'a été remis.")
        relue = _relire_une(c, dav, uid, ligne["href"])
        actuels = json.loads(ligne["fiche"]).get("groupes", [])
        _ecrire_groupes(c, dav, uid, sorted(actuels), sorted(groupes_avant))
    finally:
        dav.fermer()
    etag, texte = relue if relue else ("", texte_avant)
    fiche, a_photo = F.lire(texte, groupes_avant, c.cfg.region)
    with c.base.transaction() as cx:
        cx.execute("UPDATE fiches SET etag = ?, texte = ?, fiche = ?, photo = ? WHERE uid = ?",
                   (etag, texte, json.dumps(fiche, ensure_ascii=False), int(a_photo), uid))
    c.oublier()
    c.base.noter("ecriture", motif, {"uid": uid})
    return {"ok": True, "uid": uid}


def annuler(c: Carnet, jeton: str) -> dict:
    """Remet la carte telle qu'elle était avant la dernière écriture (10 s maximum)."""
    a = c.annulations.pop(jeton, None)
    if not a or a["jusqua"] < time.monotonic():
        raise ErreurCarnet("Trop tard pour annuler : modifie la fiche à nouveau si besoin.")
    ligne = c.base.un("SELECT etag FROM fiches WHERE uid = ?", (a["uid"],))
    if not ligne or ligne["etag"] != a["etag"]:
        raise ErreurCarnet("La fiche a changé depuis : annulation impossible sans risque.")
    return remettre(c, a["uid"], a["texte"], a["groupes"], "Écriture annulée : fiche remise comme avant")


# ================================================================ restauration

def liste_sauvegardes(c: Carnet) -> list[dict]:
    dossier = c.cfg.sauvegardes
    if not dossier.is_dir():
        return []
    return [{"nom": f.name, "taille": f.stat().st_size} for f in sorted(dossier.glob("icloud-*.vcf"), reverse=True)]


def _fichier(c: Carnet, nom: str) -> Path:
    if not re.fullmatch(r"icloud-[\w-]+\.vcf", nom or ""):
        raise ErreurCarnet("Nom de sauvegarde invalide.")
    chemin = c.cfg.sauvegardes / nom
    if not chemin.is_file():
        raise ErreurCarnet("Sauvegarde introuvable.")
    return chemin


def contenu_sauvegarde(c: Carnet, nom: str) -> list[dict]:
    """Cartes d'une sauvegarde, comparées à iCloud : identique, différente ou absente."""
    texte = _fichier(c, nom).read_text(encoding="utf-8")
    actuelles = {l["uid"]: l["texte"] for l in c.base.tous("SELECT uid, texte FROM fiches")}
    res = []
    for bloc in re.findall(r"BEGIN:VCARD.*?END:VCARD\r?\n?", texte, flags=re.S | re.I):
        x = synchro.analyser("", "", bloc)
        if x.groupe:
            continue
        actuelle = actuelles.get(x.uid)
        etat = "absente" if actuelle is None else ("identique" if synchro.empreinte(actuelle) == synchro.empreinte(bloc)
                                                   else "differente")
        res.append({"uid": x.uid, "nom": x.nom, "etat": etat})
    return sorted(res, key=lambda r: r["nom"].casefold())


def restaurer(c: Carnet, nom: str, uids: list[str]) -> dict:
    """Remet dans iCloud les cartes choisies, telles qu'elles étaient dans la sauvegarde
    (verrou d'écriture déjà pris). Une copie de l'état actuel est faite d'abord."""
    texte = _fichier(c, nom).read_text(encoding="utf-8")
    voulues = set(uids)
    blocs = {}
    for bloc in re.findall(r"BEGIN:VCARD.*?END:VCARD\r?\n?", texte, flags=re.S | re.I):
        x = synchro.analyser("", "", bloc)
        if not x.groupe and x.uid in voulues:
            blocs[x.uid] = bloc
    if not blocs:
        raise ErreurCarnet("Aucune des fiches choisies n'est dans cette sauvegarde.")
    sauvegarder(c, "avant-restauration")
    bilan = {"restaurees": 0, "recreees": 0, "erreurs": []}
    dav = c.icloud()
    try:
        for uid, bloc in blocs.items():
            ligne = c.base.un("SELECT href, etag FROM fiches WHERE uid = ?", (uid,))
            try:
                if ligne:
                    dav.ecrire(ligne["href"], bloc, ligne["etag"])
                    bilan["restaurees"] += 1
                else:
                    dav.ecrire(dav.href_nouveau(uid), bloc, None)
                    bilan["recreees"] += 1
            except (Conflit, ErreurICloud) as exc:
                bilan["erreurs"].append(f"{synchro.analyser('', '', bloc).nom} : {exc}")
    finally:
        dav.fermer()
    c.base.noter("restauration", f"Restauration depuis {nom} : {bilan['restaurees']} remise(s), "
                 f"{bilan['recreees']} recréée(s), {len(bilan['erreurs'])} erreur(s)", bilan)
    # La base reprend l'état réel d'iCloud ; les cartes restaurées ne sont pas signalées
    # comme « modifiées sur l'iPhone » : la restauration est ton geste
    relire(c, "après restauration")
    with c.base.transaction() as cx:
        for uid in blocs:
            cx.execute("DELETE FROM a_traiter WHERE uid = ? AND motif IN ('iphone_modifiee', 'iphone_nouvelle', 'iphone_supprimee')", (uid,))
    c.oublier()
    return bilan


__all__ = ["relire", "ecrire", "creer", "supprimer", "annuler", "restaurer", "sauvegarder", "timedelta"]

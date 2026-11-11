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
    bilan = _appliquer(c, contacts, groupes, appartenance, stockees, disparues, bool(reference), origine)
    if contacts:
        from . import attentes
        attentes.semer(c)   # premier démarrage de la 2.8 : tableau de départ des attentes
    return bilan


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


def reanalyser(c: Carnet) -> int:
    """Passage à la 2.8 : relit les cartes déjà en base avec la lecture d'aujourd'hui, pour que
    les champs nouveaux (service, prononciation, fête, mariage, décès) déjà présents dans iCloud
    soient connus sans attendre que la carte change. Rien n'est signalé, rien n'est écrit dans
    iCloud. Fait une seule fois."""
    if c.base.lire("analyse_28"):
        return 0
    changees = 0
    with c.base.transaction() as cx:
        for l in cx.execute("SELECT uid, texte, fiche FROM fiches").fetchall():
            avant = json.loads(l["fiche"])
            try:
                apres, _ = F.lire(l["texte"], avant.get("groupes", []), c.cfg.region)
            except Exception:  # noqa: BLE001 — carte illisible : laissée telle quelle
                continue
            if apres != avant:
                cx.execute("UPDATE fiches SET fiche = ? WHERE uid = ?", (json.dumps(apres, ensure_ascii=False), l["uid"]))
                changees += 1
    c.base.ecrire("analyse_28", True)
    c.oublier()
    return changees


# ================================================================ écriture

def _groupes_actuels(c: Carnet) -> dict[str, list[dict]]:
    """nom → cartes de groupe portant ce nom (iCloud permet deux groupes du même nom)."""
    res: dict[str, list[dict]] = {}
    for l in c.base.tous("SELECT * FROM groupes ORDER BY uid"):
        res.setdefault(l["nom"], []).append({"uid": l["uid"], "href": l["href"], "etag": l["etag"], "texte": l["texte"],
                                             "membres": json.loads(l["membres"])})
    return res


def carte(c: Carnet, uid: str, fiche: dict, photo: tuple[bytes, str] | None, texte_distant: str | None,
          avant: dict | None = None, forcer: set[str] | None = None) -> str:
    """Carte à écrire. Sur une carte existante, seules les propriétés des champs qui changent
    sont remplacées ; tout le reste de la carte iCloud est gardé à l'identique.
    Contrôle de taille : la photo est réduite si besoin, sinon l'écriture est refusée."""
    def assembler(image):
        nouvelle = export.vcard(fiche, uid, image)
        if not texte_distant:
            return nouvelle
        champs = ({d["champ"] for d in F.differences(avant or {}, fiche)} | (forcer or set())) - {"groupes"}
        if image:
            champs.add("photo")
        # Site dont seul le type a changé (LinkedIn, Facebook…) : sa ligne est réécrite
        from .normalisation import cle_site
        types_avant = {cle_site(x): x.get("type") for x in (avant or {}).get("sites", [])}
        retypes = {cle_site(x) for x in fiche.get("sites", [])
                   if cle_site(x) in types_avant and types_avant[cle_site(x)] != x.get("type")}
        partielle = synchro.assembler_partiel(nouvelle, texte_distant, champs, retypes)
        return synchro.remplacer_dates(partielle, fiche, champs)
    texte = assembler(photo)
    if len(texte.encode()) > TAILLE_MAX and photo:
        texte = assembler(images.alleger(photo, 50_000))
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


def _etag_sur(c: Carnet, dav, ligne) -> str:
    """ETag de la carte pour un If-Match : jamais vide (une écriture sans condition pourrait
    écraser l'iPhone). Relu dans iCloud s'il manque ; s'il a changé, c'est un conflit."""
    if ligne["etag"]:
        return ligne["etag"]
    relue = dav.lire_une(ligne["href"])
    if not relue or not relue.etag:
        raise ErreurCarnet("iCloud ne donne pas la version de cette carte : relis iCloud, puis réessaie.")
    if synchro.empreinte(relue.texte) != synchro.empreinte(ligne["texte"]):
        raise Conflit("Carte modifiée dans iCloud depuis la lecture.")
    return relue.etag


def _enregistrer(c: Carnet, uid: str, href: str, etag: str, texte: str, groupes: list[str]) -> dict:
    """La base suit iCloud aussitôt la carte écrite (avant de toucher aux groupes). Une fiche
    validée et à jour le reste : l'empreinte de validation suit l'écriture de carnet."""
    from . import completude
    fiche, a_photo = F.lire(texte, groupes, c.cfg.region)
    ancienne = c.base.un("SELECT fiche FROM fiches WHERE uid = ?", (uid,))
    with c.base.transaction() as cx:
        completude.suivre_ecriture(cx, uid, json.loads(ancienne["fiche"]) if ancienne else None, fiche)
        cx.execute("INSERT INTO fiches(uid, href, etag, texte, fiche, photo, lu_le) VALUES (?,?,?,?,?,?,?) "
                   "ON CONFLICT(uid) DO UPDATE SET href=excluded.href, etag=excluded.etag, texte=excluded.texte, "
                   "fiche=excluded.fiche, photo=excluded.photo, lu_le=excluded.lu_le",
                   (uid, href, etag, texte, json.dumps(fiche, ensure_ascii=False), int(a_photo), iso(maintenant())))
    c.oublier()
    return fiche


def _apres_ecriture(c: Carnet, dav, uid: str, href: str, texte_envoye: str, etag_put: str | None) -> tuple[str, str]:
    relue = dav.lire_une(href)
    if relue:
        return relue.etag, relue.texte
    return etag_put or dav.etag(href) or "", texte_envoye


def _maj_groupes(c: Carnet, dav, uid: str, avant: list[str], apres: list[str]) -> int:
    """Cartes de groupe mises à jour, puis groupes de la fiche dans la base."""
    n = _ecrire_groupes(c, dav, uid, avant, apres)
    if n or sorted(avant) != sorted(apres):
        ligne = c.base.un("SELECT fiche FROM fiches WHERE uid = ?", (uid,))
        if ligne:
            f = json.loads(ligne["fiche"])
            f["groupes"] = sorted(set(apres))
            c.base.executer("UPDATE fiches SET fiche = ? WHERE uid = ?", (json.dumps(f, ensure_ascii=False), uid))
            c.oublier()
    return n


def ecrire(c: Carnet, uid: str, fiche: dict, photo: tuple[bytes, str] | None = None,
           origine: str = "manuel", motif: str = "modification", etag_vu: str | None = None,
           forcer: set[str] | None = None) -> dict:
    """Écrit une fiche existante dans iCloud (verrou d'écriture déjà pris).
    forcer : champs réécrits même s'ils semblent identiques (mise en forme de la carte).
    etag_vu : version que l'interface avait affichée ; si la carte a changé depuis (relue la nuit
    après une modification sur l'iPhone), rien n'est écrit et les deux versions vont en conflit.
    Renvoie {etag, jeton} ; jeton sert à « Annuler » pendant 10 s."""
    c.exiger_ecriture("iCloud")
    ligne = c.base.un("SELECT * FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        raise ErreurCarnet("Ce contact n'existe plus dans iCloud : relis iCloud avant de le modifier.")
    avant = json.loads(ligne["fiche"])
    if etag_vu is not None and etag_vu != ligne["etag"]:
        with c.base.transaction() as cx:
            traiter.ajouter(cx, "conflit", uid, uid, {"voulue": fiche, "iphone": avant}, remplacer=True)
        raise ErreurCarnet("Cette fiche a changé sur l'iPhone depuis que tu l'as ouverte : rien n'a été écrasé. "
                           "Les deux versions t'attendent dans « À traiter ».")
    sauvegarde_du_jour(c)
    texte = carte(c, uid, fiche, photo, ligne["texte"], avant, forcer)
    groupes_avant = sorted(avant.get("groupes", []))
    dav = c.icloud()
    try:
        try:
            etag_put = dav.ecrire(ligne["href"], texte, _etag_sur(c, dav, ligne))
        except Conflit:
            _signaler_conflit(c, dav, uid, ligne, fiche)
            raise ErreurCarnet("Ce contact vient d'être modifié sur l'iPhone : rien n'a été écrasé. "
                               "Les deux versions t'attendent dans « À traiter ».")
        etag, texte_final = _apres_ecriture(c, dav, uid, ligne["href"], texte, etag_put)
        lue = _enregistrer(c, uid, ligne["href"], etag, texte_final, groupes_avant)
        c.annulations[jeton := secrets.token_urlsafe(12)] = {
            "uid": uid, "texte": ligne["texte"], "etag": etag, "groupes": groupes_avant,
            "jusqua": time.monotonic() + DELAI_ANNULER}
        modifs_groupes = _maj_groupes(c, dav, uid, groupes_avant, sorted(set(fiche.get("groupes", []))))
    finally:
        dav.fermer()
    diff = F.differences(avant, dict(lue, groupes=sorted(set(fiche.get("groupes", [])))), photo=bool(photo))
    c.base.noter("ecriture", f"{origine} : {motif} écrite dans iCloud ({len(diff)} champ(s), {modifs_groupes} groupe(s))",
                 {"uid": uid, "champs": [d["champ"] for d in diff], "origine": origine})
    return {"uid": uid, "etag": etag, "jeton": jeton, "champs": diff, "groupes": modifs_groupes}


def creer(c: Carnet, fiche: dict, photo: tuple[bytes, str] | None = None, origine: str = "manuel") -> dict:
    """Nouvelle fiche dans iCloud (import)."""
    c.exiger_ecriture("iCloud")
    uid = str(uuid.uuid4()).upper()
    sauvegarde_du_jour(c)
    dav = c.icloud()
    try:
        href = dav.href_nouveau(uid)
        texte = carte(c, uid, fiche, photo, None)
        etag_put = dav.ecrire(href, texte, None)
        etag, texte_final = _apres_ecriture(c, dav, uid, href, texte, etag_put)
        _enregistrer(c, uid, href, etag, texte_final, [])
        _maj_groupes(c, dav, uid, [], sorted(set(fiche.get("groupes", []))))
    finally:
        dav.fermer()
    c.base.noter("ecriture", f"{origine} : fiche créée dans iCloud", {"uid": uid, "origine": origine})
    return {"uid": uid, "etag": etag}


def recreer(c: Carnet, texte: str, href: str, groupes: list[str]) -> dict:
    """Remet dans iCloud une carte supprimée sur l'iPhone, à l'identique (même UID, mêmes groupes)."""
    c.exiger_ecriture("iCloud")
    carte_ = synchro.analyser(href, "", texte)
    sauvegarde_du_jour(c)
    dav = c.icloud()
    try:
        etag_put = dav.ecrire(href, texte, None)
        etag, texte_final = _apres_ecriture(c, dav, carte_.uid, href, texte, etag_put)
        _enregistrer(c, carte_.uid, href, etag, texte_final, [])
        _maj_groupes(c, dav, carte_.uid, [], sorted(set(groupes)))
    finally:
        dav.fermer()
    c.base.noter("ecriture", "Fiche supprimée sur l'iPhone recréée dans iCloud", {"uid": carte_.uid})
    return {"uid": carte_.uid}


def supprimer(c: Carnet, uid: str, origine: str = "fusion") -> None:
    """Suppression d'une carte : seulement à la demande (fusion), jamais la nuit. La carte est
    supprimée d'abord ; les groupes ne sont nettoyés qu'ensuite."""
    c.exiger_ecriture("iCloud")
    ligne = c.base.un("SELECT * FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        return
    sauvegarde_du_jour(c)
    avant = json.loads(ligne["fiche"])
    dav = c.icloud()
    try:
        try:
            dav.supprimer(ligne["href"], _etag_sur(c, dav, ligne))
        except Conflit:
            raise ErreurCarnet("Ce contact vient d'être modifié sur l'iPhone : il n'a pas été supprimé. Relis iCloud.")
        with c.base.transaction() as cx:
            cx.execute("DELETE FROM fiches WHERE uid = ?", (uid,))
            cx.execute("DELETE FROM a_traiter WHERE uid = ?", (uid,))
        c.oublier()
        _ecrire_groupes(c, dav, uid, sorted(avant.get("groupes", [])), [])
    finally:
        dav.fermer()
    c.base.noter("ecriture", f"{origine} : fiche retirée d'iCloud", {"uid": uid, "origine": origine})


def _signaler_conflit(c: Carnet, dav, uid: str, ligne, fiche_voulue: dict) -> None:
    relue = dav.lire_une(ligne["href"])
    iphone = F.lire(relue.texte, json.loads(ligne["fiche"]).get("groupes", []), c.cfg.region)[0] if relue else None
    with c.base.transaction() as cx:
        traiter.ajouter(cx, "conflit", uid, uid, {"voulue": fiche_voulue, "iphone": iphone}, remplacer=True)
    c.base.noter("ecriture", "Conflit : carte modifiée sur l'iPhone, rien n'a été écrasé", {"uid": uid})


def _ecrire_groupes(c: Carnet, dav, uid: str, avant: list[str], apres: list[str]) -> int:
    """Met à jour les cartes de groupe d'iCloud (ajout ou retrait de ce membre). Retourne le
    nombre de cartes de groupe écrites. Deux groupes du même nom : le membre est retiré de tous,
    ajouté au premier."""
    ajoutes, retires = set(apres) - set(avant), set(avant) - set(apres)
    if not (ajoutes or retires):
        return 0
    actuels = _groupes_actuels(c)
    ecrites = 0
    for nom in sorted(ajoutes | retires):
        cartes = actuels.get(nom) or []
        if nom in ajoutes:
            cibles = [g for g in cartes if uid in g["membres"]][:1] or cartes[:1]
            if not cibles:
                guid = _uid_groupe(nom)
                href = dav.href_nouveau(guid)
                texte = synchro.carte_groupe(nom, guid, [uid])
                etag = dav.ecrire(href, texte, None) or dav.etag(href) or ""
                c.base.executer("INSERT OR REPLACE INTO groupes(uid, href, etag, nom, texte, membres) VALUES (?,?,?,?,?,?)",
                                (guid, href, etag, nom, texte, json.dumps([uid])))
                ecrites += 1
                continue
        else:
            cibles = [g for g in cartes if uid in g["membres"]]
        for g in cibles:
            for essai in range(2):
                membres = set(g["membres"])
                if nom in ajoutes:
                    membres.add(uid)
                else:
                    membres.discard(uid)
                if membres == set(g["membres"]):
                    break
                texte = synchro.carte_groupe(nom, g["uid"], sorted(membres), g["texte"])
                try:
                    if not g["etag"]:
                        raise Conflit("ETag inconnu")
                    etag = dav.ecrire(g["href"], texte, g["etag"]) or dav.etag(g["href"]) or ""
                except Conflit:
                    relue = dav.lire_une(g["href"])
                    if essai or not relue:
                        raise ErreurCarnet(f"Le groupe « {nom} » change en ce moment dans iCloud : réessaie.")
                    x = synchro.analyser(relue.href, relue.etag, relue.texte)
                    g = {**g, "etag": x.etag, "texte": x.texte, "membres": x.membres}
                    continue
                c.base.executer("INSERT OR REPLACE INTO groupes(uid, href, etag, nom, texte, membres) VALUES (?,?,?,?,?,?)",
                                (g["uid"], g["href"], etag, nom, texte, json.dumps(sorted(membres))))
                ecrites += 1
                break
    return ecrites


def remettre(c: Carnet, uid: str, texte_avant: str, groupes_avant: list[str], motif: str) -> dict:
    """Remet une carte exactement comme elle était (photo comprise), groupes compris.
    La carte actuelle est contrôlée par If-Match : un changement sur l'iPhone n'est pas écrasé."""
    c.exiger_ecriture("iCloud")
    ligne = c.base.un("SELECT * FROM fiches WHERE uid = ?", (uid,))
    if not ligne:
        raise ErreurCarnet("Ce contact n'existe plus dans iCloud.")
    sauvegarde_du_jour(c)
    actuels = sorted(json.loads(ligne["fiche"]).get("groupes", []))
    dav = c.icloud()
    try:
        try:
            etag_put = dav.ecrire(ligne["href"], texte_avant, _etag_sur(c, dav, ligne))
        except Conflit:
            raise ErreurCarnet("La fiche vient d'être modifiée sur l'iPhone : rien n'a été remis.")
        etag, texte = _apres_ecriture(c, dav, uid, ligne["href"], texte_avant, etag_put)
        _enregistrer(c, uid, ligne["href"], etag, texte, actuels)
        _maj_groupes(c, dav, uid, actuels, sorted(groupes_avant))
    finally:
        dav.fermer()
    c.base.noter("ecriture", motif, {"uid": uid})
    return {"ok": True, "uid": uid}


def annuler(c: Carnet, jeton: str) -> dict:
    """Remet la carte telle qu'elle était avant la dernière écriture (10 s maximum)."""
    a = c.annulations.pop(jeton, None)
    if not a or a["jusqua"] < time.monotonic():
        raise ErreurCarnet("Trop tard pour annuler : modifie la fiche à nouveau si besoin.")
    if a.get("supprimee"):
        # Suppression demandée sur la fiche (2.8) : la carte revient à l'identique, avec ce que
        # carnet savait d'elle (liaisons, exceptions, validation)
        if c.base.un("SELECT 1 FROM fiches WHERE uid = ?", (a["uid"],)):
            raise ErreurCarnet("Cette fiche existe de nouveau : rien à remettre.")
        res = recreer(c, a["texte"], a["href"], a["groupes"])
        with c.base.transaction() as cx:
            for table, lignes in a["memoire"].items():
                for l in lignes:
                    cles = list(l)
                    cx.execute(f"INSERT OR IGNORE INTO {table}({', '.join(cles)}) VALUES ({', '.join('?' * len(cles))})",
                               tuple(l[k] for k in cles))
        c.oublier()
        c.base.noter("ecriture", "Suppression annulée : fiche remise dans iCloud", {"uid": a["uid"]})
        return res
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
    c.exiger_ecriture("iCloud")
    texte = _fichier(c, nom).read_text(encoding="utf-8")
    voulues = set(uids)
    blocs, groupes_sauves = {}, {}
    for bloc in re.findall(r"BEGIN:VCARD.*?END:VCARD\r?\n?", texte, flags=re.S | re.I):
        x = synchro.analyser("", "", bloc)
        if x.groupe:
            for m in x.membres:
                groupes_sauves.setdefault(m, set()).add(x.nom)
        elif x.uid in voulues:
            blocs[x.uid] = bloc
    if not blocs:
        raise ErreurCarnet("Aucune des fiches choisies n'est dans cette sauvegarde.")
    sauvegarder(c, "avant-restauration")
    bilan = {"restaurees": 0, "recreees": 0, "erreurs": []}
    dav = c.icloud()
    try:
        for uid, bloc in blocs.items():
            ligne = c.base.un("SELECT href, etag, texte FROM fiches WHERE uid = ?", (uid,))
            try:
                if ligne:
                    dav.ecrire(ligne["href"], bloc, _etag_sur(c, dav, ligne))
                    bilan["restaurees"] += 1
                else:
                    dav.ecrire(dav.href_nouveau(uid), bloc, None)
                    bilan["recreees"] += 1
            except (Conflit, ErreurICloud, ErreurCarnet) as exc:
                bilan["erreurs"].append(f"{synchro.analyser('', '', bloc).nom} : {exc}")
                blocs[uid] = None
    finally:
        dav.fermer()
    c.base.noter("restauration", f"Restauration depuis {nom} : {bilan['restaurees']} remise(s), "
                 f"{bilan['recreees']} recréée(s), {len(bilan['erreurs'])} erreur(s)", bilan)
    # La base reprend l'état réel d'iCloud ; les cartes restaurées ne sont pas signalées
    # comme « modifiées sur l'iPhone » : la restauration est ton geste
    relire(c, "après restauration")
    remises = [u for u, b in blocs.items() if b]
    dav = c.icloud()
    try:
        for uid in remises:
            ligne = c.base.un("SELECT fiche FROM fiches WHERE uid = ?", (uid,))
            if ligne:
                _maj_groupes(c, dav, uid, sorted(json.loads(ligne["fiche"]).get("groupes", [])),
                             sorted(groupes_sauves.get(uid, set())))
    finally:
        dav.fermer()
    with c.base.transaction() as cx:
        for uid in remises:
            cx.execute("DELETE FROM a_traiter WHERE uid = ? AND motif IN ('iphone_modifiee', 'iphone_nouvelle', 'iphone_supprimee')", (uid,))
    c.oublier()
    return bilan


__all__ = ["relire", "ecrire", "creer", "supprimer", "annuler", "restaurer", "sauvegarder", "timedelta"]

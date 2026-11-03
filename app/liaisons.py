"""Liaisons entre les fiches et les personnes d'Immich (visages) et de Treemich (arbre).

- liaison sûre (faite seule la nuit) : même nom, unique des deux côtés, même date de naissance
  complète ; la personne Treemich suit si elle est reliée à ce visage dans Treemich ;
- liaison approchante (nom proche ≥ 80 %) : proposée dans « À traiter » ;
- une personne Immich ou Treemich n'est liée qu'à une seule fiche ; « Pas lui » et « Délier »
  la refusent pour cette fiche, définitivement.
Les données d'Immich et de Treemich sont gardées 26 h (Treemich limite le nombre d'appels).
"""
from __future__ import annotations

import logging
from collections import defaultdict

from rapidfuzz import fuzz

from .carnet import Carnet, ErreurCarnet
from .liens import ErreurLien, relations_de
from .modele import nom_affiche
from .normalisation import cle_texte
from .temps import iso, maintenant

log = logging.getLogger("carnet")
DUREE_CACHE = 26 * 3600
SEUIL_PROCHE = 80


def donnees(c: Carnet, rafraichir: bool = False) -> dict:
    """{immich: [...], treemich: [...], relations: [...], naissances_treemich: {id: date}, erreurs: [...]}."""
    if rafraichir:
        c.oublier("liens")

    def calcul():
        res = {"immich": [], "treemich": [], "relations": [], "naissances_treemich": {}, "erreurs": [],
               "le": iso(maintenant())}
        if c.cfg.immich_cle:
            im = c.immich()
            try:
                res["immich"] = im.personnes()
            except ErreurLien as exc:
                res["erreurs"].append(str(exc))
            finally:
                im.fermer()
        if c.cfg.treemich_email:
            try:
                tm = c.treemich()
                res["treemich"] = tm.personnes()
                res["relations"] = tm.relations()
                lies = {l["ext_id"] for l in c.base.tous("SELECT ext_id FROM liaisons WHERE service = 'treemich'")}
                for p in res["treemich"]:
                    if p["id"] in lies:   # dates lues seulement pour les personnes liées (Treemich limite les appels)
                        try:
                            res["naissances_treemich"][p["id"]] = tm.naissance(p["id"])
                        except ErreurLien as exc:
                            res["erreurs"].append(str(exc))
                            break
            except ErreurLien as exc:
                res["erreurs"].append(str(exc))
        return res
    return c.memo("liens", calcul, duree=DUREE_CACHE)


def _refus(c: Carnet) -> set[tuple[str, str, str]]:
    return {(l["uid"], l["service"], l["ext_id"]) for l in c.base.tous("SELECT * FROM refus")}


def _date_complete(texte: str) -> str:
    t = (texte or "")[:10]
    return t if len(t) == 10 and t[4] == "-" and not t.startswith("--") else ""


def sures(c: Carnet, d: dict | None = None) -> list[dict]:
    """Liaisons Immich exactes, pas encore faites : [{uid, immich, treemich|None}]."""
    d = d or donnees(c)
    fiches = c.fiches()
    liees = c.liaisons()
    pris_immich = {v["immich"] for v in liees.values() if v.get("immich")}
    refus = _refus(c)
    par_nom_fiche: dict[str, list[str]] = defaultdict(list)
    for uid, f in fiches.items():
        par_nom_fiche[cle_texte(nom_affiche(f))].append(uid)
    par_nom_immich: dict[str, list[dict]] = defaultdict(list)
    for p in d["immich"]:
        par_nom_immich[cle_texte(p["nom"])].append(p)
    tree_par_immich = {p["immich"]: p for p in d["treemich"] if p.get("immich")}
    pris_tree = {v["treemich"] for v in liees.values() if v.get("treemich")}
    res = []
    for cle, personnes in par_nom_immich.items():
        uids = par_nom_fiche.get(cle, [])
        if len(personnes) != 1 or len(uids) != 1 or not cle:
            continue
        p, uid = personnes[0], uids[0]
        if liees.get(uid, {}).get("immich") or p["id"] in pris_immich or (uid, "immich", p["id"]) in refus:
            continue
        date_fiche, date_immich = _date_complete(fiches[uid].get("anniversaire", "")), _date_complete(p.get("naissance", ""))
        if not date_fiche or date_fiche != date_immich:
            continue
        t = tree_par_immich.get(p["id"])
        treemich = t["id"] if t and t["id"] not in pris_tree and (uid, "treemich", t["id"]) not in refus \
            and not liees.get(uid, {}).get("treemich") else None
        res.append({"uid": uid, "immich": p["id"], "treemich": treemich})
    return res


def lier(c: Carnet, uid: str, service: str, ext_id: str, statut: str = "confirmee") -> None:
    if service not in ("immich", "treemich"):
        raise ErreurCarnet("Service inconnu.")
    deja = c.base.un("SELECT uid FROM liaisons WHERE service = ? AND ext_id = ?", (service, ext_id))
    if deja and deja["uid"] != uid:
        nom = nom_affiche(c.fiches().get(deja["uid"], {})) if deja["uid"] in c.fiches() else "un autre contact"
        raise ErreurCarnet(f"Cette personne est déjà liée à {nom} : délie-la d'abord.")
    with c.base.transaction() as cx:
        cx.execute("INSERT OR REPLACE INTO liaisons(uid, service, ext_id, statut, le) VALUES (?,?,?,?,?)",
                   (uid, service, ext_id, statut, iso(maintenant())))
        cx.execute("DELETE FROM refus WHERE uid = ? AND service = ? AND ext_id = ?", (uid, service, ext_id))
        cx.execute("DELETE FROM a_traiter WHERE motif = 'liaison' AND uid = ?", (uid,))
    c.oublier()


def delier(c: Carnet, uid: str, service: str) -> None:
    """Défait une liaison ; la même personne n'est plus jamais proposée pour cette fiche."""
    ligne = c.base.un("SELECT ext_id FROM liaisons WHERE uid = ? AND service = ?", (uid, service))
    if not ligne:
        return
    with c.base.transaction() as cx:
        cx.execute("DELETE FROM liaisons WHERE uid = ? AND service = ?", (uid, service))
        cx.execute("INSERT OR IGNORE INTO refus(uid, service, ext_id) VALUES (?,?,?)", (uid, service, ligne["ext_id"]))
    c.oublier()


def refuser(c: Carnet, uid: str, service: str, ext_id: str) -> None:
    c.base.executer("INSERT OR IGNORE INTO refus(uid, service, ext_id) VALUES (?,?,?)", (uid, service, ext_id))
    c.oublier()


def proches(c: Carnet, uid: str, d: dict | None = None) -> list[dict]:
    """Personnes Immich et Treemich au nom proche d'une fiche (pour « Lier » dans la fiche)."""
    d = d or donnees(c)
    f = c.fiches().get(uid)
    if not f:
        return []
    nom = cle_texte(nom_affiche(f))
    liees = c.liaisons()
    pris = {(s, v[s]) for v in liees.values() for s in ("immich", "treemich") if v.get(s)}
    refus = _refus(c)
    res = []
    for service in ("immich", "treemich"):
        for p in d[service]:
            score = fuzz.token_sort_ratio(nom, cle_texte(p["nom"]))
            if score < SEUIL_PROCHE or (service, p["id"]) in pris or (uid, service, p["id"]) in refus:
                continue
            res.append({"service": service, "id": p["id"], "nom": p["nom"], "score": round(score),
                        "naissance": p.get("naissance") or d["naissances_treemich"].get(p["id"], "")})
    return sorted(res, key=lambda x: -x["score"])[:6]


def propositions(c: Carnet, d: dict | None = None) -> list[dict]:
    """Liaisons approchantes pour les fiches pas encore liées à Immich (une par fiche, la meilleure)."""
    d = d or donnees(c)
    if not d["immich"]:
        return []
    fiches = c.fiches()
    liees = c.liaisons()
    sures_uids = {s["uid"] for s in sures(c, d)}
    pris = {v["immich"] for v in liees.values() if v.get("immich")}
    refus = _refus(c)
    index: dict[str, list[dict]] = defaultdict(list)
    for p in d["immich"]:
        if p["id"] not in pris:
            for mot in cle_texte(p["nom"]).split():
                if len(mot) >= 3:
                    index[mot].append(p)
    res = []
    for uid, f in fiches.items():
        if liees.get(uid, {}).get("immich") or uid in sures_uids:
            continue
        nom = cle_texte(nom_affiche(f))
        candidats = {p["id"]: p for mot in nom.split() for p in index.get(mot, [])}
        meilleur = None
        for p in candidats.values():
            if (uid, "immich", p["id"]) in refus:
                continue
            score = fuzz.token_sort_ratio(nom, cle_texte(p["nom"]))
            if score >= SEUIL_PROCHE and (not meilleur or score > meilleur["score"]):
                meilleur = {"id": p["id"], "nom": p["nom"], "score": round(score), "naissance": p.get("naissance", "")}
        if meilleur:
            res.append({"uid": uid, "immich": meilleur})
    return res


def dates(c: Carnet, d: dict | None = None) -> list[dict]:
    """Dates de naissance qui diffèrent entre la fiche, Immich et Treemich (fiches liées)."""
    d = d or donnees(c)
    im = {p["id"]: p for p in d["immich"]}
    res = []
    for uid, lien in c.liaisons().items():
        f = c.fiches().get(uid)
        if not f:
            continue
        valeurs = {"carnet": f.get("anniversaire", "")}
        if lien.get("immich") and lien["immich"] in im:
            valeurs["immich"] = (im[lien["immich"]].get("naissance") or "")[:10]
        if lien.get("treemich") and lien["treemich"] in d["naissances_treemich"]:
            valeurs["treemich"] = d["naissances_treemich"][lien["treemich"]]
        connues = {v for v in valeurs.values() if v}
        if len(valeurs) < 2 or not connues:
            continue
        # Fiche sans date et une seule valeur connue ailleurs : écrite seule la nuit
        if not valeurs["carnet"] and len(connues) == 1 and len(next(iter(connues))) == 10:
            continue
        if len(connues) > 1 or any(not v for v in valeurs.values()):
            res.append({"uid": uid, "valeurs": valeurs})
    return res


def dates_manquantes(c: Carnet, d: dict | None = None) -> list[dict]:
    """Fiches liées sans date de naissance, dont la date complète est connue sans conflit."""
    d = d or donnees(c)
    im = {p["id"]: p for p in d["immich"]}
    res = []
    for uid, lien in c.liaisons().items():
        f = c.fiches().get(uid)
        if not f or f.get("anniversaire"):
            continue
        connues = set()
        if lien.get("immich") and lien["immich"] in im:
            connues.add(_date_complete(im[lien["immich"]].get("naissance", "")))
        if lien.get("treemich"):
            connues.add(_date_complete(d["naissances_treemich"].get(lien["treemich"], "")))
        connues.discard("")
        if len(connues) == 1:
            res.append({"uid": uid, "date": connues.pop()})
    return res


def renommages(c: Carnet, d: dict | None = None) -> list[dict]:
    """Personnes liées dont le nom, dans Immich ou Treemich, n'est pas « Prénom NOM » de la fiche."""
    d = d or donnees(c)
    noms = {("immich", p["id"]): p["nom"] for p in d["immich"]}
    noms.update({("treemich", p["id"]): p["nom"] for p in d["treemich"]})
    res = []
    for uid, lien in c.liaisons().items():
        f = c.fiches().get(uid)
        if not f or not (f.get("prenom") or f.get("nom")):
            continue
        voulu = nom_affiche(f)
        for service in ("immich", "treemich"):
            actuel = noms.get((service, lien.get(service)))
            if lien.get(service) and actuel is not None and actuel != voulu:
                res.append({"uid": uid, "service": service, "id": lien[service], "actuel": actuel, "voulu": voulu})
    return res


def relations(c: Carnet, d: dict | None = None) -> list[dict]:
    """Liens familiaux de Treemich absents des noms associés de la fiche."""
    d = d or donnees(c)
    if not d["relations"]:
        return []
    genres = {p["id"]: p.get("genre", "") for p in d["treemich"]}
    uid_par_tree = {v["treemich"]: u for u, v in c.liaisons().items() if v.get("treemich")}
    fiches = c.fiches()
    res = []
    for uid, lien in c.liaisons().items():
        tid = lien.get("treemich")
        f = fiches.get(uid)
        if not tid or not f:
            continue
        presents = {cle_texte(n["valeur"]) for n in f.get("noms_associes", [])}
        manquants = []
        for autre, type_ in relations_de(tid, d["relations"], genres):
            autre_uid = uid_par_tree.get(autre)
            if autre_uid and autre_uid in fiches:
                nom = nom_affiche(fiches[autre_uid])
                if cle_texte(nom) not in presents:
                    manquants.append({"valeur": nom, "type": type_})
        if manquants:
            res.append({"uid": uid, "ajouts": manquants})
    return res


def _maj_cache(c: Carnet, service: str, ext_id: str, **champs) -> None:
    """Après une écriture dans Immich ou Treemich : les données gardées en mémoire sont mises à
    jour sur place (les relire entièrement coûterait des centaines d'appels à Treemich)."""
    d = c.memo_present("liens", DUREE_CACHE)
    if not d:
        return
    if service == "treemich" and "naissance" in champs:
        d["naissances_treemich"][ext_id] = champs.pop("naissance") or ""
    for p in d[service]:
        if p["id"] == ext_id:
            p.update(champs)


def ecrire_partout(c: Carnet, uid: str, date: str) -> list[str]:
    """Date de naissance tranchée : écrite dans Immich et Treemich (la fiche est écrite à part)."""
    lien = c.liaison(uid)
    faits = []
    if lien.get("immich"):
        im = c.immich()
        try:
            im.maj_naissance(lien["immich"], date or None)
            faits.append("Immich")
            _maj_cache(c, "immich", lien["immich"], naissance=date)
        finally:
            im.fermer()
    if lien.get("treemich"):
        c.treemich().maj_naissance(lien["treemich"], date or None)
        faits.append("Treemich")
        _maj_cache(c, "treemich", lien["treemich"], naissance=date)
    c.base.noter("liens", f"Date de naissance écrite dans {', '.join(faits) or 'aucun service'}", {"uid": uid})
    return faits


def renommer(c: Carnet, uid: str, service: str) -> str:
    f = c.fiche(uid)
    lien = c.liaison(uid)
    if not lien.get(service):
        raise ErreurCarnet("Ce contact n'est pas lié à ce service.")
    voulu = nom_affiche(f)
    if service == "immich":
        im = c.immich()
        try:
            im.renommer(lien["immich"], voulu)
        finally:
            im.fermer()
    else:
        c.treemich().renommer(lien["treemich"], f.get("prenom", ""), f.get("nom", ""))
    _maj_cache(c, service, lien[service], nom=voulu)
    c.base.noter("liens", f"Nom écrit dans {service.capitalize()}", {"uid": uid})
    return voulu

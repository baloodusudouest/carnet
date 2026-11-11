"""Ce que carnet écrit tout seul depuis la 2.8 : la fête, et les dates de famille (mariage, décès)
accordées avec Treemich.

Deux interrupteurs, éteints à la livraison : « fetes » et « famille ». Tant qu'un interrupteur est
éteint, rien n'est écrit et `apercu` dit ce qui le serait.

Dates de famille — remplir, jamais écraser :
- une date présente d'un côté et absente de l'autre est copiée ;
- deux dates différentes deviennent un point dans « À traiter » ;
- une date effacée d'un côté n'est jamais effacée de l'autre.
Le mariage vit sur le couple dans Treemich, et sur la carte de chaque conjoint relié dans iCloud.
Le divorce est seulement lu. Treemich n'a pas de sauvegarde côté carnet : chaque écriture
automatique est inscrite avec la valeur d'avant (table `automatiques`) et peut être défaite.
"""
from __future__ import annotations

from . import attentes, fetes, icloud, traiter
from .carddav import ErreurICloud
from .carnet import Carnet, ErreurCarnet
from .fiches import date_lisible
from .liens import ErreurLien
from .modele import nom_affiche
from .temps import iso, maintenant

INTERRUPTEURS = {"fetes": "Écrire les fêtes dans iCloud",
                 "famille": "Accorder mariages et décès avec Treemich"}
REVUE = ("iphone_modifiee", "iphone_nouvelle", "conflit")


# ----------------------------------------------------------------- interrupteurs

def actif(c: Carnet, quoi: str) -> bool:
    return bool(c.base.lire(f"auto_{quoi}", False))


def regler(c: Carnet, quoi: str, oui: bool) -> dict:
    if quoi not in INTERRUPTEURS:
        raise ErreurCarnet("Interrupteur inconnu.")
    c.base.ecrire(f"auto_{quoi}", bool(oui))
    c.base.noter("automatique", f"« {INTERRUPTEURS[quoi]} » : {'allumé' if oui else 'éteint'}")
    c.oublier()
    return {"ok": True, "actif": bool(oui)}


# ----------------------------------------------------------------- lecture de Treemich

def _complete(date: str) -> bool:
    return len(date or "") == 10


def _reliees(c: Carnet) -> dict[str, str]:
    """id Treemich → uid de la fiche reliée."""
    return {v["treemich"]: u for u, v in c.liaisons().items() if v.get("treemich") and u in c.fiches()}


def couples(d: dict) -> list[dict]:
    """Couples de l'arbre : [{a, b, mariage, divorce}] avec a < b."""
    vus: dict[tuple[str, str], dict] = {}
    for r in d.get("relations", []):
        if r.get("type") != "SPOUSE_OF" or r["de"] == r["vers"]:
            continue
        a, b = sorted((r["de"], r["vers"]))
        x = vus.setdefault((a, b), {"a": a, "b": b, "mariage": "", "divorce": ""})
        x["mariage"] = x["mariage"] or r.get("mariage", "")
        x["divorce"] = x["divorce"] or r.get("divorce", "")
    return list(vus.values())


def _treemich_parle(d: dict | None) -> bool:
    """Treemich a répondu en entier à la dernière lecture (sinon on garde le dernier état connu)."""
    return bool(d and d.get("treemich") and not d.get("erreurs"))


def memoriser(c: Carnet, d: dict | None) -> None:
    """Garde le dernier état lu dans Treemich : couples (mariage, divorce) et décès. Si Treemich
    n'a pas répondu, rien ne bouge : un décès connu reste connu, les annonces ne reprennent pas."""
    if not _treemich_parle(d):
        return
    maintenant_ = iso(maintenant())
    reliees = _reliees(c)
    with c.base.transaction() as cx:
        for x in couples(d):
            cx.execute("INSERT INTO unions(a, b, mariage, divorce, lu_le) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(a, b) DO UPDATE SET mariage = excluded.mariage, divorce = excluded.divorce, "
                       "lu_le = excluded.lu_le", (x["a"], x["b"], x["mariage"] or None, x["divorce"] or None, maintenant_))
        morts = {reliees[t]: date for t, date in d.get("deces_treemich", {}).items() if t in reliees}
        cx.execute("DELETE FROM deces WHERE origine = 'treemich'")
        for uid, date in morts.items():
            cx.execute("INSERT OR IGNORE INTO deces(uid, date, origine, le) VALUES (?,?,?,?)",
                       (uid, date if date != "inconnue" else None, "treemich", maintenant_))
    c.oublier("decedes")
    c.oublier("bilans")
    c.oublier("completude")
    c.oublier("contacts")


def divorces(c: Carnet) -> set[str]:
    """uid des fiches dont le couple est divorcé d'après le dernier état lu."""
    reliees = _reliees(c)
    res = set()
    for l in c.base.tous("SELECT a, b FROM unions WHERE divorce IS NOT NULL"):
        res |= {reliees[t] for t in (l["a"], l["b"]) if t in reliees}
    return res


def marquer_decede(c: Carnet, uid: str, oui: bool) -> dict:
    """Case « décédé(e) » d'une fiche quand la date n'est pas connue. Reste dans carnet."""
    c.fiche(uid)
    if oui:
        c.base.executer("INSERT OR IGNORE INTO deces(uid, date, origine, le) VALUES (?, NULL, 'main', ?)",
                        (uid, iso(maintenant())))
    else:
        c.base.executer("DELETE FROM deces WHERE uid = ? AND origine = 'main'", (uid,))
    c.oublier()
    return {"ok": True, "decede": uid in attentes.decedes(c)}


# ----------------------------------------------------------------- ce qui serait écrit

def _action(service: str, sujet: str, cible: str, uid: str | None, nom: str, avant: str, apres: str, **plus) -> dict:
    ou = "iCloud" if service == "icloud" else "Treemich"
    quoi = {"fete": "Fête", "mariage": "Mariage", "deces": "Décès"}[sujet]
    return {"service": service, "sujet": sujet, "cible": cible, "uid": uid, "nom": nom, "avant": avant, "apres": apres,
            "texte": f"{quoi} de {nom} : {date_lisible(apres)}, écrit dans {ou}", **plus}


def fetes_a_ecrire(c: Carnet) -> list[dict]:
    """Fiches dont un groupe attend la fête, qui n'en ont pas sur leur carte et dont le prénom est
    au calendrier. Une fête écrite par carnet suit le prénom s'il est corrigé ; une fête saisie
    à la main ne bouge jamais."""
    tableau, morts = attentes.par_groupe(c), attentes.decedes(c)
    ecrites = {l["cible"]: l["apres"] for l in c.base.tous(
        "SELECT cible, apres FROM automatiques WHERE sujet = 'fete' AND service = 'icloud' AND defaite IS NULL ORDER BY id")}
    res = []
    for uid, f in c.fiches().items():
        if uid in morts or "fete" not in attentes.attendues(f, tableau):
            continue
        calendrier = fetes.pour(f.get("prenom") or "")
        actuelle = f.get("fete") or ""
        if not calendrier or actuelle == calendrier:
            continue
        if actuelle and ecrites.get(uid) != actuelle:
            continue                                   # saisie à la main : on n'y touche pas
        res.append(_action("icloud", "fete", uid, uid, nom_affiche(f), actuelle, calendrier))
    return sorted(res, key=lambda x: x["nom"].casefold())


def _unions(c: Carnet) -> dict[tuple[str, str], dict]:
    return {(l["a"], l["b"]): dict(l) for l in c.base.tous("SELECT * FROM unions")}


def examiner(c: Carnet, d: dict | None) -> dict:
    """{actions, points} pour les dates de famille, d'après les fiches et la dernière lecture de
    Treemich. Sans réponse complète de Treemich : ni action ni point."""
    actions: list[dict] = []
    points: list[dict] = []
    if not _treemich_parle(d):
        return {"actions": actions, "points": points}
    fiches, reliees, memo = c.fiches(), _reliees(c), _unions(c)
    noms = {p["id"]: p["nom"] for p in d["treemich"]}
    for x in couples(d):
        uids = [reliees[t] for t in (x["a"], x["b"]) if t in reliees]
        if not uids:
            continue
        m = x["mariage"]
        if m and not _complete(m):
            continue                                   # date partielle dans l'arbre : on n'y touche pas
        cartes = {u: fiches[u].get("mariage") or "" for u in uids}
        valeurs = sorted({v for v in [m, *cartes.values()] if v})
        couple = " et ".join(noms.get(t, "?") for t in (x["a"], x["b"]))
        cle = f"{x['a']}|{x['b']}"
        if not valeurs:
            if not (memo.get((x["a"], x["b"])) or {}).get("sans") and not x["divorce"]:
                points.append({"motif": "mariage", "uid": uids[0], "cle": cle,
                               "donnees": {"a": x["a"], "b": x["b"], "couple": couple}})
        elif len(valeurs) == 1:
            date = valeurs[0]
            for u in uids:
                if not cartes[u]:
                    actions.append(_action("icloud", "mariage", u, u, nom_affiche(fiches[u]), "", date))
            if not m and _complete(date):
                actions.append(_action("treemich", "mariage", cle, uids[0], couple, "", date, a=x["a"], b=x["b"]))
        else:
            sources = ([{"source": "Treemich", "date": m}] if m else []) + \
                [{"source": f"iCloud ({nom_affiche(fiches[u])})", "date": v} for u, v in cartes.items() if v]
            points.append({"motif": "mariage_different", "uid": uids[0], "cle": f"{cle}|{traiter.empreinte(valeurs)}",
                           "donnees": {"a": x["a"], "b": x["b"], "couple": couple, "valeurs": sources}})
    for t, uid in reliees.items():
        arbre = d.get("deces_treemich", {}).get(t, "")
        carte = fiches[uid].get("deces") or ""
        nom = nom_affiche(fiches[uid])
        if _complete(arbre) and carte and carte != arbre:
            points.append({"motif": "deces_different", "uid": uid, "cle": f"{uid}|{traiter.empreinte([arbre, carte])}",
                           "donnees": {"treemich": t, "valeurs": [{"source": "Treemich", "date": arbre},
                                                                 {"source": "iCloud", "date": carte}]}})
        elif _complete(arbre) and not carte:
            actions.append(_action("icloud", "deces", uid, uid, nom, "", arbre))
        elif _complete(carte) and not arbre:
            actions.append(_action("treemich", "deces", t, uid, nom, "", carte))
    return {"actions": actions, "points": points}


def apercu(c: Carnet) -> dict:
    """Pour l'écran Réglages : par interrupteur, s'il est allumé et ce que carnet écrirait."""
    from . import liaisons
    d = c.memo_present("liens", liaisons.DUREE_CACHE)
    return {"fetes": {"nom": INTERRUPTEURS["fetes"], "actif": actif(c, "fetes"), "actions": fetes_a_ecrire(c)},
            "famille": {"nom": INTERRUPTEURS["famille"], "actif": actif(c, "famille"),
                        "actions": examiner(c, d)["actions"], "treemich": _treemich_parle(d)}}


# ----------------------------------------------------------------- écritures

def _noter(c: Carnet, a: dict) -> None:
    c.base.executer("INSERT INTO automatiques(le, service, sujet, cible, avant, apres) VALUES (?,?,?,?,?,?)",
                    (iso(maintenant()), a["service"], a["sujet"], a["cible"], a["avant"] or None, a["apres"]))


def _en_revue(c: Carnet) -> set[str]:
    return {l["uid"] for l in c.base.tous(f"SELECT uid FROM a_traiter WHERE motif IN {REVUE}")}


def _ecrire_cartes(c: Carnet, actions: list[dict], bilan: dict, plafond: int, motif: str) -> None:
    """Une seule écriture par fiche (fête, mariage et décès réunis), sous le plafond de la nuit."""
    par_uid: dict[str, list[dict]] = {}
    for a in actions:
        par_uid.setdefault(a["uid"], []).append(a)
    en_revue = _en_revue(c)
    for uid, lot in sorted(par_uid.items()):
        if uid in en_revue:
            continue                                   # fiche en attente de relecture : jamais touchée
        if bilan["ecrites"] >= plafond:
            bilan["reportees"] += 1
            continue
        f = c.fiches().get(uid)
        if not f:
            continue
        fiche = {k: v for k, v in f.items() if k != "a_photo"}
        faites = []
        for a in lot:
            if (fiche.get(a["sujet"]) or "") == a["avant"]:      # revérifié au moment d'écrire
                fiche[a["sujet"]] = a["apres"]
                faites.append(a)
        if not faites:
            continue
        try:
            icloud.ecrire(c, uid, fiche, origine="nuit", motif=motif)
            bilan["ecrites"] += 1
            for a in faites:
                _noter(c, a)
        except (ErreurCarnet, ErreurICloud) as exc:
            bilan["details"].append(str(exc))


def appliquer(c: Carnet, d: dict | None, bilan: dict, plafond: int) -> None:
    """La nuit, après les écritures sûres : fêtes puis dates de famille, si leur interrupteur est
    allumé. Verrou d'écriture déjà pris."""
    memoriser(c, d)
    if actif(c, "fetes"):
        _ecrire_cartes(c, fetes_a_ecrire(c), bilan, plafond, "fête")
    if not actif(c, "famille") or not _treemich_parle(d):
        return
    actions = examiner(c, d)["actions"]
    _ecrire_cartes(c, [a for a in actions if a["service"] == "icloud"], bilan, plafond, "date de famille")
    vers_treemich = [a for a in actions if a["service"] == "treemich"]
    if not vers_treemich:
        return
    tm = c.treemich()
    try:
        for a in vers_treemich:
            if a["sujet"] == "mariage":
                tm.maj_mariage(a["a"], a["b"], a["apres"])
            else:
                tm.maj_deces(a["cible"], a["apres"])
            _noter(c, a)
        # Relecture : la version de Treemich installée suit « latest », son interface peut changer.
        # Si ce qui revient n'est pas ce qui a été écrit, l'interrupteur est coupé.
        relues = {(x["a"], x["b"]): x["mariage"] for x in couples({"relations": tm.relations()})}
        for a in vers_treemich:
            lu = relues.get((a["a"], a["b"]), "") if a["sujet"] == "mariage" else tm.evenements(a["cible"])["deces"]
            if lu != a["apres"]:
                regler(c, "famille", False)
                message = (f"Treemich n'a pas rendu la date écrite ({a['texte']}) : l'accord des dates de famille "
                           "est coupé. Vérifie dans Treemich, puis rallume-le dans Réglages.")
                bilan["details"].append(message)
                c.base.noter("automatique", message)
                break
            if a["sujet"] == "mariage":
                for r in d["relations"]:
                    if r.get("type") == "SPOUSE_OF" and sorted((r["de"], r["vers"])) == [a["a"], a["b"]]:
                        r["mariage"] = a["apres"]
            else:
                d.setdefault("deces_treemich", {})[a["cible"]] = a["apres"]
    except ErreurLien as exc:
        bilan["details"].append(str(exc))
    memoriser(c, d)


# ----------------------------------------------------------------- réponses de Julien (À traiter)

def ecrire_partout(c: Carnet, sujet: str, date: str, uids: list[str], a: str | None = None, b: str | None = None,
                   treemich: str | None = None) -> dict:
    """Une date choisie par Julien, écrite des deux côtés (elle remplace ce qui s'y trouve)."""
    from .normalisation import anniversaire
    propre = anniversaire(date or "")
    if not _complete(propre):
        raise ErreurCarnet("Date non reconnue : écris par exemple 15/03/1985.")
    c.exiger_ecriture("iCloud")
    ecrites = 0
    with c.ecriture(attendre=5):
        for uid in uids:
            f = c.fiche(uid)
            if (f.get(sujet) or "") == propre:
                continue
            fiche = {k: v for k, v in f.items() if k != "a_photo"}
            fiche[sujet] = propre
            icloud.ecrire(c, uid, fiche, origine="À traiter", motif="date de mariage" if sujet == "mariage" else "date de décès")
            ecrites += 1
    from . import liaisons
    d = c.memo_present("liens", liaisons.DUREE_CACHE)
    try:
        tm = c.treemich()
        if sujet == "mariage" and a and b:
            tm.maj_mariage(a, b, propre)
            for r in (d or {}).get("relations", []):
                if r.get("type") == "SPOUSE_OF" and sorted((r["de"], r["vers"])) == [a, b]:
                    r["mariage"] = propre
        elif sujet == "deces" and treemich:
            tm.maj_deces(treemich, propre)
            if d is not None:
                d.setdefault("deces_treemich", {})[treemich] = propre
    except ErreurLien as exc:
        raise ErreurCarnet(f"Écrit dans iCloud ({ecrites} fiche(s)), mais pas dans Treemich : {exc}")
    memoriser(c, d)
    c.oublier()
    return {"ok": True, "date": propre, "fiches": ecrites}


def sans_union(c: Carnet, a: str, b: str, oui: bool = True) -> dict:
    """« Pas de mariage ni PACS » : la question n'est plus posée pour ce couple."""
    c.base.executer("INSERT INTO unions(a, b, sans, lu_le) VALUES (?,?,?,?) "
                    "ON CONFLICT(a, b) DO UPDATE SET sans = excluded.sans", (a, b, 1 if oui else 0, iso(maintenant())))
    c.oublier()
    return {"ok": True}


def sans_union_declaree(c: Carnet) -> set[str]:
    """uid des fiches d'un couple pour lequel Julien a répondu « pas de mariage ni PACS »."""
    reliees = _reliees(c)
    res = set()
    for l in c.base.tous("SELECT a, b FROM unions WHERE sans = 1"):
        res |= {reliees[t] for t in (l["a"], l["b"]) if t in reliees}
    return res


# ----------------------------------------------------------------- écrit par carnet tout seul

def journal(c: Carnet, limite: int = 200) -> list[dict]:
    fiches = c.fiches()
    res = []
    for l in c.base.tous("SELECT * FROM automatiques ORDER BY id DESC LIMIT ?", (limite,)):
        f = fiches.get(l["cible"])
        quoi = {"fete": "Fête", "mariage": "Mariage", "deces": "Décès"}.get(l["sujet"], l["sujet"])
        res.append({"id": l["id"], "le": l["le"], "service": l["service"], "sujet": l["sujet"],
                    "nom": nom_affiche(f) if f else ("un couple de l'arbre" if "|" in l["cible"] else "une personne de l'arbre"),
                    "uid": l["cible"] if f else None, "avant": l["avant"] or "", "apres": l["apres"] or "",
                    "texte": f"{quoi} : {date_lisible(l['apres'] or '')}"
                             + (f" (avant : {date_lisible(l['avant'])})" if l["avant"] else ""),
                    "defaite": l["defaite"]})
    return res


def defaire(c: Carnet, ident: int) -> dict:
    """Remet la valeur d'avant. Refusé si la valeur a changé depuis : carnet ne défait que ce
    qu'il a lui-même écrit."""
    l = c.base.un("SELECT * FROM automatiques WHERE id = ?", (ident,))
    if not l or l["defaite"]:
        raise ErreurCarnet("Cette écriture a déjà été défaite.")
    sujet, avant, apres = l["sujet"], l["avant"] or "", l["apres"] or ""
    if l["service"] == "icloud":
        with c.ecriture(attendre=5):
            f = c.fiche(l["cible"])
            if (f.get(sujet) or "") != apres:
                raise ErreurCarnet("Cette date a changé depuis : rien n'est défait. Corrige-la sur la fiche.")
            fiche = {k: v for k, v in f.items() if k != "a_photo"}
            fiche[sujet] = avant
            icloud.ecrire(c, l["cible"], fiche, origine="État", motif="écriture automatique défaite")
    else:
        from . import liaisons
        c.exiger_ecriture("Treemich")
        d = c.memo_present("liens", liaisons.DUREE_CACHE)
        try:
            tm = c.treemich()
            if sujet == "mariage":
                a, b = l["cible"].split("|", 1)
                tm.maj_mariage(a, b, avant or None)
                for r in (d or {}).get("relations", []):
                    if r.get("type") == "SPOUSE_OF" and sorted((r["de"], r["vers"])) == [a, b]:
                        r["mariage"] = avant
            else:
                tm.maj_deces(l["cible"], avant or None)
                if d is not None:
                    d.get("deces_treemich", {}).pop(l["cible"], None)
        except ErreurLien as exc:
            raise ErreurCarnet(str(exc))
        memoriser(c, d)
    c.base.executer("UPDATE automatiques SET defaite = ? WHERE id = ?", (iso(maintenant()), ident))
    # Défaire une fête ou une date de famille coupe son interrupteur : sinon la nuit la réécrirait
    regler(c, "fetes" if sujet == "fete" else "famille", False)
    c.oublier()
    return {"ok": True}


__all__ = ["INTERRUPTEURS", "actif", "regler", "apercu", "appliquer", "examiner", "memoriser", "fetes_a_ecrire",
           "ecrire_partout", "sans_union", "sans_union_declaree", "divorces", "marquer_decede", "journal", "defaire"]

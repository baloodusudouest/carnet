"""2.22 : le genre d'une personne (homme, femme, autre) et les liens familiaux accordés au genre.

Le genre n'est pas dans la carte iCloud (l'iPhone ne l'affiche pas) : il vit dans la base de carnet.
- Treemich → carnet : à chaque lecture de l'arbre, le genre des personnes reliées est repris, sauf
  si Julien l'a choisi lui-même dans carnet (origine « main », jamais écrasée).
- carnet → Treemich : un genre choisi dans carnet (femme, homme ou autre) est écrit dans l'arbre
  tout de suite s'il y est inconnu (aussi après une validation par lot ; la nuit rattrape les échecs).
  Remplir, jamais écraser tout seul.
- Désaccord (2.24.2) : quand le genre choisi dans carnet n'est pas celui de l'arbre, un point
  « Genre différent dans Treemich » demande lequel garder ; garder celui de carnet l'écrit dans
  l'arbre (seul cas où carnet écrase), prendre celui de l'arbre remplace le choix fait dans carnet.

Le genre décide du libellé d'un lien : frère / sœur / « frère ou sœur », père / mère / parent.
Un lien déjà écrit qui ne s'accorde pas devient une ligne dans « À traiter » ; carnet ne corrige
rien tout seul.
"""
from __future__ import annotations

from .carnet import Carnet, ErreurCarnet
from .liens import ErreurLien
from .modele import nom_affiche
from .normalisation import cle_texte
from .temps import iso, maintenant

GENRES = {"femme": "Femme", "homme": "Homme", "autre": "Autre"}
DE_TREEMICH = {"FEMALE": "femme", "MALE": "homme", "OTHER": "autre"}
VERS_TREEMICH = {v: k for k, v in DE_TREEMICH.items()}

FRATRIE_NEUTRE = "frère ou sœur"
FRATRIE = {"femme": "sœur", "homme": "frère", "autre": FRATRIE_NEUTRE}
PARENT = {"femme": "mère", "homme": "père", "autre": "parent"}
COUPE = "genre_treemich_coupe"      # vrai : Treemich n'a pas gardé un genre écrit, carnet n'en écrit plus


def accorde(type_: str, genre: str) -> str:
    """Le libellé qu'un lien doit porter pour une personne de ce genre (inchangé hors fratrie et parents)."""
    if genre not in GENRES:
        return type_
    if type_ in FRATRIE.values():
        return FRATRIE[genre]
    if type_ in PARENT.values():
        return PARENT[genre]
    return type_


# ----------------------------------------------------------------- lecture

def tous(c: Carnet) -> dict[str, dict]:
    """uid → {genre, origine} (« main » : choisi dans carnet ; « treemich » : lu dans l'arbre)."""
    return c.memo("genres", lambda: {l["uid"]: {"genre": l["genre"], "origine": l["origine"]}
                                     for l in c.base.tous("SELECT uid, genre, origine FROM genres")})


def de(c: Carnet, uid: str) -> str:
    return (tous(c).get(uid) or {}).get("genre", "")


def _reliees(c: Carnet) -> dict[str, str]:
    """id Treemich → uid de la fiche reliée."""
    return {v["treemich"]: u for u, v in c.liaisons().items() if v.get("treemich") and u in c.fiches()}


def _treemich_parle(d: dict | None) -> bool:
    if not d or not d.get("treemich"):
        return False
    return d["treemich_ok"] if "treemich_ok" in d else not d.get("erreurs")


def memoriser(c: Carnet, d: dict | None) -> None:
    """Après une lecture complète de Treemich : le genre des personnes reliées est repris. Un genre
    choisi dans carnet reste tel quel."""
    if not _treemich_parle(d):
        return
    reliees = _reliees(c)
    lus = {reliees[p["id"]]: DE_TREEMICH[p["genre"]] for p in d["treemich"]
           if p["id"] in reliees and p.get("genre") in DE_TREEMICH}
    le = iso(maintenant())
    with c.base.transaction() as cx:
        cx.execute("DELETE FROM genres WHERE origine = 'treemich'")
        for uid, genre in lus.items():
            cx.execute("INSERT OR IGNORE INTO genres(uid, genre, origine, le) VALUES (?,?,'treemich',?)", (uid, genre, le))
    c.oublier("genres")


def par_treemich(c: Carnet, d: dict) -> dict[str, str]:
    """id Treemich → genre retenu par carnet (celui de la fiche reliée, sinon celui de l'arbre)."""
    connus, reliees = tous(c), _reliees(c)
    res = {}
    for p in d.get("treemich", []):
        uid = reliees.get(p["id"])
        res[p["id"]] = (connus.get(uid) or {}).get("genre") or DE_TREEMICH.get(p.get("genre", ""), "")
    return res


def fiche(c: Carnet, uid: str) -> dict:
    """Pour l'écran de la fiche : le genre retenu, d'où il vient, et ce que dit Treemich s'il dit autre chose."""
    from . import liaisons
    connu = tous(c).get(uid) or {}
    d = c.memo_present("liens", liaisons.DUREE_CACHE) or {}
    tid = c.liaison(uid).get("treemich")
    arbre = next((DE_TREEMICH.get(p.get("genre", ""), "") for p in d.get("treemich", []) if p["id"] == tid), "")
    return {"valeur": connu.get("genre", ""), "origine": connu.get("origine", ""),
            "treemich": arbre if arbre and arbre != connu.get("genre") else "", "choix": GENRES}


# ----------------------------------------------------------------- noms associés → fiches

def cibles(c: Carnet, uid: str, f: dict, index: dict[str, set[str]] | None = None) -> list[str | None]:
    """Pour chaque nom associé de la fiche, la fiche qui porte ce nom, si une seule le porte (comparé
    sans accents ni casse, sur le nom affiché puis le surnom). Sinon None : le nom reste du texte."""
    index = index if index is not None else _index(c)
    res = []
    for n in f.get("noms_associes") or []:
        trouves = index.get(cle_texte(n.get("valeur", "")), set()) - {uid}
        res.append(next(iter(trouves)) if len(trouves) == 1 else None)
    return res


def _index(c: Carnet) -> dict[str, set[str]]:
    """Nom (sans accents ni casse) → uid des fiches qui le portent."""
    index: dict[str, set[str]] = {}
    for u, x in c.fiches().items():
        for t in {cle_texte(nom_affiche(x)), cle_texte(x.get("surnom") or "")} - {""}:
            index.setdefault(t, set()).add(u)
    return index


# ----------------------------------------------------------------- À traiter

def points(c: Carnet) -> list[dict]:
    """Deux sortes de points :
    - « lien_genre » : un lien de fratrie ou de parent qui ne s'accorde pas au genre connu de la
      personne (frère → sœur, « frère ou sœur » → frère, parent → mère…) ;
    - « genre » : toute personne (fiche avec un prénom ou un nom ; pas une entreprise seule) dont
      le genre est inconnu (2.22.3 ; avant : seulement celles notées « frère »). Le point dit sur
      quelles fiches elle est notée « frère », et le genre que son prénom laisse supposer."""
    return c.memo("genres_points", lambda: _points(c))


def _points(c: Carnet) -> list[dict]:
    connus, fiches, index = tous(c), c.fiches(), _index(c)
    res: list[dict] = []
    a_preciser: dict[str, list[dict]] = {}
    for uid, f in fiches.items():
        if not f.get("noms_associes"):
            continue
        for n, cible in zip(f["noms_associes"], cibles(c, uid, f, index)):
            type_ = n.get("type") or ""
            if not cible or (type_ not in FRATRIE.values() and type_ not in PARENT.values()):
                continue
            genre = (connus.get(cible) or {}).get("genre", "")
            voulu = accorde(type_, genre)
            if voulu != type_:
                res.append({"motif": "lien_genre", "uid": uid, "cle": f"{uid}|{cle_texte(n['valeur'])}|{type_}|{voulu}",
                            "donnees": {"valeur": n["valeur"], "de": type_, "vers": voulu, "cible": cible, "genre": genre}})
            elif not genre and type_ in ("frère", FRATRIE_NEUTRE):
                a_preciser.setdefault(cible, []).append({"fiche": nom_affiche(f), "type": type_})
    # 2.24.2 : genre choisi dans carnet ≠ genre de l'arbre (d'après la dernière lecture de Treemich)
    from . import liaisons
    d = c.memo_present("liens", liaisons.DUREE_CACHE)
    if _treemich_parle(d):
        arbre = {p["id"]: DE_TREEMICH.get(p.get("genre", ""), "") for p in d["treemich"]}
        for tid, uid in _reliees(c).items():
            connu = connus.get(uid) or {}
            g_arbre = arbre.get(tid, "")
            if connu.get("origine") == "main" and g_arbre and g_arbre != connu.get("genre"):
                res.append({"motif": "genre_treemich", "uid": uid, "cle": f"{uid}|{connu['genre']}|{g_arbre}",
                            "donnees": {"carnet": connu["genre"], "treemich": g_arbre}})
    # 2.31.5 : plus de genre proposé d'après le prénom (gender-guesser, GPLv3, retiré) : Julien choisit à la main
    for uid, f in fiches.items():
        if uid in connus or not (f.get("prenom") or f.get("nom")):
            continue
        res.append({"motif": "genre", "uid": uid, "cle": uid,
                    "donnees": {"notes": sorted(a_preciser.get(uid, []), key=lambda x: x["fiche"].casefold())}})
    return res


def definir_lot(c: Carnet, choix: dict[str, str]) -> int:
    """Plusieurs genres d'un coup (propositions validées par lot), dans la base de carnet. L'écriture
    dans Treemich suit avec `vers_treemich_maintenant` (appelée par l'action groupée)."""
    le = iso(maintenant())
    fiches = c.fiches()
    faits = 0
    with c.base.transaction() as cx:
        for uid, genre in choix.items():
            if uid in fiches and genre in GENRES:
                cx.execute("INSERT INTO genres(uid, genre, origine, le) VALUES (?,?,'main',?) ON CONFLICT(uid) DO UPDATE "
                           "SET genre = excluded.genre, origine = 'main', le = excluded.le", (uid, genre, le))
                faits += 1
    c.oublier()
    return faits


# ----------------------------------------------------------------- écriture

def definir(c: Carnet, uid: str, genre: str) -> dict:
    """Genre choisi par Julien (« » : retirer son choix). Écrit dans Treemich s'il y est inconnu."""
    c.fiche(uid)
    genre = (genre or "").strip().lower()
    if genre and genre not in GENRES:
        raise ErreurCarnet("Genre inconnu : femme, homme ou autre.")
    if genre:
        c.base.executer("INSERT INTO genres(uid, genre, origine, le) VALUES (?,?,'main',?) ON CONFLICT(uid) DO UPDATE "
                        "SET genre = excluded.genre, origine = 'main', le = excluded.le", (uid, genre, iso(maintenant())))
    else:
        c.base.executer("DELETE FROM genres WHERE uid = ? AND origine = 'main'", (uid,))
        from . import liaisons
        memoriser(c, c.memo_present("liens", liaisons.DUREE_CACHE))      # le genre de l'arbre reprend sa place
    c.oublier()
    message = "Genre enregistré." if genre else "Genre retiré."
    if genre in VERS_TREEMICH and c.liaison(uid).get("treemich"):
        try:
            with c.ecriture(attendre=5):
                message += " " + _vers_treemich(c, uid, genre)
        except (ErreurLien, ErreurCarnet) as exc:
            message += f" Treemich : {exc} Le genre reste dans carnet ; il sera proposé à Treemich à la prochaine synchronisation."
    return {"ok": True, "genre": fiche(c, uid), "message": message}


def _vers_treemich(c: Carnet, uid: str, genre: str, tm=None, personnes: list[dict] | None = None,
                   ecraser: bool = False) -> str:
    """Écrit le genre dans l'arbre s'il y est inconnu (ou, avec `ecraser`, s'il y est différent :
    seulement quand Julien l'a demandé dans un point de désaccord), puis relit."""
    if c.cfg.lecture_seule:
        return "carnet est en lecture seule : rien n'est écrit dans Treemich."
    if not c.cfg.treemich_email:
        return ""
    if c.base.lire(COUPE, False):
        return "Treemich n'a pas gardé le dernier genre écrit : carnet ne lui en écrit plus (voir le journal)."
    tid = c.liaison(uid).get("treemich")
    tm = tm or c.treemich()
    actuel = next((p["genre"] for p in (personnes if personnes is not None else tm.personnes()) if p["id"] == tid), None)
    if actuel is None:
        return "La personne reliée n'est plus dans Treemich."
    if actuel in DE_TREEMICH:
        if DE_TREEMICH[actuel] == genre:
            return "Treemich dit la même chose."
        if not ecraser:
            return f"Treemich dit « {DE_TREEMICH[actuel]} » : rien n'y a été écrasé (à trancher dans À traiter)."
    tm.maj_genre(tid, VERS_TREEMICH[genre])
    # Relecture : la forme de l'écriture n'a jamais été vue sur la vraie installation. Si le genre ne
    # revient pas tel qu'écrit, carnet arrête d'en écrire.
    relu = next((p["genre"] for p in tm.personnes() if p["id"] == tid), None)
    if relu != VERS_TREEMICH[genre]:
        c.base.ecrire(COUPE, True)
        c.base.noter("automatique", "Genre : Treemich n'a pas gardé ce que carnet a écrit ; carnet ne lui écrit plus de genre.")
        raise ErreurLien("l'arbre n'a pas gardé le genre écrit ; carnet ne lui en écrira plus.")
    from . import liaisons
    liaisons._maj_cache(c, "treemich", tid, genre=VERS_TREEMICH[genre])
    c.base.noter("ecriture", "Genre écrit dans Treemich" + (" (remplace celui de l'arbre)" if ecraser else ""), {"uid": uid})
    c.oublier("genres_points")
    return "Écrit aussi dans Treemich."


def en_attente(c: Carnet, d: dict | None) -> list[str]:
    """uid des fiches dont le genre choisi dans carnet manque dans l'arbre (d'après la dernière lecture)."""
    if not _treemich_parle(d):
        return []
    arbre = {p["id"]: p.get("genre", "") for p in d["treemich"]}
    return sorted(uid for t, uid in _reliees(c).items()
                  if (tous(c).get(uid) or {}).get("origine") == "main" and de(c, uid) in VERS_TREEMICH
                  and arbre.get(t) not in DE_TREEMICH)


def vers_treemich_maintenant(c: Carnet) -> dict:
    """Juste après une validation par lot : les genres que l'arbre ne connaît pas y sont écrits, d'après
    la dernière lecture de Treemich. Ce qui échoue sera repris la nuit ou par « Synchroniser »."""
    from . import liaisons
    bilan: dict = {}
    if not c.cfg.treemich_email:
        return bilan
    try:
        with c.ecriture(attendre=5):
            synchroniser(c, c.memo_present("liens", liaisons.DUREE_CACHE), bilan)
    except ErreurCarnet as exc:          # occupé : la nuit s'en chargera
        bilan.setdefault("details", []).append(f"Genre : {exc}")
    return bilan


def garder(c: Carnet, uid: str, lequel: str) -> dict:
    """Point « Genre différent dans Treemich » : « carnet » écrit le genre de carnet dans l'arbre (écrasé),
    « treemich » remplace le choix fait dans carnet par celui de l'arbre."""
    if lequel == "treemich":
        res = definir(c, uid, "")
        res["message"] = "La fiche reprend le genre de Treemich."
        return res
    if lequel != "carnet":
        raise ErreurCarnet("Choix inconnu.")
    genre = de(c, uid)
    if genre not in VERS_TREEMICH:
        raise ErreurCarnet("Aucun genre choisi dans carnet pour cette fiche.")
    with c.ecriture(attendre=5):
        message = _vers_treemich(c, uid, genre, ecraser=True)
    c.oublier()
    return {"ok": True, "genre": fiche(c, uid), "message": message or "Rien à écrire."}


def synchroniser(c: Carnet, d: dict | None, bilan: dict) -> None:
    """Synchroniser Treemich, ou la nuit : les genres choisis dans carnet qui manquent dans l'arbre."""
    attente = en_attente(c, d)
    if not attente or c.cfg.lecture_seule or c.base.lire(COUPE, False):
        return
    tm = c.treemich()
    try:
        personnes = tm.personnes()
        for uid in attente:
            if _vers_treemich(c, uid, de(c, uid), tm, personnes).startswith("Écrit"):
                bilan["treemich"] = bilan.get("treemich", 0) + 1
    except (ErreurLien, ErreurCarnet) as exc:
        bilan.setdefault("details", []).append(f"Genre : {exc}")


def corriger_lien(c: Carnet, uid: str, d: dict) -> dict:
    """La fiche avec le lien accordé (frère → sœur…), prête à être validée."""
    f = c.fiche(uid)
    trouve = False
    liens = []
    for n in f.get("noms_associes") or []:
        if not trouve and cle_texte(n.get("valeur", "")) == cle_texte(d["valeur"]) and n.get("type") == d["de"]:
            n, trouve = {**n, "type": d["vers"]}, True
        liens.append(n)
    if not trouve:
        raise ErreurCarnet("Ce lien n'est plus sur la fiche.")
    f["noms_associes"] = liens
    return f

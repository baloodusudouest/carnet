"""Attentes par groupe et manques (carnet 2.8).

Un tableau dit quelles informations chaque groupe doit avoir. Les attentes de tous les groupes
d'un contact s'additionnent. Un *manque* est une information attendue et absente ; ce n'est pas
une décision : il ne compte pas dans le compteur d'« À traiter ».

Ne comptent jamais dans les manques : une fiche validée (elle couvre tout), une personne décédée,
une information exceptée pour ce contact (« normal pour ce contact »). Une fiche d'entreprise
(ni prénom ni nom) n'attend ni naissance, ni fête, ni Immich, ni Treemich, ni liens familiaux.
"""
from __future__ import annotations

from . import fetes
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

# clé → (nom de la colonne du tableau, libellé du manque)
INFOS = {
    "telephone": ("Téléphone", "Sans téléphone"),
    "courriel": ("Courriel", "Sans courriel"),
    "adresse": ("Adresse", "Sans adresse"),
    "jour": ("Jour de naissance", "Sans jour de naissance"),
    "annee": ("Année de naissance", "Sans année de naissance"),
    "photo": ("Photo ou logo", "Sans photo ni logo"),
    "immich": ("Relié à Immich", "Sans Immich"),
    "treemich": ("Relié à l'arbre", "Sans Treemich"),
    "liens": ("Liens familiaux", "Sans liens familiaux"),
    "societe": ("Société ou fonction", "Sans société ni fonction"),
    "fete": ("Fête", "Sans fête"),
}
# Tableau de départ (grill du 11/11/2026). Un groupe absent d'ici reçoit, au premier démarrage,
# les attentes d'Amis — sauf « Moi », qui n'attend rien.
DEPART = {
    "Famille": ["telephone", "jour", "annee", "photo", "immich", "treemich", "liens", "fete"],
    "Amis": ["telephone", "jour", "photo", "immich", "fete"],
    "Jardin secret": ["telephone", "photo"],
    "Collègues": ["telephone", "photo", "societe"],
    "Clients": ["telephone", "photo", "societe"],
    "Artisans et services": ["telephone", "photo", "societe"],
    "Urgence": ["telephone"],
    "Moi": [],
}
FAMILIAUX = {"conjoint", "partenaire", "mère", "père", "parent", "enfant", "frère", "sœur"}
PERSONNELLES = {"jour", "annee", "fete", "immich", "treemich", "liens"}   # sans objet pour une entreprise
SANS_GROUPE = "sans_groupe"


# ----------------------------------------------------------------- le tableau

def _groupes_connus(c: Carnet) -> list[str]:
    from .modele import groupes_tous
    noms = {l["nom"] for l in c.base.tous("SELECT nom FROM groupes")} | set(groupes_tous())
    for f in c.fiches().values():
        noms.update(f.get("groupes") or [])
    return sorted(noms, key=str.casefold)


def semer(c: Carnet) -> bool:
    """Premier démarrage de la 2.8 : inscrit le tableau de départ. Ne refait jamais rien ensuite,
    même si Julien a tout décoché."""
    if c.base.lire("attentes_semees"):
        return False
    with c.base.transaction() as cx:
        for g in _groupes_connus(c):
            for info in DEPART.get(g, DEPART["Amis"]):
                cx.execute("INSERT OR IGNORE INTO attentes(groupe, info) VALUES (?, ?)", (g, info))
    c.base.ecrire("attentes_semees", iso(maintenant()))
    c.oublier()
    return True


def par_groupe(c: Carnet) -> dict[str, set[str]]:
    def calcul():
        res: dict[str, set[str]] = {}
        for l in c.base.tous("SELECT groupe, info FROM attentes"):
            res.setdefault(l["groupe"], set()).add(l["info"])
        return res
    return c.memo("attentes", calcul)


def regler(c: Carnet, groupe: str, info: str, attendue: bool) -> dict:
    if info not in INFOS:
        raise ErreurCarnet("Information inconnue.")
    if groupe not in _groupes_connus(c):
        raise ErreurCarnet("Ce groupe n'existe pas.")
    if attendue:
        c.base.executer("INSERT OR IGNORE INTO attentes(groupe, info) VALUES (?, ?)", (groupe, info))
    else:
        c.base.executer("DELETE FROM attentes WHERE groupe = ? AND info = ?", (groupe, info))
    c.oublier()
    return {"ok": True, "manques": total(c)}


# ----------------------------------------------------------------- une fiche

def est_entreprise(f: dict) -> bool:
    return not (f.get("prenom") or f.get("nom"))


def fete_de(f: dict) -> tuple[str, str]:
    """(date « --MM-JJ », origine) : la fête écrite sur la carte, sinon celle du calendrier.
    origine : « carte » (écrite et conforme au calendrier), « main » (écrite, différente du
    calendrier : saisie à la main, jamais remplacée), « calendrier » (pas encore écrite), « »."""
    du_calendrier = fetes.pour(f.get("prenom") or "") or ""
    ecrite = f.get("fete") or ""
    if ecrite:
        return ecrite, "carte" if ecrite == du_calendrier else "main"
    return (du_calendrier, "calendrier") if du_calendrier else ("", "")


def remplies(f: dict, liens: dict) -> dict[str, bool]:
    """info → remplie ou non, pour une fiche et ses liaisons."""
    a = f.get("anniversaire") or ""
    return {
        "telephone": bool(f.get("telephones")),
        "courriel": bool(f.get("courriels")),
        "adresse": bool(f.get("adresses")),
        "jour": bool(a),
        "annee": len(a) == 10 and not a.startswith("1900"),
        "photo": bool(f.get("a_photo")),
        "immich": bool(liens.get("immich")),
        "treemich": bool(liens.get("treemich")),
        "liens": any((n.get("type") or "") in FAMILIAUX for n in f.get("noms_associes") or []),
        "societe": bool(f.get("societe") or f.get("fonction")),
        "fete": bool(fete_de(f)[0]),
    }


def attendues(f: dict, tableau: dict[str, set[str]]) -> list[str]:
    voulues = set()
    for g in f.get("groupes") or []:
        voulues |= tableau.get(g, set())
    if est_entreprise(f):
        voulues -= PERSONNELLES
    return [k for k in INFOS if k in voulues]


def exceptions(c: Carnet) -> dict[str, set[str]]:
    def calcul():
        res: dict[str, set[str]] = {}
        for l in c.base.tous("SELECT uid, info FROM exceptions"):
            res.setdefault(l["uid"], set()).add(l["info"])
        return res
    return c.memo("exceptions", calcul)


def decedes(c: Carnet) -> dict[str, str]:
    """uid → date de décès (« » si inconnue) : la carte iCloud, puis ce que carnet sait par ailleurs
    (Treemich, case cochée à la main)."""
    def calcul():
        res = {l["uid"]: l["date"] or "" for l in c.base.tous("SELECT uid, date FROM deces")}
        for uid, f in c.fiches().items():
            if f.get("deces"):
                res[uid] = f["deces"]
        return {u: d for u, d in res.items() if u in c.fiches()}
    return c.memo("decedes", calcul)


def bilan(f: dict, liens: dict, tableau: dict[str, set[str]], exceptees: set[str], valide: bool, decede: bool) -> dict:
    """{attendues, manques, exceptees, score, total} d'une fiche."""
    voulues = attendues(f, tableau)
    etat = remplies(f, liens)
    absentes = [k for k in voulues if not etat[k]]
    if valide or decede:
        return {"attendues": voulues, "manques": [], "exceptees": [], "score": len(voulues), "total": len(voulues)}
    manques = [k for k in absentes if k not in exceptees]
    return {"attendues": voulues, "manques": manques, "exceptees": [k for k in absentes if k in exceptees],
            "score": len(voulues) - len(manques), "total": len(voulues)}


# ----------------------------------------------------------------- tout le carnet

def tout(c: Carnet) -> dict[str, dict]:
    """uid → bilan, pour toutes les fiches (gardé en mémoire tant que la base ne change pas)."""
    def calcul():
        from . import completude
        tableau, exc, morts, liens = par_groupe(c), exceptions(c), decedes(c), c.liaisons()
        valides = {u for u, f in c.fiches().items() if completude.statut(c, u, f) == "valide"}
        return {u: bilan(f, liens.get(u, {}), tableau, exc.get(u, set()), u in valides, u in morts)
                for u, f in c.fiches().items()}
    return c.memo("bilans", calcul)


def lignes(c: Carnet) -> list[dict]:
    """Les lignes de la famille « Manques » : une par information qui manque à au moins une fiche,
    de la plus longue à la plus courte, puis « Sans groupe »."""
    compte = {k: 0 for k in INFOS}
    for b in tout(c).values():
        for k in b["manques"]:
            compte[k] += 1
    res = [{"cle": k, "libelle": INFOS[k][1], "nombre": n} for k, n in compte.items() if n]
    res.sort(key=lambda x: -x["nombre"])
    morts = decedes(c)
    sans = sum(1 for u, f in c.fiches().items() if not f.get("groupes") and u not in morts)
    if sans:
        res.append({"cle": SANS_GROUPE, "libelle": "Sans groupe", "nombre": sans})
    return res


def total(c: Carnet) -> dict:
    b = tout(c)
    return {"fiches": len(b), "incompletes": sum(1 for x in b.values() if x["manques"]),
            "manques": sum(len(x["manques"]) for x in b.values())}


def tableau(c: Carnet) -> dict:
    """Ce que montre l'écran Réglages : colonnes, groupes, cases cochées, nombre de contacts."""
    t = par_groupe(c)
    nombre: dict[str, int] = {}
    for f in c.fiches().values():
        for g in f.get("groupes") or []:
            nombre[g] = nombre.get(g, 0) + 1
    return {"infos": [{"cle": k, "nom": v[0]} for k, v in INFOS.items()],
            "groupes": [{"nom": g, "nombre": nombre.get(g, 0), "attentes": [k for k in INFOS if k in t.get(g, set())]}
                        for g in _groupes_connus(c)],
            "total": total(c), "lignes": lignes(c)}


def apercu(c: Carnet, groupe: str, info: str, attendue: bool) -> dict:
    """Ce que changerait une case, sans rien enregistrer : nombre de fiches qui gagnent ou perdent
    ce manque."""
    if info not in INFOS:
        raise ErreurCarnet("Information inconnue.")
    t = {g: set(v) for g, v in par_groupe(c).items()}
    (t.setdefault(groupe, set()).add if attendue else t.setdefault(groupe, set()).discard)(info)
    avant = sum(1 for b in tout(c).values() if info in b["manques"])
    from . import completude
    exc, morts, liens = exceptions(c), decedes(c), c.liaisons()
    apres = 0
    for u, f in c.fiches().items():
        if groupe not in (f.get("groupes") or []) and info not in tout(c)[u]["manques"]:
            continue
        valide = completude.statut(c, u, f) == "valide"
        apres += info in bilan(f, liens.get(u, {}), t, exc.get(u, set()), valide, u in morts)["manques"]
    return {"info": info, "libelle": INFOS[info][1], "avant": avant, "apres": apres}


# ----------------------------------------------------------------- exceptions

def excepter(c: Carnet, uid: str, info: str, oui: bool = True) -> dict:
    c.fiche(uid)
    if info not in INFOS:
        raise ErreurCarnet("Information inconnue.")
    if oui:
        c.base.executer("INSERT OR IGNORE INTO exceptions(uid, info, le) VALUES (?, ?, ?)", (uid, info, iso(maintenant())))
    else:
        c.base.executer("DELETE FROM exceptions WHERE uid = ? AND info = ?", (uid, info))
    c.oublier()
    return {"ok": True, "bilan": tout(c).get(uid)}


def liste_exceptions(c: Carnet) -> list[dict]:
    from .modele import nom_affiche
    fiches = c.fiches()
    res = [{"uid": l["uid"], "nom": nom_affiche(fiches[l["uid"]]), "info": l["info"],
            "libelle": INFOS.get(l["info"], ("", l["info"]))[1], "le": l["le"]}
           for l in c.base.tous("SELECT uid, info, le FROM exceptions ORDER BY info, le") if l["uid"] in fiches]
    return sorted(res, key=lambda x: (x["libelle"], x["nom"].casefold()))


__all__ = ["INFOS", "DEPART", "semer", "regler", "tableau", "apercu", "tout", "lignes", "total", "excepter",
           "liste_exceptions", "decedes", "fete_de", "est_entreprise"]

"""Boîte « À traiter » : tout ce qui attend une décision de Julien, au même endroit.

Deux sortes de points :
- enregistrés au moment où ils arrivent (modifié / créé / supprimé sur l'iPhone, conflit
  d'écriture, changement LinkedIn, fiche importée) ;
- calculés à partir de l'état actuel (doublons, forme du nom ou des numéros, émoji sans son
  groupe, liaison proposée, date de naissance à trancher, nom à reporter dans Immich ou
  Treemich, liens familiaux).
Un point écarté (« Ignorer », « Pas lui », « Pas la même personne ») n'est plus reproposé.
"""
from __future__ import annotations

import hashlib
import json

from . import fiches as F, normalisation
from .modele import nom_affiche
from .temps import iso, maintenant

TITRES = {
    "iphone_modifiee": "Modifiée sur l'iPhone", "iphone_nouvelle": "Nouvelle sur l'iPhone",
    "iphone_supprimee": "Supprimée sur l'iPhone", "conflit": "Conflit d'écriture", "import": "Fiche importée",
    "linkedin": "Changement LinkedIn", "doublon": "Doublon possible", "forme": "Mise en forme",
    "emoji": "Groupe par émoji", "liaison": "Liaison à confirmer", "date": "Date de naissance à trancher",
    "nom": "Nom à reporter", "relations": "Liens familiaux", "reseau": "Réseau à rattacher",
    "mariage": "Date de mariage manquante", "mariage_different": "Dates de mariage différentes",
    "deces_different": "Dates de décès différentes", "societe": "Société écrite de plusieurs façons",
}
ORDRE = list(TITRES)
ENREGISTRES = {"iphone_modifiee", "iphone_nouvelle", "iphone_supprimee", "conflit", "import", "linkedin", "reseau"}


# 2.9 : une tuile par type de chose à traiter. « incomplet » et « sans_groupe » ne sont pas des points
# mais des listes de fiches ; « sans_groupe » compte dans le chiffre de l'onglet, « incomplet » non.
TUILES = [
    ("icloud", "Changé sur l'iPhone", {"iphone_modifiee", "iphone_nouvelle", "iphone_supprimee", "conflit"}),
    ("sans_groupe", "Pas de groupe", set()),
    ("immich", "Immich non synchronisé", {"liaison"}),
    ("treemich", "Treemich non synchronisé", {"relations", "mariage", "mariage_different", "deces_different"}),
    ("doublons", "Doublons", {"doublon"}),
    ("societes", "Sociétés", {"societe"}),
    ("forme", "Mise en forme", {"forme", "emoji"}),
    ("reseaux", "Réseaux", {"reseau"}),
    ("imports", "Imports", {"import", "linkedin"}),
    ("incomplet", "Contact incomplet", set()),
]


def tuile_de(p: dict) -> str:
    """Tuile d'un point. Un nom ou une date de naissance à trancher va au service concerné
    (Treemich dès qu'il est en cause, sinon Immich)."""
    m, d = p["motif"], p.get("donnees") or {}
    if m == "nom":
        return "treemich" if d.get("service") == "treemich" else "immich"
    if m == "date":
        return "treemich" if "treemich" in (d.get("valeurs") or {}) else "immich"
    return next((cle for cle, _, motifs in TUILES if m in motifs), "forme")


def tuiles(c) -> list[dict]:
    """[{cle, nom, nombre, compte}] : ce que montre la grille d'« À traiter » (types vides compris,
    l'interface ne montre que ceux qui ont quelque chose)."""
    from . import attentes
    par: dict[str, int] = {}
    for p in liste(c):
        par[p["tuile"]] = par.get(p["tuile"], 0) + 1
    par["sans_groupe"] = next((l["nombre"] for l in attentes.lignes(c) if l["cle"] == attentes.SANS_GROUPE), 0)
    par["incomplet"] = attentes.total(c)["incompletes"]
    return [{"cle": cle, "nom": nom, "nombre": par.get(cle, 0), "compte": cle != "incomplet"} for cle, nom, _ in TUILES]


def empreinte(objet) -> str:
    return hashlib.sha1(json.dumps(objet, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def ajouter(cx, motif: str, uid: str | None, cle: str, donnees: dict, remplacer: bool = False) -> bool:
    """Ajoute un point (dans une transaction ouverte). Faux si déjà écarté ou déjà présent."""
    if cx.execute("SELECT 1 FROM ignores WHERE motif = ? AND cle = ?", (motif, cle)).fetchone():
        return False
    sql = "INSERT OR REPLACE" if remplacer else "INSERT OR IGNORE"
    cx.execute(f"{sql} INTO a_traiter(uid, motif, cle, donnees, cree_le) VALUES (?,?,?,?,?)",
               (uid, motif, cle, json.dumps(donnees, ensure_ascii=False), iso(maintenant())))
    return True


def _ignores(c) -> set[tuple[str, str]]:
    return {(l["motif"], l["cle"]) for l in c.base.tous("SELECT motif, cle FROM ignores")}


def calcules(c) -> list[dict]:
    """Points calculés, d'après les fiches et les données d'Immich/Treemich déjà en mémoire."""
    from . import liaisons
    fiches = c.fiches()
    ignores = _ignores(c)
    res = []

    def point(motif, uid, cle, donnees):
        if (motif, cle) not in ignores:
            res.append({"motif": motif, "uid": uid, "cle": cle, "donnees": donnees})

    distincts = {tuple(k.split("|", 1)) for m, k in ignores if m == "doublon"}
    for p in c.memo("doublons", lambda: F.paires_doublons(fiches, distincts)):
        point("doublon", p["a"], F.cle_paire(p["a"], p["b"]), p)
    textes = {l["uid"]: l["texte"] for l in c.base.tous("SELECT uid, texte FROM fiches")}
    for uid, f in fiches.items():
        ecarts = F.ecarts_de_forme(textes.get(uid, ""), f)
        if ecarts:
            point("forme", uid, f"{uid}|{empreinte(ecarts)}", {"ecarts": ecarts})
        for m in normalisation.emojis_sans_groupe(f):
            point("emoji", uid, f"{uid}|{m['groupe']}", m)
    from . import societes
    for p in societes.points(c):
        point(p["motif"], p["uid"], p["cle"], p["donnees"])
    d = c.memo_present("liens", liaisons.DUREE_CACHE)
    if d:
        for p in liaisons.propositions(c, d):
            point("liaison", p["uid"], f"{p['uid']}|{p['immich']['id']}", p)
        for p in liaisons.dates(c, d):
            point("date", p["uid"], f"{p['uid']}|{empreinte(p['valeurs'])}", p)
        for p in liaisons.renommages(c, d):
            point("nom", p["uid"], f"{p['uid']}|{p['service']}|{p['actuel']}", p)
        for p in liaisons.relations(c, d):
            point("relations", p["uid"], f"{p['uid']}|{empreinte(p['ajouts'])}", p)
        from . import famille
        for p in famille.examiner(c, d)["points"]:
            point(p["motif"], p["uid"], p["cle"], p["donnees"])
    return res


def liste(c) -> list[dict]:
    fiches = c.fiches()
    points = [{"motif": l["motif"], "uid": l["uid"], "cle": l["cle"], "donnees": json.loads(l["donnees"]),
               "cree_le": l["cree_le"]} for l in c.base.tous("SELECT * FROM a_traiter ORDER BY id")]
    points += calcules(c)
    for p in points:
        f = fiches.get(p["uid"]) if p["uid"] else None
        if p["motif"] == "iphone_supprimee":
            f = p["donnees"].get("fiche")
        elif p["motif"] == "import":
            f = p["donnees"].get("fiche")
        p["nom"] = nom_affiche(f) if f else "(contact inconnu)"
        if p["motif"] == "societe":
            p["nom"] = p["donnees"]["variantes"][0]["nom"]     # le point porte le nom de la société, pas d'une fiche
        p["titre"] = TITRES.get(p["motif"], p["motif"])
        p["id"] = f"{p['motif']}:{p['cle']}"
        p["tuile"] = tuile_de(p)
        if p["motif"] == "doublon":
            autre = fiches.get(p["donnees"]["b"])
            p["autre"] = nom_affiche(autre) if autre else ""
    return sorted(points, key=lambda p: (ORDRE.index(p["motif"]) if p["motif"] in ORDRE else 99, p["nom"].casefold()))


def compte(c) -> dict:
    tous = liste(c)
    par = {}
    for p in tous:
        par[p["motif"]] = par.get(p["motif"], 0) + 1
    from . import attentes
    sans_groupe = next((l["nombre"] for l in attentes.lignes(c) if l["cle"] == attentes.SANS_GROUPE), 0)
    # 2.9 : une fiche sans groupe est une décision à prendre ; elle compte dans le chiffre de l'onglet
    return {"total": len(tous) + sans_groupe, "points": len(tous), "sans_groupe": sans_groupe, "par_motif": par}


def trouver(c, ident: str) -> dict:
    from .carnet import ErreurCarnet
    for p in liste(c):
        if p["id"] == ident:
            return p
    raise ErreurCarnet("Ce point a déjà été traité.")


def retirer(c, motif: str, cle: str) -> None:
    c.base.executer("DELETE FROM a_traiter WHERE motif = ? AND cle = ?", (motif, cle))
    c.oublier()


def ignorer(c, motif: str, cle: str) -> None:
    with c.base.transaction() as cx:
        cx.execute("INSERT OR IGNORE INTO ignores(motif, cle, le) VALUES (?,?,?)", (motif, cle, iso(maintenant())))
        cx.execute("DELETE FROM a_traiter WHERE motif = ? AND cle = ?", (motif, cle))
    c.oublier()

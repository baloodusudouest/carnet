"""3.6 : l'arbre de famille pour Sillage (vue 3D), et les propositions des invités.

- `graphe` : toutes les personnes de Treemich et leurs liens (parent, conjoint, fratrie), tels que carnet les garde
  déjà en mémoire (`liaisons.donnees`). Les dates ne sont connues que des personnes reliées à une fiche (Treemich
  limite les appels : rien de plus n'est lu). La case « jamais aux invités » est gardée ici (table `arbre_masques`).
  Lecture seule.
- `recevoir` : une proposition d'un invité de Sillage devient un point « Proposition d'invité » d'« À traiter ».
- `accepter` : après validation de Julien, seules les dates (naissance, décès, mariage) et les noms s'écrivent dans
  Treemich, une à la fois, relues. Une personne ou un lien proposé ne s'écrit jamais : c'est à faire dans Treemich.
"""
from __future__ import annotations

import logging
import re

from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

log = logging.getLogger("carnet")

CONTRAT = 1
MOTIF = "proposition_invite"
TYPES = {"date", "nom", "lien", "personne"}
CHAMPS_DATE = {"naissance", "deces", "mariage"}
CHAMPS_NOM = {"prenom", "nom"}
LIENS = {"parent", "enfant", "conjoint", "frere_soeur", "autre"}
EN_ATTENTE_MAX = 300           # au-delà, carnet refuse les nouvelles propositions (un formulaire public ne doit pas noyer « À traiter »)
LONGUEUR_MOT = 500
_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_GENRES = {"FEMALE": "femme", "MALE": "homme", "OTHER": "autre"}


class PropositionRefusee(ErreurCarnet):
    pass


# ================================================================ l'arbre

def masques(c: Carnet) -> set[str]:
    return {l["treemich"] for l in c.base.tous("SELECT treemich FROM arbre_masques")}


def masquer(c: Carnet, tid: str, masque: bool) -> dict:
    """Case « jamais aux invités » d'une personne de l'arbre (identifiant Treemich)."""
    if not tid or len(tid) > 100:
        raise ErreurCarnet("Personne de l'arbre inconnue.")
    if masque:
        c.base.executer("INSERT OR REPLACE INTO arbre_masques(treemich, le) VALUES (?, ?)", (tid, iso(maintenant())))
    else:
        c.base.executer("DELETE FROM arbre_masques WHERE treemich = ?", (tid,))
    return {"treemich": tid, "masque": masque}


def _date_fiche(texte: str) -> str:
    """« AAAA-MM-JJ » ou « AAAA » d'une fiche ; une date sans année (« --MM-JJ ») ne dit rien de l'âge : vide."""
    t = (texte or "").strip()
    return t if _DATE.match(t) else ""


def _liens(relations: list[dict], ids: set[str], couples: dict[tuple[str, str], dict]) -> list[dict]:
    vus, res = set(), []
    for r in relations:
        a, b, t = r["de"], r["vers"], r["type"]
        if a == b or a not in ids or b not in ids:
            continue
        if t in ("PARENT_OF", "CHILD_OF"):
            parent, enfant = (a, b) if t == "PARENT_OF" else (b, a)
            cle = ("parent", parent, enfant)
            lien = {"de": parent, "vers": enfant, "type": "parent"}
        elif t == "SPOUSE_OF":
            x, y = sorted((a, b))
            cle = ("conjoint", x, y)
            lien = {"de": x, "vers": y, "type": "conjoint", "divorce": bool((couples.get((x, y)) or {}).get("divorce"))}
        elif t == "SIBLING_OF":
            x, y = sorted((a, b))
            cle = ("fratrie", x, y)
            lien = {"de": x, "vers": y, "type": "fratrie"}
        else:
            continue
        if cle not in vus:
            vus.add(cle)
            res.append(lien)
    return res


def graphe(c: Carnet) -> dict:
    """{contrat, ok, genere_le, personnes, liens}. `ok` faux : Treemich n'a pas encore été lu (ou n'a pas répondu
    en entier) ; les listes sont alors celles de la dernière lecture, éventuellement vides."""
    from . import attentes, famille, genres, liaisons, personnes as P
    d = liaisons.donnees(c)
    fiches = c.fiches()
    reliees = {v["treemich"]: u for u, v in c.liaisons().items() if v.get("treemich")}
    ids_maison = P.ids(c)
    morts = attentes.decedes(c)
    g = genres.par_treemich(c, d)
    caches = masques(c)
    couples = {(x["a"], x["b"]): x for x in famille.couples(d)}
    gens = []
    for p in d.get("treemich") or []:
        tid = p["id"]
        uid = reliees.get(tid) if reliees.get(tid) in fiches else None
        naissance = _date_fiche(fiches[uid].get("anniversaire")) if uid else ""
        naissance = naissance or (d.get("naissances_treemich") or {}).get(tid, "")
        deces = ""
        if uid and uid in morts:
            deces = morts[uid] or "inconnue"
        deces = deces or (d.get("deces_treemich") or {}).get(tid, "")
        gens.append({"id": tid, "nom": p.get("nom") or "", "genre": g.get(tid) or _GENRES.get(p.get("genre"), ""),
                     "immich": p.get("immich") or None, "naissance": naissance, "deces": deces,
                     "decede": bool(deces), "fiche": bool(uid), "carnet_uid": uid,
                     "personne_id": ids_maison.get(uid) if uid else None, "masque_invites": tid in caches})
    ids = {x["id"] for x in gens}
    return {"contrat": CONTRAT, "ok": bool(famille._treemich_parle(d)), "genere_le": d.get("le") or iso(maintenant()),
            "personnes": gens, "liens": _liens(d.get("relations") or [], ids, couples)}


# ================================================================ propositions des invités

def _texte(v, longueur: int = 120) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:longueur]


def recevoir(c: Carnet, corps: dict) -> dict:
    """Une proposition venue de Sillage (jeton commun). Corps : {id, personne (id Treemich), nom (de la personne,
    pour l'affichage), type, champ, valeur, autre, autre_nom, lien, mot, invites: [prénoms], sejour: {du, au}}.
    Idempotent sur `id`. Rien n'est écrit hors de carnet."""
    from . import traiter
    if not isinstance(corps, dict):
        raise PropositionRefusee("Proposition illisible.")
    ident = _texte(corps.get("id"), 64)
    type_ = corps.get("type")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", ident or ""):
        raise PropositionRefusee("Identifiant de proposition manquant.")
    if type_ not in TYPES:
        raise PropositionRefusee("Type de proposition inconnu.")
    tid = _texte(corps.get("personne"), 100)
    if not tid:
        raise PropositionRefusee("Personne de l'arbre manquante.")
    champ, valeur = _texte(corps.get("champ"), 20), _texte(corps.get("valeur"), 120)
    if type_ == "date":
        if champ not in CHAMPS_DATE:
            raise PropositionRefusee("Date inconnue : naissance, décès ou mariage.")
        if valeur and not _DATE.match(valeur):
            raise PropositionRefusee("Date attendue : AAAA, AAAA-MM ou AAAA-MM-JJ.")
    elif type_ == "nom":
        if champ not in CHAMPS_NOM or not valeur:
            raise PropositionRefusee("Nom proposé manquant.")
    elif type_ == "lien" and _texte(corps.get("lien"), 20) not in LIENS:
        raise PropositionRefusee("Lien inconnu.")
    mot = _texte(corps.get("mot"), LONGUEUR_MOT)
    if type_ in ("lien", "personne") and not (mot or valeur):
        raise PropositionRefusee("Dites en quelques mots ce qui manque.")
    deja = c.base.un("SELECT 1 FROM a_traiter WHERE motif = ? AND cle = ?", (MOTIF, ident))
    if deja:
        return {"ok": True, "deja": True}
    attente = c.base.un("SELECT COUNT(*) AS n FROM a_traiter WHERE motif = ?", (MOTIF,))
    if attente and attente["n"] >= EN_ATTENTE_MAX:
        raise PropositionRefusee("Trop de propositions en attente : réessayez plus tard.")
    reliees = {v["treemich"]: u for u, v in c.liaisons().items() if v.get("treemich")}
    sejour = corps.get("sejour") if isinstance(corps.get("sejour"), dict) else {}
    donnees = {"personne": tid, "nom": _texte(corps.get("nom"), 120), "type": type_, "champ": champ,
               "valeur": valeur, "autre": _texte(corps.get("autre"), 100) or None,
               "autre_nom": _texte(corps.get("autre_nom"), 120), "lien": _texte(corps.get("lien"), 20),
               "mot": mot, "invites": [_texte(x, 40) for x in (corps.get("invites") or [])[:8] if _texte(x, 40)],
               "sejour": {"du": _texte(sejour.get("du"), 10), "au": _texte(sejour.get("au"), 10)},
               "recu_le": iso(maintenant())}
    with c.base.transaction() as cx:
        traiter.ajouter(cx, MOTIF, reliees.get(tid), ident, donnees)
    c.oublier()
    log.info("Proposition d'invité reçue (%s, %s)", type_, champ or "-")
    return {"ok": True, "deja": False}


def _relire(c: Carnet, tid: str) -> dict:
    return c.treemich().evenements(tid)


def accepter(c: Carnet, p: dict, valeur=None) -> dict:
    """Écrit une date ou un nom proposé dans Treemich, après validation de Julien (valeur éventuellement corrigée
    par lui). Une date est relue juste après ; un écart arrête tout et le point reste."""
    from . import liaisons, traiter
    d = p["donnees"]
    if d["type"] not in ("date", "nom"):
        raise ErreurCarnet("Un lien ou une personne se crée dans Treemich : fais-le, puis « C'est fait ».")
    c.exiger_ecriture("Treemich")
    tm = c.treemich()
    tid = d["personne"]
    if d["type"] == "date":
        date = (valeur if isinstance(valeur, str) else d["valeur"]).strip()
        if not _DATE.match(date):
            raise ErreurCarnet("Date attendue : AAAA, AAAA-MM ou AAAA-MM-JJ.")
        if d["champ"] == "naissance":
            tm.maj_naissance(tid, date)
            lu = _relire(c, tid)["naissance"]
        elif d["champ"] == "deces":
            tm.maj_deces(tid, date)
            lu = _relire(c, tid)["deces"]
        else:
            if not d.get("autre"):
                raise ErreurCarnet("Le conjoint n'est pas indiqué : écris la date dans Treemich.")
            couple = {tuple(sorted((r["de"], r["vers"]))): r for r in tm.relations() if r["type"] == "SPOUSE_OF"}
            cle = tuple(sorted((tid, d["autre"])))
            if cle not in couple:
                raise ErreurCarnet("Ce couple n'existe pas dans Treemich : crée-le d'abord.")
            tm.maj_mariage(tid, d["autre"], date)
            lu = {tuple(sorted((r["de"], r["vers"]))): r for r in tm.relations()
                  if r["type"] == "SPOUSE_OF"}.get(cle, {}).get("mariage", "")
        if lu[:len(date)] != date:
            raise ErreurCarnet("Treemich n'a pas gardé la date : rien n'est changé, le point reste.")
        message = "Date écrite dans Treemich."
    else:
        v = valeur if isinstance(valeur, dict) else {}
        prenom, nom = _texte(v.get("prenom"), 80), _texte(v.get("nom"), 80)
        if not (prenom or nom):
            raise ErreurCarnet("Donne le prénom et le nom tels qu'ils doivent être écrits.")
        tm.renommer(tid, prenom, nom)
        message = "Nom écrit dans Treemich."
    traiter.retirer(c, MOTIF, p["cle"])
    liaisons.donnees(c, rafraichir=True)
    log.info("Proposition d'invité acceptée (%s)", d["type"])
    return {"ok": True, "message": message}

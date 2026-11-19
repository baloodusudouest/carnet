"""Événements envoyés par les applis de la maison (3.1) : une seule adresse commune.

Décision de Julien du 19/11/2026 (dossier « coffre Contacts » v2, § 7) : chaque appli (Gazette, Douze points, plus
tard Capsule, Comptoir, les albums d'Immich…) envoie ses événements à carnet sous la même forme, et carnet les range
pour les fiches et le coffre Contacts.

    PUT    /evenements/{appli}/{cle}     (jeton commun MAISON_JETON)
    DELETE /evenements/{appli}/{cle}
    PUT    /compteurs/{appli}/{nom}      (ex. gazette / photos_scandale)

Corps d'un événement :
    {"type": "sejour" | "gazette" | "recidive" | "douze_points" | "livre_or" | "autre",
     "date": "AAAA-MM-JJ", "titre": "…", "resume": "…", "lien": "https://…",
     "personnes": [{"personne_id": "p-…" | "immich_id": "…" | "nom": "…", "role": "…", "donnees": {…}}]}

Une personne est reconnue par son identifiant maison (fusions suivies), sinon par sa personne d'Immich, sinon par un
nom porté par une seule fiche. Une personne non reconnue est gardée, sans fiche, et apparaît dans À traiter
(« Événements à rattacher ») : rien n'est créé ni deviné (envoi partiel accepté). Reste dans carnet : permis en
lecture seule (rien ne sort vers iCloud).
"""
from __future__ import annotations

import json
import re

from . import personnes
from .carnet import Carnet, ErreurCarnet
from .normalisation import cle_texte
from .temps import iso, maintenant

TYPES = {"sejour": "Séjour", "gazette": "La Gazette", "recidive": "La Récidive", "douze_points": "Douze points",
         "livre_or": "Livre d'or", "autre": "Événement"}
APPLI = re.compile(r"^[a-z][a-z0-9-]{1,29}$")
CLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,79}$")
NOM_COMPTEUR = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_PERSONNES = 80
MAX_DONNEES = 2000

# Tables : voir app/base.py (schéma 10).


def _texte(v, maxi: int) -> str:
    return " ".join(str(v or "").split())[:maxi]


def _lien(v) -> str:
    v = str(v or "").strip()
    if not v:
        return ""
    if not re.match(r"^https?://", v) or len(v) > 400 or any(ch.isspace() for ch in v):
        raise ErreurCarnet("Lien invalide (adresse http ou https attendue).")
    return v


def _verifier_ids(appli: str, cle: str) -> None:
    if not APPLI.fullmatch(appli or ""):
        raise ErreurCarnet("Nom d'appli invalide (minuscules, chiffres et tirets).")
    if not CLE.fullmatch(cle or ""):
        raise ErreurCarnet("Clé d'événement invalide (minuscules, chiffres, « - », « _ » et « . »).")


# ---------------------------------------------------------------- reconnaissance d'une personne

class _Index:
    """Tables de reconnaissance, faites une fois par envoi."""

    def __init__(self, c: Carnet):
        from .sorties import contacts_ha
        self.c = c
        self.ids = personnes.ids(c)
        self.par_immich = {lien["immich"]: self.ids[uid] for uid, lien in c.liaisons().items()
                           if lien.get("immich") and uid in self.ids}
        noms: dict[str, set[str]] = {}
        for p in contacts_ha(c):
            if not p.get("personne_id"):
                continue
            for n in {p["nom"], p["nom_carnet"]}:
                if n:
                    noms.setdefault(cle_texte(n), set()).add(p["personne_id"])
        self.par_nom = noms

    def actuel(self, ident: str) -> str:
        uid = personnes.uid_de(self.c, ident) if ident else None
        return self.ids.get(uid, "") if uid else ""

    def resoudre(self, ref: dict) -> str:
        """Identifiant maison, ou "" si la personne n'est pas reconnue sans doute possible."""
        if (pid := str(ref.get("personne_id") or "")) and (ident := self.actuel(pid)):
            return ident
        if (imm := str(ref.get("immich_id") or "")) and imm in self.par_immich:
            return self.par_immich[imm]
        nom = _texte(ref.get("nom"), 120)
        trouves = self.par_nom.get(cle_texte(nom), set()) if nom else set()
        return next(iter(trouves)) if len(trouves) == 1 else ""


# ---------------------------------------------------------------- réception

def recevoir(c: Carnet, appli: str, cle: str, corps: dict) -> dict:
    """Crée ou remplace un événement. Renvoie {appli, cle, reconnues, a_rattacher}."""
    _verifier_ids(appli, cle)
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    type_ = str(corps.get("type") or "")
    if type_ not in TYPES:
        raise ErreurCarnet(f"Type d'événement inconnu (attendu : {', '.join(TYPES)}).")
    date = str(corps.get("date") or "")[:10]
    if not DATE.fullmatch(date):
        raise ErreurCarnet("Date invalide (AAAA-MM-JJ).")
    titre, resume_ = _texte(corps.get("titre"), 160), _texte(corps.get("resume"), 800)
    lien = _lien(corps.get("lien"))
    gens = corps.get("personnes") or []
    if not isinstance(gens, list) or len(gens) > MAX_PERSONNES:
        raise ErreurCarnet(f"« personnes » : une liste de {MAX_PERSONNES} personnes au plus est attendue.")
    idx = _Index(c)
    lignes, vus, reconnues, a_rattacher = [], set(), 0, []
    for ref in gens:
        if not isinstance(ref, dict):
            raise ErreurCarnet("Chaque personne est un objet.")
        donnees = ref.get("donnees") or {}
        if not isinstance(donnees, dict):
            raise ErreurCarnet("« donnees » d'une personne : un objet est attendu.")
        brut = json.dumps(donnees, ensure_ascii=False)
        if len(brut) > MAX_DONNEES:
            raise ErreurCarnet("« donnees » d'une personne trop longues.")
        ident = idx.resoudre(ref)
        nom = _texte(ref.get("nom"), 120)
        if ident:
            if ident in vus:
                continue
            vus.add(ident)
            reconnues += 1
        elif not nom and not ref.get("immich_id") and not ref.get("personne_id"):
            raise ErreurCarnet("Une personne sans identifiant ni nom.")
        else:
            a_rattacher.append(nom or str(ref.get("immich_id") or ref.get("personne_id")))
        lignes.append((ident, nom, _texte(ref.get("immich_id"), 80), _texte(ref.get("role"), 60), brut))
    le = iso(maintenant())
    with c.base.transaction() as cx:
        # les rattachements faits à la main restent : un nom déjà rattaché garde sa personne
        mains = {(l["nom"], l["immich"]): l["personne"] for l in cx.execute(
            "SELECT nom, immich, personne FROM evenements_personnes WHERE appli = ? AND cle = ? AND personne != ''",
            (appli, cle)).fetchall()}
        cx.execute("INSERT INTO evenements(appli, cle, type, date, titre, resume, lien, maj) VALUES (?,?,?,?,?,?,?,?) "
                   "ON CONFLICT(appli, cle) DO UPDATE SET type = excluded.type, date = excluded.date, titre = excluded.titre, "
                   "resume = excluded.resume, lien = excluded.lien, maj = excluded.maj",
                   (appli, cle, type_, date, titre, resume_, lien, le))
        cx.execute("DELETE FROM evenements_personnes WHERE appli = ? AND cle = ?", (appli, cle))
        for ident, nom, imm, role, brut in lignes:
            if not ident and (nom, imm) in mains and mains[(nom, imm)] not in vus:
                ident = mains[(nom, imm)]
                vus.add(ident)
                a_rattacher.remove(nom or imm)
                reconnues += 1
            cx.execute("INSERT INTO evenements_personnes(appli, cle, personne, nom, immich, role, donnees) "
                       "VALUES (?,?,?,?,?,?,?)", (appli, cle, ident, nom, imm, role, brut))
    c.base.noter("evenements", f"Événement reçu de {appli}",
                 {"cle": cle, "type": type_, "reconnues": reconnues, "a_rattacher": len(a_rattacher)})
    return {"appli": appli, "cle": cle, "reconnues": reconnues, "a_rattacher": a_rattacher}


def retirer(c: Carnet, appli: str, cle: str) -> dict:
    _verifier_ids(appli, cle)
    with c.base.transaction() as cx:
        n = cx.execute("DELETE FROM evenements WHERE appli = ? AND cle = ?", (appli, cle)).rowcount
        cx.execute("DELETE FROM evenements_personnes WHERE appli = ? AND cle = ?", (appli, cle))
    return {"retire": bool(n)}


def recevoir_compteur(c: Carnet, appli: str, nom: str, corps: dict) -> dict:
    """{personnes: [{personne_id | immich_id | nom, valeur}], complet: bool}. `complet` : la liste couvre tout le monde,
    les personnes absentes repassent à zéro. Une personne non reconnue est ignorée (comptée dans la réponse)."""
    if not APPLI.fullmatch(appli or "") or not NOM_COMPTEUR.fullmatch(nom or ""):
        raise ErreurCarnet("Nom d'appli ou de compteur invalide.")
    if not isinstance(corps, dict) or not isinstance(corps.get("personnes"), list):
        raise ErreurCarnet("« personnes » : une liste est attendue.")
    idx = _Index(c)
    valeurs: dict[str, int] = {}
    inconnues = 0
    for ref in corps["personnes"][:5000]:
        if not isinstance(ref, dict):
            raise ErreurCarnet("Chaque personne est un objet.")
        try:
            v = int(ref.get("valeur"))
        except (TypeError, ValueError):
            raise ErreurCarnet("« valeur » : un nombre entier est attendu.")
        if v < 0:
            raise ErreurCarnet("« valeur » : un nombre positif est attendu.")
        ident = idx.resoudre(ref)
        if ident:
            valeurs[ident] = v
        else:
            inconnues += 1
    le = iso(maintenant())
    with c.base.transaction() as cx:
        if corps.get("complet"):
            cx.execute("DELETE FROM compteurs WHERE appli = ? AND nom = ?", (appli, nom))
        for ident, v in valeurs.items():
            cx.execute("INSERT INTO compteurs(personne, appli, nom, valeur, maj) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(personne, appli, nom) DO UPDATE SET valeur = excluded.valeur, maj = excluded.maj",
                       (ident, appli, nom, v, le))
    return {"enregistres": len(valeurs), "inconnues": inconnues}


# ---------------------------------------------------------------- lecture

def compteur(c: Carnet, ident: str, appli: str, nom: str) -> int | None:
    l = c.base.un("SELECT valeur FROM compteurs WHERE personne = ? AND appli = ? AND nom = ?", (ident, appli, nom))
    return l["valeur"] if l else None


def tous(c: Carnet) -> list[dict]:
    """Tous les événements, avec leurs personnes reconnues : [{appli, cle, type, date, titre, resume, lien,
    personnes: [{personne, role, donnees}]}], du plus récent au plus ancien."""
    evts: dict[tuple[str, str], dict] = {}
    for l in c.base.tous("SELECT * FROM evenements ORDER BY date DESC, appli, cle"):
        evts[(l["appli"], l["cle"])] = {k: l[k] for k in ("appli", "cle", "type", "date", "titre", "resume", "lien")} | {"personnes": []}
    for l in c.base.tous("SELECT * FROM evenements_personnes WHERE personne != '' ORDER BY id"):
        e = evts.get((l["appli"], l["cle"]))
        if e is not None:
            e["personnes"].append({"personne": l["personne"], "role": l["role"], "donnees": json.loads(l["donnees"] or "{}")})
    return list(evts.values())


def de_personne(c: Carnet, ident: str) -> list[dict]:
    """Événements d'une personne, sa ligne en plus : [{…, role, donnees}]."""
    res = []
    for e in tous(c):
        moi = next((p for p in e["personnes"] if p["personne"] == ident), None)
        if moi:
            res.append({k: e[k] for k in ("appli", "cle", "type", "date", "titre", "resume", "lien")}
                       | {"role": moi["role"], "donnees": moi["donnees"]})
    return res


def a_rattacher(c: Carnet) -> list[dict]:
    """Personnes d'événements non reconnues : [{id, nom, immich, role, appli, cle, type, date, titre}]."""
    return [dict(l) for l in c.base.tous(
        "SELECT p.id, p.nom, p.immich, p.role, e.appli, e.cle, e.type, e.date, e.titre FROM evenements_personnes p "
        "JOIN evenements e ON e.appli = p.appli AND e.cle = p.cle WHERE p.personne = '' ORDER BY e.date DESC, p.id")]


def rattacher(c: Carnet, ligne_id: int, uid: str) -> dict:
    """Rattache une personne d'événement non reconnue à la fiche `uid` (depuis À traiter)."""
    ident = personnes.de(c, uid)
    l = c.base.un("SELECT appli, cle FROM evenements_personnes WHERE id = ? AND personne = ''", (int(ligne_id),))
    if not l:
        raise ErreurCarnet("Personne d'événement introuvable ou déjà rattachée.")
    if c.base.un("SELECT 1 FROM evenements_personnes WHERE appli = ? AND cle = ? AND personne = ?", (l["appli"], l["cle"], ident)):
        c.base.executer("DELETE FROM evenements_personnes WHERE id = ?", (int(ligne_id),))
    else:
        c.base.executer("UPDATE evenements_personnes SET personne = ? WHERE id = ?", (ident, int(ligne_id)))
    return {"ok": True}


def ecarter(c: Carnet, ligne_id: int) -> dict:
    """Retire une personne d'événement non reconnue (pas quelqu'un de carnet : un invité de passage)."""
    c.base.executer("DELETE FROM evenements_personnes WHERE id = ? AND personne = ''", (int(ligne_id),))
    return {"ok": True}

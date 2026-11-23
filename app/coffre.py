"""Synchronisation vers le coffre « Contacts » (2.28 ; forme SilverBullet en 3.0 ; dossier complet en 3.1).

carnet est le maître des informations contact ; le coffre en est une vue, avec les notes de Julien.
À sens unique (décision du 18/11/2026 : coffre Contacts en lecture seule côté carnet) : carnet écrit,
il ne relit jamais ce que Julien écrit dans les notes.

Forme 3.1 (dossier « coffre Contacts » v2, décisions de Julien du 19/11/2026) — le dossier d'une personne réunit
l'intégralité de ce que la maison sait d'elle :

- `Personnes/<Nom>/<Nom>.md` : la note Contact (informations iCloud, famille et proches, statut des allergies,
  liste de ses fiches liées, liens) — une par fiche avec un prénom ou un nom ;
- `Personnes/<Nom>/<Nom> — <Type>.md` : une fiche liée par sujet, seulement s'il y a du contenu : Allergies,
  Pépites, Récidives, Gazette, Livre d'or, Douze points, Séjours, Sillage, Arbre ; celles qui listent des
  événements renvoient aux notes d'événement ;
- `Événements/<Type>/<date> — <titre>.md` : une note par numéro, séjour ou soirée (Récidives, Gazette, Livre d'or,
  Douze points, Séjours), partagée par toutes les personnes concernées, avec le lien vers la page de l'appli.

Chaque note a un bloc entre `<!-- carnet:debut … -->` et `<!-- carnet:fin -->`, réécrit à chaque
synchronisation ; tout le reste (zone « Mes notes », ce qui est écrit avant ou après le bloc) n'est jamais
touché. L'en-tête garde les clés ajoutées à la main ; carnet ne réécrit que les siennes (`CLES_CARNET`).
Les notes sont retrouvées par leur identifiant (`personne_id`, `index_de` + `index_type`, `evenement_id`),
même déplacées. carnet ne supprime jamais une note. Il range une seule fois les notes des formes précédentes
(2.28 : `Personnes/<Nom>.md` → dossier ; 3.0 : « Pour les journaux » → « Pépites », « Journaux parus » →
« Récidives », dossiers `Événements/La Récidive` et `La Gazette` → `Récidives` et `Gazette`), et renomme le dossier
d'une personne quand son nom change (seulement si la note est à sa place d'origine et que le nouveau nom est libre).

Sillage (étapes du chemin de vie) est lu au plus une fois par jour et par personne ; Sillage injoignable : la fiche
liée n'est pas touchée (jamais vidée). L'Arbre vient des relations de Treemich gardées en mémoire par carnet ; sans
elles (Treemich pas encore lu depuis le démarrage), la fiche liée n'est pas touchée non plus.

3.2 (choix de Julien du 19/11/2026, visualisations du coffre Contacts) : chaque note porte une étiquette dans son
en-tête (`tags` : `contact`, `fiche` ou `evenement`, en plus de celles ajoutées à la main) pour que Graphview colore le
graphe par sorte de note ; la fiche liée « Arbre » commence par un schéma Mermaid (la personne, ses parents, sa fratrie,
son conjoint, ses enfants) et la note Contact a une « Frise » Mermaid de ses séjours, soirées et journaux, année par
année. Ce sont de simples blocs de code ```mermaid : SilverBullet les dessine avec le plug officiel Mermaid.

Garde-fou : le coffre doit être monté et contenir un dossier `Personnes/` créé par Julien. Si le dossier
partagé chiffré n'est pas monté, rien n'est écrit (pas de copie en clair dans un dossier vide).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from . import alimentation, attentes, evenements as evts_, genres, journaux, maison, personnes
from .carnet import Carnet, ErreurCarnet
from .fiches import date_lisible
from .modele import nom_affiche
from .normalisation import cle_texte
from .temps import iso, maintenant

DOSSIER = "Personnes"
EVENEMENTS = "Événements"
DEBUT = "<!-- carnet:debut — partie écrite par carnet, réécrite à chaque synchronisation : ne pas modifier ici -->"
FIN = "<!-- carnet:fin -->"
ZONE_LIBRE = "## Mes notes\n\n"
CLES_CARNET = ("personne_id", "type", "tags", "nom", "aliases", "groupes", "naissance", "allergies", "carnet", "maj_carnet",
               "index_de", "index_type", "evenement_id", "evenement", "date", "personnes")
ID = re.compile(r"^personne_id:\s*[\"']?(p-[0-9a-f]{10})[\"']?\s*$", re.M)
INDEX_DE = re.compile(r"^index_de:\s*[\"']?(p-[0-9a-f]{10})[\"']?\s*$", re.M)
INDEX_TYPE = re.compile(r"^index_type:\s*[\"']?([a-z_]+)[\"']?\s*$", re.M)
EVT = re.compile(r"^evenement_id:\s*[\"']?([a-z0-9_.-]+)[\"']?\s*$", re.M)
# 3.0 : le point en plus (SilverBullet n'ouvre pas une note dont le nom contient un point : « J. Dupont » → « J Dupont »)
INTERDITS = re.compile(r'[\\/:*?"<>|#^\[\].]')
# 3.1 : fiches liées (clé → titre), dans l'ordre de la note Contact
TYPES = {"allergies": "Allergies", "pepites": "Pépites", "recidives": "Récidives", "gazette": "Gazette",
         "livre_or": "Livre d'or", "douze_points": "Douze points", "sejours": "Séjours", "sillage": "Sillage",
         "arbre": "Arbre"}
# 3.0 → 3.1 : anciennes fiches liées, renommées une fois (clé → (nouvelle clé, ancien titre))
ANCIENS = {"journaux": ("pepites", "Pour les journaux"), "parus": ("recidives", "Journaux parus")}
# Dossiers des notes d'événement (nature → dossier) ; anciens dossiers de la 3.0 (déplacés une fois)
DOSSIERS = {"recidives": "Récidives", "gazette": "Gazette", "livre_or": "Livre d'or", "douze_points": "Douze points",
            "sejours": "Séjours"}
DOSSIERS_ANCIENS = {"La Récidive": "Récidives", "La Gazette": "Gazette"}
# Types des événements envoyés par les applis (app/evenements.py) → nature (fiche liée et dossier)
NATURE = {"recidive": "recidives", "gazette": "gazette", "livre_or": "livre_or", "douze_points": "douze_points",
          "sejour": "sejours"}
JOURNAUX = {"recidive": ("La Récidive", "recidives"), "gazette": ("La Gazette", "gazette")}
APPLIS = {"gazette": "Gazette", "douze-points": "Douze points", "home-assistant": "Home Assistant"}
MOTIF_DEBUT = re.compile(r"<!-- carnet:debut\b.*?-->")
# 3.2 : étiquette de chaque sorte de note (Graphview colore le graphe par étiquette)
TAG_CONTACT, TAG_FICHE, TAG_EVENEMENT = "contact", "fiche", "evenement"
# Couleurs du coffre en tête du bloc, lisibles sur fond sombre comme sur fond clair (le fond du cadre suit le mode
# de l'appareil) ; forme « config » : la directive %%{init}%% n'est pas lue par mermaid.init(), qu'utilise
# le plug Mermaid de SilverBullet — essayé avec Mermaid 11.10.1, la version que charge le plug)
_MM_VARIABLES = {"primaryColor": "#2e2822", "primaryTextColor": "#ece4d8", "primaryBorderColor": "#857a6c",
                 "lineColor": "#b3a796",
                 **{f"cScale{k}": c for k, c in enumerate(("#3a2e26", "#2e2822", "#4a3428") * 4)},
                 **{f"cScaleLabel{k}": "#ece4d8" for k in range(12)}}
MERMAID_THEME = "\n".join(["---", "config:", "  theme: base", "  themeVariables:"]
                          + [f'    {k}: "{v}"' for k, v in _MM_VARIABLES.items()] + ["---"])
FRISE_PAR_ANNEE = 8          # au-delà, « et N autres » sur l'année
INCONNU = object()          # contenu d'une fiche liée qu'on ne peut pas calculer maintenant : la note n'est pas touchée
DUREE_SILLAGE = timedelta(hours=24)
_ANNUAIRE: maison.Annuaire | None = None


class CoffreAbsent(ErreurCarnet):
    """Coffre non monté ou dossier Personnes/ absent."""


def _annuaire() -> maison.Annuaire:
    global _ANNUAIRE
    if _ANNUAIRE is None:
        _ANNUAIRE = maison.Annuaire()
    return _ANNUAIRE


def racine(c: Carnet) -> Path:
    """Dossier du coffre, après vérification du garde-fou (CoffreAbsent sinon)."""
    r = c.cfg.contacts
    if not r:
        raise CoffreAbsent("Coffre Contacts non configuré (volume /contacts absent de la stack).")
    if not r.is_dir():
        raise CoffreAbsent("Coffre Contacts introuvable : le dossier partagé chiffré n'est sans doute pas monté.")
    if not (r / DOSSIER).is_dir():
        raise CoffreAbsent(f"Coffre Contacts : dossier « {DOSSIER} » absent. Si le coffre est bien monté, "
                           f"crée ce dossier (garde-fou contre un dossier chiffré non monté).")
    return r


def personne_a_note(f: dict) -> bool:
    return bool(f.get("prenom") or f.get("nom"))


# ---------------------------------------------------------------- lecture du coffre (en-têtes seulement)

def _entete_brute(p: Path) -> str | None:
    try:
        with p.open(encoding="utf-8") as f:
            tete = f.read(4000)
    except (OSError, UnicodeDecodeError):
        return None
    return tete.split("\n---", 1)[0] if tete.startswith("---") else None


def _inventaire(r: Path) -> dict:
    """Notes de carnet déjà dans le coffre, retrouvées par leur identifiant, partout (hors dossiers cachés).
    Les fiches liées de la 3.0 sont comptées sous leur nouvelle clé (« journaux » → « pepites »…)."""
    inv = {"contacts": {}, "index": {}, "evenements": {}}
    for p in r.rglob("*.md"):
        if any(part.startswith(".") for part in p.relative_to(r).parts):
            continue
        tete = _entete_brute(p)
        if not tete:
            continue
        if (m := INDEX_DE.search(tete)) and (t := INDEX_TYPE.search(tete)):
            typ = ANCIENS.get(t.group(1), (t.group(1),))[0]
            inv["index"].setdefault((m.group(1), typ), p)
        elif m := EVT.search(tete):
            inv["evenements"].setdefault(m.group(1), p)
        elif m := ID.search(tete):
            inv["contacts"].setdefault(m.group(1), p)
    return inv


def _nom_de_fichier(nom: str, ident: str) -> str:
    propre = " ".join(INTERDITS.sub(" ", nom).split()).strip(" .")
    return propre or ident


# ---------------------------------------------------------------- rendu

def _yaml(v: str) -> str:
    """Valeur YAML sûre sur une ligne (entre guillemets si besoin)."""
    if v == "" or re.search(r"[:#\[\]{},&*!|>'\"%@`]", v) or v.strip() != v or v.lower() in ("oui", "non", "yes", "no",
                                                                                               "true", "false", "null"):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def _entete_carnet(c: Carnet, f: dict, ident: str, statut: str, le: str) -> list[str]:
    nom = nom_affiche(f)
    alias = [nom] + ([f["surnom"]] if f.get("surnom") and f["surnom"] != nom else [])
    lignes = [f"personne_id: {ident}", "type: contact", "tags:", f"  - {TAG_CONTACT}", f"nom: {_yaml(nom)}", "aliases:"] + [f"  - {_yaml(a)}" for a in alias]
    groupes = sorted(f.get("groupes") or [])
    lignes += ["groupes:"] + [f"  - {_yaml(g)}" for g in groupes] if groupes else ["groupes: []"]
    if f.get("anniversaire"):
        lignes.append(f"naissance: {_yaml(f['anniversaire'])}")
    lignes.append(f"allergies: {alimentation.statut(alimentation.de_personne(c, ident))}")
    lignes += [f"carnet: {statut}", f"maj_carnet: {le}"]
    return lignes


def _liste(titre: str, valeurs: list[str]) -> list[str]:
    return [f"- **{titre}** : {', '.join(valeurs)}"] if valeurs else []


def _lien_note(valeur: str, cibles: dict[str, str]) -> str:
    cible = cibles.get(cle_texte(valeur))
    if not cible:
        return valeur
    return f"[[{cible}]]" if cible == valeur else f"[[{cible}|{valeur}]]"


def _lien(stem: str, texte: str | None = None) -> str:
    return f"[[{stem}]]" if not texte or texte == stem else f"[[{stem}|{texte}]]"


def _date(v: str) -> str:
    return f"{v[8:10]}/{v[5:7]}/{v[:4]}" if len(v) >= 10 else v


# ---------------------------------------------------------------- 3.2 : schémas Mermaid (arbre, frise)

def _mm_libelle(t: str) -> str:
    """Texte sûr dans un libellé Mermaid entre guillemets."""
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t.replace("&", "et").replace('"', "#quot;").replace("<", "‹").replace(">", "›")


def _mm_frise(t: str) -> str:
    """Texte sûr dans une frise Mermaid (« : » sépare les événements, « # » et « ; » coupent la ligne)."""
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return re.sub(r"\s*[:;#]\s*", " – ", t).replace("%%", "%").strip(" –")


PARENTS = ("père", "mère", "parent")
FRATRIE = ("frère", "sœur", "frère ou sœur")


Relation = tuple  # (type, nom) ou (type, nom, frozenset des noms de SES parents, d'après Treemich)


def arbre_mermaid(nom: str, lignes: list[Relation]) -> str:
    """Bloc ```mermaid de la fiche « Arbre » : parents au-dessus, la personne avec sa fratrie et son conjoint, enfants
    en dessous. Relations directes seulement (celles de Treemich gardées par carnet).
    3.4 : un point d'union relie deux parents (en haut) et la personne à chaque conjoint (en bas) ; les enfants d'un
    couple partent de son point d'union, la fratrie partagée part du point d'union des parents. Avec les parents de
    chacun (3e élément, lu dans Treemich), un demi-frère, une demi-sœur ou un enfant d'une autre union part du seul
    parent commun ; sans cette information, comme avant : sous le couple."""
    l = ["```mermaid", MERMAID_THEME, "flowchart TD", f'  moi["{_mm_libelle(nom)}"]']
    rel = [(x[0], x[1], frozenset(x[2]) if len(x) > 2 and x[2] else frozenset()) for x in lignes]
    parents = [r for r in rel if r[0] in PARENTS]
    fratrie = [r for r in rel if r[0] in FRATRIE]
    conjoints = [r for r in rel if r[0] == "conjoint"]
    enfants = [r for r in rel if r[0] == "enfant"]
    autres = [r for r in rel if r not in parents + fratrie + conjoints + enfants]
    k = 0
    u = 0

    def noeud(t: str, n: str) -> str:
        nonlocal k
        k += 1
        l.append(f'  n{k}["{_mm_libelle(n)}<br/><small>{_mm_libelle(t)}</small>"]')
        return f"n{k}"

    def union(*sources: str) -> str:
        """Point d'union : les sources au-dessus (traits sans flèche), les enfants partent de lui."""
        nonlocal u
        u += 1
        l.append(f'  u{u}((" "))')
        for x in sources:
            l.append(f"  {x} --- u{u}")
        return f"u{u}"

    # En haut : les parents, et leur point d'union quand ils sont deux
    ids_parents = {n: noeud(t, n) for t, n, _ in parents}
    haut = union(*ids_parents.values()) if len(ids_parents) >= 2 else None
    if haut:
        l.append(f"  {haut} --> moi")
    else:
        for i in ids_parents.values():
            l.append(f"  {i} --> moi")

    def source_fratrie(ses_parents: frozenset) -> str | None:
        communs = [ids_parents[n] for n in ids_parents if n in ses_parents]
        if ses_parents and len(communs) == 1 and len(ids_parents) >= 2:
            return communs[0]                                   # demi-frère, demi-sœur : le parent commun seul
        if haut:
            return haut
        return next(iter(ids_parents.values()), None)
    for t, n, sp in fratrie:
        i = noeud(t, n)
        src = source_fratrie(sp)
        l.append(f"  {src} --> {i}" if src else f"  moi --- {i}")

    # En bas : un point d'union par conjoint ; chaque enfant part du couple dont il est l'enfant
    unions = {}
    for t, n, _ in conjoints:
        unions[n] = union("moi", noeud(t, n))
    for t, n, sp in enfants:
        i = noeud(t, n)
        if sp:
            avec = [c for c in unions if c in sp]
            src = unions[avec[0]] if avec else "moi"            # enfant d'une autre union : de la personne seule
        else:
            src = next(iter(unions.values())) if len(unions) == 1 else "moi"
        l.append(f"  {src} --> {i}")
    for t, n, _ in autres:
        l.append(f"  moi -.- {noeud(t, n)}")
    l += ["  classDef moi fill:#c9714a,stroke:#c9714a,color:#1a1714", "  class moi moi"]
    if u:
        l += ["  classDef union fill:#c9a96e,stroke:#c9a96e,color:#c9a96e",
              "  class " + ",".join(f"u{i}" for i in range(1, u + 1)) + " union"]
    l.append("```")
    return "\n".join(l)


def frise_mermaid(evts: list[tuple[str, str]]) -> str | None:
    """Bloc ```mermaid « timeline » d'une personne : [(date AAAA-MM-JJ, titre)] → une colonne par année. None si vide."""
    par_annee: dict[str, list[str]] = {}
    for date, titre in sorted(evts):
        annee = (date or "")[:4]
        if len(annee) == 4 and annee.isdigit() and _mm_frise(titre):
            par_annee.setdefault(annee, []).append(_mm_frise(titre))
    if not par_annee:
        return None
    l = ["```mermaid", MERMAID_THEME, "timeline"]
    for annee, titres in sorted(par_annee.items()):
        vus = titres[:FRISE_PAR_ANNEE]
        if len(titres) > FRISE_PAR_ANNEE:
            vus.append(f"et {len(titres) - FRISE_PAR_ANNEE} autres")
        l.append(f"  {annee} : " + " : ".join(vus))
    l.append("```")
    return "\n".join(l)


def bloc(c: Carnet, uid: str, f: dict, ident: str, cibles: dict[str, str], index: dict[str, str] | None = None,
         frise: list[tuple[str, str]] | None = None) -> str:
    """Partie écrite par carnet dans la note Contact (sans les marqueurs). `index` : type → nom de la fiche liée ;
    `frise` (3.2) : [(date, titre)] des événements de la personne."""
    index = index or {}
    nom = nom_affiche(f)
    l = [f"# {nom}", "", "## Fiche"]
    g = genres.de(c, uid)
    simples = [("Surnom", f.get("surnom")), ("Genre", g), ("Naissance", date_lisible(f.get("anniversaire") or "")),
               ("Fête", date_lisible(attentes.fete_de(f)[0] or "")), ("Mariage", date_lisible(f.get("mariage") or "")),
               ("Décès", date_lisible(attentes.decedes(c).get(uid) or f.get("deces") or "")),
               ("Société", f.get("societe")), ("Service", f.get("service")), ("Fonction", f.get("fonction"))]
    l += [f"- **{t}** : {v}" for t, v in simples if v]
    l += _liste("Téléphones", [f"{x.get('affichage') or x.get('valeur')} ({x.get('type') or 'autre'})"
                               for x in f.get("telephones") or []])
    l += _liste("Courriels", [f"{x.get('valeur')} ({x.get('type') or 'autre'})" for x in f.get("courriels") or []])
    l += _liste("Adresses", ["; ".join([", ".join(v for v in (x.get("rue"), " ".join(p for p in (x.get("cp"), x.get("ville"))
                                                                                     if p), x.get("pays")) if v)
                                        + f" ({x.get('type') or 'autre'})"]) for x in f.get("adresses") or []])
    l += _liste("Sites", [x.get("valeur", "") for x in f.get("sites") or [] if x.get("valeur")])
    l += _liste("Groupes", sorted(f.get("groupes") or []))
    # 3.1 : statut des allergies seulement ; le détail est dans la fiche liée « Allergies »
    st = alimentation.statut(alimentation.de_personne(c, ident))
    allergies = alimentation.STATUTS[st] + (f" — {_lien(index['allergies'], 'détail')}" if "allergies" in index else "")
    l.append(f"- **Allergies et intolérances** : {allergies}")
    proches = [(x.get("type") or "proche", x.get("valeur", "")) for x in f.get("noms_associes") or [] if x.get("valeur")]
    if proches:
        l += ["", "## Famille et proches"] + [f"- {t} : {_lien_note(v, cibles)}" for t, v in proches]
    if index:
        l += ["", "## Ses fiches"] + [f"- {_lien(index[t], TYPES[t])}" for t in TYPES if t in index]
    if frise and (schema := frise_mermaid(frise)):
        l += ["", "## Frise", "", schema]
    if f.get("notes"):
        l += ["", "## Notes de la fiche (iCloud)", *[f"> {x}" if x else ">" for x in f["notes"].splitlines()]]
    lien = c.liaisons().get(uid, {})
    liens = []
    if (adr := _annuaire().adresse("carnet")):
        liens.append(f"- [Fiche dans carnet]({adr}/#/contacts/{uid})")
    if lien.get("immich"):
        if (adr := _annuaire().adresse("Immich")):
            liens.append(f"- [Photos dans Immich]({adr}/people/{lien['immich']})")
        if (adr := _annuaire().adresse("Sillage")):
            liens.append(f"- [Chemin de vie dans Sillage]({adr}/#/chemin/{lien['immich']})")
    ids = [f"identifiant maison `{ident}`", f"iCloud `{uid}`"] + \
          [f"{s} `{lien[s]}`" for s in ("immich", "treemich") if lien.get(s)]
    l += ["", "## Liens", *liens, f"- Identifiants : {', '.join(ids)}"]
    return "\n".join(l)


# ---------------------------------------------------------------- événements (partagés entre personnes)

def _ligne_personne(nature: str, role: str, donnees: dict) -> list[str]:
    """Ce qui est dit d'une personne sous son nom dans une note d'événement (et dans sa fiche liée)."""
    l = []
    if role:
        l.append(f"  - Rôle : {role}")
    if nature == "douze_points":
        if donnees.get("moyenne") not in (None, ""):
            l.append(f"  - Note moyenne : {donnees['moyenne']}")
        if donnees.get("classement") not in (None, ""):
            l.append(f"  - Classement : {donnees['classement']}")
        if donnees.get("top3"):
            l.append(f"  - Son podium : {', '.join(str(x) for x in donnees['top3'][:3])}")
        for r in (donnees.get("remarques") or [])[:5]:
            if isinstance(r, dict) and r.get("commentaire"):
                pts = r.get("points")
                l.append(f"  - {r.get('pays', '?')}" + (f" ({pts} point{'s' if pts not in (0, 1) else ''})" if pts is not None else "")
                         + f" : « {r['commentaire']} »")
    else:
        for k, v in donnees.items():
            if isinstance(v, (str, int, float)) and str(v).strip():
                l.append(f"  - {k.replace('_', ' ').capitalize()} : {v}")
    return l


def evenements(c: Carnet, ids: dict[str, str]) -> dict[str, dict]:
    """evenement_id → {nature, dossier, titre, date, personnes: [ident], lignes: {ident: [str]}, autres: [str], lien, appli,
    resume, details: {ident: dict}}. Seulement les personnes qui ont une fiche (les autres signataires sont nommés dans
    `autres`)."""
    actifs = set(ids.values())
    evts: dict[str, dict] = {}

    def nouvel(eid, **champs):
        base = {"sous_titre": "", "evenement": "", "personnes": [], "lignes": {}, "autres": [], "lien": "", "appli": "",
                "resume": "", "details": {}}
        return evts.setdefault(eid, {**base, **champs})

    # Numéros parus (La Récidive, La Gazette) : un événement par numéro (clé « recidive-AAAA-MM-JJ »)
    for l in c.base.tous("SELECT * FROM journaux_parus ORDER BY le DESC, cle DESC"):
        if l["personne"] not in actifs:
            continue
        p = {"cle": l["cle"], "le": l["le"], **json.loads(l["donnees"])}
        journal, nature = JOURNAUX.get(p.get("journal") or "", (p.get("journal") or "Journal", "recidives"))
        e = nouvel("paru-" + l["cle"], nature=nature, dossier=DOSSIERS[nature], date=l["le"],
                   titre=journal + (f" N° {p['numero']}" if p.get("numero") else ""),
                   sous_titre=p.get("titre") or "", evenement=p.get("evenement") or "",
                   lien=p.get("lien") or "", appli="gazette" if p.get("lien") else "")
        e["personnes"].append(l["personne"])
        e["lignes"][l["personne"]] = [f"  - Photo : {x}" for x in p.get("descriptions") or []] + \
                                     [f"  - Imprimé : {x}" for x in p.get("textes") or []]
    # Livre d'or : un événement par séjour (date de début + chambre)
    for l in c.base.tous("SELECT * FROM livre_or ORDER BY le DESC, id"):
        chambre = l["chambre"] or ""
        cle = "livre-" + l["le"] + ("-" + re.sub(r"[^a-z0-9]+", "-", cle_texte(chambre)).strip("-") if chambre else "")
        e = nouvel(cle, nature="livre_or", dossier=DOSSIERS["livre_or"], date=l["le"],
                   titre="Livre d'or" + (f" ({_nom_de_fichier(chambre, '')})" if chambre else ""), chambre=chambre)
        texte = [f"  > {x}" if x else "  >" for x in l["message"].splitlines()]
        if l["personne"] in actifs:
            if l["personne"] not in e["personnes"]:
                e["personnes"].append(l["personne"])
            e["lignes"].setdefault(l["personne"], []).extend(texte)
        else:
            e["autres"].append(f"- **{l['nom']}** (pas encore rattaché dans carnet) :")
            e["autres"].extend(texte)
    # 3.1 : événements envoyés par les applis (séjours de Gazette, soirées de Douze points…)
    for e_app in evts_.tous(c):
        nature = NATURE.get(e_app["type"])
        if not nature:
            continue
        titre = e_app["titre"] or evts_.TYPES[e_app["type"]]
        e = nouvel(f"evt-{e_app['appli']}-{e_app['cle']}", nature=nature, dossier=DOSSIERS[nature], date=e_app["date"],
                   titre=titre, lien=e_app["lien"], appli=e_app["appli"], resume=e_app["resume"])
        for p in e_app["personnes"]:
            if p["personne"] not in actifs or p["personne"] in e["personnes"]:
                continue
            e["personnes"].append(p["personne"])
            e["lignes"][p["personne"]] = _ligne_personne(nature, p["role"], p["donnees"])
            e["details"][p["personne"]] = p["donnees"]
    return evts


def _stem_evenement(e: dict) -> str:
    return _nom_de_fichier(f"{e['date']} — {e['titre']}", "evenement")


def _entete_evenement(eid: str, e: dict, le: str) -> list[str]:
    return [f"evenement_id: {eid}", "type: evenement", "tags:", f"  - {TAG_EVENEMENT}", f"evenement: {e['nature']}", f"date: {_yaml(e['date'])}",
            "personnes:"] + [f"  - {i}" for i in e["personnes"]] + ["carnet: présente", f"maj_carnet: {le}"]


def _bloc_evenement(e: dict, noms: dict[str, str]) -> str:
    l = [f"# {e['titre']}", "", f"- **Date** : {_date(e['date'])}"]
    if e["sous_titre"]:
        l.append(f"- **Titre** : {e['sous_titre']}")
    if e["evenement"]:
        l.append(f"- **Événement** : {e['evenement']}")
    if e.get("resume"):
        l.append(f"- **Résumé** : {e['resume']}")
    if e.get("lien"):
        l.append(f"- [Ouvrir dans {APPLIS.get(e.get('appli') or '', e.get('appli') or 'l’appli')}]({e['lien']})")
    l += ["", "## Personnes"]
    for i in e["personnes"]:
        l.append(f"- {_lien(noms[i])}" + (" :" if e["lignes"].get(i) else ""))
        l += e["lignes"].get(i, [])
    if e["autres"]:
        l += ["", "## Autres signataires"] + e["autres"]
    return "\n".join(l)


# ---------------------------------------------------------------- Sillage et Arbre

def _lire_sillage_http(c: Carnet, immich_id: str) -> list[dict] | None:
    """Étapes d'une personne dans Sillage ({nom, annee}), ou None si Sillage ne répond pas."""
    import httpx
    adresse = _annuaire().adresse("Sillage", repli="http://sillage:8093")
    jeton = maison.jeton_a_envoyer()
    if not adresse or not jeton:
        return None
    try:
        with c.http("sillage") as client:
            r = client.get(f"{adresse}/externe/personnes/{immich_id}/etapes", timeout=8,
                           headers={"Authorization": f"Bearer {jeton}"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        donnees = r.json()
        etapes = donnees.get("etapes", donnees) if isinstance(donnees, dict) else donnees
        return [{"nom": str(x.get("nom") or ""), "annee": x.get("annee")} for x in etapes or [] if isinstance(x, dict)]
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


LIRE_SILLAGE = _lire_sillage_http      # remplacé par les tests


def sillage(c: Carnet, immich_ids: list[str]) -> dict[str, list[dict]]:
    """immich_id → étapes, lues au plus une fois par jour et par personne (gardées dans la base). Une personne dont
    Sillage n'a pas répondu garde ses dernières étapes connues ; sans étapes connues, elle n'est pas dans le résultat."""
    cache = c.base.lire("coffre_sillage", {}) or {}
    limite = iso(maintenant() - DUREE_SILLAGE)
    change = False
    for imm in immich_ids:
        connu = cache.get(imm)
        if connu and connu.get("le", "") > limite:
            continue
        etapes = LIRE_SILLAGE(c, imm)
        if etapes is None:
            continue
        cache[imm] = {"le": iso(maintenant()), "etapes": etapes}
        change = True
    if change:
        c.base.ecrire("coffre_sillage", cache)
    return {imm: cache[imm]["etapes"] for imm in immich_ids if imm in cache}


def arbre(c: Carnet) -> dict[str, list[tuple]] | None:
    """uid → [(type, nom de l'autre personne)] d'après les relations de Treemich gardées en mémoire ;
    None si Treemich n'a pas encore été lu depuis le démarrage."""
    from . import liaisons
    from .liens import relations_de
    d = c.memo_present("liens", liaisons.DUREE_CACHE)
    if not d or not d.get("treemich_ok"):
        return None
    g = genres.par_treemich(c, d)
    noms_tree = {p["id"]: p.get("nom") or "" for p in d.get("treemich") or []}
    uid_par_tree = {v["treemich"]: u for u, v in c.liaisons().items() if v.get("treemich")}
    fiches = c.fiches()
    rels = d.get("relations") or []

    def nom_de(tid_: str) -> str:
        autre_uid = uid_par_tree.get(tid_)
        return nom_affiche(fiches[autre_uid]) if autre_uid in fiches else noms_tree.get(tid_, "")
    res: dict[str, list[tuple]] = {}
    for uid, lien in c.liaisons().items():
        tid = lien.get("treemich")
        if not tid or uid not in fiches:
            continue
        lignes = []
        for autre, type_ in relations_de(tid, rels, g):
            nom = nom_de(autre)
            if not nom:
                continue
            if type_ in ("enfant",) + FRATRIE:                   # 3.4 : ses parents, pour le placer sous le bon couple
                ses = frozenset(x for x in (nom_de(p) for p, t in relations_de(autre, rels, g) if t in PARENTS) if x)
                lignes.append((type_, nom, ses))
            else:
                lignes.append((type_, nom))
        res[uid] = lignes
    return res


# ---------------------------------------------------------------- fiches liées (une par personne et par type)

def _contenu_index(c: Carnet, typ: str, ident: str, nom_contact: str, liens_evts: list[str], extra=None):
    """Bloc d'une fiche liée ; None si la personne n'a rien de ce type ; INCONNU si on ne peut pas le savoir
    maintenant (Sillage injoignable, Treemich pas encore lu) : la note existante n'est alors pas touchée."""
    tete = [f"# {nom_contact} — {TYPES[typ]}", "", f"Note Contact : {_lien(nom_contact)}"]
    if typ == "allergies":
        a = alimentation.de_personne(c, ident)
        if not a:
            return None
        l = tete + ["", f"- **Statut** : {alimentation.STATUTS[alimentation.statut(a)]}"]
        if a.get("verifiee_le"):
            l.append(f"- **Vérifiée le** : {date_lisible(a['verifiee_le'])}")
        for k in alimentation.LISTES:
            l += _liste(alimentation.LIBELLES[k], a[k])
        return "\n".join(l)
    if typ == "pepites":
        lignes = journaux.resume_coffre(c, ident)
        if not lignes:
            return None
        return "\n".join(tete + [x for x in lignes if not x.startswith("## ")])
    if typ == "gazette":
        n = evts_.compteur(c, ident, "gazette", "photos_scandale")
        if not liens_evts and not n:
            return None
        l = tete + ["", f"- **Photos scandale** : {n if n is not None else 'pas encore envoyé par Gazette'}"]
        return "\n".join(l + ([""] + liens_evts if liens_evts else []))
    if typ == "sillage":
        if extra is INCONNU:
            return INCONNU
        if not extra:
            return None
        etapes, lien = extra
        l = tete + [""] + [f"- {e['annee'] or '?'} — {e['nom']}" for e in etapes]
        if lien:
            l += ["", f"[Chemin de vie dans Sillage]({lien})"]
        return "\n".join(l)
    if typ == "arbre":
        if extra is INCONNU:
            return INCONNU
        if not extra:
            return None
        lignes, cibles, lien = extra
        l = tete + ["", arbre_mermaid(nom_contact, lignes), ""] + [f"- {x[0]} : {_lien_note(x[1], cibles)}" for x in lignes]
        if lien:
            l += ["", f"[Arbre dans Treemich]({lien})"]
        return "\n".join(l)
    if not liens_evts:
        return None
    return "\n".join(tete + [""] + liens_evts)


def _entete_index(ident: str, typ: str, le: str) -> list[str]:
    return [f"index_de: {ident}", "type: index", "tags:", f"  - {TAG_FICHE}", f"index_type: {typ}", "carnet: présente", f"maj_carnet: {le}"]


def _ligne_index(nature: str, stem: str, e: dict, ident: str) -> str:
    """Ligne d'une fiche liée qui renvoie à une note d'événement (résumé + lien)."""
    plus = []
    if e["sous_titre"]:
        plus.append(f"« {e['sous_titre']} »")
    if nature == "douze_points":
        d = e["details"].get(ident) or {}
        if d.get("moyenne") not in (None, ""):
            plus.append(f"note {d['moyenne']}")
        if d.get("classement") not in (None, ""):
            plus.append(f"classement {d['classement']}")
    return f"- {_lien(stem)}" + (f" — {', '.join(plus)}" if plus else "")


# ---------------------------------------------------------------- assemblage avec l'existant

def _separer(texte: str) -> tuple[list[str], str]:
    """(lignes de l'en-tête, reste du texte). Sans en-tête : ([], texte)."""
    if texte.startswith("---\n"):
        fin = texte.find("\n---", 4)
        if fin != -1:
            apres = texte[fin + 4:]
            return texte[4:fin].split("\n"), apres[1:] if apres.startswith("\n") else apres
    return [], texte


def _entete_gardee(lignes: list[str]) -> list[str]:
    """Lignes de l'en-tête qui ne sont pas à carnet (clés ajoutées à la main), avec leurs lignes de suite."""
    garde, sauter = [], False
    for ligne in lignes:
        if re.match(r"^[^\s#][^:]*:", ligne):
            sauter = ligne.split(":", 1)[0].strip() in CLES_CARNET
        if not sauter:
            garde.append(ligne)
    return garde


def _tags(lignes: list[str]) -> list[str]:
    """Étiquettes de l'en-tête existant (`tags: a`, `tags: [a, b]`, `tags: a, b` ou liste en tirets)."""
    res, dedans = [], False
    for ligne in lignes:
        m = re.match(r"^tags:\s*(.*)$", ligne)
        if m:
            dedans = True
            v = m.group(1).strip()
            if v.startswith("[") and v.endswith("]"):
                v = v[1:-1]
            res += [x for x in (t.strip().strip("'\"").lstrip("#") for t in v.split(",")) if x]
            continue
        if dedans:
            m = re.match(r"^\s+-\s*(.+)$", ligne)
            if m:
                res.append(m.group(1).strip().strip("'\"").lstrip("#"))
                continue
            if ligne.strip():
                dedans = False
    return res


def _fusionner_tags(entete: list[str], anciennes: list[str]) -> list[str]:
    """3.2 : l'étiquette de carnet d'abord, puis celles ajoutées à la main (gardées, sans doublon)."""
    if "tags:" not in entete:
        return entete
    i = entete.index("tags:")
    j = i + 1
    while j < len(entete) and entete[j].startswith("  - "):
        j += 1
    tags = [t[4:] for t in entete[i + 1:j]]
    tags += [t for t in _tags(anciennes) if t not in tags]
    return entete[:i + 1] + [f"  - {_yaml(t)}" for t in tags] + entete[j:]


def assembler(existant: str | None, entete: list[str], contenu: str) -> str | None:
    """Nouveau texte de la note, ou None si l'existant n'a plus de bloc carnet (rien n'est réécrit)."""
    if existant is None:
        return "---\n" + "\n".join(entete) + f"\n---\n{DEBUT}\n{contenu}\n{FIN}\n\n{ZONE_LIBRE}"
    lignes, corps = _separer(existant)
    tete = "---\n" + "\n".join(_fusionner_tags(entete, lignes)) + "\n"
    m, fin = MOTIF_DEBUT.search(corps), corps.find(FIN)
    if not m or fin == -1 or fin < m.end():
        return None
    gardees = _entete_gardee(lignes)
    tete += ("\n".join(gardees) + "\n") if gardees else ""
    return f"{tete}---\n{corps[:m.start()]}{DEBUT}\n{contenu}\n{corps[fin:]}"


def _sans_date(texte: str) -> str:
    return re.sub(r"^maj_carnet: .*$", "", texte, count=1, flags=re.M)


def _ecrire(chemin: Path, texte: str) -> None:
    """Écriture atomique dans le même dossier (l'éditeur ne voit jamais une note à moitié écrite)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".carnet-", suffix=".tmp", dir=str(chemin.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(texte)
        os.replace(tmp, chemin)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _modifier_statut(texte: str, statut: str, le: str) -> str:
    lignes, corps = _separer(texte)
    if not lignes:
        return texte
    lignes = [l for l in lignes if not re.match(r"^(carnet|maj_carnet):", l)] + [f"carnet: {statut}", f"maj_carnet: {le}"]
    return "---\n" + "\n".join(lignes) + "\n---\n" + corps


def _poser(chemin: Path, existe: bool, entete: list[str], contenu: str, ecrire: bool, bilan: dict, cle: str) -> None:
    """Écrit une note (création ou mise à jour du bloc) et compte dans bilan[cle] (« crees », « mises_a_jour »…).
    La note est relue juste avant d'être écrite (3.1) : une modification faite entre-temps dans SilverBullet est gardée
    hors du bloc."""
    existant = chemin.read_text(encoding="utf-8") if existe else None
    texte = assembler(existant, entete, contenu)
    if texte is None:
        bilan["sans_bloc"] += 1
        return
    if existant is not None and _sans_date(texte) == _sans_date(existant):
        bilan["inchangees"] += 1
        return
    if ecrire:
        _ecrire(chemin, texte)
    bilan[cle if existant is None else "mises_a_jour"] += 1


# ---------------------------------------------------------------- rangement (formes précédentes, changement de nom)

def _titres(typ: str) -> list[str]:
    """Titres possibles du fichier d'une fiche liée : l'actuel, puis l'ancien (3.0)."""
    return [TYPES[typ]] + [ancien for (nouveau, ancien) in ANCIENS.values() if nouveau == typ]


def _ranger(r: Path, ident: str, actuel: Path, base: str, inv: dict, ecrire: bool, bilan: dict) -> Path:
    """Chemin de la note Contact d'une personne existante, après rangement éventuel :
    - forme 2.28 (`Personnes/<x>.md`) → `Personnes/<x>/<x>.md` (une fois) ;
    - nom changé (`Personnes/<ancien>/<ancien>.md`) → `Personnes/<base>/<base>.md`, fiches liées comprises,
      seulement si le nouveau dossier est libre. Une note rangée ailleurs par Julien n'est jamais déplacée."""
    dossier = r / DOSSIER
    try:
        rel = actuel.relative_to(dossier)
    except ValueError:
        return actuel
    if len(rel.parts) == 1:                                         # forme 2.28
        cible = dossier / actuel.stem / actuel.name
        if cible.exists():
            return actuel
        if ecrire:
            cible.parent.mkdir(parents=True, exist_ok=True)
            os.replace(actuel, cible)
        bilan["rangees"] += 1
        return cible if ecrire else actuel
    if len(rel.parts) == 2 and rel.parts[0] == actuel.stem and actuel.stem != base:   # nom changé
        nouveau = dossier / base
        if nouveau.exists():
            return actuel
        ancien = actuel.stem
        if ecrire:
            os.replace(actuel.parent, nouveau)
            os.replace(nouveau / actuel.name, nouveau / f"{base}.md")
            for (i, typ), p in list(inv["index"].items()):
                if i != ident or p.parent != actuel.parent:
                    continue
                vieux = nouveau / p.name
                cible = vieux
                for titre in _titres(typ):
                    if p.stem == f"{ancien} — {titre}":
                        cible = nouveau / f"{base} — {titre}.md"
                if cible != vieux and vieux.exists() and not cible.exists():
                    os.replace(vieux, cible)
                inv["index"][(i, typ)] = cible if cible.exists() else vieux
        bilan["renommees"] += 1
        return nouveau / f"{base}.md" if ecrire else actuel
    return actuel


def _renommer_index_30(chemin_contact: Path, typ: str, p: Path, ecrire: bool, bilan: dict) -> Path:
    """3.0 → 3.1 : « <Nom> — Pour les journaux » → « <Nom> — Pépites » (une fois, si le nom est libre)."""
    for nouveau, ancien in ANCIENS.values():
        if nouveau == typ and p.stem == f"{chemin_contact.stem} — {ancien}":
            cible = p.with_name(f"{chemin_contact.stem} — {TYPES[typ]}.md")
            if cible.exists():
                return p
            if ecrire:
                os.replace(p, cible)
            bilan["rangees"] += 1
            return cible if ecrire else p
    return p


def _deplacer_evenement_30(r: Path, p: Path, ecrire: bool, bilan: dict) -> Path:
    """3.0 → 3.1 : une note d'événement dans `Événements/La Récidive/` passe dans `Événements/Récidives/` (une fois)."""
    try:
        rel = p.relative_to(r / EVENEMENTS)
    except ValueError:
        return p
    if len(rel.parts) != 2 or rel.parts[0] not in DOSSIERS_ANCIENS:
        return p
    cible = r / EVENEMENTS / DOSSIERS_ANCIENS[rel.parts[0]] / p.name
    if cible.exists():
        return p
    if ecrire:
        cible.parent.mkdir(parents=True, exist_ok=True)
        os.replace(p, cible)
        try:
            p.parent.rmdir()            # l'ancien dossier, seulement s'il est vide
        except OSError:
            pass
    bilan["rangees"] += 1
    return cible if ecrire else p


# ---------------------------------------------------------------- synchroniser

def synchroniser(c: Carnet, ecrire: bool = True) -> dict:
    """Écrit (ou, avec ecrire=False, compte seulement) les notes du coffre. Renvoie le bilan."""
    r = racine(c)
    if ecrire:
        c.exiger_ecriture("Coffre Contacts")
    le = iso(maintenant())[:10]
    fiches, ids = c.fiches(), personnes.ids(c)
    gens = {uid: f for uid, f in fiches.items() if personne_a_note(f)}
    inv = _inventaire(r)
    bilan = {"le": iso(maintenant()), "crees": 0, "mises_a_jour": 0, "inchangees": 0, "sans_bloc": 0,
             "retirees": 0, "rangees": 0, "renommees": 0, "index": 0, "evenements": 0, "erreurs": [], "ecrit": ecrire}

    # 1. Chemin de la note Contact de chaque personne (existante, rangée, ou à créer) ; noms pour les liens
    chemins: dict[str, Path] = {}
    pris = {p.resolve() for p in inv["contacts"].values()}
    for uid, f in sorted(gens.items(), key=lambda x: nom_affiche(x[1]).casefold()):
        ident = ids[uid]
        base = _nom_de_fichier(nom_affiche(f), ident)
        if ident in inv["contacts"]:
            try:
                chemins[uid] = _ranger(r, ident, inv["contacts"][ident], base, inv, ecrire, bilan)
            except OSError as exc:
                bilan["erreurs"].append(f"{base} : {exc.strerror or exc}")
                chemins[uid] = inv["contacts"][ident]
            continue
        dossier = r / DOSSIER / base
        if dossier.exists() or (dossier / f"{base}.md").resolve() in pris:
            base = f"{base} ({ident})"
            dossier = r / DOSSIER / base
        chemins[uid] = dossier / f"{base}.md"
        pris.add(chemins[uid].resolve())
    cibles: dict[str, str] = {}
    noms: dict[str, str] = {}
    for uid, chemin in chemins.items():
        cibles.setdefault(cle_texte(nom_affiche(gens[uid])), chemin.stem)
        noms[ids[uid]] = chemin.stem

    # 2. Notes d'événement (partagées)
    evts = evenements(c, ids)
    par_personne: dict[tuple[str, str], list[str]] = {}
    frises: dict[str, list[tuple[str, str]]] = {}
    for eid, e in sorted(evts.items(), key=lambda x: (x[1]["date"], x[0]), reverse=True):
        e["personnes"] = [i for i in e["personnes"] if i in noms]
        existant = inv["evenements"].get(eid)
        if existant:
            try:
                existant = _deplacer_evenement_30(r, existant, ecrire, bilan)
            except OSError as exc:
                bilan["erreurs"].append(f"{existant.name} : {exc.strerror or exc}")
        chemin = existant or (r / EVENEMENTS / e["dossier"] / f"{_stem_evenement(e)}.md")
        if not existant and chemin.exists():
            chemin = chemin.with_name(f"{_stem_evenement(e)} ({eid}).md")
        for i in e["personnes"]:
            par_personne.setdefault((i, e["nature"]), []).append(_ligne_index(e["nature"], chemin.stem, e, i))
            frises.setdefault(i, []).append((e["date"], e["titre"]))
        try:
            avant = bilan["crees"]
            _poser(chemin, existant is not None, _entete_evenement(eid, e, le), _bloc_evenement(e, noms), ecrire, bilan, "crees")
            bilan["evenements"] += bilan["crees"] - avant
            bilan["crees"] = avant
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")

    # 3.5 : une note d'événement dont l'événement n'est plus dans carnet (mot du livre d'or supprimé, séjour annulé)
    # garde sa place mais son bloc dit qu'il a été retiré ; ce que Julien a écrit hors du bloc reste.
    for eid, chemin in inv["evenements"].items():
        if eid in evts:
            continue
        try:
            avant = bilan["crees"]
            _poser(chemin, True, [f"evenement_id: {eid}", "type: evenement", "tags:", f"  - {TAG_EVENEMENT}",
                                  "evenement: retire", "personnes: []", "carnet: retirée", f"maj_carnet: {le}"],
                   f"# {chemin.stem}\n\nCet événement n'est plus dans carnet (retiré). Rien d'autre n'a été effacé : "
                   "supprime cette note si elle ne sert plus.", ecrire, bilan, "crees")
            bilan["crees"] = avant
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")

    # 3. Sillage et Arbre (lus une fois pour tout le monde)
    liens = c.liaisons()
    immich = sorted({liens[u]["immich"] for u in gens if liens.get(u, {}).get("immich")})
    etapes = sillage(c, immich) if immich else {}
    relations = arbre(c)
    adr_sillage, adr_treemich = _annuaire().adresse("Sillage"), _annuaire().adresse("Treemich")

    # 4. Fiches liées puis note Contact de chaque personne
    for uid, f in gens.items():
        ident, chemin = ids[uid], chemins[uid]
        lien = liens.get(uid, {})
        index: dict[str, str] = {}
        for typ in TYPES:
            extra = None
            if typ == "sillage":
                imm = lien.get("immich")
                extra = (etapes[imm], f"{adr_sillage}/#/chemin/{imm}" if adr_sillage else "") if imm in etapes and etapes[imm] \
                    else (INCONNU if imm and imm not in etapes else None)
            elif typ == "arbre":
                tid = lien.get("treemich")
                if tid and relations is None:
                    extra = INCONNU
                elif tid and relations.get(uid):
                    extra = (relations[uid], cibles, f"{adr_treemich}/person/{tid}" if adr_treemich else "")
            contenu = _contenu_index(c, typ, ident, chemin.stem, par_personne.get((ident, typ), []), extra)
            existant = inv["index"].get((ident, typ))
            if existant:
                try:
                    existant = _renommer_index_30(chemin, typ, existant, ecrire, bilan)
                except OSError as exc:
                    bilan["erreurs"].append(f"{existant.name} : {exc.strerror or exc}")
            if contenu is INCONNU:
                if existant:
                    index[typ] = existant.stem
                continue
            if contenu is None and existant is None:
                continue
            p_idx = existant or chemin.parent / f"{chemin.stem} — {TYPES[typ]}.md"
            index[typ] = p_idx.stem
            if contenu is None:
                contenu = f"# {chemin.stem} — {TYPES[typ]}\n\nNote Contact : {_lien(chemin.stem)}\n\nPlus rien de ce type dans carnet."
            try:
                avant = bilan["crees"]
                _poser(p_idx, existant is not None, _entete_index(ident, typ, le), contenu, ecrire, bilan, "crees")
                bilan["index"] += bilan["crees"] - avant
                bilan["crees"] = avant
            except OSError as exc:
                bilan["erreurs"].append(f"{p_idx.name} : {exc.strerror or exc}")
        try:
            _poser(chemin, ident in inv["contacts"], _entete_carnet(c, f, ident, "présente", le),
                   bloc(c, uid, f, ident, cibles, index, frises.get(ident)), ecrire, bilan, "crees")
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")

    # 5. Personnes sans fiche (retirées ou fusionnées) : seule la clé « carnet » de l'en-tête change
    actifs = set(ids.values())
    for ident, chemin in inv["contacts"].items():
        if ident in actifs:
            continue
        l = c.base.un("SELECT remplacee_par FROM personnes WHERE id = ?", (ident,))
        statut = "fusionnée" if l and l["remplacee_par"] else "retirée"
        try:
            texte = chemin.read_text(encoding="utf-8")
            if re.search(rf"^carnet: {statut}$", texte, re.M):
                continue
            if ecrire:
                _ecrire(chemin, _modifier_statut(texte, statut, le))
            bilan["retirees"] += 1
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")
    if ecrire:
        c.base.ecrire("coffre_contacts", bilan)
        c.base.noter("coffre", f"Coffre Contacts : {bilan['crees']} note(s) créée(s), {bilan['mises_a_jour']} mise(s) à jour"
                     + (f", {bilan['evenements']} événement(s) et {bilan['index']} fiche(s) liée(s) créés" if bilan["evenements"] or bilan["index"] else "")
                     + (f", {bilan['rangees']} rangée(s)" if bilan["rangees"] else "")
                     + (f", {bilan['renommees']} renommée(s)" if bilan["renommees"] else "")
                     + (f", {bilan['sans_bloc']} sans bloc carnet" if bilan["sans_bloc"] else "")
                     + (f", {len(bilan['erreurs'])} erreur(s)" if bilan["erreurs"] else ""),
                     {k: bilan[k] for k in ("crees", "mises_a_jour", "inchangees", "sans_bloc", "retirees", "rangees",
                                            "renommees", "index", "evenements")})
    return bilan


# ---------------------------------------------------------------- copie de sécurité avant l'écriture de nuit

def copier_avant_nuit(c: Carnet, garder_jours: int = 7) -> Path | None:
    """3.1 (conseil) : copie des notes du coffre (hors dossiers cachés) dans `<state>/copies-coffre/AAAA-MM-JJ.tar.gz`
    avant l'écriture de nuit ; les copies de plus de `garder_jours` jours sont effacées. None si rien à copier."""
    import tarfile
    try:
        r = racine(c)
    except CoffreAbsent:
        return None
    dossier = Path(c.cfg.state) / "copies-coffre"
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"{iso(maintenant())[:10]}.tar.gz"
    if not cible.exists():
        tmp = cible.with_suffix(".tmp")
        with tarfile.open(tmp, "w:gz") as tar:
            for p in sorted(r.rglob("*.md")):
                rel = p.relative_to(r)
                if not any(part.startswith(".") for part in rel.parts):
                    tar.add(p, arcname=str(rel))
        os.replace(tmp, cible)
    limite = (maintenant() - timedelta(days=garder_jours)).date()
    for vieux in dossier.glob("*.tar.gz"):
        try:
            if datetime.strptime(vieux.name[:10], "%Y-%m-%d").date() < limite:
                vieux.unlink()
        except (ValueError, OSError):
            continue
    return cible


def resume(c: Carnet) -> str:
    b = c.base.lire("coffre_contacts")
    if not b:
        return "jamais synchronisé"
    return f"{b['crees'] + b['mises_a_jour']} note(s) écrite(s) à la dernière synchronisation"


def sante(c: Carnet) -> dict:
    """Voyant de Connexion : off (pas de volume), erreur (coffre non monté, écriture refusée), ok."""
    if not c.cfg.contacts:
        return {"etat": "off", "message": ""}
    try:
        racine(c)
    except CoffreAbsent as exc:
        return {"etat": "erreur", "message": str(exc)}
    b = c.base.lire("coffre_contacts") or {}
    if b.get("erreurs"):
        return {"etat": "erreur", "message": b["erreurs"][0]}
    return {"etat": "ok", "message": ""}

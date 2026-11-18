"""Synchronisation vers le coffre « Contacts » (2.28 ; nouvelle forme en 3.0, lu dans SilverBullet).

carnet est le maître des informations contact ; le coffre en est une vue, avec les notes de Julien.
À sens unique (3.0, décision du 18/11/2026 : coffre Contacts en lecture seule côté carnet) : carnet écrit,
il ne relit jamais ce que Julien écrit dans les notes.

Forme 3.0 (SilverBullet, qui n'ouvre pas une note dont le nom contient un point) :

- `Personnes/<Nom>/<Nom>.md` : la note Contact d'une personne (fiche, famille et proches, alimentation,
  notes iCloud, liens) — une par fiche avec un prénom ou un nom ;
- `Personnes/<Nom>/<Nom> — <Type>.md` : une note d'index par type d'information, seulement s'il y en a
  (« Pour les journaux », « Journaux parus », « Livre d'or »), qui renvoie aux notes d'événement ;
- `Événements/<Type>/<date> — <titre>.md` : une note par événement (un numéro de La Récidive ou de La
  Gazette, les mots d'un séjour dans le livre d'or), partagée par toutes les personnes concernées.

Chaque note a un bloc entre `<!-- carnet:debut … -->` et `<!-- carnet:fin -->`, réécrit à chaque
synchronisation ; tout le reste (zone « Mes notes », ce qui est écrit avant ou après le bloc) n'est jamais
touché. L'en-tête garde les clés ajoutées à la main ; carnet ne réécrit que les siennes (`CLES_CARNET`).
Les notes sont retrouvées par leur identifiant (`personne_id`, `index_de` + `index_type`, `evenement_id`),
même déplacées. carnet ne supprime jamais une note. Il range une seule fois les notes de la forme 2.28
(`Personnes/<Nom>.md`) dans leur dossier, et renomme le dossier d'une personne quand son nom change
(seulement si la note est à sa place d'origine et que le nouveau nom est libre).

Garde-fou : le coffre doit être monté et contenir un dossier `Personnes/` créé par Julien. Si le dossier
partagé chiffré n'est pas monté, rien n'est écrit (pas de copie en clair dans un dossier vide).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from . import alimentation, attentes, genres, journaux, maison, personnes
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
CLES_CARNET = ("personne_id", "type", "nom", "aliases", "groupes", "naissance", "allergies", "carnet", "maj_carnet",
               "index_de", "index_type", "evenement_id", "evenement", "date", "personnes")
ID = re.compile(r"^personne_id:\s*[\"']?(p-[0-9a-f]{10})[\"']?\s*$", re.M)
INDEX_DE = re.compile(r"^index_de:\s*[\"']?(p-[0-9a-f]{10})[\"']?\s*$", re.M)
INDEX_TYPE = re.compile(r"^index_type:\s*[\"']?([a-z_]+)[\"']?\s*$", re.M)
EVT = re.compile(r"^evenement_id:\s*[\"']?([a-z0-9_-]+)[\"']?\s*$", re.M)
# 3.0 : le point en plus (SilverBullet n'ouvre pas une note dont le nom contient un point : « J. Dupont » → « J Dupont »)
INTERDITS = re.compile(r'[\\/:*?"<>|#^\[\].]')
# Types de notes d'index (clé → titre), dans l'ordre de la note Contact
TYPES = {"journaux": "Pour les journaux", "parus": "Journaux parus", "livre_or": "Livre d'or"}
JOURNAUX = {"recidive": "La Récidive", "gazette": "La Gazette"}
MOTIF_DEBUT = re.compile(r"<!-- carnet:debut\b.*?-->")
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
                           f"crée ce dossier dans Obsidian (garde-fou contre un dossier chiffré non monté).")
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
    """Notes de carnet déjà dans le coffre, retrouvées par leur identifiant, partout (hors dossiers cachés)."""
    inv = {"contacts": {}, "index": {}, "evenements": {}}
    for p in r.rglob("*.md"):
        if any(part.startswith(".") for part in p.relative_to(r).parts):
            continue
        tete = _entete_brute(p)
        if not tete:
            continue
        if (m := INDEX_DE.search(tete)) and (t := INDEX_TYPE.search(tete)):
            inv["index"].setdefault((m.group(1), t.group(1)), p)
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
    lignes = [f"personne_id: {ident}", "type: contact", f"nom: {_yaml(nom)}", "aliases:"] + [f"  - {_yaml(a)}" for a in alias]
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


def bloc(c: Carnet, uid: str, f: dict, ident: str, cibles: dict[str, str], index: dict[str, str] | None = None) -> str:
    """Partie écrite par carnet dans la note Contact (sans les marqueurs). `index` : type → nom de la note d'index."""
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
    proches = [(x.get("type") or "proche", x.get("valeur", "")) for x in f.get("noms_associes") or [] if x.get("valeur")]
    if proches:
        l += ["", "## Famille et proches"] + [f"- {t} : {_lien_note(v, cibles)}" for t, v in proches]
    a = alimentation.de_personne(c, ident)
    st = alimentation.statut(a)
    l += ["", "## Alimentation", f"- **Statut** : {alimentation.STATUTS[st]}"]
    if a:
        if a.get("verifiee_le"):
            l.append(f"- **Vérifiée le** : {date_lisible(a['verifiee_le'])}")
        for k in alimentation.LISTES:
            l += _liste(alimentation.LIBELLES[k], a[k])
    if index:
        l += ["", "## Dans le coffre"] + [f"- {_lien(index[t], TYPES[t])}" for t in TYPES if t in index]
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

def evenements(c: Carnet, ids: dict[str, str]) -> dict[str, dict]:
    """evenement_id → {nature, dossier, titre, date, personnes: [ident], lignes: {ident: [str]}, autres: [str]}.
    Seulement les personnes qui ont une fiche (les autres signataires sont nommés dans `autres`)."""
    actifs = set(ids.values())
    evts: dict[str, dict] = {}
    # Numéros parus (Gazette, La Récidive) : un événement par numéro (clé « recidive-AAAA-MM-JJ »)
    for l in c.base.tous("SELECT * FROM journaux_parus ORDER BY le DESC, cle DESC"):
        if l["personne"] not in actifs:
            continue
        p = {"cle": l["cle"], "le": l["le"], **json.loads(l["donnees"])}
        journal = JOURNAUX.get(p.get("journal") or "", p.get("journal") or "Journal")
        e = evts.setdefault("paru-" + l["cle"], {
            "nature": "parus", "dossier": journal, "date": l["le"],
            "titre": journal + (f" N° {p['numero']}" if p.get("numero") else ""),
            "sous_titre": p.get("titre") or "", "evenement": p.get("evenement") or "",
            "personnes": [], "lignes": {}, "autres": []})
        e["personnes"].append(l["personne"])
        e["lignes"][l["personne"]] = [f"  - Photo : {x}" for x in p.get("descriptions") or []] + \
                                     [f"  - Imprimé : {x}" for x in p.get("textes") or []]
    # Livre d'or : un événement par séjour (date de début + chambre)
    for l in c.base.tous("SELECT * FROM livre_or ORDER BY le DESC, id"):
        chambre = l["chambre"] or ""
        cle = "livre-" + l["le"] + ("-" + re.sub(r"[^a-z0-9]+", "-", cle_texte(chambre)).strip("-") if chambre else "")
        e = evts.setdefault(cle, {
            "nature": "livre_or", "dossier": "Livre d'or", "date": l["le"],
            "titre": "Livre d'or" + (f" ({_nom_de_fichier(chambre, '')})" if chambre else ""),
            "sous_titre": "", "evenement": "", "personnes": [], "lignes": {}, "autres": []})
        texte = [f"  > {x}" if x else "  >" for x in l["message"].splitlines()]
        if l["personne"] in actifs:
            if l["personne"] not in e["personnes"]:
                e["personnes"].append(l["personne"])
            e["lignes"].setdefault(l["personne"], []).extend(texte)
        else:
            e["autres"].append(f"- **{l['nom']}** (pas encore rattaché dans carnet) :")
            e["autres"].extend(texte)
    return evts


def _stem_evenement(e: dict) -> str:
    return _nom_de_fichier(f"{e['date']} — {e['titre']}", "evenement")


def _entete_evenement(eid: str, e: dict, le: str) -> list[str]:
    return [f"evenement_id: {eid}", "type: evenement", f"evenement: {e['nature']}", f"date: {_yaml(e['date'])}",
            "personnes:"] + [f"  - {i}" for i in e["personnes"]] + ["carnet: présente", f"maj_carnet: {le}"]


def _bloc_evenement(e: dict, noms: dict[str, str]) -> str:
    le = e["date"]
    l = [f"# {e['titre']}", "", f"- **Date** : {le[8:10]}/{le[5:7]}/{le[:4]}"]
    if e["sous_titre"]:
        l.append(f"- **Titre** : {e['sous_titre']}")
    if e["evenement"]:
        l.append(f"- **Événement** : {e['evenement']}")
    l += ["", "## Personnes"]
    for i in e["personnes"]:
        l.append(f"- {_lien(noms[i])}" + (" :" if e["lignes"].get(i) else ""))
        l += e["lignes"].get(i, [])
    if e["autres"]:
        l += ["", "## Autres signataires"] + e["autres"]
    return "\n".join(l)


# ---------------------------------------------------------------- notes d'index (une par personne et par type)

def _contenu_index(c: Carnet, typ: str, ident: str, nom_contact: str, liens_evts: list[str]) -> str | None:
    """Bloc d'une note d'index, ou None si la personne n'a rien de ce type."""
    if typ == "journaux":
        lignes = journaux.resume_coffre(c, ident)
        if not lignes:
            return None
        corps = [l for l in lignes if not l.startswith("## ")]
        return "\n".join([f"# {nom_contact} — {TYPES[typ]}", "", f"Note Contact : {_lien(nom_contact)}"] + corps)
    if not liens_evts:
        return None
    return "\n".join([f"# {nom_contact} — {TYPES[typ]}", "", f"Note Contact : {_lien(nom_contact)}", ""] + liens_evts)


def _entete_index(ident: str, typ: str, le: str) -> list[str]:
    return [f"index_de: {ident}", "type: index", f"index_type: {typ}", "carnet: présente", f"maj_carnet: {le}"]


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


def assembler(existant: str | None, entete: list[str], contenu: str) -> str | None:
    """Nouveau texte de la note, ou None si l'existant n'a plus de bloc carnet (rien n'est réécrit)."""
    tete = "---\n" + "\n".join(entete) + "\n"
    if existant is None:
        return f"{tete}---\n{DEBUT}\n{contenu}\n{FIN}\n\n{ZONE_LIBRE}"
    lignes, corps = _separer(existant)
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
    """Écrit une note (création ou mise à jour du bloc) et compte dans bilan[cle] (« crees », « mises_a_jour »…)."""
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


# ---------------------------------------------------------------- rangement (forme 2.28, changement de nom)

def _ranger(r: Path, ident: str, actuel: Path, base: str, inv: dict, ecrire: bool, bilan: dict) -> Path:
    """Chemin de la note Contact d'une personne existante, après rangement éventuel :
    - forme 2.28 (`Personnes/<x>.md`) → `Personnes/<x>/<x>.md` (une fois) ;
    - nom changé (`Personnes/<ancien>/<ancien>.md`) → `Personnes/<base>/<base>.md`, notes d'index comprises,
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
            for typ, titre in TYPES.items():
                vieux = nouveau / f"{ancien} — {titre}.md"
                if vieux.exists() and not (nouveau / f"{base} — {titre}.md").exists():
                    os.replace(vieux, nouveau / f"{base} — {titre}.md")
            for (i, typ), p in list(inv["index"].items()):
                if i == ident and p.parent == actuel.parent:
                    titre = TYPES.get(typ, "")
                    p2 = nouveau / f"{base} — {titre}.md"
                    inv["index"][(i, typ)] = p2 if p2.exists() else nouveau / p.name
        bilan["renommees"] += 1
        return nouveau / f"{base}.md" if ecrire else actuel
    return actuel


def _accueil(r: Path, ecrire: bool) -> None:
    """Pages d'accueil et de réglages de SilverBullet, posées une seule fois (Julien peut les modifier)."""
    for nom, texte in (("Accueil.md", ACCUEIL), ("CONFIG.md", CONFIG)):
        if ecrire and not (r / nom).exists():
            _ecrire(r / nom, texte)


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
    _accueil(r, ecrire)

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
    for eid, e in sorted(evts.items(), key=lambda x: (x[1]["date"], x[0]), reverse=True):
        e["personnes"] = [i for i in e["personnes"] if i in noms]
        existant = inv["evenements"].get(eid)
        chemin = existant or (r / EVENEMENTS / e["dossier"] / f"{_stem_evenement(e)}.md")
        if not existant and chemin.exists():
            chemin = chemin.with_name(f"{_stem_evenement(e)} ({eid}).md")
        for i in e["personnes"]:
            par_personne.setdefault((i, e["nature"]), []).append(f"- {_lien(chemin.stem)}")
        try:
            avant = bilan["crees"]
            _poser(chemin, existant is not None, _entete_evenement(eid, e, le), _bloc_evenement(e, noms), ecrire, bilan, "crees")
            bilan["evenements"] += bilan["crees"] - avant
            bilan["crees"] = avant
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")

    # 3. Notes d'index puis note Contact de chaque personne
    for uid, f in gens.items():
        ident, chemin = ids[uid], chemins[uid]
        index: dict[str, str] = {}
        for typ in TYPES:
            contenu = _contenu_index(c, typ, ident, chemin.stem, par_personne.get((ident, typ), []))
            existant = inv["index"].get((ident, typ))
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
                   bloc(c, uid, f, ident, cibles, index), ecrire, bilan, "crees")
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")

    # 4. Personnes sans fiche (retirées ou fusionnées) : seule la clé « carnet » de l'en-tête change
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
                     + (f", {bilan['evenements']} événement(s) et {bilan['index']} index créés" if bilan["evenements"] or bilan["index"] else "")
                     + (f", {bilan['rangees']} rangée(s) dans leur dossier" if bilan["rangees"] else "")
                     + (f", {bilan['renommees']} renommée(s)" if bilan["renommees"] else "")
                     + (f", {bilan['sans_bloc']} sans bloc carnet" if bilan["sans_bloc"] else "")
                     + (f", {len(bilan['erreurs'])} erreur(s)" if bilan["erreurs"] else ""),
                     {k: bilan[k] for k in ("crees", "mises_a_jour", "inchangees", "sans_bloc", "retirees", "rangees",
                                            "renommees", "index", "evenements")})
    return bilan


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


# ---------------------------------------------------------------- pages de SilverBullet (posées une fois)

ACCUEIL = """# Coffre Contacts

Vue de carnet (lecture seule côté carnet : les modifications se font dans carnet). Chaque personne a sa note dans
`Personnes/<Nom>/`, ses notes par type à côté, et les événements partagés sont dans `Événements/`.
Ta zone « Mes notes », en bas de chaque note, n'est jamais touchée par carnet.
(Les tableaux ci-dessous sont des requêtes SilverBullet : en Lua, un nom de colonne accentué s'écrit `["Événement"]`.)

## Anniversaires du mois
${query[[
  from p = index.tag "page"
  where p.type == "contact" and p.carnet == "présente" and p.naissance
    and string.sub(p.naissance, -5, -4) == os.date("%m")
  order by string.sub(p.naissance, -2)
  select {Nom = "[[" .. p.name .. "]]", Date = p.naissance}
]]}

## Allergies à connaître
${query[[
  from p = index.tag "page"
  where p.type == "contact" and p.carnet == "présente" and p.allergies == "a_connaitre"
  order by p.name
  select {Nom = "[[" .. p.name .. "]]"}
]]}

## Derniers événements
${query[[
  from p = index.tag "page"
  where p.type == "evenement"
  order by p.date desc
  limit 10
  select {["Événement"] = "[[" .. p.name .. "]]", Date = p.date}
]]}
"""

CONFIG = """# CONFIG

Réglages de SilverBullet pour le coffre Contacts (posés une fois par carnet ; à modifier ici). Habillage « Répertoire
chaud » choisi par Julien le 18/11/2026 : fond encre brune, accent terre cuite, titres en Fraunces (si la police est
installée sur l'appareil, sinon une police à empattements), corps en Inter, liens soulignés en pointillés.

```space-lua
-- Toujours sombre, quel que soit le réglage de l'appareil
event.listen {
  name = "editor:init",
  run = function()
    editor.setUiOption("darkMode", true)
  end
}
```

```space-style
html, html[data-theme="light"], html[data-theme="dark"] {
  --root-background-color: #1a1714;
  --root-color: #ece4d8;
  --top-background-color: #221e1a;
  --top-color: #ece4d8;
  --top-border-color: #3a332c;
  --panel-background-color: #221e1a;
  --panel-border-color: #3a332c;
  --modal-background-color: #221e1a;
  --modal-border-color: #3a332c;
  --modal-color: #ece4d8;
  --modal-selected-option-background-color: #2e2822;
  --subtle-color: #b3a796;
  --subtle-background-color: #221e1a;
  --meta-color: #b3a796;
  --meta-subtle-color: #857a6c;
  --editor-meta-color: #b3a796;
  --editor-heading-color: #ece4d8;
  --editor-heading-meta-color: #857a6c;
  --ui-accent-color: #c9714a;
  --ui-accent-text-color: #1a1714;
  --ui-accent-contrast-color: #1a1714;
  --ui-surface-border-color: #3a332c;
  --ui-surface-hover-background-color: #2e2822;
  --link-color: #c9714a;
  --editor-link-color: #c9714a;
  --editor-wiki-link-page-color: #c9714a;
  --editor-wiki-link-page-background-color: transparent;
  --editor-code-background-color: #221e1a;
  --editor-blockquote-border-color: #c9714a;
  --editor-list-bullet-color: #b3a796;
  --editor-selection-background-color: #c9714a33;
  --editor-caret-color: #c9714a;
  --button-background-color: #221e1a;
  --button-border-color: #3a332c;
  --button-color: #ece4d8;
  --button-hover-background-color: #2e2822;
  --text-field-background-color: #221e1a;
  --ui-font: Inter, -apple-system, "Segoe UI", system-ui, sans-serif;
  --editor-font: Inter, -apple-system, "Segoe UI", system-ui, sans-serif;
}
.sb-line-h1, .sb-line-h2, .sb-line-h3, #sb-current-page { font-family: Fraunces, Georgia, "Times New Roman", serif; }
.sb-wiki-link-page, .sb-wiki-link { text-decoration: underline dotted; text-underline-offset: 3px; }
```
"""

"""Synchronisation vers le coffre Obsidian « Contacts » (2.28).

carnet est le maître des informations contact ; le coffre en est une vue, avec les notes de Julien.
Une note par personne (fiche avec un prénom ou un nom ; les fiches d'entreprise seule n'en ont pas),
rangée dans `Personnes/` à la création. Chaque note a deux parties :

- un bloc entre `<!-- carnet:debut … -->` et `<!-- carnet:fin -->`, réécrit à chaque synchronisation ;
- tout le reste (la zone libre « Mes notes », ce qui est écrit avant ou après le bloc), jamais touché.

L'en-tête (frontmatter) garde les clés ajoutées à la main ; carnet n'y réécrit que les siennes
(`personne_id`, `nom`, `aliases`, `groupes`, `naissance`, `carnet`, `maj_carnet`). Une note est retrouvée
par son `personne_id`, même déplacée ou renommée dans le coffre : carnet ne renomme ni ne déplace
jamais une note, et n'en supprime jamais. Une note sans bloc carnet (bloc effacé à la main) n'est pas
réécrite : elle est comptée à part.

Garde-fou : le coffre doit être monté et contenir un dossier `Personnes/` créé par Julien. Si le dossier
partagé chiffré n'est pas monté, rien n'est écrit (pas de copie en clair dans un dossier vide).
Les informations que Julien ne veut pas confier à carnet restent dans sa zone libre : carnet ne lit
jamais le contenu des notes au-delà de l'en-tête et des marqueurs.
"""
from __future__ import annotations

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
DEBUT = "<!-- carnet:debut — partie écrite par carnet, réécrite à chaque synchronisation : ne pas modifier ici -->"
FIN = "<!-- carnet:fin -->"
ZONE_LIBRE = "## Mes notes\n\n"
CLES_CARNET = ("personne_id", "nom", "aliases", "groupes", "naissance", "carnet", "maj_carnet")
ID = re.compile(r"^personne_id:\s*[\"']?(p-[0-9a-f]{10})[\"']?\s*$", re.M)
INTERDITS = re.compile(r'[\\/:*?"<>|#^\[\]]')
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

def _notes_existantes(r: Path) -> dict[str, Path]:
    """personne_id → note, partout dans le coffre (hors dossiers cachés : .obsidian, .trash, .carnet…)."""
    res: dict[str, Path] = {}
    for p in r.rglob("*.md"):
        if any(part.startswith(".") for part in p.relative_to(r).parts):
            continue
        try:
            with p.open(encoding="utf-8") as f:
                tete = f.read(4000)
        except (OSError, UnicodeDecodeError):
            continue
        if tete.startswith("---"):
            m = ID.search(tete.split("\n---", 1)[0])
            if m:
                res.setdefault(m.group(1), p)
    return res


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


def _entete_carnet(f: dict, ident: str, statut: str, le: str) -> list[str]:
    nom = nom_affiche(f)
    alias = [nom] + ([f["surnom"]] if f.get("surnom") and f["surnom"] != nom else [])
    lignes = [f"personne_id: {ident}", f"nom: {_yaml(nom)}", "aliases:"] + [f"  - {_yaml(a)}" for a in alias]
    groupes = sorted(f.get("groupes") or [])
    lignes += ["groupes:"] + [f"  - {_yaml(g)}" for g in groupes] if groupes else ["groupes: []"]
    if f.get("anniversaire"):
        lignes.append(f"naissance: {_yaml(f['anniversaire'])}")
    lignes += [f"carnet: {statut}", f"maj_carnet: {le}"]
    return lignes


def _liste(titre: str, valeurs: list[str]) -> list[str]:
    return [f"- **{titre}** : {', '.join(valeurs)}"] if valeurs else []


def _lien_note(valeur: str, cibles: dict[str, str]) -> str:
    cible = cibles.get(cle_texte(valeur))
    if not cible:
        return valeur
    return f"[[{cible}]]" if cible == valeur else f"[[{cible}|{valeur}]]"


def bloc(c: Carnet, uid: str, f: dict, ident: str, cibles: dict[str, str]) -> str:
    """Partie écrite par carnet (sans les marqueurs)."""
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
    if (pj := journaux.de_personne(c, ident)):          # 2.29 : « Pour les journaux » (Gazette)
        l += ["", "## Pour les journaux (Gazette)", *[f"> {x}" if x else ">" for x in pj.splitlines()]]
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
    """Écriture atomique dans le même dossier (Obsidian ne voit jamais une note à moitié écrite)."""
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


# ---------------------------------------------------------------- synchroniser

def synchroniser(c: Carnet, ecrire: bool = True) -> dict:
    """Écrit (ou, avec ecrire=False, compte seulement) les notes du coffre. Renvoie le bilan."""
    r = racine(c)
    if ecrire:
        c.exiger_ecriture("Coffre Contacts")
    le = iso(maintenant())[:10]
    fiches, ids = c.fiches(), personnes.ids(c)
    gens = {uid: f for uid, f in fiches.items() if personne_a_note(f)}
    existantes = _notes_existantes(r)
    bilan = {"le": iso(maintenant()), "crees": 0, "mises_a_jour": 0, "inchangees": 0, "sans_bloc": 0,
             "retirees": 0, "erreurs": [], "ecrit": ecrire}
    # Nom de chaque note (pour les liens [[…]] entre personnes) : existante, sinon à créer
    chemins: dict[str, Path] = {}
    pris = {p.resolve() for p in existantes.values()}
    for uid, f in sorted(gens.items(), key=lambda x: nom_affiche(x[1]).casefold()):
        ident = ids[uid]
        if ident in existantes:
            chemins[uid] = existantes[ident]
            continue
        base = _nom_de_fichier(nom_affiche(f), ident)
        chemin = r / DOSSIER / f"{base}.md"
        if chemin.exists() or chemin.resolve() in pris:
            chemin = r / DOSSIER / f"{base} ({ident}).md"
        pris.add(chemin.resolve())
        chemins[uid] = chemin
    cibles: dict[str, str] = {}
    for uid, chemin in chemins.items():
        cibles.setdefault(cle_texte(nom_affiche(gens[uid])), chemin.stem)
    for uid, f in gens.items():
        ident, chemin = ids[uid], chemins[uid]
        try:
            existant = chemin.read_text(encoding="utf-8") if ident in existantes else None
            texte = assembler(existant, _entete_carnet(f, ident, "présente", le), bloc(c, uid, f, ident, cibles))
            if texte is None:
                bilan["sans_bloc"] += 1
                continue
            if existant is not None and _sans_date(texte) == _sans_date(existant):
                bilan["inchangees"] += 1
                continue
            if ecrire:
                _ecrire(chemin, texte)
            bilan["crees" if existant is None else "mises_a_jour"] += 1
        except OSError as exc:
            bilan["erreurs"].append(f"{chemin.name} : {exc.strerror or exc}")
    # Personnes sans fiche (retirées ou fusionnées) : seule la clé « carnet » de l'en-tête change
    actifs = set(ids.values())
    for ident, chemin in existantes.items():
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
                     + (f", {bilan['sans_bloc']} sans bloc carnet" if bilan["sans_bloc"] else "")
                     + (f", {len(bilan['erreurs'])} erreur(s)" if bilan["erreurs"] else ""),
                     {k: bilan[k] for k in ("crees", "mises_a_jour", "inchangees", "sans_bloc", "retirees")})
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

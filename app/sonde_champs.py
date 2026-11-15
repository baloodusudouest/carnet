"""Sonde avant d'ajouter à carnet tous les champs de la fiche de l'iPhone : lecture seule.

    python -m app.sonde_champs "Essai Champs"

Dit comment iCloud écrit les champs que carnet ne gère pas encore (titre, second prénom, suffixe,
nom de naissance, phonétiques, prononciations, pronoms, dates libres, messagerie instantanée…),
et si sonnerie, son SMS et code de validation arrivent jusqu'à iCloud.

  A. Sur toutes les cartes : le nom de chaque propriété, ses paramètres, le nombre de cartes qui la
     portent, et les libellés d'Apple. Aucune valeur, aucun nom de personne, aucun libellé écrit à la main.
  B. Pour la fiche d'essai seulement (celle dont le nom contient tous les mots donnés, remplie sur
     l'iPhone avec des valeurs inventées) : la carte entière, telle qu'iCloud la donne, sans la photo.

Les cartes sont lues dans la base de carnet (sur une copie) : iCloud n'est pas contacté, rien n'est
écrit nulle part, sauf le rapport dans le dossier de données. La fiche d'essai doit avoir été lue par
carnet : Connexion › iCloud › Vérifier, avant de lancer la sonde.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import charger

__version__ = "1"
LIBELLE_APPLE = re.compile(r"^_\$!<(.+)>!\$_$")
GEREES = {"N", "FN", "NICKNAME", "ORG", "TITLE", "BDAY", "TEL", "EMAIL", "ADR", "URL", "X-SOCIALPROFILE",
          "X-ABRELATEDNAMES", "NOTE", "CATEGORIES", "PHOTO", "IMPP", "X-ABSHOWAS", "X-PHONETIC-FIRST-NAME",
          "X-PHONETIC-LAST-NAME", "X-ABDATE", "X-ABLABEL", "BEGIN", "END", "VERSION", "PRODID", "UID", "REV"}


def deplier(texte: str) -> list[str]:
    """Lignes logiques d'une carte (une ligne qui commence par une espace continue la précédente)."""
    lignes: list[str] = []
    for brute in texte.replace("\r\n", "\n").split("\n"):
        if brute[:1] in (" ", "\t") and lignes:
            lignes[-1] += brute[1:]
        elif brute:
            lignes.append(brute)
    return lignes


def decouper(ligne: str) -> tuple[str, list[str], str]:
    """« item1.TEL;type=CELL:+33… » → (TEL, [TYPE=CELL], valeur)."""
    tete, _, valeur = ligne.partition(":")
    morceaux = tete.split(";")
    nom = morceaux[0].split(".")[-1].upper()
    return nom, [m.upper() if "=" not in m else m.split("=")[0].upper() + "=" + m.split("=", 1)[1] for m in morceaux[1:]], valeur


def nom_complet(texte: str) -> str:
    for ligne in deplier(texte):
        nom, _, valeur = decouper(ligne)
        if nom == "FN":
            return valeur.replace("\\,", ",").strip()
    return ""


def lire_cartes(chemin: Path) -> list[str]:
    travail = Path(tempfile.mkdtemp(prefix="sonde-champs-"))
    try:
        for suffixe in ("", "-wal", "-shm"):
            source = Path(str(chemin) + suffixe)
            if source.is_file():
                shutil.copy2(source, travail / source.name)
        cx = sqlite3.connect(str(travail / chemin.name))
        try:
            return [l[0] for l in cx.execute("SELECT texte FROM fiches")]
        finally:
            cx.close()
    finally:
        shutil.rmtree(travail, ignore_errors=True)


def inventaire(cartes: list[str]) -> dict:
    """Propriétés rencontrées : nombre de cartes, paramètres vus, forme de la valeur (jamais la valeur)."""
    presentes: Counter = Counter()
    parametres: dict[str, Counter] = {}
    champs_n: Counter = Counter()        # combien de cartes remplissent chaque case de N (nom;prénom;second;titre;suffixe)
    libelles: Counter = Counter()
    for texte in cartes:
        vues = set()
        for ligne in deplier(texte):
            nom, params, valeur = decouper(ligne)
            vues.add(nom)
            for p in params:
                # Un paramètre peut porter une valeur personnelle (X-USER=…) : on ne garde que son nom,
                # sauf pour TYPE et VALUE dont les valeurs sont des mots techniques
                cle = p if p.split("=")[0] in ("TYPE", "VALUE", "X-SERVICE-TYPE") else p.split("=")[0]
                parametres.setdefault(nom, Counter())[cle] += 1
            if nom == "N":
                for i, case in enumerate(valeur.split(";")[:5]):
                    if case.strip():
                        champs_n[("nom", "prénom", "second prénom", "titre", "suffixe")[i]] += 1
            if nom == "X-ABLABEL":
                m = LIBELLE_APPLE.match(valeur.strip())
                libelles[m.group(1) if m else "(libellé écrit à la main)"] += 1
        presentes.update(vues)
    return {"cartes": len(cartes), "presentes": presentes, "parametres": parametres, "n": champs_n, "libelles": libelles}


def carte_d_essai(cartes: list[str], cherche: str) -> tuple[list[str] | None, str]:
    """La carte dont le nom contient `cherche` (sans casse), sans sa photo. Une seule, sinon rien."""
    if not cherche.strip():
        return None, "aucun nom de fiche d'essai donné : la partie B est sautée."
    # Tous les mots donnés doivent être dans le nom (l'iPhone y glisse le titre et le second prénom)
    mots = cherche.casefold().split()
    trouvees = [t for t in cartes if all(m in nom_complet(t).casefold() for m in mots)]
    if not trouvees:
        return None, f"aucune carte dont le nom contient « {cherche} » : crée la fiche sur l'iPhone, puis Connexion › iCloud › Vérifier dans carnet."
    if len(trouvees) > 1:
        return None, f"{len(trouvees)} cartes ont un nom qui contient « {cherche} » : donne un nom plus précis. Rien n'est montré."
    lignes = []
    for ligne in deplier(trouvees[0]):
        nom, _, _ = decouper(ligne)
        lignes.append(ligne.split(":", 1)[0] + ":(photo retirée)" if nom == "PHOTO" else ligne)
    return lignes, ""


def rapport(inv: dict, essai: list[str] | None, raison: str, cherche: str) -> str:
    md = [f"# Sonde carnet — champs de la fiche iPhone — {datetime.now():%Y-%m-%d %H:%M}", "",
          f"Sonde {__version__}, lecture seule, {inv['cartes']} cartes lues dans la base de carnet.", "",
          "## A. Propriétés des cartes (aucune valeur, aucun nom)", "",
          "| Propriété | Cartes | Gérée par carnet | Paramètres vus |", "|---|---|---|---|"]
    for nom, nombre in sorted(inv["presentes"].items(), key=lambda x: (x[0] in GEREES, x[0])):
        params = ", ".join(f"{p} ({n})" for p, n in inv["parametres"].get(nom, Counter()).most_common(8))
        md.append(f"| `{nom}` | {nombre} | {'oui' if nom in GEREES else '**non**'} | {params} |")
    md += ["", "**Cases du nom (N) remplies** : " + (", ".join(f"{k} {v}" for k, v in inv["n"].most_common()) or "aucune") + ".", "",
           "**Libellés** : " + (", ".join(f"{k} ({v})" for k, v in inv["libelles"].most_common(40)) or "aucun") + ".", "",
           f"## B. Fiche d'essai « {cherche} »", ""]
    if essai is None:
        md.append(f"Non montrée : {raison}")
    else:
        md += ["Carte telle qu'iCloud la donne (photo retirée) :", "", "```"] + essai + ["```"]
    return "\n".join(md) + "\n"


def main(args: list[str]) -> int:
    cfg = charger()
    if not cfg.db_path.is_file():
        print("Base de carnet introuvable : la sonde se lance avec les mêmes volumes que carnet.", file=sys.stderr)
        return 2
    cherche = " ".join(args).strip()
    cartes = lire_cartes(cfg.db_path)
    essai, raison = carte_d_essai(cartes, cherche)
    md = rapport(inventaire(cartes), essai, raison, cherche)
    print(md)
    try:
        cfg.data.mkdir(parents=True, exist_ok=True)
        (cfg.data / "rapport-sonde-champs.md").write_text(md, encoding="utf-8")
        print(f"Rapport écrit dans {cfg.data}/rapport-sonde-champs.md", file=sys.stderr)
    except OSError as exc:
        print(f"Rapport non écrit sur disque ({exc}) : il est affiché ci-dessus.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

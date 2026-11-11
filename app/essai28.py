"""Essai avant la 2.8.0 : ce qu'iCloud et l'iPhone font des champs nouveaux, et ce que vaut la
recherche de logos. À lancer deux fois, avec la même commande :

    python -m app.essai28

1er lancement
  A. Crée UNE carte d'essai dans iCloud (« Carnet Essai », données inventées), la relit aussitôt
     et dit ce qu'iCloud a gardé, changé ou perdu.
  B. Mesure la recherche de logos sur 30 fiches de société sans photo, tirées au hasard :
     combien ont un site ou un courriel professionnel, combien de logos sont trouvés.

Entre les deux : regarder la carte « Carnet Essai » sur l'iPhone (voir docs/essai-2.8.md), puis
y changer une date.

2e lancement
  C. Relit la carte d'essai et dit ce qui a changé depuis le premier lancement. La mesure des
     logos n'est pas refaite.

Ce que ce programme écrit : la carte d'essai, une seule fois, et rien d'autre. Aucune carte
existante n'est touchée, la base de carnet est lue sur une copie, Immich et Treemich ne sont pas
contactés. Il écrit même si carnet tourne en lecture seule : c'est un programme à part.
La recherche de logos lit les sites des sociétés, sans rien envoyer à un service tiers. Le rapport
ne contient ni nom de personne, ni nom de société, ni adresse de site.
"""
from __future__ import annotations

import json
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import logos
from .carddav import CardDAV
from .config import charger
from .normalisation import domaine_pro

__version__ = "1"

UID = "carnet-essai-28"
GROUPES_LOGO = ("Clients", "Artisans et services")
ECHANTILLON = 30
BON_LOGO = 180   # côté minimal d'un logo net sur une photo de contact

# Chaque date est différente : sur l'iPhone, on sait ainsi quel libellé montre laquelle.
CHAMPS = [
    ("Prononciation du prénom", "X-PHONETIC-FIRST-NAME:Karnè"),
    ("Prononciation du nom", "X-PHONETIC-LAST-NAME:Essè"),
    ("Société et service", "ORG:Société d'essai;Service d'essai"),
    ("Date, libellé d'Apple (12 juin 2010)", "item1.X-ABDATE:2010-06-12\r\nitem1.X-ABLabel:_$!<Anniversary>!$_"),
    ("Date, libellé « Mariage » (13 juillet 2011)", "item2.X-ABDATE:2011-07-13\r\nitem2.X-ABLabel:Mariage"),
    ("Date sans année, libellé « Fête » (15 août)",
     "item3.X-ABDATE;X-APPLE-OMIT-YEAR=1604:1604-08-15\r\nitem3.X-ABLabel:Fête"),
    ("Date, libellé « Décès » (2 janvier 2020)", "item4.X-ABDATE:2020-01-02\r\nitem4.X-ABLabel:Décès"),
]


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def carte_essai() -> str:
    lignes = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//carnet//essai28//FR", "N:Essai;Carnet;;;", "FN:Carnet Essai"]
    lignes += [texte for _, texte in CHAMPS]
    lignes += ["NOTE:Carte d'essai de carnet 2.8. À supprimer après l'essai.", f"UID:{UID}",
               f"REV:{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}", "END:VCARD"]
    return "\r\n".join(lignes) + "\r\n"


def lignes_utiles(texte: str) -> list[str]:
    """Lignes de la carte, dépliées, sans la date de révision ni la photo (elles bougent seules)."""
    deplie = texte.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
    return [l for l in deplie.split("\n") if l.strip() and not l.upper().startswith(("REV:", "PHOTO", "PRODID:"))]


def comparer(avant: str, apres: str) -> tuple[list[str], list[str]]:
    """(lignes disparues, lignes apparues), sans tenir compte de l'ordre."""
    a, b = Counter(lignes_utiles(avant)), Counter(lignes_utiles(apres))
    return sorted((a - b).elements()), sorted((b - a).elements())


def bloc(titre: str, lignes: list[str]) -> list[str]:
    return [f"**{titre}**", "", "```", *(lignes or ["(rien)"]), "```", ""]


# ----------------------------------------------------------------- A et C : la carte d'essai

def essai_carte(dav: CardDAV, dossier: Path) -> list[str]:
    href = dav.href_nouveau(UID)
    memoire = dossier / "essai-28-carte.vcf"
    existante = dav.lire_une(href)
    out: list[str] = []
    if existante is None:
        envoyee = carte_essai()
        log("Carte d'essai absente : création dans iCloud…")
        dav.ecrire(href, envoyee, None)
        time.sleep(2)
        relue = dav.lire_une(href)
        if relue is None:
            return ["## A. Carte d'essai", "", "La carte a été envoyée mais iCloud ne la rend pas. Relancer dans une minute."]
        try:
            memoire.write_text(relue.texte, encoding="utf-8")
        except OSError as exc:
            log(f"Carte non gardée sur disque ({exc}) : le 2e lancement comparera à la carte envoyée.")
        perdues, apparues = comparer(envoyee, relue.texte)
        out += ["## A. Carte d'essai créée dans iCloud", "",
                "Contact « Carnet Essai », données inventées. Ce qu'iCloud rend juste après l'écriture :", ""]
        out += ["| Champ | Rendu tel quel |", "|---|---|"]
        rendues = set(lignes_utiles(relue.texte))
        for nom, texte in CHAMPS:
            ok = all(l in rendues for l in texte.split("\r\n"))
            out.append(f"| {nom} | {'oui' if ok else '**non**'} |")
        out += ["", *bloc("Lignes envoyées qu'iCloud n'a pas rendues telles quelles", perdues),
                *bloc("Lignes qu'iCloud a ajoutées ou réécrites", apparues),
                *bloc("Carte complète, telle qu'iCloud la rend", lignes_utiles(relue.texte)),
                "**À faire maintenant** : suivre `docs/essai-2.8.md` sur l'iPhone, puis relancer ce programme."]
        return out
    reference = memoire.read_text(encoding="utf-8") if memoire.is_file() else carte_essai()
    perdues, apparues = comparer(reference, existante.texte)
    out += ["## C. Carte d'essai relue", "",
            "Comparée à la carte du premier lancement"
            + ("." if memoire.is_file() else " (carte envoyée : la copie du premier lancement est introuvable)."), ""]
    if not perdues and not apparues:
        out += ["Aucun changement : rien n'a été modifié sur l'iPhone, ou la modification n'est pas encore arrivée dans iCloud.", ""]
    out += [*bloc("Lignes disparues ou remplacées", perdues), *bloc("Lignes nouvelles", apparues),
            *bloc("Carte complète aujourd'hui", lignes_utiles(existante.texte)),
            "L'essai est fini : supprimer le contact « Carnet Essai » sur l'iPhone, puis confirmer la "
            "suppression dans « À traiter » de carnet."]
    return out


# ----------------------------------------------------------------- B : les logos

def fiches_sans_photo(chemin) -> list[dict]:
    """Fiches des groupes de sociétés, sans photo, lues sur une copie de la base."""
    travail = Path(tempfile.mkdtemp(prefix="essai28-"))
    for suffixe in ("", "-wal", "-shm"):
        source = Path(str(chemin) + suffixe)
        if source.is_file():
            shutil.copy2(source, travail / source.name)
    cx = sqlite3.connect(str(travail / Path(chemin).name))
    lignes = cx.execute("SELECT fiche FROM fiches WHERE NOT COALESCE(photo, 0)").fetchall()
    cx.close()
    shutil.rmtree(travail, ignore_errors=True)
    fiches = [json.loads(l[0]) for l in lignes]
    return [f for f in fiches if set(f.get("groupes") or []) & set(GROUPES_LOGO)]


def essai_logos(fiches: list[dict], chercher=logos.chercher, taille: int = ECHANTILLON, graine: int = 28) -> list[str]:
    domaines = [logos.domaine_de(f, domaine_pro) for f in fiches]
    avec = [d for d in domaines if d]
    distincts = sorted(set(avec))
    tirage = random.Random(graine).sample(distincts, min(taille, len(distincts)))
    trouves = nets = 0
    t0 = time.monotonic()
    for i, d in enumerate(tirage, 1):
        try:
            res = chercher(d)
        except Exception:  # noqa: BLE001 — un site qui casse ne doit pas arrêter la mesure
            res = []
        trouves += bool(res)
        nets += any(min(r["largeur"], r["hauteur"]) >= BON_LOGO for r in res)
        if i % 10 == 0:
            log(f"  logos : {i}/{len(tirage)} sites lus")
    duree = time.monotonic() - t0
    n = len(tirage)
    pct = lambda x: f"{round(100 * x / n)} %" if n else "sans objet"   # noqa: E731
    return ["## B. Recherche de logos", "",
            f"Groupes {' et '.join(GROUPES_LOGO)}, fiches sans photo : **{len(fiches)}**.", "",
            "| Mesure | Nombre |", "|---|---|",
            f"| Fiches avec un site ou un courriel professionnel | {len(avec)} |",
            f"| Fiches sans aucun des deux (logo introuvable par carnet) | {len(fiches) - len(avec)} |",
            f"| Sociétés différentes parmi elles | {len(distincts)} |",
            f"| Sociétés essayées | {n} |",
            f"| Logo trouvé | {trouves} ({pct(trouves)}) |",
            f"| dont logo net ({BON_LOGO} px ou plus) | {nets} ({pct(nets)}) |",
            f"| Durée moyenne par société | {duree / n:.1f} s |" if n else "| Durée | sans objet |", ""]


def main() -> int:
    cfg = charger()
    log(f"Essai carnet 2.8 (version {__version__})")
    md = ["# Essai avant carnet 2.8.0", ""]
    dav = CardDAV(cfg.icloud_url, cfg.icloud_user, cfg.icloud_password)
    try:
        premier = dav.lire_une(dav.href_nouveau(UID)) is None
        md += essai_carte(dav, cfg.data)
    finally:
        dav.fermer()
    if premier:
        if cfg.db_path.is_file():
            log("Mesure des logos (lecture des sites des sociétés)…")
            md += ["", *essai_logos(fiches_sans_photo(cfg.db_path))]
        else:
            md += ["", "## B. Recherche de logos", "", "Base de carnet introuvable : mesure non faite."]
    texte = "\n".join(md)
    print("\n" + texte)
    try:
        (cfg.data / f"rapport-essai-2.8-{'1' if premier else '2'}.md").write_text(texte, encoding="utf-8")
    except OSError as exc:
        log(f"Rapport non écrit sur disque ({exc}) : il est dans ce journal.")
    log("Fini — l'essai s'arrête.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

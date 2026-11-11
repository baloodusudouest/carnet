"""Sonde avant la 2.8.0 (étape 0 de la méthode) : lecture seule, rapport sans aucun nom.

    python -m app.sonde28

Répond à ce dont la conception de la 2.8.0 dépend :
  A. Les cartes iCloud, telles que carnet les a lues (base /state/carnet2.db, ouverte en lecture
     seule) : quelles propriétés existent déjà (dates supplémentaires, service, prononciation,
     conjoint), combien de contacts par groupe.
  B. La taille de la future famille « Manques », avec le tableau de départ des attentes par groupe.
  C. Les prénoms : combien sont composés ou multiples (pour le calcul des fêtes).
  D. Treemich : quels types d'évènements de vie et de relations existent, un mariage porte-t-il
     une date, et l'interface de Treemich annonce-t-elle de quoi en écrire un.

Rien n'est écrit : ni dans la base (lue sur une copie), ni dans iCloud (jamais contacté), ni dans Treemich (lectures
seulement, client verrouillé en lecture seule). Le rapport ne contient que des nombres, des noms
de propriétés techniques et des noms de groupes.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import charger
from .liens import ErreurLien, Treemich

__version__ = "1"

# Tableau de départ décidé au grill du 11/11/2026 (version allégée)
ATTENTES = {
    "Famille": ["telephone", "jour", "annee", "photo", "immich", "treemich", "liens"],
    "Amis": ["telephone", "jour", "photo", "immich"],
    "Jardin secret": ["telephone", "photo"],
    "Collègues": ["telephone", "photo", "societe"],
    "Clients": ["telephone", "photo", "societe"],
    "Artisans et services": ["telephone", "photo", "societe"],
    "Urgence": ["telephone"],
}
LIBELLES = {"telephone": "Sans téléphone", "jour": "Sans jour de naissance", "annee": "Sans année de naissance",
            "photo": "Sans photo ni logo", "immich": "Sans Immich", "treemich": "Sans Treemich",
            "liens": "Sans liens familiaux", "societe": "Sans société ni fonction"}
FAMILIAUX = {"conjoint", "partenaire", "mère", "père", "parent", "enfant", "frère", "sœur"}
LIBELLES_APPLE = re.compile(r"^_\$!<(.+)>!\$_$")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def tableau(entetes: list, lignes: list) -> str:
    out = ["| " + " | ".join(entetes) + " |", "|" + "|".join("---" for _ in entetes) + "|"]
    out += ["| " + " | ".join("" if v is None else str(v) for v in ligne) + " |" for ligne in lignes]
    return "\n".join(out)


# ----------------------------------------------------------------- A, B, C : la base de carnet

def proprietes(texte: str) -> tuple[Counter, Counter, bool]:
    """Noms des propriétés d'une carte, libellés des dates supplémentaires, présence d'un service."""
    noms, libelles_dates = Counter(), Counter()
    service = False
    lignes = re.sub(r"\r?\n[ \t]", "", texte).splitlines()       # lignes repliées recollées
    groupes_date = set()
    etiquettes = {}
    for ligne in lignes:
        if ":" not in ligne:
            continue
        tete, valeur = ligne.split(":", 1)
        nom = tete.split(";")[0]
        prefixe = None
        if "." in nom:
            prefixe, nom = nom.split(".", 1)
        nom = nom.upper()
        if nom in ("BEGIN", "END", "VERSION", "PRODID", "REV", "UID"):
            continue
        noms[nom] += 1
        if nom == "X-ABDATE" and prefixe:
            groupes_date.add(prefixe)
        if nom == "X-ABLABEL" and prefixe:
            etiquettes[prefixe] = valeur.strip()
        if nom == "ORG" and len([x for x in valeur.split(";") if x.strip()]) > 1:
            service = True
    for g in groupes_date:
        brut = etiquettes.get(g, "")
        m = LIBELLES_APPLE.match(brut)
        # Les libellés standard d'Apple sont cités ; un libellé saisi à la main est compté sans être écrit
        libelles_dates[m.group(1) if m else ("(libellé personnel)" if brut else "(sans libellé)")] += 1
    return noms, libelles_dates, service


def manques_de(fiche: dict, photo: bool, liens: set) -> dict[str, bool]:
    a = fiche.get("anniversaire") or ""
    return {
        "telephone": not fiche.get("telephones"),
        "jour": not a,
        "annee": len(a) != 10 or a.startswith("1900"),
        "photo": not photo,
        "immich": "immich" not in liens,
        "treemich": "treemich" not in liens,
        "liens": not any((n.get("type") or "") in FAMILIAUX for n in fiche.get("noms_associes") or []),
        "societe": not (fiche.get("societe") or fiche.get("fonction")),
    }


def sonder_base(chemin) -> dict:
    # La sonde travaille sur une copie : le volume de la base peut être monté en lecture seule,
    # et la base de carnet (qui tourne à côté) n'est jamais ouverte par un second programme.
    travail = Path(tempfile.mkdtemp(prefix="sonde28-"))
    for suffixe in ("", "-wal", "-shm"):
        source = Path(str(chemin) + suffixe)
        if source.is_file():
            shutil.copy2(source, travail / source.name)
    cx = sqlite3.connect(str(travail / Path(chemin).name))
    cx.row_factory = sqlite3.Row
    lignes = cx.execute("SELECT uid, texte, fiche, photo FROM fiches").fetchall()
    liens: dict[str, set] = {}
    for l in cx.execute("SELECT uid, service FROM liaisons"):
        liens.setdefault(l["uid"], set()).add(l["service"])
    validees = cx.execute("SELECT COUNT(*) FROM validations").fetchone()[0]
    cx.close()
    shutil.rmtree(travail, ignore_errors=True)

    cartes_avec = Counter()          # propriété → nombre de cartes qui la portent
    libelles_dates = Counter()
    avec_service = 0
    par_groupe = Counter()
    sans_groupe = plusieurs_groupes = 0
    manques = {g: Counter() for g in ATTENTES}
    fiches_incompletes = Counter()   # groupe → fiches avec au moins un manque attendu
    total_manques = Counter()        # manque → fiches (attentes cumulées de tous leurs groupes)
    incompletes_total = 0
    prenoms = Counter()
    conjoints = 0
    hors_tableau = Counter()
    for l in lignes:
        noms, dates, service = proprietes(l["texte"])
        for n in noms:
            cartes_avec[n] += 1
        libelles_dates.update(dates)
        avec_service += service
        f = json.loads(l["fiche"])
        groupes = f.get("groupes") or []
        if not groupes:
            sans_groupe += 1
        if len(groupes) > 1:
            plusieurs_groupes += 1
        m = manques_de(f, bool(l["photo"]), liens.get(l["uid"], set()))
        attendus = set()
        for g in groupes:
            par_groupe[g] += 1
            if g not in ATTENTES:
                hors_tableau[g] += 1
                continue
            attendus.update(ATTENTES[g])
            manquants = [k for k in ATTENTES[g] if m[k]]
            for k in manquants:
                manques[g][k] += 1
            fiches_incompletes[g] += bool(manquants)
        cumules = [k for k in attendus if m[k]]
        for k in cumules:
            total_manques[k] += 1
        incompletes_total += bool(cumules)
        p = (f.get("prenom") or "").strip()
        prenoms["vide" if not p else "composé (trait d'union)" if "-" in p else "plusieurs mots" if " " in p else "simple"] += 1
        conjoints += any((n.get("type") or "") in ("conjoint", "partenaire") for n in f.get("noms_associes") or [])
    return {"cartes": len(lignes), "cartes_avec": cartes_avec, "libelles_dates": libelles_dates,
            "avec_service": avec_service, "par_groupe": par_groupe, "sans_groupe": sans_groupe,
            "plusieurs_groupes": plusieurs_groupes, "manques": manques, "fiches_incompletes": fiches_incompletes,
            "total_manques": total_manques, "incompletes_total": incompletes_total, "prenoms": prenoms,
            "conjoints": conjoints, "validees": validees, "hors_tableau": hors_tableau,
            "liees": Counter(s for x in liens.values() for s in x)}


# ----------------------------------------------------------------- D : Treemich (lectures seulement)

def sonder_treemich(tm: Treemich, limite: int = 600) -> dict:
    tm.lecture_seule = True
    personnes = tm.personnes()
    relations = tm._get("/relationships", limit=2000).get("relationships", [])
    types_relations = Counter(r.get("type") for r in relations)
    cles_relations = Counter(k for r in relations for k, v in r.items() if v not in (None, "", [], {}))
    couples = {frozenset((r.get("fromPersonId"), r.get("toPersonId"))) for r in relations
               if "SPOUSE" in (r.get("type") or "") or "PARTNER" in (r.get("type") or "")}
    types_evenements, cles_evenements = Counter(), {}
    avec_date = Counter()
    personnes_mariage = set()
    lues = 0
    for i, p in enumerate(personnes[:limite], 1):
        for e in tm._get(f"/people/{p['id']}/life-events").get("lifeEvents", []):
            t = e.get("eventType") or "(sans type)"
            types_evenements[t] += 1
            cles_evenements.setdefault(t, Counter()).update(k for k, v in e.items() if v not in (None, "", [], {}))
            avec_date[t] += bool(e.get("year"))
            if "MARR" in t or "WEDD" in t or "UNION" in t or "PACS" in t:
                personnes_mariage.add(p["id"])
        lues = i
        if i % 100 == 0:
            log(f"  {i}/{min(len(personnes), limite)} personnes lues dans Treemich")
    couples_avec = sum(1 for c in couples if c & personnes_mariage)
    # L'interface de Treemich décrit-elle comment écrire un évènement ? (simple lecture de sa description)
    api = []
    for chemin in ("/openapi.json", "/docs-json", "/api-json", "/swagger.json"):
        try:
            r = tm._appel("GET", chemin)
        except ErreurLien:
            continue
        if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
            try:
                chemins = r.json().get("paths", {})
            except ValueError:
                continue
            for c, methodes in sorted(chemins.items()):
                if re.search(r"life-event|relationship|marriage|union", c, re.I):
                    api.append((c, ", ".join(sorted(m.upper() for m in methodes if m.lower() in
                                                    ("get", "post", "put", "patch", "delete")))))
            break
    return {"personnes": len(personnes), "personnes_lues": lues, "relations": len(relations),
            "types_relations": types_relations, "cles_relations": cles_relations, "couples": len(couples),
            "couples_avec_evenement": couples_avec, "types_evenements": types_evenements,
            "cles_evenements": cles_evenements, "avec_date": avec_date, "api": api}


# ----------------------------------------------------------------- rapport

def rapport(b: dict, t: dict | None, erreur_treemich: str | None) -> str:
    md = [f"# Sonde carnet 2.8 — {datetime.now():%Y-%m-%d %H:%M}", "",
          f"Sonde {__version__}, lecture seule. Aucun nom de personne : des nombres, des noms de propriétés et de groupes.", ""]
    md += ["## A. Cartes iCloud (d'après la base de carnet)", "", f"- {b['cartes']} cartes, {b['validees']} validées.",
           f"- Liées : Immich {b['liees'].get('immich', 0)}, Treemich {b['liees'].get('treemich', 0)}.",
           f"- Avec un conjoint ou partenaire parmi les noms associés : {b['conjoints']}.",
           f"- Avec un service en plus de la société (ORG à deux parties) : {b['avec_service']}.", "",
           "### Propriétés présentes (nombre de cartes)", "",
           tableau(["Propriété", "Cartes"], b["cartes_avec"].most_common()), "",
           "### Dates supplémentaires déjà présentes (X-ABDATE), par libellé", "",
           tableau(["Libellé", "Dates"], b["libelles_dates"].most_common()) if b["libelles_dates"] else "Aucune.", ""]
    md += ["## B. Groupes et future famille « Manques »", "",
           f"- Sans groupe : {b['sans_groupe']}. Dans plusieurs groupes : {b['plusieurs_groupes']}.",
           f"- Fiches avec au moins un manque attendu (attentes cumulées de leurs groupes) : **{b['incompletes_total']}** sur {b['cartes']}.", "",
           "### Par groupe", "",
           tableau(["Groupe", "Contacts", "Incomplets"] + [LIBELLES[k] for k in LIBELLES],
                   [[g, b["par_groupe"].get(g, 0), b["fiches_incompletes"].get(g, 0)]
                    + [(b["manques"][g].get(k, 0) if k in ATTENTES[g] else "—") for k in LIBELLES] for g in ATTENTES]), "",
           "« — » : non attendu pour ce groupe.", "",
           "### Lignes de la famille « Manques » (une ligne par manque)", "",
           tableau(["Manque", "Fiches"], [[LIBELLES[k], n] for k, n in b["total_manques"].most_common()]), ""]
    if b["hors_tableau"]:
        md += ["### Groupes sans attentes dans le tableau de départ", "",
               tableau(["Groupe", "Contacts"], b["hors_tableau"].most_common()), ""]
    md += ["## C. Prénoms (pour les fêtes)", "", tableau(["Forme", "Contacts"], b["prenoms"].most_common()), ""]
    md += ["## D. Treemich", ""]
    if erreur_treemich:
        md += [f"Non sondé : {erreur_treemich}", ""]
    elif t:
        md += [f"- {t['personnes']} personnes ({t['personnes_lues']} lues), {t['relations']} relations.",
               f"- Couples (relation de conjoint ou partenaire) : {t['couples']}, dont {t['couples_avec_evenement']} avec un évènement de mariage ou d'union.", "",
               "### Types de relations", "", tableau(["Type", "Nombre"], t["types_relations"].most_common()), "",
               "Champs remplis dans une relation : " + (", ".join(f"{k} ({n})" for k, n in t["cles_relations"].most_common()) or "aucun") + ".", "",
               "### Types d'évènements de vie", "",
               tableau(["Type", "Nombre", "Avec une année", "Champs remplis"],
                       [[ty, n, t["avec_date"].get(ty, 0), ", ".join(sorted(t["cles_evenements"].get(ty, {})))]
                        for ty, n in t["types_evenements"].most_common()]) if t["types_evenements"] else "Aucun évènement de vie.", "",
               "### Ce que l'interface de Treemich annonce pour les évènements et les relations", "",
               tableau(["Chemin", "Méthodes"], t["api"]) if t["api"] else "Aucune description d'interface trouvée (openapi.json et variantes).", ""]
    return "\n".join(md) + "\n"


def main() -> int:
    cfg = charger()
    log(f"Sonde carnet 2.8 (version {__version__}) — base {cfg.db_path}")
    if not cfg.db_path.is_file():
        print("Base de carnet introuvable : la sonde se lance avec les mêmes volumes que carnet.", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    b = sonder_base(cfg.db_path)
    log(f"Base lue : {b['cartes']} cartes en {time.monotonic() - t0:.1f} s")
    t, erreur = None, None
    if cfg.treemich_email:
        try:
            log("Treemich (lectures seulement)…")
            t = sonder_treemich(Treemich(cfg.treemich_url, cfg.treemich_email, cfg.treemich_password))
        except Exception as exc:  # noqa: BLE001 — la sonde va au bout
            erreur = f"{type(exc).__name__}: {exc}"
            log(f"  Treemich non sondé : {erreur}")
    else:
        erreur = "Treemich n'est pas configuré."
    md = rapport(b, t, erreur)
    print("\n" + md)
    try:
        (cfg.data / "rapport-sonde-2.8.md").write_text(md, encoding="utf-8")
        log(f"Rapport écrit dans {cfg.data}/rapport-sonde-2.8.md — la sonde s'arrête.")
    except OSError as exc:
        log(f"Rapport non écrit sur disque ({exc}) : il est dans ce journal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

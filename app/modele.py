"""Forme d'une fiche contact, commune aux sources et à la fiche retenue.

{
  "prenom": str, "nom": str, "surnom": str, "societe": str, "fonction": str,
  "anniversaire": "AAAA-MM-JJ" | "--MM-JJ" | "", "notes": str,
  "photo": id de la fiche source dont on garde la photo | None,
  "telephones":    [{"valeur": "+33612345678", "type": "mobile", "affichage": "+33 6 12 34 56 78", "valide": True}],
  "courriels":     [{"valeur": "a@b.fr", "type": "domicile"}],
  "adresses":      [{"rue": "", "cp": "", "ville": "", "region": "", "pays": "", "type": "domicile"}],
  "sites":         [{"valeur": "https://…", "type": "linkedin"}],
  "noms_associes": [{"valeur": "Marie DURAND", "type": "conjoint"}],
  "groupes":       ["Famille", …],
}
"""
from __future__ import annotations

import copy

GROUPE_VERIFIES = "✓ Vérifiés"
GROUPES = ["Moi", "Urgence", "Famille", "Amis", "Artisans et services", "Collègues", "Clients", "Jardin secret"]
# Ta propre fiche : une seule à la fois
GROUPE_MOI = "Moi"
GROUPES_TRAVAIL = ["Collègues", "Clients"]
# Ancien groupe, remplacé par Collègues / Clients : gardé à l'import, à classer dans l'onglet Revue
GROUPE_A_CLASSER = "Travail"
GROUPES_RECONNUS = GROUPES + [GROUPE_A_CLASSER]
# Groupes créés dans l'onglet Groupes : [{"nom": …, "regle": "proches" | "travail" | None}],
# enregistrés dans la base et chargés au démarrage (normalisation.configurer_groupes)
GROUPES_PERSO: list[dict] = []
# Règles des groupes intégrés (non modifiables)
REGLES_GROUPES = {"Famille": "proches", "Amis": "proches", "Jardin secret": "proches",
                  "Artisans et services": "travail", "Collègues": "travail", "Clients": "travail"}


def groupes_tous() -> list[str]:
    return GROUPES + [g["nom"] for g in GROUPES_PERSO]


def groupes_reconnus() -> list[str]:
    return groupes_tous() + [GROUPE_A_CLASSER]


def regles_groupes() -> dict[str, str]:
    return {**REGLES_GROUPES, **{g["nom"]: g["regle"] for g in GROUPES_PERSO if g.get("regle")}}
GROUPE_URGENCE = "Urgence"

CHAMPS_SIMPLES = ["prenom", "nom", "surnom", "societe", "fonction", "anniversaire", "notes"]
CHAMPS_MULTIPLES = ["telephones", "courriels", "adresses", "sites", "noms_associes"]

TYPES = {
    "telephones": ["mobile", "domicile", "travail", "bureau", "principal", "autre"],
    "courriels": ["domicile", "travail", "autre"],
    "adresses": ["domicile", "travail", "autre"],
    "sites": ["site", "linkedin", "facebook", "instagram", "x", "tiktok", "telegram", "whatsapp",
              "signal", "autre"],
    "noms_associes": ["conjoint", "partenaire", "mère", "père", "parent", "enfant",
                      "frère", "sœur", "ami", "assistant", "responsable", "autre"],
}

# Ordre de préférence pour proposer une valeur unique (prénom, société…)
PRIORITE_SOURCES = ["icloud", "gmail", "outlook", "linkedin"]
LIBELLES_SOURCES = {"icloud": "iCloud", "gmail": "Gmail", "outlook": "Outlook", "linkedin": "LinkedIn",
                    "immich": "Immich"}


def fiche_vide() -> dict:
    return {
        "prenom": "", "nom": "", "surnom": "", "societe": "", "fonction": "",
        "anniversaire": "", "notes": "", "photo": None,
        "telephones": [], "courriels": [], "adresses": [], "sites": [], "noms_associes": [],
        "groupes": [],
    }


def completer(fiche: dict | None) -> dict:
    """Ajoute les clés manquantes (fiches anciennes ou partielles)."""
    base = fiche_vide()
    for cle, valeur in (fiche or {}).items():
        if cle in base:
            base[cle] = copy.deepcopy(valeur)
    return base


def nom_affiche(fiche: dict) -> str:
    nom = " ".join(p for p in (fiche.get("prenom", ""), fiche.get("nom", "")) if p).strip()
    if nom:
        return nom
    for repli in ("societe", "surnom"):
        if fiche.get(repli):
            return fiche[repli]
    if fiche.get("courriels"):
        return fiche["courriels"][0]["valeur"]
    if fiche.get("telephones"):
        return fiche["telephones"][0].get("affichage") or fiche["telephones"][0]["valeur"]
    return "(sans nom)"

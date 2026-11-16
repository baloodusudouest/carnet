"""Réglages d'usage de carnet (2.26) et leur sauvegarde chez l'Anneau (contrat de sauvegarde 1).

Deux sortes de réglages, rendus ensemble en un seul dict :
- ceux qui venaient de la stack (heure de la nuit, émojis → groupes, carnet d'adresses Synology,
  vérification du certificat de Synology) : fichier `<state>/reglages.json` (maison.Reglages).
  Au premier démarrage, chacun reprend son ancienne variable si elle est posée, puis la variable
  n'est plus jamais lue : seul l'écran Réglages fait foi ;
- les interrupteurs déjà réglables dans l'appli (écritures de la nuit, service par service) :
  ils gardent leur stockage dans la table `kv` (`auto_fetes`, `auto_famille`, `nuit_<service>`).

Un réglage changé s'applique tout de suite : `c.cfg` est refait, les règles d'émojis rechargées,
et la boucle de la nuit réveillée pour recalculer son heure (aucun redémarrage).
"""
from __future__ import annotations

import dataclasses
import re

from . import maison, normalisation
from .garde import ErreurCarnet

ID_APPLI = "carnet"                     # nom du dépôt : identifiant chez l'Anneau

# Réglages sortis de la stack : clé → ancienne variable, reprise une seule fois (premier démarrage)
VARIABLES = {
    "emoji_groupes": "CARNET_EMOJI_GROUPES",
    "veille_heure": "CARNET_VEILLE_HEURE",
    "synology_carnet": "CARNET_SYNOLOGY_CARNET",
    "synology_verifier_tls": "CARNET_SYNOLOGY_VERIFIER_TLS",
}

# Interrupteurs de la nuit déjà réglables dans l'appli (Connexion), gardés dans la table kv
INTERRUPTEURS = {
    "auto_fetes": ("famille", "fetes"),         # iCloud : écrire les fêtes
    "auto_famille": ("famille", "famille"),     # Treemich : accorder mariages et décès
    "nuit_immich": ("connexion", "immich"),
    "nuit_synology": ("connexion", "synology"),
    "nuit_kit": ("connexion", "kit"),
}

# Clés qui ne sortent jamais de carnet, même si un jour elles entraient dans les réglages :
# adresses de la stack et forçage de lecture seule (ce sont des variables, pas des réglages d'usage).
EXCLUS = ("icloud_url", "synology_url", "immich_url", "treemich_url", "kit_url", "millesime_url",
          "linkedin_redirect", "lecture_seule")

HEURE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
ARRET = ("", "off", "non", "0")


def _defauts(cfg) -> dict:
    return {k: getattr(cfg, k) for k in VARIABLES}


def _verifier_un(k: str, v):
    """Valeur propre ou ErreurCarnet (400) avec un message clair."""
    if k in INTERRUPTEURS or k == "synology_verifier_tls":
        if not isinstance(v, bool):
            raise ErreurCarnet(f"Réglage « {k} » : oui ou non attendu (true ou false).")
        return v
    if not isinstance(v, str):
        raise ErreurCarnet(f"Réglage « {k} » : texte attendu.")
    v = v.strip()
    if k == "veille_heure":
        if v.lower() in ARRET:
            return "off"
        if not HEURE.match(v):
            raise ErreurCarnet("Heure de la nuit : « HH:MM » attendu (par exemple 03:00), ou « off » pour la désactiver.")
        h, m = v.split(":")
        return f"{int(h):02d}:{m}"
    if k == "emoji_groupes":
        for regle in v.split(";"):
            if not regle.strip():
                continue
            emoji, _, groupe = regle.partition(":")
            if not emoji.strip() or not groupe.strip():
                raise ErreurCarnet(f"Émojis : la règle « {regle.strip()} » doit s'écrire « émoji:groupe » "
                                   "(règles séparées par ;).")
        return v
    return v                                # synology_carnet : un ou plusieurs noms séparés par |


def verifier(valeurs) -> dict:
    if not isinstance(valeurs, dict):
        raise ErreurCarnet("Réglages : un objet {clé: valeur} est attendu.")
    propres = {}
    for k, v in valeurs.items():
        if k not in VARIABLES and k not in INTERRUPTEURS:
            raise ErreurCarnet(f"Réglage inconnu : « {k} ».")
        propres[k] = _verifier_un(k, v)
    return propres


def _appliquer(c) -> None:
    """Recopie les réglages du fichier dans c.cfg ; recharge les émojis ; réveille la nuit."""
    valeurs = c.reglages_fichier.tout()
    normalisation.configurer_emojis(valeurs["emoji_groupes"])
    if c.cfg.emoji_groupes != valeurs["emoji_groupes"]:
        c.oublier()                           # À traiter recalcule les émojis sans groupe
    c.cfg = dataclasses.replace(c.cfg, **valeurs)
    c.reveil.set()


def ouvrir(c) -> None:
    """Au démarrage de carnet : fichier des réglages, reprise des anciennes variables (une fois)."""
    defauts = _defauts(c.cfg)
    fichier = maison.Reglages(c.cfg.state / "reglages.json", defauts, VARIABLES)
    c.reglages_fichier = fichier
    for k in fichier.repris:
        c.base.noter("reglages", f"Réglage « {k} » repris de la variable {VARIABLES[k]} (premier démarrage) : "
                                 "il se change désormais dans Réglages.")
    # Une valeur reprise ou écrite à la main qui ne tient pas (heure impossible…) : défaut, et on le dit
    for k, v in fichier.tout().items():
        try:
            propre = _verifier_un(k, v)
        except ErreurCarnet as exc:
            fichier.changer({k: defauts[k]})
            c.base.noter("reglages", f"{exc} Valeur par défaut remise.")
            continue
        if propre != v:
            fichier.changer({k: propre})
    _appliquer(c)


def _interrupteur(c, k: str) -> bool:
    from . import connexion, famille
    module, quoi = INTERRUPTEURS[k]
    return famille.actif(c, quoi) if module == "famille" else connexion.nuit_active(c, quoi)


def tout(c) -> dict:
    return {**c.reglages_fichier.tout(), **{k: _interrupteur(c, k) for k in INTERRUPTEURS}}


def changer(c, valeurs, origine: str = "Réglages") -> dict:
    """Change les réglages donnés (ErreurCarnet si une valeur ne va pas : rien n'est changé)."""
    from . import connexion, famille
    propres = verifier(valeurs)
    avant = tout(c)
    fichier = {k: v for k, v in propres.items() if k in VARIABLES}
    if fichier:
        c.reglages_fichier.changer(fichier)
        _appliquer(c)
    for k, v in propres.items():
        if k in INTERRUPTEURS:
            if avant[k] != v:
                module, quoi = INTERRUPTEURS[k]
                (famille.regler if module == "famille" else connexion.regler_nuit)(c, quoi, v)
        elif avant[k] != v:
            c.base.noter("reglages", f"{origine} : « {k} » {avant[k]!r} → {v!r}")
    return tout(c)


# ---------------------------------------------------------------- sauvegarde et restauration

def sauvegarde(c, version: str) -> dict:
    return maison.sauvegarde(ID_APPLI, version, tout(c), exclus=EXCLUS)


def differences(c, sauves: dict) -> list[dict]:
    return maison.differences(tout(c), sauves or {}, EXCLUS)


def restaurer(c, sauvegarde_: dict) -> dict:
    """Applique les différences d'une sauvegarde (réglages seulement ; permis en lecture seule)."""
    diff = differences(c, sauvegarde_.get("reglages") or {})
    valeurs = {}
    for d in diff:
        try:
            valeurs[d["cle"]] = _verifier_un(d["cle"], d["sauve"])
        except ErreurCarnet:
            continue                          # valeur d'une ancienne version qui ne tient plus : ignorée
    if valeurs:
        changer(c, valeurs, origine=f"Restauration du {sauvegarde_.get('le', '?')}")
    c.base.noter("reglages", f"Réglages restaurés depuis la sauvegarde du {sauvegarde_.get('le', '?')} : "
                             f"{len(valeurs)} changement(s).")
    return {"reglages": tout(c), "changes": sorted(valeurs)}

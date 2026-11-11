"""Erreurs communes, et garde du mode lecture seule.

Mode lecture seule (CARNET_LECTURE_SEULE=oui dans la stack) : carnet lit tout, calcule tout,
mais n'écrit dans aucun service extérieur (iCloud, Immich, Treemich, Synology Contacts, kit
d'urgence). Sert à essayer une nouvelle version sans risque. La garde est posée deux fois :
à l'entrée des opérations (message clair avant tout travail) et dans les accès réseau
eux-mêmes (rien ne passe, même par un chemin oublié).
"""
from __future__ import annotations


class ErreurCarnet(Exception):
    """Erreur à afficher telle quelle dans l'interface."""


class Occupe(ErreurCarnet):
    """Une autre écriture est en cours."""


class LectureSeule(ErreurCarnet):
    """Écriture refusée : carnet est en mode lecture seule."""

    def __init__(self, service: str):
        super().__init__(f"Mode lecture seule : rien n'est écrit dans {service}. "
                         "Retire CARNET_LECTURE_SEULE de la stack pour écrire de nouveau.")
        self.service = service

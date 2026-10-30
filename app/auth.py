"""Connexion par mot de passe unique (CARNET_PASSWORD) et cookie de session signé.

Le cookie est signé avec une clé dérivée du mot de passe et de la clé de la base :
changer l'un ou l'autre déconnecte tous les navigateurs. « Se déconnecter » incrémente
une génération enregistrée dans la base : tous les cookies émis avant deviennent invalides.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

COOKIE = "carnet_session"


class Sessions:
    def __init__(self, mot_de_passe: str, cle_base: str, jours: int, generation: int = 0):
        self._mdp = mot_de_passe.encode()
        secret = hashlib.sha256(b"carnet-session|" + self._mdp + b"|" + cle_base.encode()).hexdigest()
        self._signer = TimestampSigner(secret, salt="carnet")
        self.duree = jours * 86400
        self.generation = generation
        self._echecs: list[float] = []

    def attente(self) -> float:
        """Délai à imposer avant de répondre : 1 s par défaut, 5 s après 5 échecs en 5 minutes."""
        maintenant = time.monotonic()
        self._echecs = [t for t in self._echecs if maintenant - t < 300]
        return 5.0 if len(self._echecs) >= 5 else 1.0

    def verifier_mot_de_passe(self, propose: str) -> bool:
        ok = hmac.compare_digest(propose.encode(), self._mdp)
        if not ok:
            self._echecs.append(time.monotonic())
        return ok

    def creer(self) -> str:
        return self._signer.sign(f"session:{self.generation}".encode()).decode()

    def valide(self, jeton: str | None) -> bool:
        if not jeton:
            return False
        try:
            contenu = self._signer.unsign(jeton, max_age=self.duree).decode()
        except (BadSignature, SignatureExpired):
            return False
        return contenu == f"session:{self.generation}"

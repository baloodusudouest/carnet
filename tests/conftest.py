"""Réglages communs aux tests."""
import pytest

from app import carddav


@pytest.fixture(autouse=True)
def sans_pauses(monkeypatch):
    # Les nouveaux essais CardDAV après un raté du serveur se font sans attendre dans les tests
    monkeypatch.setattr(carddav.CardDAV, "PAUSES", (0, 0, 0))


@pytest.fixture(autouse=True)
def sans_pause_de_refus():
    # Chaque test repart sans pause après refus ni découverte retenue
    carddav._refus.clear()
    carddav._decouverts.clear()
    yield


# 2.11.1 : pas d'attente d'Immich avant la reprise du visage par Treemich pendant les tests
from app import photos as _photos  # noqa: E402

_photos.ATTENTE_IMMICH = 0

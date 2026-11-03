"""Heure locale (Europe/Paris) : remplaçable dans les tests."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Paris")
_decalage = None   # tests : datetime fixe


def maintenant() -> datetime:
    return _decalage or datetime.now(ZONE)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def fixer(d: datetime | None) -> None:
    global _decalage
    _decalage = d

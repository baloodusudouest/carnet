"""Portraits haute définition tirés des photos Immich.

Immich donne, pour chaque visage reconnu, son cadre dans l'image analysée (imageWidth ×
imageHeight) : on le garde en coordonnées relatives (0 à 1), valables pour n'importe quelle
taille de la même photo (aperçu, pleine taille, original redressé).

Classement : taille réelle du visage sur la photo d'origine, puis netteté mesurée sur le
visage (variance du laplacien, sur un aperçu ramené à une taille fixe).
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

TAILLE_SORTIE = 1024     # côté du portrait carré envoyé à iCloud (assez pour un écran Retina)
MARGE_BORD = 0.01        # un visage qui touche le bord de la photo est coupé : écarté
VISAGE_MIN = 250         # côté minimal du visage sur la photo d'origine (pixels)
NETTETE_REF = 120.0      # variance du laplacien à partir de laquelle un visage est jugé net
NETTETE_MIN = 25.0       # en dessous : flou, écarté s'il existe d'autres choix


def boite_relative(visage: dict) -> tuple[float, float, float, float] | None:
    """Cadre Immich → (x1, y1, x2, y2) entre 0 et 1."""
    l, h = visage.get("imageWidth") or 0, visage.get("imageHeight") or 0
    if l <= 0 or h <= 0:
        return None
    x1, x2 = sorted((visage["boundingBoxX1"] / l, visage["boundingBoxX2"] / l))
    y1, y2 = sorted((visage["boundingBoxY1"] / h, visage["boundingBoxY2"] / h))
    if x2 - x1 <= 0 or y2 - y1 <= 0:
        return None
    return x1, y1, x2, y2


def entier(boite: tuple[float, float, float, float]) -> bool:
    """Visage entier : il ne touche aucun bord de la photo."""
    x1, y1, x2, y2 = boite
    return x1 > MARGE_BORD and y1 > MARGE_BORD and x2 < 1 - MARGE_BORD and y2 < 1 - MARGE_BORD


def taille_reelle(boite, largeur: int | None, hauteur: int | None, visage: dict) -> int:
    """Côté du visage en pixels sur la photo d'origine (à défaut, sur l'image analysée)."""
    l, h = largeur or 0, hauteur or 0
    li, hi = visage.get("imageWidth") or 0, visage.get("imageHeight") or 0
    if l and h and li and hi and (l > h) != (li > hi):   # original non redressé : on retourne
        l, h = h, l
    if not (l and h):
        l, h = li, hi
    x1, y1, x2, y2 = boite
    return int(min((x2 - x1) * l, (y2 - y1) * h))


def _ouvrir(contenu: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(contenu))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def lisible(contenu: bytes) -> bool:
    try:
        Image.open(io.BytesIO(contenu)).verify()
        return True
    except Exception:  # noqa: BLE001 — format inconnu de Pillow (HEIC, RAW…)
        return False


def nettete(contenu: bytes, boite) -> float:
    """Variance du laplacien sur le visage ramené à 256 px (indépendant de la résolution)."""
    img = _ouvrir(contenu)
    l, h = img.size
    x1, y1, x2, y2 = boite
    visage = img.crop((int(x1 * l), int(y1 * h), max(int(x2 * l), int(x1 * l) + 1), max(int(y2 * h), int(y1 * h) + 1)))
    gris = np.asarray(visage.convert("L").resize((256, 256), Image.Resampling.LANCZOS), dtype=np.float64)
    lap = (gris[:-2, 1:-1] + gris[2:, 1:-1] + gris[1:-1, :-2] + gris[1:-1, 2:] - 4 * gris[1:-1, 1:-1])
    return float(lap.var())


def score(taille: int, net: float | None) -> float:
    """Taille (plafonnée : au-delà de 1 200 px, plus grand n'apporte rien) pondérée par la netteté."""
    t = min(taille, 1200)
    if net is None:
        return t * 0.6
    return t * (0.35 + 0.65 * min(net / NETTETE_REF, 1.0))


def cadre_portrait(boite, l: int, h: int) -> tuple[int, int, int, int]:
    """Carré « haut des épaules » : visage centré horizontalement, un peu au-dessus du centre."""
    x1, y1, x2, y2 = boite[0] * l, boite[1] * h, boite[2] * l, boite[3] * h
    cote = max(x2 - x1, y2 - y1) * 2.4
    cote = min(cote, l, h)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2 + (y2 - y1) * 0.35
    gauche = min(max(cx - cote / 2, 0), l - cote)
    haut = min(max(cy - cote / 2, 0), h - cote)
    return int(gauche), int(haut), int(gauche + cote), int(haut + cote)


def portrait(contenu: bytes, boite, taille: int = TAILLE_SORTIE) -> tuple[bytes, str]:
    """Portrait carré en JPEG, à partir de n'importe quelle taille de la photo."""
    img = _ouvrir(contenu)
    carre = img.crop(cadre_portrait(boite, *img.size))
    if carre.width > taille:
        carre = carre.resize((taille, taille), Image.Resampling.LANCZOS)
    sortie = io.BytesIO()
    carre.save(sortie, "JPEG", quality=90, optimize=True)
    return sortie.getvalue(), "image/jpeg"

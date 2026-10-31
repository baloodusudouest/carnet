"""Portraits haute définition tirés des photos Immich.

Immich donne, pour chaque visage reconnu, son cadre dans l'image analysée (imageWidth ×
imageHeight) : on le garde en coordonnées relatives (0 à 1), valables pour n'importe quelle
taille de la même photo (aperçu, pleine taille, original redressé).

Classement : taille réelle du visage sur la photo d'origine, netteté mesurée sur le visage
(détail des fréquences moyennes, sur un aperçu ramené à une taille fixe : le grain d'un écran
photographié ou d'une image pixélisée n'y compte pas), repérage des photos d'écran (trame
régulière : pics dans le spectre), et orientation : le détecteur
YuNet (OpenCV, modèle MIT de opencv_zoo) repère les yeux, le nez et la bouche ; un visage de
profil ou caché (main, verre, cheveux) est pénalisé.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

TAILLE_SORTIE = 1024     # côté du portrait carré envoyé à iCloud (assez pour un écran Retina)
MARGE_BORD = 0.01        # un visage qui touche le bord de la photo est coupé : écarté
VISAGE_MIN = 250         # côté minimal du visage sur la photo d'origine (pixels)
NETTETE_REF = 110.0      # détail des traits à partir duquel un visage est jugé net
NETTETE_MIN = 45.0       # en dessous : flou, écarté s'il existe d'autres choix
ECRAN_MAX = 0.5          # au-dessus : photo d'un écran ou image pixélisée, écartée s'il existe d'autres choix
VERSION_MESURES = 2      # changer cette valeur fait remesurer les candidats déjà connus


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


def _visage_gris(contenu: bytes, boite) -> Image.Image:
    img = _ouvrir(contenu)
    l, h = img.size
    x1, y1, x2, y2 = boite
    visage = img.crop((int(x1 * l), int(y1 * h), max(int(x2 * l), int(x1 * l) + 1), max(int(y2 * h), int(y1 * h) + 1)))
    return visage.convert("L").resize((256, 256), Image.Resampling.LANCZOS)


def qualite(contenu: bytes, boite) -> tuple[float, float]:
    """(netteté, écran) mesurées sur le visage ramené à 256 px.

    Netteté : écart type de la bande de fréquences moyennes (différence de deux flous), celle des
    traits du visage. Le grain très fin (pixels d'un écran, moiré, bruit) n'y entre pas, alors
    qu'il gonflait la variance du laplacien.
    Écran : 0 à 1 selon la force des pics isolés dans les hautes fréquences du spectre ; une
    trame régulière (pixels d'un écran photographié, image agrandie) en crée, une photo non."""
    gris = _visage_gris(contenu, boite)
    g = np.asarray(gris, dtype=np.float64)

    def flou(r: float) -> np.ndarray:
        return np.asarray(gris.filter(ImageFilter.GaussianBlur(r)), dtype=np.float64)
    net = float((flou(1.5) - flou(4)).std()) * 15
    spectre = np.abs(np.fft.fftshift(np.fft.fft2(g - g.mean())))
    yy, xx = np.mgrid[-128:128, -128:128]
    rayon = np.hypot(xx, yy)
    hautes = spectre[(rayon > 40) & (rayon < 127)]
    pic = float(hautes.max() / max(float(np.median(hautes)), 1e-6))
    ecran = min(max((pic - 80) / 120, 0.0), 1.0)
    return round(net, 1), round(ecran, 2)


MODELE_YUNET = Path(__file__).parent / "modeles" / "face_detection_yunet_2023mar.onnx"
_verrou_yunet = threading.Lock()
_yunet = None


def _detecteur():
    global _yunet
    if _yunet is None:
        import cv2   # chargé seulement quand on en a besoin (démarrage plus rapide)
        _yunet = cv2.FaceDetectorYN.create(str(MODELE_YUNET), "", (320, 320), 0.6, 0.3, 50)
    return _yunet


def de_face(contenu: bytes, boite) -> float:
    """Orientation du visage : 1 = bien de face, 0 = de profil ou masqué (pas de visage repéré).
    Mesure : décalage du nez et de la bouche par rapport au milieu des yeux, et écart entre les
    yeux rapporté à la largeur du visage (il se réduit quand la tête tourne)."""
    img = _ouvrir(contenu)
    l, h = img.size
    x1, y1, x2, y2 = boite[0] * l, boite[1] * h, boite[2] * l, boite[3] * h
    m = max(x2 - x1, y2 - y1) * 0.6
    cadre = (int(max(x1 - m, 0)), int(max(y1 - m, 0)), int(min(x2 + m, l)), int(min(y2 + m, h)))
    zone = img.crop(cadre)
    echelle = 480 / max(zone.size)
    zone = zone.resize((max(int(zone.width * echelle), 1), max(int(zone.height * echelle), 1)), Image.Resampling.LANCZOS)
    bgr = np.ascontiguousarray(np.asarray(zone)[:, :, ::-1])
    with _verrou_yunet:
        det = _detecteur()
        det.setInputSize(zone.size)
        _, visages = det.detect(bgr)
    if visages is None or not len(visages):
        return 0.0
    # Le visage Immich : celui dont le centre est le plus proche du centre du cadre attendu
    cx, cy = ((x1 + x2) / 2 - cadre[0]) * echelle, ((y1 + y2) / 2 - cadre[1]) * echelle
    v = min(visages, key=lambda f: (f[0] + f[2] / 2 - cx) ** 2 + (f[1] + f[3] / 2 - cy) ** 2)
    largeur = max(float(np.sqrt(v[2] * v[3])), 1.0)          # indépendant d'une tête penchée
    oeil_d, oeil_g, nez = v[4:6], v[6:8], v[8:10]
    bouche = (v[10:12] + v[12:14]) / 2
    ecart = float(np.hypot(*(oeil_g - oeil_d)))
    if ecart < 1:
        return 0.0
    milieu = (oeil_d + oeil_g) / 2
    axe = (oeil_g - oeil_d) / ecart                           # mesuré le long de l'axe des yeux
    decalage = max(abs(float(np.dot(nez - milieu, axe))), abs(float(np.dot(bouche - milieu, axe)))) / ecart
    rotation = max(0.0, 1 - decalage / 0.5)               # nez au-dessus d'un œil : de profil
    ouverture = min(1.0, ecart / (0.36 * largeur))        # yeux rapprochés : tête tournée
    confiance = min(1.0, float(v[14]) / 0.85)
    return round(rotation * ouverture * confiance, 2)


def score(taille: int, net: float | None, face: float | None = None, ecran: float | None = None) -> float:
    """Taille (plafonnée : au-delà de 1 200 px, plus grand n'apporte rien) pondérée par la netteté
    et par l'orientation (un visage de profil vaut moins de la moitié d'un visage de face)."""
    t = min(taille, 1200)
    t *= 0.6 if net is None else 0.35 + 0.65 * min(net / NETTETE_REF, 1.0)
    if face is not None:
        t *= 0.25 + 0.75 * face
    if ecran:
        t *= 1 - 0.8 * ecran
    return t


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

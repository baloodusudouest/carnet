"""Images des contacts : portraits carrés, affiches plein écran et légendes, à partir des photos
Immich et du cadre de visage qu'Immich fournit (coordonnées relatives, de 0 à 1).

Pas de détection de visage ici : Immich l'a déjà faite. Les candidats sont classés par la taille
réelle du visage, et c'est Julien qui choisit parmi les meilleurs.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

TAILLE_SORTIE = 512      # côté du portrait carré écrit dans la fiche (assez pour l'iPhone, léger pour iCloud)
PHOTO_MAX = 100_000      # octets : iCloud refuse une fiche de plus d'environ 120 Ko, photo en base64 comprise


MARGE_BORD = 0.01        # un visage qui touche le bord de la photo est coupé : écarté


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


def cadre_portrait(boite, l: int, h: int) -> tuple[int, int, int, int]:
    """Carré « haut des épaules » : visage centré horizontalement, un peu au-dessus du centre."""
    x1, y1, x2, y2 = boite[0] * l, boite[1] * h, boite[2] * l, boite[3] * h
    cote = max(x2 - x1, y2 - y1) * 2.4
    cote = min(cote, l, h)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2 + (y2 - y1) * 0.35
    gauche = min(max(cx - cote / 2, 0), l - cote)
    haut = min(max(cy - cote / 2, 0), h - cote)
    return int(gauche), int(haut), int(gauche + cote), int(haut + cote)


def visage_dans_portrait(boite, ratio: float) -> tuple[float, float, float, float]:
    """Cadre du visage (0 à 1) dans le portrait découpé par ``cadre_portrait`` sur une photo de
    rapport largeur/hauteur ``ratio`` : Home Assistant centre ainsi le visage sur un cadre e-ink."""
    h = 10_000.0                                  # taille virtuelle : seul le rapport compte
    l = ratio * h
    g, t, d, b = cadre_portrait(boite, int(l), int(h))
    cote = max(d - g, 1)
    x1, y1, x2, y2 = boite[0] * l, boite[1] * h, boite[2] * l, boite[3] * h
    rel = [(x1 - g) / cote, (y1 - t) / cote, (x2 - g) / cote, (y2 - t) / cote]
    return tuple(round(min(max(v, 0.0), 1.0), 4) for v in rel)


MARGE_CENTRE = 1.65


REMONTE_CENTRE = 0.15


TAILLE_CENTRE = 600


def cadre_centre(boite, l: int, h: int) -> tuple[int, int, int, int]:
    """Carré centré sur le visage, gardé dans la photo (réduit puis décalé s'il le faut)."""
    x1, y1, x2, y2 = boite[0] * l, boite[1] * h, boite[2] * l, boite[3] * h
    fw, fh = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
    cote = min((fw + fh) * MARGE_CENTRE, l, h)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2 - REMONTE_CENTRE * fh
    gauche = min(max(cx - cote / 2, 0), l - cote)
    haut = min(max(cy - cote / 2, 0), h - cote)
    return int(gauche), int(haut), int(gauche + cote), int(haut + cote)


def portrait_centre(contenu: bytes, boite, taille: int = TAILLE_CENTRE) -> tuple[bytes, tuple]:
    """Portrait carré centré sur le visage (JPEG) et cadre du visage dedans (0 à 1)."""
    img = _ouvrir(contenu)
    l, h = img.size
    g, t, d, b = cadre_centre(boite, l, h)
    carre = img.crop((g, t, d, b))
    if carre.width > taille:
        carre = carre.resize((taille, taille), Image.Resampling.LANCZOS)
    cote = max(d - g, 1)
    x1, y1, x2, y2 = boite[0] * l, boite[1] * h, boite[2] * l, boite[3] * h
    visage = tuple(round(min(max(v, 0.0), 1.0), 4)
                   for v in ((x1 - g) / cote, (y1 - t) / cote, (x2 - g) / cote, (y2 - t) / cote))
    sortie = io.BytesIO()
    carre.save(sortie, "JPEG", quality=88, optimize=True)
    return sortie.getvalue(), visage


def portrait(contenu: bytes, boite, taille: int = TAILLE_SORTIE) -> tuple[bytes, str]:
    """Portrait carré en JPEG, à partir de n'importe quelle taille de la photo."""
    img = _ouvrir(contenu)
    carre = img.crop(cadre_portrait(boite, *img.size))
    if carre.width > taille:
        carre = carre.resize((taille, taille), Image.Resampling.LANCZOS)
    sortie = io.BytesIO()
    carre.save(sortie, "JPEG", quality=90, optimize=True)
    return sortie.getvalue(), "image/jpeg"


def alleger(image: tuple[bytes, str], max_octets: int = PHOTO_MAX) -> tuple[bytes, str]:
    """Photo réduite (taille puis qualité JPEG) jusqu'à tenir dans max_octets ; inchangée si elle tient."""
    contenu, type_ = image
    if len(contenu) <= max_octets:
        return image
    try:
        img = _ouvrir(contenu)
    except Exception:  # noqa: BLE001 — illisible : laissée telle quelle
        return image
    meilleur = contenu
    for cote in (800, 640, 512, 400):
        essai = img.copy()
        essai.thumbnail((cote, cote), Image.Resampling.LANCZOS)
        for qualite in (88, 80, 72, 64):
            sortie = io.BytesIO()
            essai.save(sortie, "JPEG", quality=qualite, optimize=True)
            meilleur = sortie.getvalue()
            if len(meilleur) <= max_octets:
                return meilleur, "image/jpeg"
    return meilleur, "image/jpeg"


FORMAT_AFFICHE = 9 / 19.5   # largeur / hauteur d'un écran d'iPhone


VISAGE_AFFICHE = 0.28       # part idéale de la hauteur occupée par le visage


VISAGE_AFFICHE_MAX = 0.55   # au-delà, le visage est trop serré pour une affiche


HAUTEUR_AFFICHE = 2532      # pixels : hauteur d'un écran d'iPhone récent


def cadre_affiche(boite, ratio: float) -> tuple[tuple[float, float, float, float], float] | None:
    """Cadre vertical (relatif, 0 à 1) autour du visage, et note de 0 à 1 : 1 quand la photo laisse
    assez de place autour du visage, moins quand il faut le serrer. None si impossible."""
    x1, y1, x2, y2 = boite
    fx1, fx2 = x1 * ratio, x2 * ratio          # repère : hauteur 1, largeur = ratio
    fh = y2 - y1
    voulue = fh / VISAGE_AFFICHE
    possible = min(1.0, ratio / FORMAT_AFFICHE)
    hc = min(voulue, possible)
    if fh / hc > VISAGE_AFFICHE_MAX:
        return None
    wc = hc * FORMAT_AFFICHE
    cx, cy = (fx1 + fx2) / 2, (y1 + y2) / 2
    gauche = min(max(cx - wc / 2, 0), ratio - wc)
    haut = min(max(cy - 0.38 * hc, 0), 1 - hc)
    return (gauche / ratio, haut, (gauche + wc) / ratio, haut + hc), hc / voulue


def affiche(contenu: bytes, boite, hauteur: int = HAUTEUR_AFFICHE) -> bytes:
    """Image verticale plein écran (JPEG), cadrée sur le visage."""
    img = _ouvrir(contenu)
    l, h = img.size
    cadre, _ = cadre_affiche(boite, l / h) or (None, 0)
    if cadre is None:
        raise ValueError("visage trop serré pour une affiche")
    x1, y1, x2, y2 = cadre
    decoupe = img.crop((int(x1 * l), int(y1 * h), int(x2 * l), int(y2 * h)))
    if decoupe.height > hauteur:
        decoupe = decoupe.resize((max(int(hauteur * decoupe.width / decoupe.height), 1), hauteur),
                                 Image.Resampling.LANCZOS)
    sortie = io.BytesIO()
    decoupe.save(sortie, "JPEG", quality=90 if hauteur >= 1000 else 82, optimize=True)
    return sortie.getvalue()


def ratio_image(contenu: bytes) -> float:
    img = _ouvrir(contenu)
    return img.width / img.height


def vignette(contenu: bytes, cote: int) -> tuple[bytes, str]:
    """Petite image carrée (centrée) en WebP pour les avatars de l'interface."""
    img = _ouvrir(contenu)
    l, h = img.size
    c = min(l, h)
    img = img.crop(((l - c) // 2, (h - c) // 2, (l - c) // 2 + c, (h - c) // 2 + c))
    if c > cote:
        img = img.resize((cote, cote), Image.Resampling.LANCZOS)
    sortie = io.BytesIO()
    img.save(sortie, "WEBP", quality=82, method=4)
    return sortie.getvalue(), "image/webp"


def legender(contenu: bytes, legende: str) -> bytes:
    """Écrit le nom de la personne dans la photo (titre et légende EXIF/XMP, que Photos sur
    l'iPhone et le Mac affichent et retrouvent par la recherche). Recompression évitée :
    les tables de quantification d'origine sont gardées."""
    from xml.sax.saxutils import escape
    img = Image.open(io.BytesIO(contenu))
    exif = img.getexif()
    # (pas d'ImageDescription EXIF : limitée à l'ASCII, elle afficherait « Agn?s »)
    exif[0x9C9B] = (legende + "\0").encode("utf-16-le")     # XPTitle (Windows)
    t = escape(legende)
    xmp = ('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
           '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
           'xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">'
           f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{t}</rdf:li></rdf:Alt></dc:title>'
           f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{t}</rdf:li></rdf:Alt></dc:description>'
           f'<photoshop:Headline>{t}</photoshop:Headline>'
           '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>').encode("utf-8")
    sortie = io.BytesIO()
    try:
        img.save(sortie, "JPEG", quality="keep", exif=exif, xmp=xmp)
    except (ValueError, OSError):   # pas un JPEG d'origine : nouvelle compression, de bonne qualité
        img.convert("RGB").save(sortie, "JPEG", quality=92, exif=exif, xmp=xmp)
    return sortie.getvalue()


def vignette_affiche(contenu: bytes, hauteur: int) -> bytes:
    """Affiche réduite (aperçu), proportions gardées."""
    img = _ouvrir(contenu)
    if img.height > hauteur:
        img = img.resize((max(1, int(img.width * hauteur / img.height)), hauteur), Image.Resampling.LANCZOS)
    sortie = io.BytesIO()
    img.save(sortie, "JPEG", quality=85, optimize=True)
    return sortie.getvalue()

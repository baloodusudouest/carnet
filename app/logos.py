"""Logos de sociétés, cherchés sur le site de la société (aucun service tiers).

Domaine : site de la fiche, sinon domaine du courriel professionnel. Sur la page d'accueil :
icônes déclarées (apple-touch-icon, icon avec sizes), image de partage (og:image), puis les
adresses habituelles (/apple-touch-icon.png, /favicon.ico). Les SVG sont ignorés (Pillow ne
les lit pas). Chaque image retenue fait au moins 64 px.

Fabrication : photo ronde (logo centré sur un fond de sa couleur, carré 800 px) et affiche
iPhone (logo dans le tiers haut, nom de la société dessous, 1179 × 2556).
"""
from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

TAILLE_MIN = 64
POIDS_MAX = 3_000_000
MAX_CANDIDATS = 4
UA = "Mozilla/5.0 (carnet ; logo de contact)"


def domaine_de(fiche: dict, domaine_pro) -> str | None:
    """Site de la fiche (type « site »), sinon domaine du premier courriel professionnel."""
    for s in fiche.get("sites", []):
        if s.get("type") in ("site", "", None) and s.get("valeur"):
            hote = urlsplit(s["valeur"] if "://" in s["valeur"] else f"https://{s['valeur']}").hostname
            if hote and not any(r in hote for r in ("linkedin.", "facebook.", "instagram.", "twitter.", "x.com")):
                return hote.removeprefix("www.")
    for c in fiche.get("courriels", []):
        d = domaine_pro(c.get("valeur", ""))
        if d:
            return d
    return None


class _Liens(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icones: list[tuple[int, str]] = []   # (priorité, adresse)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower()
            taille = max((int(x) for x in re.findall(r"(\d+)x\d+", a.get("sizes", ""))), default=0)
            if "apple-touch-icon" in rel:
                self.icones.append((300 + taille, a["href"]))
            elif "icon" in rel and not a["href"].lower().endswith(".svg"):
                self.icones.append((100 + taille, a["href"]))
        elif tag == "meta" and a.get("content") and a.get("property", a.get("name", "")).lower() in ("og:image", "og:logo"):
            self.icones.append((150, a["content"]))


def chercher(domaine: str, transport: httpx.BaseTransport | None = None, taille_min: int = TAILLE_MIN) -> list[dict]:
    """Logos trouvés : [{url, octets, largeur, hauteur}], les plus prometteurs d'abord.
    domaine : « exemple.fr » (https) ou une adresse complète (« http://immich-server:2283 »)."""
    with httpx.Client(timeout=8, follow_redirects=True, headers={"User-Agent": UA}, transport=transport) as c:
        base, adresses = (domaine.rstrip("/") + "/" if "://" in domaine else f"https://{domaine}/"), []
        try:
            r = c.get(base)
            if r.status_code < 400 and "html" in r.headers.get("content-type", ""):
                base = str(r.url)
                p = _Liens()
                p.feed(r.text[:400_000])
                adresses = [urljoin(base, h) for _, h in sorted(p.icones, key=lambda x: -x[0])]
        except httpx.HTTPError:
            pass
        adresses += [urljoin(base, "/apple-touch-icon.png"), urljoin(base, "/favicon.ico")]
        res, vues = [], set()
        for url in adresses:
            if url in vues or len(res) >= MAX_CANDIDATS:
                continue
            vues.add(url)
            try:
                r = c.get(url)
            except httpx.HTTPError:
                continue
            if r.status_code >= 400 or not r.content or len(r.content) > POIDS_MAX:
                continue
            try:
                img = Image.open(io.BytesIO(r.content))
                img.load()
            except Exception:  # noqa: BLE001 — pas une image lisible (SVG, HTML d'erreur…)
                continue
            if min(img.size) < taille_min:
                continue
            if any(abs(img.size[0] - x["largeur"]) < 2 and abs(img.size[1] - x["hauteur"]) < 2 for x in res):
                continue   # même image en double (favicon.ico et icône déclarée)
            res.append({"url": url, "octets": r.content, "largeur": img.size[0], "hauteur": img.size[1]})
        return res


def _logo_rgba(contenu: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(contenu))   # .ico : Pillow ouvre la plus grande taille
    img.load()
    return ImageOps.exif_transpose(img).convert("RGBA")


def _fond(logo: Image.Image) -> tuple[int, int, int]:
    """Couleur de fond : celle des bords du logo s'ils sont opaques, sinon blanc cassé."""
    l, h = logo.size
    bords = [logo.getpixel((x, y)) for x in (0, l - 1) for y in range(0, h, max(1, h // 8))]
    bords += [logo.getpixel((x, y)) for y in (0, h - 1) for x in range(0, l, max(1, l // 8))]
    opaques = [p for p in bords if p[3] > 200]
    if len(opaques) < len(bords) * 0.7:
        return (245, 242, 236)
    return tuple(sorted(c[i] for c in opaques)[len(opaques) // 2] for i in range(3))


def _poser(fond: Image.Image, logo: Image.Image, boite: tuple[int, int, int, int]) -> None:
    x, y, l, h = boite
    logo = logo.copy()
    logo.thumbnail((l, h), Image.Resampling.LANCZOS)
    if logo.width < l * 0.5 and logo.height < h * 0.5:   # petite icône : agrandie, sans dépasser ×3
        f = min(l / logo.width, h / logo.height, 3)
        logo = logo.resize((int(logo.width * f), int(logo.height * f)), Image.Resampling.LANCZOS)
    fond.alpha_composite(logo, (x + (l - logo.width) // 2, y + (h - logo.height) // 2))


def photo(contenu: bytes, cote: int = 800) -> bytes:
    logo = _logo_rgba(contenu)
    fond = Image.new("RGBA", (cote, cote), _fond(logo) + (255,))
    marge = int(cote * 0.17)
    _poser(fond, logo, (marge, marge, cote - 2 * marge, cote - 2 * marge))
    sortie = io.BytesIO()
    fond.convert("RGB").save(sortie, "JPEG", quality=90, optimize=True)
    return sortie.getvalue()


def _police(taille: int):
    for nom in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    return ImageFont.load_default(size=taille)


def affiche(contenu: bytes, societe: str, largeur: int = 1179, hauteur: int = 2556) -> bytes:
    logo = _logo_rgba(contenu)
    couleur = _fond(logo)
    fond = Image.new("RGBA", (largeur, hauteur), couleur + (255,))
    l = int(largeur * 0.62)
    _poser(fond, logo, ((largeur - l) // 2, int(hauteur * 0.17), l, l))
    if societe:
        d = ImageDraw.Draw(fond)
        clair = sum(couleur) / 3 > 140
        police = _police(int(largeur * 0.075))
        texte = societe if len(societe) <= 28 else societe[:27] + "…"
        while d.textlength(texte, font=police) > largeur * 0.86 and police.size > 30:
            police = _police(police.size - 4)
        d.text((largeur / 2, int(hauteur * 0.17) + l + int(hauteur * 0.05)), texte, anchor="mt", font=police,
               fill=(40, 34, 30) if clair else (245, 242, 236))
    sortie = io.BytesIO()
    fond.convert("RGB").save(sortie, "JPEG", quality=90, optimize=True)
    return sortie.getvalue()


def vignette(contenu: bytes, cote: int = 96) -> bytes:
    """Icône carrée en PNG transparent (pastilles des plateformes)."""
    img = _logo_rgba(contenu)
    img.thumbnail((cote, cote), Image.LANCZOS)
    fond = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    fond.paste(img, ((cote - img.width) // 2, (cote - img.height) // 2), img)
    sortie = io.BytesIO()
    fond.save(sortie, "PNG", optimize=True)
    return sortie.getvalue()

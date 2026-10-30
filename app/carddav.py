"""Client CardDAV minimal pour iCloud (contacts.icloud.com).

Découverte : principal → addressbook-home-set → carnet d'adresses (« card » chez iCloud).
Lecture : PROPFIND (ETag de chaque carte) puis addressbook-multiget par paquets.
Écriture : PUT avec If-Match (modification) ou If-None-Match: * (création), DELETE avec If-Match.
Une carte modifiée sur l'iPhone entre la lecture et l'écriture provoque un conflit (412) :
elle n'est pas écrasée.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import logging

import httpx

log = logging.getLogger("carnet")

D, C = "DAV:", "urn:ietf:params:xml:ns:carddav"
PAQUET = 100


class ErreurICloud(Exception):
    """Erreur à afficher telle quelle."""


class Conflit(ErreurICloud):
    """La carte a changé dans iCloud depuis la lecture."""


@dataclass
class Brute:
    href: str     # chemin sur le serveur
    etag: str
    texte: str


def _corps_propfind(props: str) -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="{D}" xmlns:c="{C}">'
            f"<d:prop>{props}</d:prop></d:propfind>")


class CardDAV:
    def __init__(self, url: str, utilisateur: str, mot_de_passe: str,
                 transport: httpx.BaseTransport | None = None, nom_carnet: str | None = None):
        if not utilisateur or not mot_de_passe:
            raise ErreurICloud("Identifiant iCloud absent : renseigne CARNET_ICLOUD_USER et "
                               "CARNET_ICLOUD_PASSWORD dans les variables de la stack.")
        self.base = url.rstrip("/") + "/"
        self.client = httpx.Client(auth=(utilisateur, mot_de_passe), timeout=60, follow_redirects=True,
                                   transport=transport, headers={"User-Agent": "carnet (CardDAV)"})
        self.carnet: str | None = None
        self.nom_carnet = nom_carnet   # carnet d'adresses voulu (nom affiché) ; None : le premier

    def fermer(self) -> None:
        self.client.close()

    # ------------------------------------------------------------ bas niveau

    def _requete(self, methode: str, url: str, **kw) -> httpx.Response:
        try:
            r = self.client.request(methode, url, **kw)
        except httpx.HTTPError as exc:
            raise ErreurICloud(f"iCloud injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code == 401:
            raise ErreurICloud("iCloud refuse la connexion : vérifie l'identifiant Apple et le "
                               "mot de passe d'application (pas le mot de passe du compte).")
        if r.status_code == 412:
            raise Conflit("Carte modifiée dans iCloud depuis la lecture.")
        if r.status_code >= 400:
            # Le motif donné par iCloud (souvent un XML court) est gardé pour le diagnostic
            motif = " ".join(r.text.split())[:300] if r.text else ""
            log.warning("iCloud %s %s → %s %s", methode, urlsplit(url).path, r.status_code, motif)
            raise ErreurICloud(f"iCloud a répondu {r.status_code} à {methode} {urlsplit(url).path}"
                               + (f" ({motif})" if motif else "") + ".")
        return r

    def _propfind(self, url: str, props: str, profondeur: int) -> list[tuple[str, ET.Element]]:
        r = self._requete("PROPFIND", url, content=_corps_propfind(props).encode(),
                          headers={"Depth": str(profondeur), "Content-Type": "application/xml; charset=utf-8"})
        return self._reponses(r.content)

    @staticmethod
    def _reponses(contenu: bytes) -> list[tuple[str, ET.Element]]:
        try:
            racine = ET.fromstring(contenu)
        except ET.ParseError as exc:
            raise ErreurICloud("Réponse d'iCloud illisible.") from exc
        res = []
        for rep in racine.iter(f"{{{D}}}response"):
            href = (rep.findtext(f"{{{D}}}href") or "").strip()
            for ps in rep.findall(f"{{{D}}}propstat"):
                if " 200 " in (ps.findtext(f"{{{D}}}status") or " 200 "):
                    prop = ps.find(f"{{{D}}}prop")
                    if prop is not None:
                        res.append((href, prop))
        return res

    def _url(self, href: str, base: str | None = None) -> str:
        return urljoin(base or self.base, href)

    # ------------------------------------------------------------ découverte et lecture

    def decouvrir(self) -> str:
        if self.carnet:
            return self.carnet
        reps = self._propfind(self.base, "<d:current-user-principal/>", 0)
        principal = next((p.findtext(f"{{{D}}}current-user-principal/{{{D}}}href") for _, p in reps), None)
        if not principal:
            raise ErreurICloud("iCloud n'a pas indiqué le compte (current-user-principal).")
        url_principal = self._url(principal.strip())
        reps = self._propfind(url_principal, "<c:addressbook-home-set/>", 0)
        maison = next((p.findtext(f"{{{C}}}addressbook-home-set/{{{D}}}href") for _, p in reps), None)
        if not maison:
            raise ErreurICloud("iCloud n'a pas indiqué le dossier des contacts (addressbook-home-set).")
        url_maison = self._url(maison.strip(), url_principal)
        carnets = []
        for href, prop in self._propfind(url_maison, "<d:resourcetype/><d:displayname/>", 1):
            rt = prop.find(f"{{{D}}}resourcetype")
            if rt is not None and rt.find(f"{{{C}}}addressbook") is not None:
                carnets.append(((prop.findtext(f"{{{D}}}displayname") or "").strip(), self._url(href, url_maison)))
        if not carnets:
            raise ErreurICloud("Aucun carnet d'adresses trouvé dans ce compte.")
        if self.nom_carnet:
            # Jamais de choix par défaut quand un nom est demandé : écrire dans un carnet partagé
            # (« Contacts de l'équipe ») effacerait les contacts des autres
            choisi = next((u for n, u in carnets if n.casefold() == self.nom_carnet.casefold()), None)
            if not choisi:
                raise ErreurICloud(f"Carnet d'adresses « {self.nom_carnet} » introuvable. Carnets du compte : "
                                   + ", ".join(f"« {n or '(sans nom)'} »" for n, _ in carnets) + ".")
            self.carnet = choisi
        else:
            self.carnet = carnets[0][1]
        return self.carnet

    def lister(self) -> list[Brute]:
        carnet = self.decouvrir()
        chemin_carnet = urlsplit(carnet).path.rstrip("/")
        etags = {}
        for href, prop in self._propfind(carnet, "<d:getetag/><d:resourcetype/>", 1):
            rt = prop.find(f"{{{D}}}resourcetype")
            if urlsplit(self._url(href, carnet)).path.rstrip("/") == chemin_carnet:
                continue
            if rt is not None and len(rt):  # sous-collection
                continue
            etags[href] = (prop.findtext(f"{{{D}}}getetag") or "").strip()
        cartes = []
        hrefs = sorted(etags)
        for i in range(0, len(hrefs), PAQUET):
            paquet = hrefs[i:i + PAQUET]
            corps = (f'<?xml version="1.0" encoding="utf-8"?><c:addressbook-multiget xmlns:d="{D}" xmlns:c="{C}">'
                     "<d:prop><d:getetag/><c:address-data/></d:prop>"
                     + "".join(f"<d:href>{_xml(h)}</d:href>" for h in paquet) + "</c:addressbook-multiget>")
            r = self._requete("REPORT", carnet, content=corps.encode(),
                              headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
            for href, prop in self._reponses(r.content):
                texte = prop.findtext(f"{{{C}}}address-data")
                if texte:
                    etag = (prop.findtext(f"{{{D}}}getetag") or etags.get(href, "")).strip()
                    cartes.append(Brute(href, etag, texte))
        return cartes

    def telecharger(self, url: str) -> bytes | None:
        """Image d'une carte que iCloud ne fournit que sous forme de lien (avec authentification)."""
        try:
            r = self.client.get(url)
        except httpx.HTTPError:
            return None
        return r.content if r.status_code == 200 and r.content else None

    # ------------------------------------------------------------ écriture

    def href_nouveau(self, uid: str) -> str:
        return urlsplit(self.decouvrir()).path.rstrip("/") + "/" + "".join(
            c if c.isalnum() or c in "-_." else "_" for c in uid) + ".vcf"

    def ecrire(self, href: str, texte: str, etag: str | None) -> str | None:
        """Crée (etag None) ou remplace la carte. Renvoie le nouvel ETag s'il est fourni."""
        entetes = {"Content-Type": "text/vcard; charset=utf-8"}
        entetes["If-Match" if etag else "If-None-Match"] = etag or "*"
        r = self._requete("PUT", self._url(href, self.decouvrir()), content=texte.encode("utf-8"), headers=entetes)
        return r.headers.get("ETag")

    def supprimer(self, href: str, etag: str | None) -> None:
        entetes = {"If-Match": etag} if etag else {}
        self._requete("DELETE", self._url(href, self.decouvrir()), headers=entetes)


def _xml(texte: str) -> str:
    return texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

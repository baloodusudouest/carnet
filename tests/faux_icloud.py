"""Faux serveur CardDAV qui se comporte comme contacts.icloud.com (pour les tests)."""
from __future__ import annotations

import base64
import re
from xml.sax.saxutils import escape

import httpx

PRINCIPAL = "/1234/principal/"
MAISON = "/1234/carddavhome/"
CARNET = "/1234/carddavhome/card/"
NS = 'xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"'


def _multistatus(reponses: list[str]) -> httpx.Response:
    corps = f'<?xml version="1.0"?><d:multistatus {NS}>' + "".join(reponses) + "</d:multistatus>"
    return httpx.Response(207, content=corps.encode(), headers={"Content-Type": "application/xml"})


def _reponse(href: str, props: str) -> str:
    return (f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>{props}</d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")


class FauxICloud:
    def __init__(self, vcf: str, utilisateur="moi@icloud.com", mot_de_passe="abcd-efgh-ijkl-mnop"):
        self.auth = "Basic " + base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode()).decode()
        self.n = 0
        self.cartes: dict[str, list[str]] = {}   # chemin → [etag, texte]
        for bloc in re.findall(r"BEGIN:VCARD.*?END:VCARD\r?\n?", vcf, flags=re.S):
            uid = re.search(r"^UID:(.+)$", bloc, flags=re.M).group(1).strip()
            self.cartes[f"{CARNET}{uid}.vcf"] = [self._etag(), bloc]
        self.ecritures: list[tuple[str, str]] = []
        self.nom_carnet = "My Contacts"
        self.autres_carnets: list[tuple[str, str]] = []   # (nom, chemin) listés AVANT le carnet principal
        self.photos: dict[str, bytes] = {}       # chemin → image servie par lien (comme iCloud)

    def _etag(self) -> str:
        self.n += 1
        return f'"e{self.n}"'

    def texte(self, uid: str) -> str | None:
        c = self.cartes.get(f"{CARNET}{uid}.vcf")
        return c[1] if c else None

    def modifier_sur_iphone(self, uid: str, texte: str) -> None:
        self.cartes[f"{CARNET}{uid}.vcf"] = [self._etag(), texte]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, r: httpx.Request) -> httpx.Response:
        if r.headers.get("authorization") != self.auth:
            return httpx.Response(401)
        chemin, corps = r.url.path, r.content.decode()
        if r.method == "GET" and chemin in self.photos:
            return httpx.Response(200, content=self.photos[chemin], headers={"Content-Type": "image/jpeg"})
        if r.method == "PROPFIND":
            if chemin not in (PRINCIPAL, MAISON, CARNET):  # racine (ou /carddav/<compte>/ chez Synology)
                return _multistatus([_reponse("/", f"<d:current-user-principal><d:href>{PRINCIPAL}</d:href></d:current-user-principal>")])
            if chemin == PRINCIPAL:
                # iCloud renvoie une adresse absolue, sur un autre serveur
                return _multistatus([_reponse(PRINCIPAL, "<c:addressbook-home-set><d:href>"
                                              f"https://p42-contacts.icloud.com:443{MAISON}</d:href></c:addressbook-home-set>")])
            if chemin == MAISON:
                autres = [_reponse(h, f"<d:displayname>{escape(n)}</d:displayname>"
                                      "<d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>")
                          for n, h in self.autres_carnets]
                return _multistatus([_reponse(MAISON, "<d:resourcetype><d:collection/></d:resourcetype>")] + autres
                                    + [_reponse(CARNET, f"<d:displayname>{escape(self.nom_carnet)}</d:displayname>"
                                                "<d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>")])
            if chemin == CARNET:
                return _multistatus([_reponse(CARNET, "<d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>")]
                                    + [_reponse(h, f"<d:getetag>{e}</d:getetag><d:resourcetype/>")
                                       for h, (e, _) in self.cartes.items()])
        if r.method == "REPORT" and chemin == CARNET:
            hrefs = re.findall(r"<d:href>(.*?)</d:href>", corps)
            return _multistatus([_reponse(h, f"<d:getetag>{self.cartes[h][0]}</d:getetag>"
                                             f"<c:address-data>{escape(self.cartes[h][1])}</c:address-data>")
                                 for h in hrefs if h in self.cartes])
        if r.method == "PUT":
            actuel = self.cartes.get(chemin)
            if "if-match" in r.headers and (not actuel or actuel[0] != r.headers["if-match"]):
                return httpx.Response(412)
            if r.headers.get("if-none-match") == "*" and actuel:
                return httpx.Response(412)
            etag = self._etag()
            self.cartes[chemin] = [etag, corps]
            self.ecritures.append(("PUT", chemin))
            return httpx.Response(204 if actuel else 201, headers={"ETag": etag})
        if r.method == "DELETE":
            actuel = self.cartes.get(chemin)
            if not actuel:
                return httpx.Response(404)
            if "if-match" in r.headers and actuel[0] != r.headers["if-match"]:
                return httpx.Response(412)
            del self.cartes[chemin]
            self.ecritures.append(("DELETE", chemin))
            return httpx.Response(204)
        return httpx.Response(405)

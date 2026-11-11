"""Faux Immich, Treemich et Synology pour les tests (aucun accès réseau)."""
from __future__ import annotations

import io
import json

import httpx
from PIL import Image


def jpeg(largeur=1200, hauteur=1600, couleur=(180, 120, 90)) -> bytes:
    sortie = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), couleur).save(sortie, "JPEG", quality=80)
    return sortie.getvalue()


class FauxImmich:
    def __init__(self):
        self.personnes = [
            {"id": "im-claire", "name": "Claire MARTIN", "birthDate": "1985-03-14", "isHidden": False},
            {"id": "im-jp", "name": "Jean-Pierre Duboiss", "birthDate": "1970-07-02", "isHidden": False},
            {"id": "im-paul", "name": "Paul MARTIN", "birthDate": "1983-01-09", "isHidden": False},
        ]
        self.photos = {"im-claire": ["a1", "a2"], "im-paul": ["p1"], "im-jp": []}
        self.ecrits: list[tuple[str, str, object]] = []
        self.envoyees: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, r: httpx.Request) -> httpx.Response:
        chemin = r.url.path
        if r.headers.get("x-api-key") != "cle":
            return httpx.Response(401)
        if chemin == "/api/people" and r.method == "GET":
            return httpx.Response(200, json={"people": self.personnes, "hasNextPage": False})
        if chemin.startswith("/api/people/") and r.method == "PUT":
            corps = json.loads(r.content)
            self.ecrits.append(("PUT", chemin, corps))
            pid = chemin.split("/")[3]
            for p in self.personnes:
                if p["id"] == pid:
                    if "name" in corps:
                        p["name"] = corps["name"]
                    if "birthDate" in corps:
                        p["birthDate"] = corps["birthDate"]
            return httpx.Response(200, json={})
        if chemin == "/api/search/metadata":
            pid = json.loads(r.content)["personIds"][0]
            items = [{"id": a, "width": 1200, "height": 1600, "originalMimeType": "image/jpeg",
                      "fileCreatedAt": "2024-05-01T10:00:00Z"} for a in self.photos.get(pid, [])]
            return httpx.Response(200, json={"assets": {"items": items, "nextPage": None}})
        if chemin == "/api/faces":
            asset = r.url.params["id"]
            pid = next(p for p, a in self.photos.items() if asset in a)
            taille = 400 if asset.endswith("1") else 300
            return httpx.Response(200, json=[{"person": {"id": pid}, "imageWidth": 1200, "imageHeight": 1600,
                                              "boundingBoxX1": 400, "boundingBoxY1": 500,
                                              "boundingBoxX2": 400 + taille, "boundingBoxY2": 500 + taille}])
        if chemin.startswith("/api/assets/") and r.method == "GET":
            return httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})
        if chemin == "/api/assets" and r.method == "POST":
            ident = f"aff-{len(self.envoyees) + 1}"
            self.envoyees.append(ident)
            return httpx.Response(201, json={"id": ident})
        if chemin == "/api/assets" and r.method == "DELETE":
            self.ecrits.append(("DELETE", chemin, json.loads(r.content)))
            return httpx.Response(204)
        if chemin == "/api/albums" and r.method == "GET":
            return httpx.Response(200, json=[])
        if chemin == "/api/albums" and r.method == "POST":
            return httpx.Response(201, json={"id": "album-1"})
        if chemin.startswith("/api/albums/"):
            return httpx.Response(200, json={})
        return httpx.Response(404)


class FauxTreemich:
    def __init__(self):
        self.ecrits: list[tuple[str, object]] = []
        self.mariages: dict[tuple[str, str], str] = {}     # (a, b) triés → date ; rangé sur le couple
        self.divorces: dict[tuple[str, str], str] = {}
        self.deces: dict[str, str] = {}
        self.oublie = False                                # vrai : accepte l'écriture mais ne la garde pas
        self.muet = False                                  # vrai : ne répond plus (503)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, r: httpx.Request) -> httpx.Response:
        chemin = r.url.path
        if chemin == "/auth/login":
            return httpx.Response(200, json={}, headers={"set-cookie": "s=1; Path=/"})
        if self.muet:
            return httpx.Response(503)
        if r.method == "PATCH":
            corps = json.loads(r.content)
            self.ecrits.append((chemin, corps))
            if not self.oublie:
                if chemin.endswith("/relationships") and "marriageAnniversaryDate" in corps:
                    cle = tuple(sorted((chemin.split("/")[2], corps["toPersonId"])))
                    if corps["marriageAnniversaryDate"]:
                        self.mariages[cle] = corps["marriageAnniversaryDate"]
                    else:
                        self.mariages.pop(cle, None)
                elif "deathDate" in corps:
                    pid = chemin.split("/")[2]
                    if corps["deathDate"]:
                        self.deces[pid] = corps["deathDate"]
                    else:
                        self.deces.pop(pid, None)
            return httpx.Response(200, json={})
        if chemin == "/people":
            return httpx.Response(200, json={"people": [
                {"id": "t-claire", "name": "Claire MARTIN", "profile": {"gender": "FEMALE"},
                 "externalIdentities": [{"provider": "IMMICH", "providerPersonId": "im-claire"}]},
                {"id": "t-paul", "name": "Paul MARTIN", "profile": {"gender": "MALE"},
                 "externalIdentities": [{"provider": "IMMICH", "providerPersonId": "im-paul"}]}]})
        if chemin == "/relationships":
            cle = ("t-claire", "t-paul")
            return httpx.Response(200, json={"relationships": [
                {"fromPersonId": "t-claire", "toPersonId": "t-paul", "type": "SPOUSE_OF",
                 "marriageAnniversaryDate": self.mariages.get(cle), "divorceDate": self.divorces.get(cle)}],
                "nextCursor": None})
        if chemin.endswith("/life-events"):
            pid = chemin.split("/")[2]
            naissance = {"eventType": "BIRTH", "year": 1985, "month": 3, "day": 14} if pid == "t-claire" \
                else {"eventType": "BIRTH", "year": 1983, "month": 1, "day": 9}
            evenements = [naissance]
            if pid in self.deces:
                a, m, j = (int(x) for x in self.deces[pid].split("-"))
                evenements.append({"eventType": "DEATH", "year": a, "month": m, "day": j})
            return httpx.Response(200, json={"lifeEvents": evenements})
        return httpx.Response(404)

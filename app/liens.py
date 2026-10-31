"""Clients d'Immich (personnes reconnues, visages) et de Treemich (arbre généalogique).

Immich : API REST avec clé (en-tête x-api-key), permissions person.read et person.update.
Treemich : API REST du conteneur treemich-api (port 4000), session par cookie après
POST /auth/login. Les personnes Treemich liées à Immich portent une identité externe
{provider: "IMMICH", providerPersonId}.
"""
from __future__ import annotations

import time

import httpx


class ErreurLien(Exception):
    """Erreur à afficher telle quelle."""


def _client(transport, **kw) -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True, transport=transport, **kw)


class Immich:
    def __init__(self, url: str, cle: str, transport: httpx.BaseTransport | None = None):
        if not url or not cle:
            raise ErreurLien("Immich n'est pas configuré : renseigne CARNET_IMMICH_CLE dans la stack.")
        self.api = url.rstrip("/") + "/api"
        self.client = _client(transport, headers={"x-api-key": cle, "Accept": "application/json"})

    def fermer(self) -> None:
        self.client.close()

    def _get(self, chemin: str, **params) -> httpx.Response:
        try:
            r = self.client.get(self.api + chemin, params=params or None)
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code in (401, 403):
            raise ErreurLien("Immich refuse la clé d'API (droits person.read et person.update nécessaires).")
        return r

    def personnes(self) -> list[dict]:
        """Personnes nommées (masquées comprises) : id, nom, date de naissance."""
        res, page = [], 1
        while page < 200:
            r = self._get("/people", page=page, size=500, withHidden="true")
            if r.status_code >= 400:
                raise ErreurLien(f"Immich a répondu {r.status_code} à la liste des personnes.")
            corps = r.json()
            for p in corps.get("people", []):
                if (p.get("name") or "").strip():
                    res.append({"id": p["id"], "nom": p["name"].strip(), "naissance": p.get("birthDate") or "",
                                "masque": bool(p.get("isHidden"))})
            if not corps.get("hasNextPage"):
                break
            page += 1
        return res

    def visage(self, pid: str) -> tuple[bytes, str] | None:
        r = self._get(f"/people/{pid}/thumbnail")
        if r.status_code != 200 or not r.content:
            return None
        return r.content, (r.headers.get("content-type") or "image/jpeg").split(";")[0]

    def renommer(self, pid: str, nom: str) -> None:
        try:
            r = self.client.put(f"{self.api}/people/{pid}", json={"name": nom})
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code >= 400:
            raise ErreurLien(f"Immich a refusé le nouveau nom ({r.status_code}).")

    def maj_naissance(self, pid: str, date: str) -> None:
        try:
            r = self.client.put(f"{self.api}/people/{pid}", json={"birthDate": date})
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code >= 400:
            raise ErreurLien(f"Immich a refusé la date de naissance ({r.status_code}).")

    # ------------------------------------------------------------ photos HD (portraits)

    DROITS_PHOTOS = "asset.read, asset.view, asset.download et face.read"

    def _refus_photos(self, r: httpx.Response, quoi: str) -> None:
        if r.status_code in (401, 403):
            raise ErreurLien(f"Immich refuse {quoi} : ajoute à la clé d'API les droits {self.DROITS_PHOTOS}.")
        if r.status_code >= 400:
            raise ErreurLien(f"Immich a répondu {r.status_code} ({quoi}).")

    def photos_de(self, pid: str, limite: int, depuis: str | None = None) -> list[dict]:
        """Photos (pas les vidéos) où la personne apparaît, les plus récentes d'abord."""
        res, curseur, page = [], None, 1
        while len(res) < limite:
            corps = {"personIds": [pid], "type": "IMAGE", "size": min(250, limite - len(res)),
                     "order": "desc", "withExif": True}
            if depuis:
                corps["createdAfter"] = depuis
            if curseur:
                corps["cursor"] = curseur
            else:
                corps["page"] = page
            try:
                r = self.client.post(f"{self.api}/search/metadata", json=corps)
            except httpx.HTTPError as exc:
                raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
            self._refus_photos(r, "la recherche des photos")
            bloc = (r.json() or {}).get("assets") or {}
            for a in bloc.get("items") or []:
                exif = a.get("exifInfo") or {}
                res.append({"id": a["id"], "largeur": a.get("width") or exif.get("exifImageWidth"),
                            "hauteur": a.get("height") or exif.get("exifImageHeight"),
                            "type": a.get("originalMimeType") or "", "le": a.get("fileCreatedAt") or ""})
            curseur = bloc.get("nextCursor")
            if not curseur and not bloc.get("nextPage"):
                break
            page += 1
        return res[:limite]

    def visages_photo(self, asset_id: str) -> list[dict]:
        try:
            r = self.client.get(f"{self.api}/faces", params={"id": asset_id})
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        self._refus_photos(r, "la lecture des visages")
        return r.json() or []

    def image(self, asset_id: str, taille: str = "preview") -> bytes | None:
        """taille : preview (≈1 440 px), fullsize, ou original (fichier tel qu'importé)."""
        chemin = f"/assets/{asset_id}/original" if taille == "original" else f"/assets/{asset_id}/thumbnail"
        try:
            r = self.client.get(self.api + chemin, params=None if taille == "original" else {"size": taille})
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code in (401, 403):
            self._refus_photos(r, "le téléchargement des photos")
        return r.content if r.status_code == 200 and r.content else None

    def definir_couverture(self, pid: str, asset_id: str) -> None:
        try:
            r = self.client.put(f"{self.api}/people/{pid}", json={"featureFaceAssetId": asset_id})
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Immich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code >= 400:
            raise ErreurLien(f"Immich a refusé la photo de la personne ({r.status_code}).")


class Treemich:
    """Une seule session, réutilisée : Treemich limite fortement le nombre de connexions."""

    def __init__(self, url: str, courriel: str, mot_de_passe: str, transport: httpx.BaseTransport | None = None):
        if not url or not courriel or not mot_de_passe:
            raise ErreurLien("Treemich n'est pas configuré : renseigne CARNET_TREEMICH_EMAIL et "
                             "CARNET_TREEMICH_PASSWORD dans la stack.")
        self.api = url.rstrip("/")
        self._identifiants = {"email": courriel, "password": mot_de_passe}
        self.client = _client(transport)
        self.connecte = False
        self._dernier = 0.0
        self.facteur_attente = 1.0 if transport is None else 0.0   # tests : pas d'attente réelle

    def _connecter(self) -> None:
        try:
            r = self.client.post(self.api + "/auth/login", json=self._identifiants)
        except httpx.HTTPError as exc:
            raise ErreurLien(f"Treemich injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code == 429:
            raise ErreurLien("Treemich limite le nombre de connexions : réessaie dans quelques minutes.")
        if r.status_code >= 400:
            raise ErreurLien("Treemich refuse la connexion : vérifie le courriel et le mot de passe.")
        self.connecte = True

    def fermer(self) -> None:
        """Rien : la session reste ouverte pour les appels suivants."""

    INTERVALLE = 0.3   # Treemich accepte ~300 requêtes par minute : carnet reste en dessous
    ATTENTES_429 = 4   # sur « trop de requêtes », carnet patiente puis réessaie (au plus 4 fois)

    def _appel(self, methode: str, chemin: str, **kw) -> httpx.Response:
        reconnecte, attentes = False, 0
        while True:
            if not self.connecte:
                self._connecter()
            ecart = time.monotonic() - self._dernier
            if ecart < self.INTERVALLE * self.facteur_attente:
                time.sleep(self.INTERVALLE * self.facteur_attente - ecart)
            try:
                r = self.client.request(methode, self.api + chemin, **kw)
            except httpx.HTTPError as exc:
                raise ErreurLien(f"Treemich injoignable ({exc.__class__.__name__}).") from exc
            finally:
                self._dernier = time.monotonic()
            if r.status_code == 401 and not reconnecte:  # session expirée : une reconnexion
                self.connecte, reconnecte = False, True
                continue
            if r.status_code == 429 and attentes < self.ATTENTES_429:
                attentes += 1
                try:
                    delai = float(r.headers.get("retry-after", "") or 30)
                except ValueError:
                    delai = 30
                time.sleep(min(max(delai, 1), 65) * self.facteur_attente)
                continue
            if r.status_code == 429:
                raise ErreurLien("Treemich limite le nombre de requêtes : réessaie dans quelques minutes.")
            return r

    def _get(self, chemin: str, **params) -> dict:
        r = self._appel("GET", chemin, params=params or None)
        if r.status_code >= 400:
            raise ErreurLien(f"Treemich a répondu {r.status_code} à {chemin}.")
        return r.json()

    def personnes(self) -> list[dict]:
        """id, nom affiché, genre, identifiant Immich lié (s'il existe)."""
        res = []
        for p in self._get("/people").get("people", []):
            profil = p.get("profile") or {}
            immich = next((i.get("providerPersonId") for i in p.get("externalIdentities") or []
                           if i.get("provider") == "IMMICH"), None)
            nom = (p.get("name") or " ".join(x for x in (profil.get("givenName"), profil.get("surname")) if x)).strip()
            res.append({"id": p["id"], "nom": nom, "genre": profil.get("gender") or "UNKNOWN", "immich": immich})
        return res

    def relations(self) -> list[dict]:
        res, curseur = [], None
        for _ in range(100):
            params = {"limit": 2000}
            if curseur:
                params["cursor"] = curseur
            corps = self._get("/relationships", **params)
            res += [{"de": r["fromPersonId"], "vers": r["toPersonId"], "type": r["type"]}
                    for r in corps.get("relationships", [])]
            curseur = corps.get("nextCursor")
            if not curseur:
                break
        return res

    def renommer(self, pid: str, prenom: str, nom: str) -> None:
        corps = {"givenName": prenom or None, "surname": nom or None,
                 "displayNameOverride": " ".join(x for x in (prenom, nom) if x) or None}
        r = self._appel("PATCH", f"/people/{pid}", json=corps)
        if r.status_code >= 400:
            raise ErreurLien(f"Treemich a refusé le nouveau nom ({r.status_code}).")

    def naissance(self, pid: str) -> str:
        """Date de naissance enregistrée dans l'arbre (« AAAA-MM-JJ », partielle ou vide)."""
        for e in self._get(f"/people/{pid}/life-events").get("lifeEvents", []):
            if e.get("eventType") == "BIRTH" and e.get("year"):
                return f"{e['year']:04d}" + (f"-{e['month']:02d}" if e.get("month") else "") + \
                    (f"-{e['day']:02d}" if e.get("month") and e.get("day") else "")
        return ""

    def exporter_gedcom(self) -> bytes:
        r = self._appel("GET", "/export/gedcom")
        if r.status_code >= 400 or not r.content:
            raise ErreurLien(f"Export GEDCOM de Treemich impossible ({r.status_code}) : rien n'a été écrit.")
        return r.content

    def maj_naissance(self, pid: str, date: str) -> None:
        r = self._appel("PATCH", f"/people/{pid}", json={"birthDate": date})
        if r.status_code >= 400:
            raise ErreurLien(f"Treemich a refusé la date de naissance ({r.status_code}).")


# Relations de l'arbre → « noms associés » du contact (types de carnet)
TYPES_FAMILLE = {"conjoint", "partenaire", "mère", "père", "parent", "enfant", "frère", "sœur"}


def relations_de(tid: str, relations: list[dict], genres: dict[str, str]) -> list[tuple[str, str]]:
    """[(id Treemich de l'autre personne, type carnet)] pour la personne `tid`."""
    def parent(autre: str) -> str:
        return {"FEMALE": "mère", "MALE": "père"}.get(genres.get(autre, ""), "parent")

    def fratrie(autre: str) -> str:
        return {"FEMALE": "sœur", "MALE": "frère"}.get(genres.get(autre, ""), "frère")
    res: dict[str, str] = {}
    for r in relations:
        if tid not in (r["de"], r["vers"]) or r["de"] == r["vers"]:
            continue
        autre = r["vers"] if r["de"] == tid else r["de"]
        t = r["type"]
        if t == "SPOUSE_OF":
            res[autre] = "conjoint"
        elif t == "SIBLING_OF":
            res.setdefault(autre, fratrie(autre))
        elif t in ("PARENT_OF", "CHILD_OF"):
            # PARENT_OF : « de » est parent de « vers » ; CHILD_OF : « de » est enfant de « vers »
            autre_est_parent = (t == "PARENT_OF") == (r["vers"] == tid)
            res[autre] = parent(autre) if autre_est_parent else "enfant"
    return sorted(res.items())

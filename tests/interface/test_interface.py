"""Tests de l'interface dans un vrai navigateur (Chromium), sur PC (1300 px) et iPhone (390 px).

Filet avant toute retouche de la navigation ou des mises en page : chaque onglet s'affiche sans
erreur JavaScript, les raccourcis clavier de la révision fonctionnent, et les défauts connus sur
iPhone sont notés (xfail strict : le test échouera, donc préviendra, le jour où ils sont corrigés).

Lancement : construire l'interface (cd frontend && npm run build), puis python -m pytest tests/interface
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

RACINE = Path(__file__).resolve().parents[2]
pytest.importorskip("playwright.sync_api")
if not (RACINE / "app" / "static" / "index.html").is_file():
    pytest.skip("interface non construite (cd frontend && npm run build)", allow_module_level=True)

from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402

ONGLETS = [("accueil", "Accueil"), ("revision", "Révision"), ("contacts", "Contacts"), ("revue", "Revue"),
           ("groupes", "Groupes"), ("liaisons", "Liaisons"), ("export", "Export"), ("icloud", "iCloud"),
           ("archives", "Archives")]
ECRANS = {"pc": {"viewport": {"width": 1300, "height": 900}},
          "iphone": {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 3, "is_mobile": True,
                     "has_touch": True}}


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def serveur(tmp_path_factory):
    dossier, port = tmp_path_factory.mktemp("carnet-ui"), _port_libre()
    proc = subprocess.Popen([sys.executable, "-m", "tests.interface.serveur", str(dossier), str(port)], cwd=RACINE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    # Données fictives : trois sources, pour avoir des doublons à réviser
    with httpx.Client(base_url=base, headers={"X-Carnet": "1"}) as c:
        assert c.post("/api/connexion", json={"mot_de_passe": "essai"}).status_code == 200
        for fichier, source in (("icloud.vcf", "icloud"), ("gmail.vcf", "gmail"), ("outlook.csv", "outlook")):
            contenu = (RACINE / "tests" / "donnees" / fichier).read_bytes()
            assert c.post("/api/depot", files=[("fichiers", (fichier, contenu))]).status_code == 200
            assert c.post("/api/importer", json={"nom": fichier, "source": source}).status_code == 200
    yield base
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="module")
def navigateur():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _page(navigateur, serveur, ecran: str) -> tuple[Page, list[str]]:
    ctx = navigateur.new_context(**ECRANS[ecran])
    page = ctx.new_page()
    erreurs: list[str] = []
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" and "404" not in m.text else None)
    page.goto(serveur)
    page.fill("input[type=password]", "essai")
    page.keyboard.press("Enter")
    expect(page.locator("nav")).to_be_visible()
    return page, erreurs


@pytest.mark.parametrize("ecran", ["pc", "iphone"])
def test_chaque_onglet_s_affiche_sans_erreur(navigateur, serveur, ecran):
    page, erreurs = _page(navigateur, serveur, ecran)
    for route, _ in ONGLETS:
        page.goto(f"{serveur}/#/{route}")
        expect(page.locator("h1").first).to_be_visible()
        page.wait_for_timeout(300)
    assert erreurs == []
    page.context.close()


def test_raccourcis_de_la_revision(navigateur, serveur):
    page, erreurs = _page(navigateur, serveur, "pc")
    page.goto(f"{serveur}/#/revision")
    titre = page.locator("h1").first
    expect(titre).to_be_visible()
    premier = titre.inner_text()
    page.keyboard.press("ArrowRight")                     # → : passer sans valider
    expect(titre).not_to_have_text(premier)
    second = titre.inner_text()
    page.keyboard.press("?")                              # ? : aide des raccourcis
    expect(page.get_by_label("Raccourcis clavier")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_label("Raccourcis clavier")).to_have_count(0)
    contacts = httpx.Client(base_url=serveur, cookies={c["name"]: c["value"] for c in page.context.cookies()})
    pid = next(p["id"] for p in contacts.get("/api/contacts").json() if p["nom"] == second)
    page.wait_for_timeout(500)                            # brouillon de la proposition enregistré
    d = contacts.get(f"/api/personnes/{pid}").json()
    amis_avant = "Amis" in (d.get("brouillon") or d["fiche"] or {}).get("groupes", [])
    page.keyboard.press("a")                              # A : ajouter ou retirer le groupe Amis
    page.keyboard.press("Enter")                          # Entrée : valider et passer à la suivante
    expect(titre).not_to_have_text(second)
    d = contacts.get(f"/api/personnes/{pid}").json()
    assert d["statut"] == "verifie" and ("Amis" in d["fiche"]["groupes"]) != amis_avant
    assert erreurs == []
    page.context.close()


def _deborde(page: Page) -> bool:
    """Le contenu de la page (hors barre d'onglets) sort de l'écran, ou un bloc défile en largeur.
    Sur mobile, innerWidth s'agrandit avec le contenu : la largeur de l'écran est clientWidth."""
    return page.evaluate("""() => { const l = document.documentElement.clientWidth;
        return [...document.querySelectorAll('main *')].some(el => el.getBoundingClientRect().right > l + 1
          || (el.scrollWidth > el.clientWidth + 1 && ['auto', 'scroll'].includes(getComputedStyle(el).overflowX))) }""")


def _onglets_caches(page: Page) -> int:
    return page.evaluate("""() => { const l = document.documentElement.clientWidth;
        return [...document.querySelectorAll('header a, header button')].filter(a => {
          const r = a.getBoundingClientRect(); return r.right > l + 1 || r.left < 0 }).length }""")


@pytest.mark.parametrize("route", ["accueil", "export", "icloud", "liaisons", "groupes"])
def test_iphone_sans_defilement_horizontal(navigateur, serveur, route):
    page, _ = _page(navigateur, serveur, "iphone")
    page.goto(f"{serveur}/#/{route}")
    expect(page.locator("h1").first).to_be_visible()
    assert not _deborde(page)
    page.context.close()


@pytest.mark.xfail(strict=True, reason="défaut connu : la barre d'onglets déborde sur iPhone (chantier 6)")
def test_iphone_tous_les_onglets_accessibles(navigateur, serveur):
    page, _ = _page(navigateur, serveur, "iphone")
    assert _onglets_caches(page) == 0
    page.context.close()


@pytest.mark.xfail(strict=True, reason="défaut connu : la liste des contacts est un tableau plus large que l'iPhone (chantier 6)")
def test_iphone_contacts(navigateur, serveur):
    page, _ = _page(navigateur, serveur, "iphone")
    page.goto(f"{serveur}/#/contacts")
    expect(page.locator("h1").first).to_be_visible()
    page.wait_for_timeout(500)
    assert not _deborde(page)
    page.context.close()


@pytest.mark.xfail(strict=True, reason="défaut connu : la révision n'indique pas « à faire sur PC » sur iPhone (chantier 6)")
def test_iphone_revision_renvoie_au_pc(navigateur, serveur):
    page, _ = _page(navigateur, serveur, "iphone")
    page.goto(f"{serveur}/#/revision")
    expect(page.get_by_text("sur PC")).to_be_visible(timeout=2000)
    page.context.close()

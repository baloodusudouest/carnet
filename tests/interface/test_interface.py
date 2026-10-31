"""Tests de l'interface dans un vrai navigateur (Chromium), sur PC (1300 px) et iPhone (390 px).

Filet avant toute retouche de la navigation ou des mises en page : chaque onglet s'affiche sans
erreur JavaScript, les raccourcis clavier de la révision fonctionnent, et les défauts connus sur
iPhone sont notés (xfail strict : le test échouera, donc préviendra, le jour où ils sont corrigés).

Lancement : construire l'interface (cd frontend && npm run build), puis python -m pytest tests/interface
"""
from __future__ import annotations

import re
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

ONGLETS = [("accueil", "Accueil"), ("importer", "Importer"), ("revision", "Révision"), ("contacts", "Contacts"),
           ("revue", "Revue"), ("groupes", "Groupes"), ("liaisons", "Liaisons"), ("photos", "Photos"),
           ("export", "Export"), ("icloud", "iCloud"), ("archives", "Archives")]
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
    amis_avant = "Amis" in d["fiche"]["groupes"]
    page.keyboard.press("a")                              # A : ajouter ou retirer le groupe Amis
    page.keyboard.press("Enter")                          # Entrée : valider et passer à la suivante
    expect(titre).not_to_have_text(second)
    d = contacts.get(f"/api/personnes/{pid}").json()
    assert d["statut"] == "verifie" and ("Amis" in d["fiche"]["groupes"]) != amis_avant
    assert erreurs == []
    page.context.close()


def _deborde(page: Page) -> bool:
    """Le contenu de la page sort de l'écran, ou un bloc défile en largeur sans le vouloir
    (les bandeaux de photos marqués data-defile défilent exprès). Sur mobile, innerWidth
    s'agrandit avec le contenu : la largeur de l'écran est clientWidth."""
    return page.evaluate("""() => { const l = document.documentElement.clientWidth;
        if (document.documentElement.scrollWidth > l + 1) return true;
        return [...document.querySelectorAll('main *')].some(el => !el.closest('[data-defile]') && (
          el.getBoundingClientRect().right > l + 1
          || (el.scrollWidth > el.clientWidth + 1 && ['auto', 'scroll'].includes(getComputedStyle(el).overflowX)))) }""")


@pytest.mark.parametrize("route", ["chercher", "photos", "plus", "accueil", "revue", "groupes", "liaisons",
                                   "export", "icloud", "archives", "contacts", "revision"])
def test_iphone_sans_defilement_horizontal(navigateur, serveur, route):
    page, _ = _page(navigateur, serveur, "iphone")
    page.goto(f"{serveur}/#/{route}")
    expect(page.locator("h1").first).to_be_attached()
    page.wait_for_timeout(400)
    assert not _deborde(page)
    page.context.close()


def test_iphone_barre_d_onglets_et_fiche(navigateur, serveur):
    page, erreurs = _page(navigateur, serveur, "iphone")
    barre = page.get_by_role("navigation", name="Sections")
    for nom in ("Accueil", "Chercher", "Photos", "Plus"):
        expect(barre.get_by_role("link", name=nom)).to_be_visible()
    hauteur = page.evaluate("Math.min(...[...document.querySelectorAll('nav a')].map(a => a.getBoundingClientRect().height))")
    assert hauteur >= 44                                    # cibles tactiles
    barre.get_by_role("link", name="Chercher").click()
    page.get_by_label("Rechercher un contact").fill("claire")
    page.locator("main a[href^='#/fiche/']").first.click()
    expect(page.locator("h1")).to_have_text("Claire MARTIN")
    expect(page.get_by_role("link", name="Appeler")).to_have_attribute("href", "tel:+33612345678")
    page.go_back()
    expect(page.get_by_label("Rechercher un contact")).to_be_visible()
    barre.get_by_role("link", name="Chercher").click()
    barre.get_by_role("link", name="Plus").click()
    expect(page.get_by_role("link", name="Groupes")).to_be_visible()
    assert erreurs == []
    page.context.close()


def test_iphone_revision_renvoie_au_pc(navigateur, serveur):
    page, _ = _page(navigateur, serveur, "iphone")
    page.goto(f"{serveur}/#/revision")
    expect(page.get_by_text("à faire sur PC")).to_be_visible()
    page.get_by_role("button", name="Afficher quand même la vue PC").click()
    expect(page.get_by_role("navigation", name="Pages de l'onglet").get_by_role("link", name="Révision")).to_be_attached()
    page.context.close()


def test_pc_quatre_onglets_et_sous_onglets(navigateur, serveur):
    page, erreurs = _page(navigateur, serveur, "pc")
    principal = page.locator("header nav a")
    expect(principal).to_have_text(["Accueil", "Contacts", re.compile(r"^Actions"), "Sauvegarde"])
    page.get_by_label("Chercher un contact").fill("sophie")
    page.get_by_role("link", name="Sophie LEFÈVRE").click()
    expect(page.locator("h1")).to_have_text("Sophie LEFÈVRE")
    expect(page.get_by_role("link", name="Modifier dans la Révision")).to_be_visible()
    principal.filter(has_text="Actions").click()
    sous = page.get_by_role("navigation", name="Pages de l'onglet")
    for nom in ("Importer", "Révision", "Revue", "Liaisons", "Photos", "iCloud"):
        expect(sous.get_by_role("link", name=nom)).to_be_visible()
    principal.filter(has_text="Sauvegarde").click()
    expect(page.get_by_role("navigation", name="Pages de l'onglet").get_by_role("link", name="Archives")).to_be_visible()
    assert erreurs == []
    page.context.close()

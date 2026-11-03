"""Tests de l'interface dans Chromium, sur PC et à la taille d'un iPhone (390 × 844).
Il faut l'interface compilée dans app/static (voir la CI)."""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

playwright = pytest.importorskip("playwright.sync_api")
RACINE = Path(__file__).resolve().parents[2]
if not (RACINE / "app" / "static" / "index.html").is_file():
    pytest.skip("interface non compilée", allow_module_level=True)


@pytest.fixture(scope="module")
def adresse(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "tests.interface.serveur", str(tmp_path_factory.mktemp("ui")), str(port)],
                            cwd=RACINE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield base
    proc.terminate()


@pytest.fixture(scope="module")
def navigateur():
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(params=["pc", "iphone"])
def page(request, navigateur, adresse):
    mobile = request.param == "iphone"
    ctx = navigateur.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 860},
                                 is_mobile=mobile, has_touch=mobile)
    pg = ctx.new_page()
    erreurs = []
    pg.on("pageerror", lambda e: erreurs.append(str(e)))
    pg.goto(adresse)
    pg.fill("#mdp", "essai")
    pg.click("text=Ouvrir le carnet")
    pg.wait_for_selector("nav.onglets")
    pg.erreurs = erreurs
    yield pg
    assert not erreurs, erreurs
    ctx.close()


def test_trois_onglets_et_badge(page):
    onglets = page.locator("nav.onglets a.onglet")
    assert onglets.count() == 3
    assert re.fullmatch(r"\d+", page.locator(".badge").inner_text())


def test_a_traiter_garder_une_modification_iphone(page):
    # Le serveur est partagé : la première fiche de l'iPhone déjà gardée, on prend la suivante
    carte = page.locator("article", has=page.get_by_role("button", name="Garder", exact=True)).first
    carte.get_by_role("button", name="Garder", exact=True).click()
    page.wait_for_selector(".message")
    assert "gardée" in page.locator(".message").inner_text()


def test_contacts_recherche_et_tranche(page):
    page.click("nav.onglets >> text=Contacts")
    page.wait_for_selector(".ligne")
    page.fill("input[type=search]", "fabre")
    assert page.locator(".ligne").count() == 1
    page.fill("input[type=search]", "")
    if page.viewport_size["width"] > 500:
        assert page.locator(".tranche button").count() >= 5        # PC : onglets de la tranche
    else:
        assert page.locator(".index button").count() == 27         # iPhone : index fin A à Z et #


def test_tri_par_prenom_ou_par_nom(page):
    page.click("nav.onglets >> text=Contacts")
    page.wait_for_selector(".ligne")
    page.get_by_role("button", name="Prénom", exact=True).click()
    assert page.locator(".ligne .nom").first.inner_text().startswith("Agnès")
    page.get_by_role("button", name="Nom", exact=True).click()
    assert page.locator(".lettre").first.inner_text() == "A"
    assert page.locator(".ligne .nom").first.inner_text().startswith("Manon ANDRE")
    page.reload()
    page.wait_for_selector(".ligne")
    assert page.get_by_role("button", name="Nom", exact=True).get_attribute("aria-pressed") == "true"   # choix gardé
    page.get_by_role("button", name="Prénom", exact=True).click()


def test_pc_liste_et_fiche_cote_a_cote(page):
    if page.viewport_size["width"] < 900:
        pytest.skip("PC seulement")
    page.click("nav.onglets >> text=Contacts")
    page.click(".ligne:has-text('Paul MARTIN')")
    page.wait_for_selector(".volet-fiche h1:has-text('Paul MARTIN')")
    assert page.locator(".volet-liste .ligne").count() > 5


def test_fiche_apercu_puis_ecrire_et_annuler(page):
    page.goto(page.url.split("#")[0] + "#/contacts/DDDD-4444")
    page.click("text=Modifier")
    page.locator("label:has-text('Fonction') input").fill("Vigneron")
    page.click("text=Voir les changements")
    assert "Vigneron" in page.locator(".apercu").inner_text()
    page.click("text=Écrire dans iCloud")
    page.wait_for_selector(".message >> text=Annuler")
    page.click(".message >> text=Annuler")
    page.wait_for_selector(".message >> text=revenue")


def test_cibles_tactiles_et_champs(page):
    if page.viewport_size["width"] > 500:
        pytest.skip("contrôle tactile : iPhone seulement")
    page.goto(page.url.split("#")[0] + "#/contacts/DDDD-4444")
    page.click("text=Modifier")
    tailles = page.eval_on_selector_all("button.bouton, a.bouton, .onglet", "els => els.map(e => e.getBoundingClientRect().height)")
    assert min(tailles) >= 43.5
    polices = page.eval_on_selector_all("input, select, textarea", "els => els.map(e => parseFloat(getComputedStyle(e).fontSize))")
    assert min(polices) >= 16


def test_pas_de_defilement_horizontal(page):
    for route in ("#/a-traiter", "#/contacts", "#/contacts/AAAA-1111", "#/etat"):
        page.goto(page.url.split("#")[0] + route)
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), route


def test_etat_et_deconnexion(page):
    page.click("nav.onglets >> text=État")
    page.wait_for_selector("text=Sauvegardes d'iCloud")
    page.click("text=Se déconnecter")
    page.wait_for_selector("#mdp")

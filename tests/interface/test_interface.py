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


def ouvrir_tuile(page, nom):
    """2.9 : « À traiter » s'ouvre sur une grille de tuiles ; on entre dans celle demandée.
    Faux si la tuile n'existe pas (rien de ce type à traiter)."""
    page.click("nav.onglets a[aria-label='Contacts']")
    page.click("nav.onglets a[aria-label='À traiter']")
    page.wait_for_selector("nav[aria-label='Types de choses à traiter'], .vide:has-text('Rien à traiter')")
    tuile = page.locator("nav[aria-label='Types de choses à traiter'] .tuile", has_text=nom)
    page.wait_for_timeout(300)                                   # la grille se remplit après la réponse du serveur
    if not tuile.count():
        return False
    tuile.click()
    page.wait_for_selector(".retour-tuiles")
    return True


def ouvrir_service(page, nom):
    """2.9 : Connexion, une icône par service ; 3.3 : ces icônes sont les « Outils », sous les fiches communes."""
    page.click("nav.onglets a[aria-label='Connexion']")
    page.wait_for_selector("nav[aria-label='Outils'] .tuile")
    # par le nom de la tuile, pas par son résumé (« Import » cite Instagram et Facebook)
    page.locator("nav[aria-label='Outils'] .tuile", has=page.locator(".nom-tuile", has_text=nom)).first.click()


def test_trois_onglets_et_badge(page):
    onglets = page.locator("nav.onglets a.onglet")
    assert onglets.count() == 6          # 2.9 : À traiter, Contacts, Groupes, Photos, Connexion, Réglages
    assert re.fullmatch(r"\d+", page.locator(".badge").inner_text())


def test_a_traiter_garder_une_modification_iphone(page):
    # Le serveur est partagé : la première fiche de l'iPhone déjà gardée, on prend la suivante
    assert ouvrir_tuile(page, "Changé sur l'iPhone")
    carte = page.locator("article", has=page.get_by_role("button", name="Garder", exact=True)).first
    carte.get_by_role("button", name="Garder", exact=True).click()
    page.wait_for_selector(".message")
    assert "gardée" in page.locator(".message").inner_text()


def test_contacts_recherche_et_tranche(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector(".ligne")
    page.fill("input[type=search]", "fabre")
    assert page.locator(".ligne").count() == 1
    page.fill("input[type=search]", "")
    if page.viewport_size["width"] > 500:
        assert page.locator(".tranche button").count() >= 5        # PC : onglets de la tranche
    else:
        assert page.locator(".index button").count() == 27         # iPhone : index fin A à Z et #


def test_tri_par_prenom_ou_par_nom(page):
    page.click("nav.onglets a[aria-label='Contacts']")
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
    page.click("nav.onglets a[aria-label='Contacts']")
    page.click(".ligne:has-text('Paul MARTIN')")
    page.wait_for_selector(".volet-fiche h1:has-text('Paul MARTIN')")
    assert page.locator(".volet-liste .ligne").count() > 5


def test_fiche_apercu_puis_ecrire_et_annuler(page):
    page.goto(page.url.split("#")[0] + "#/contacts/DDDD-4444")
    page.get_by_role("button", name="Modifier les informations").click()
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
    page.get_by_role("button", name="Modifier les informations").click()
    tailles = page.eval_on_selector_all("button.bouton, a.bouton, .onglet", "els => els.map(e => e.getBoundingClientRect().height)")
    assert min(tailles) >= 43.5
    polices = page.eval_on_selector_all("input, select, textarea", "els => els.map(e => parseFloat(getComputedStyle(e).fontSize))")
    assert min(polices) >= 16


def test_pas_de_defilement_horizontal(page):
    for route in ("#/a-traiter", "#/contacts", "#/contacts/AAAA-1111", "#/etat", "#/reglages"):
        page.goto(page.url.split("#")[0] + route)
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), route


def test_etat_et_deconnexion(page):
    ouvrir_service(page, "Sauvegardes")
    page.wait_for_selector("text=Exporter tout le carnet")
    page.locator("nav.tuiles .tuile", has_text="Home Assistant").click()
    page.wait_for_selector("h3:has-text('Home Assistant')")
    assert page.locator("text=Exporter tout le carnet").count() == 0             # un service à la fois
    page.click("nav.onglets a[aria-label='Réglages']")
    page.wait_for_selector("h2:has-text('Journal')")
    page.click("text=Se déconnecter")
    page.wait_for_selector("#mdp")


# ------------------------------------------------------------------ 2.1 : complétude et réseaux

def test_filtres_de_completude_et_jauges(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector(".ligne")
    total = page.locator(".ligne").count()
    assert page.locator(".ligne .jauge").count() == total
    # 2.8 : les filtres viennent du tableau des attentes (ici, Amis attend le jour de naissance)
    page.locator(".manques .pastille", has_text="Sans jour de naissance").click()
    filtrees = page.locator(".ligne").count()
    assert 0 < filtrees < total
    page.locator(".manques .pastille", has_text="Sans jour de naissance").click()
    assert page.locator(".ligne").count() == total


def test_valider_puis_retirer_la_validation(page):
    page.goto(page.url.split("#")[0] + "#/contacts/F-05")
    bloc = page.locator(".completude")
    bloc.get_by_role("button", name=re.compile("Valider la fiche|Revalider")).click()
    page.wait_for_selector(".completude >> text=Fiche validée")
    bloc.get_by_role("button", name="Retirer la validation").click()
    page.wait_for_selector(".completude >> text=Valider la fiche")


def test_ajouter_puis_delier_un_profil_facebook(page):
    page.goto(page.url.split("#")[0] + "#/contacts/F-06")
    page.wait_for_selector("h2:has-text('Plateformes')")
    page.select_option("select[aria-label='Réseau à ajouter']", "facebook")
    page.fill("input[aria-label='Profil Facebook']", "https://www.facebook.com/francois.muller.demo")
    page.get_by_role("button", name="Ajouter", exact=True).click()
    page.wait_for_selector(".reseaux >> text=Facebook")
    page.locator(".reseaux li.liaison", has_text="Facebook").get_by_role("button", name="Délier").click()
    assert "francois.muller.demo" in page.locator(".confirmer").inner_text()     # l'adresse retirée est montrée
    page.get_by_role("button", name="Délier Facebook").click()
    page.wait_for_selector(".reseaux li:has-text('Facebook')", state="detached")


def test_annonce_avant_un_traitement_par_lot(page):
    """2.6.5 : avant « Confirmer », carnet dit ce que le lot fera. Rien n'est confirmé ici."""
    if not ouvrir_tuile(page, "Réseaux"):
        pytest.skip("points réseau déjà traités")
    tout_lier = page.get_by_role("button", name=re.compile(r"^Tout lier \(\d+\)$"))
    if not tout_lier.count():
        pytest.skip("un seul point réseau : pas de traitement par lot")
    tout_lier.click()
    annonce = page.locator(".lot .annonce")
    annonce.wait_for()
    assert "seront modifiées dans iCloud" in annonce.inner_text()
    assert "copie d'iCloud" in annonce.inner_text()
    page.get_by_role("button", name="Annuler", exact=True).click()
    page.get_by_role("button", name=re.compile(r"^Tout ignorer \(\d+\)$")).click()
    annonce.wait_for()
    assert "Rien n'est écrit dans iCloud" in annonce.inner_text()
    page.get_by_role("button", name="Annuler", exact=True).click()
    assert not annonce.count()


def test_a_traiter_famille_reseaux(page):
    if not ouvrir_tuile(page, "Réseaux"):
        pytest.skip("points réseau déjà traités par l'autre format")
    carte = page.locator("article", has_text="Réseau à rattacher").first
    assert carte.get_by_role("button", name="Pas lui").count() == 1
    carte.get_by_role("button", name="Lier", exact=True).click()
    page.wait_for_selector(".message >> text=Lié")


def test_etat_reseaux_et_remise_a_zero_confirmee(page):
    ouvrir_service(page, "Telegram")                                # 2.9 : un réseau par icône, dans Connexion
    page.wait_for_selector("h3#reseau-telegram")                    # 3.3 : le titre du panneau est aussi un h3
    assert page.locator("text=CARNET_TELEGRAM_API_ID").count() == 1          # non configuré dans la démo
    assert page.locator("h3:has-text('Facebook')").count() == 0              # un seul réseau affiché
    page.click("nav.onglets a[aria-label='Réglages']")              # 2.9 : l'analyse globale est dans Réglages
    page.get_by_role("button", name="Remettre les validations à zéro…").click()
    bouton = page.get_by_role("button", name="Remettre à zéro et analyser")
    assert bouton.is_disabled()
    page.fill("input[aria-label='Confirmation']", "remettre")
    assert bouton.is_disabled()
    page.get_by_role("button", name="Annuler", exact=True).click()


def test_manifeste_pwa(adresse):
    r = httpx.get(adresse + "/manifest.json")
    assert r.status_code == 200 and r.json()["display"] == "standalone"
    assert httpx.get(adresse + "/icone-512.png").status_code == 200


# ------------------------------------------------------------------ 2.2 : pilule et boutons à anneau

def test_pilule_libelle_de_l_onglet_actif(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector("nav.onglets a[aria-label='Contacts'][aria-current='page']")
    page.wait_for_timeout(500)                                  # fin de l'élargissement de la pilule
    large = page.viewport_size["width"] >= 900
    # 2.9, six onglets : sur iPhone des icônes seules (le nom est le titre de l'écran) ; sur PC, le rail garde les noms
    for onglet in ("Contacts", "Réglages"):
        libelle = page.locator(f"nav.onglets a[aria-label='{onglet}'] .libelle")
        if large:
            assert libelle.bounding_box()["width"] > 20
        else:
            assert not libelle.is_visible() or libelle.bounding_box()["width"] < 2
    barre = page.locator("nav.onglets").bounding_box()
    assert barre["x"] >= 0 and barre["x"] + barre["width"] <= page.viewport_size["width"] + 1      # la barre tient dans l'écran


def test_export_vcf_par_le_bouton_a_anneau(page):
    ouvrir_service(page, "Sauvegardes")
    with page.expect_download() as tele:
        page.get_by_role("button", name="Exporter tout le carnet (.vcf)").click()
    assert tele.value.suggested_filename.startswith("carnet-") and tele.value.suggested_filename.endswith(".vcf")
    page.wait_for_selector(".bouton-anneau[data-etat='succes']")
    page.route("**/api/export.vcf", lambda r: r.fulfill(status=502, json={"detail": "iCloud ne répond pas."}))
    page.wait_for_selector(".bouton-anneau[data-etat='repos']", timeout=6000)
    page.get_by_role("button", name="Exporter tout le carnet (.vcf)").click()
    page.wait_for_selector(".bouton-anneau[data-etat='echec'] >> text=iCloud ne répond pas.")


def test_glisser_deposer_un_export_instagram(page):
    if page.viewport_size["width"] < 900:
        pytest.skip("glisser-déposer : PC seulement")
    ouvrir_service(page, "Instagram")
    page.wait_for_selector("h3:has-text('Instagram')")
    cible = page.locator("label.bouton-anneau", has_text="Déposer l'export Instagram")
    assert "ou glisse le fichier ici" in cible.inner_text()
    contenu = '{"relationships_following": [{"title": "glisse.depot", "string_list_data": [{"value": "glisse.depot"}]}]}'
    poignee = page.evaluate_handle("""(texte) => {
        const dt = new DataTransfer(); dt.items.add(new File([texte], 'following.json', { type: 'application/json' })); return dt }""", contenu)
    page.dispatch_event("body", "dragenter", {"dataTransfer": poignee})
    cible.dispatch_event("dragover", {"dataTransfer": poignee})
    page.wait_for_selector("label.bouton-anneau.survol >> text=Lâche le fichier")
    cible.dispatch_event("drop", {"dataTransfer": poignee})
    page.wait_for_selector("label.bouton-anneau[data-etat='succes']")
    assert "Instagram : 1 compte(s) lu(s)" in page.locator(".message").inner_text()


def test_reseaux_aller_a_la_partie_et_rattacher_un_importe(page):
    ouvrir_service(page, "Telegram")
    page.wait_for_selector("h3#reseau-telegram")      # 3.3 : le titre du panneau est aussi un h3 ; on attend la partie
    assert page.locator("#reseau-telegram").is_visible()
    liste = page.locator(".non-lies", has_text="Importés de Telegram sans fiche")
    liste.get_by_role("button", name=re.compile("Importés de Telegram")).click()
    page.wait_for_selector(".non-lies ul, .non-lies p")
    ligne = liste.locator("li", has_text="Hugo B.")
    if not ligne.count():
        pytest.skip("déjà rattaché par l'autre format")
    assert "proposé dans À traiter" not in ligne.inner_text()       # nom abrégé : aucune proposition
    ligne.get_by_role("button", name="Rattacher…").click()
    liste.locator("input[aria-label='Fiche à rattacher']").fill("Bonnet")
    liste.get_by_role("button", name="Hugo BONNET").click()
    page.wait_for_selector(".message >> text=rattaché")
    page.wait_for_selector(".non-lies li:has-text('Hugo B.')", state="detached")


# ------------------------------------------------------------------ 2.8 : manques, réglages, photos, import

def test_28_manques_dans_a_traiter_ouvrent_la_liste(page):
    compteur = page.locator(".badge").inner_text()
    assert ouvrir_tuile(page, "Contact incomplet")
    ligne = page.locator(".ligne-manque", has_text="Sans photo ni logo")
    nombre = int(ligne.locator(".nombre").inner_text())
    assert nombre > 0 and page.locator(".badge").inner_text() == compteur      # les manques ne comptent pas
    assert page.get_by_role("link", name="Traiter dans Photos").count() == 1
    ligne.click()
    page.wait_for_selector(".ligne")
    assert page.locator(".ligne").count() == nombre
    assert page.locator(".manques .pastille[aria-pressed='true']").inner_text().startswith("Sans photo ni logo")


def test_28_reglages_une_case_annonce_puis_change_les_manques(page):
    ouvrir_service(page, "Attentes")                                 # 2.9 : le tableau est dans Connexion
    page.wait_for_selector("text=Ce que chaque groupe doit avoir")
    page.wait_for_selector("details.groupe, input[aria-label='Clients : Adresse']", state="attached")   # tableau chargé
    if page.viewport_size["width"] < 900:                                       # iPhone : un groupe à la fois
        page.locator("details.groupe", has_text="Clients").locator("summary").click()
        case = page.locator("details.groupe", has_text="Clients").get_by_label("Adresse")
    else:
        case = page.get_by_label("Clients : Adresse")
    avant = case.is_checked()
    case.click()
    annonce = page.locator(".confirmer")
    annonce.wait_for()
    assert "Sans adresse" in annonce.inner_text() and "passera de" in annonce.inner_text()
    annonce.get_by_role("button", name="Annuler").click()                        # rien n'est enregistré avant « Enregistrer »
    page.wait_for_function("!document.querySelector('.confirmer')")
    assert case.is_checked() == avant
    case.click()
    annonce.wait_for()
    annonce.get_by_role("button", name="Enregistrer").click()
    page.wait_for_selector(".message")
    page.wait_for_function("!document.querySelector('.confirmer')")
    assert case.is_checked() != avant
    # 2.9 : les interrupteurs « la nuit » sont par service ; celui de Treemich (écritures toutes seules) reste éteint
    page.locator("nav.tuiles .tuile", has_text="Treemich").click()
    page.wait_for_selector("h3:has-text('Treemich')")
    bascule = page.get_by_role("switch")
    assert bascule.count() == 1 and not bascule.is_checked()
    page.click("nav.onglets a[aria-label='Réglages']")
    page.get_by_role("button", name="Se déconnecter").wait_for()


def test_28_photos_logo_depose_puis_pose(page):
    import io
    from PIL import Image
    page.click("nav.onglets a[aria-label='Photos']")
    page.wait_for_selector("nav[aria-label='Files'] .tuile")
    assert page.locator("nav[aria-label='Files'] .tuile").count() == 4
    fiche = page.locator("li.fiche", has_text="Plomberie Garonne")
    if not fiche.count():
        pytest.skip("logo déjà posé par l'autre appareil (serveur partagé)")
    assert fiche.get_by_role("link", name="Chercher sur Google Images").get_attribute("href").startswith("https://www.google.com/search")
    image = io.BytesIO()
    Image.new("RGB", (240, 240), (30, 90, 160)).save(image, "PNG")
    fiche.locator("input[type=file]").set_input_files({"name": "logo.png", "mimeType": "image/png", "buffer": image.getvalue()})
    fiche.locator("text=prêt à poser").wait_for()
    assert fiche.locator("img.apercu-logo").count() == 1
    page.get_by_role("button", name=re.compile(r"Poser les logos \(1 société\)")).click()
    page.wait_for_function("!document.body.innerText.includes('Plomberie Garonne')", timeout=20000)


def test_28_import_annonce_avant_d_importer(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.get_by_role("button", name="Importer").click()
    fenetre = page.locator("dialog[open]")
    fenetre.wait_for()
    assert fenetre.get_by_role("button", name="Importer").is_disabled()
    fenetre.locator("input[type=file]").set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"rien a voir"})
    fenetre.locator(".refus").wait_for()
    assert "non reconnu" in fenetre.locator(".refus").inner_text()
    carte = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Essai;Import;;;\r\nFN:Import Essai\r\nTEL:+33 6 01 02 03 04\r\nEND:VCARD\r\n"
    fenetre.locator("input[type=file]").set_input_files({"name": "un.vcf", "mimeType": "text/vcard", "buffer": carte.encode()})
    fenetre.locator(".reconnu").wait_for()
    assert "1 fiche(s)" in fenetre.locator(".reconnu").inner_text()
    fenetre.get_by_role("button", name="Fermer").click()                        # on n'importe pas : rien n'a été ajouté
    page.wait_for_function("!document.querySelector('dialog[open]')")


def test_28_supprimer_une_fiche_demande_toujours_confirmation(page):
    base = page.url.split("#")[0]
    page.goto(base + "#/contacts/F-18")
    page.get_by_role("button", name="Modifier les informations").click()
    page.get_by_role("button", name="Supprimer cette fiche…").click()
    confirmation = page.get_by_role("alertdialog", name="Confirmer la suppression")
    assert "Sophie" in confirmation.inner_text() and "iPhone" in confirmation.inner_text()
    confirmation.get_by_role("button", name="Garder la fiche").click()            # on peut toujours renoncer
    assert page.get_by_role("alertdialog").count() == 0
    page.get_by_role("button", name="Supprimer cette fiche…").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Supprimer définitivement").click()
    page.wait_for_selector(".message >> text=supprimée d'iCloud")
    assert "#/contacts" in page.url and "F-18" not in page.url
    # « Annuler » la remet (le serveur est partagé entre PC et iPhone : la fiche doit revenir)
    page.locator(".message").get_by_role("button", name="Annuler").click()
    page.wait_for_selector(".message >> text=Annulé")
    page.goto(base + "#/contacts/F-18")
    page.wait_for_selector("h1:has-text('Sophie')")


def test_282_societe_ecrite_de_plusieurs_facons(page):
    if not ouvrir_tuile(page, "Sociétés"):
        pytest.skip("déjà harmonisée par l'autre appareil (serveur partagé)")
    page.wait_for_selector("article.point")
    point = page.locator("article.point", has_text="Société écrite de plusieurs façons")
    assert point.get_by_label("Atelier Dupont", exact=False).count() >= 2
    bouton = point.get_by_role("button", name="Écrire sur 1 fiche")
    assert bouton.is_enabled()
    bouton.click()
    page.wait_for_selector(".message >> text=écrit sur 1 fiche")


# ------------------------------------------------------------------ 2.9 : tuiles, groupes, connexion

def test_29_a_traiter_s_ouvre_sur_les_tuiles(page):
    page.wait_for_selector("nav[aria-label='Types de choses à traiter'] .tuile")
    assert page.locator("article.point").count() == 0                            # la grille d'abord, pas la liste
    noms = page.locator("nav.tuiles .tuile .nom-tuile").all_inner_texts()
    assert "Contact incomplet" in noms and "Pas de groupe" in noms
    # Le chiffre de l'onglet = les tuiles qui comptent ; « Contact incomplet » n'en fait pas partie
    compte = sum(int(t.locator(".chiffre").inner_text()) for t in page.locator("nav.tuiles .tuile:not(.secondaire)").all())
    assert int(page.locator(".badge").inner_text()) == compte
    page.locator("nav.tuiles .tuile", has_text="Pas de groupe").click()          # ouvre Contacts, déjà filtré
    page.wait_for_selector(".ligne")
    assert page.locator(".manques .pastille[aria-pressed='true']").count() == 1


def test_29_groupes_creer_ajouter_retirer_supprimer(page):
    nom = "Essai " + ("PC" if page.viewport_size["width"] >= 900 else "iPhone")   # serveur partagé : un groupe par appareil
    page.click("nav.onglets a[aria-label='Groupes']")
    page.wait_for_selector("input[aria-label='Nom du nouveau groupe']")
    page.fill("input[aria-label='Nom du nouveau groupe']", nom)
    page.get_by_role("button", name="Créer", exact=True).click()
    page.wait_for_selector(f"h2:has-text('{nom}')")
    page.locator("label.ajout input").fill("Bonnet")
    page.locator("button.candidat", has_text="BONNET").first.click()
    page.wait_for_selector(".message >> text=ajouté(s) au groupe")
    page.wait_for_selector(".membres li:has-text('BONNET')")
    page.locator(".membres li", has_text="BONNET").locator("input[type=checkbox]").check()
    page.get_by_role("button", name="Retirer du groupe (1)").click()
    page.wait_for_selector(".message >> text=retiré(s) du groupe")
    page.wait_for_selector(".membres li", state="detached")
    page.get_by_role("button", name="Supprimer ce groupe…").click()
    confirmation = page.get_by_role("alertdialog", name="Confirmer la suppression du groupe")
    assert nom in confirmation.inner_text()
    confirmation.get_by_role("button", name="Supprimer le groupe").click()
    page.wait_for_selector(".message >> text=Aucune fiche n'a été supprimée")


def test_29_connexion_verifier_puis_interrupteur_de_nuit(page):
    page.click("nav.onglets a[aria-label='Connexion']")
    page.wait_for_selector("nav[aria-label='Outils'] .tuile")
    noms = " ".join(page.locator("nav.tuiles .tuile .nom-tuile").all_inner_texts())
    for attendu in ("iCloud", "Immich", "Treemich", "Sauvegardes", "Import", "LinkedIn", "Home Assistant", "Attentes"):
        assert attendu in noms
    page.locator("nav.tuiles .tuile", has_text="Immich").click()
    page.wait_for_selector("h3:has-text('Immich')")
    page.get_by_role("button", name="Comparer", exact=True).click()    # 3.3 : « Vérifier » de l'écran de travail
    page.wait_for_selector(".rapport")
    texte = page.locator(".rapport").inner_text()
    assert "reliée(s) à une personne d'Immich" in texte
    assert "Aucun écart" not in texte                                            # rien de relié dans la démo : rien de comparé
    bascule = page.get_by_role("switch")
    avant = bascule.is_checked()
    bascule.click()
    page.wait_for_selector(".message")
    assert bascule.is_checked() != avant
    bascule.click()                                                              # on remet (serveur partagé)
    page.wait_for_function("(a) => document.querySelector('input[role=switch]').checked === a", arg=avant)


# ------------------------------------------------------------------ 2.10 : propositions de photo et d'affiche

def test_210_toucher_la_photo_ouvre_cinq_propositions(page):
    import io
    from PIL import Image
    base = page.url.split("#")[0]
    page.goto(base + "#/contacts/F-21")                                           # contact d'une société, non relié à Immich
    page.get_by_role("button", name="Modifier les informations").click()
    page.get_by_role("button", name="Changer la photo ou l'affiche").click()
    fenetre = page.locator("dialog[open]")
    fenetre.get_by_role("heading", name="Photo du contact").wait_for()
    image = io.BytesIO()
    Image.new("RGB", (260, 260), (30, 90, 170)).save(image, "PNG")
    fenetre.locator("input[type=file]").set_input_files({"name": "logo.png", "mimeType": "image/png", "buffer": image.getvalue()})
    affiches = fenetre.locator("ul[aria-label=\"Propositions d'affiche\"] .proposition")
    page.wait_for_function("document.querySelectorAll('dialog[open] ul.affiches .proposition').length === 5")
    assert fenetre.locator("ul[aria-label='Propositions de photo'] .proposition").count() >= 1
    assert "couleur de la société" in affiches.first.inner_text()
    page.wait_for_function("[...document.querySelectorAll('dialog[open] ul.affiches img')].every((i) => i.complete && i.naturalWidth > 0)")
    boite = fenetre.bounding_box()
    assert boite["x"] >= 0 and boite["x"] + boite["width"] <= page.viewport_size["width"] + 1
    affiches.first.click()
    page.wait_for_selector(".message >> text=Affiche prête")
    page.wait_for_function("!document.querySelector('dialog[open]')")


# ------------------------------------------------------------------ 2.11 : propositions pour tous les contacts

def test_211_portraits_propositions_puis_pose(page):
    """Portraits : un contact relié à Immich montre ses propositions une fois cherchées ; la première
    est le choix de carnet ; rien n'est coché d'office pour un contact qui a déjà une photo."""
    page.click("nav.onglets a[aria-label='Photos']")
    page.wait_for_selector("nav[aria-label='Files'] .tuile")
    page.locator("nav[aria-label='Files'] .tuile", has=page.locator(".nom-tuile", has_text=re.compile("^Portraits$"))).click()
    oeil = page.get_by_role("button", name=re.compile(r"Afficher les \d+ déjà choisi"))
    if oeil.count():                                                           # 2.12 : les choix déjà faits sont repliés
        oeil.click()
    lignes = page.locator("li.fiche.choix")
    if not lignes.count():
        pytest.skip("aucun contact relié à Immich dans le jeu de démonstration")
    ligne = lignes.first
    nom = ligne.locator("a.nom").inner_text()
    if ligne.get_by_text("Pas encore cherché").count():
        ligne.get_by_role("checkbox").check()
        page.get_by_role("button", name=re.compile(r"Chercher les propositions \(\d+\)")).click()
    ligne = page.locator("li.fiche.choix", has_text=nom)
    groupe = ligne.get_by_role("group", name=re.compile("Propositions pour"))
    groupe.wait_for(timeout=20000)
    premiere = groupe.get_by_role("button").first
    assert "choix de carnet" in premiere.get_attribute("aria-label")
    assert premiere.get_attribute("aria-pressed") == "true"                    # le choix de carnet est retenu par défaut
    assert not ligne.get_by_role("checkbox").is_checked()                      # mais rien n'est coché d'office
    poser = page.get_by_role("button", name=re.compile(r"Poser les photos cochées \(0\)"))
    assert poser.is_disabled()
    premiere.click()                                                           # toucher une proposition coche le contact
    assert ligne.get_by_role("checkbox").is_checked()
    page.get_by_role("button", name=re.compile(r"Poser les photos cochées \(1\)")).click()
    if not page.get_by_role("button", name=re.compile(r"Masquer les \d+ déjà choisi")).count():
        page.get_by_role("button", name=re.compile(r"Afficher les \d+ déjà choisi")).click(timeout=20000)   # le choix fait, la ligne se replie
    page.locator("li.fiche.choix", has_text=nom).get_by_text("a déjà une photo").wait_for(timeout=20000)
    page.get_by_role("button", name=re.compile(r"Masquer les \d+ déjà choisi")).click()
    assert not page.locator("li.fiche.choix", has_text=nom).count()
    largeur = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert largeur[0] <= largeur[1]


def test_2112_nom_associe_propose_les_noms_du_carnet(page):
    page.goto(page.url.split("#")[0] + "#/contacts/DDDD-4444")
    page.get_by_role("button", name="Modifier les informations").click()
    bloc = page.locator("fieldset", has_text="Noms associés")
    bloc.get_by_role("button", name="Ajouter").click()
    champ = bloc.get_by_label("Noms associés").last
    assert champ.get_attribute("list") == "noms-du-carnet"
    page.wait_for_function("document.querySelectorAll('#noms-du-carnet option').length > 2")
    noms = page.eval_on_selector_all("#noms-du-carnet option", "els => els.map(e => e.value)")
    soi = " ".join(page.eval_on_selector_all(".simples input", "els => els.slice(0, 2).map(e => e.value)")).strip().lower()
    assert len(noms) == len(set(noms)) and all(noms)
    assert soi and soi not in [n.lower() for n in noms]                # la fiche ne se propose pas elle-même
    champ.fill("Quelqu'un Hors Carnet")                                # écrire à la main reste possible
    page.click("text=Voir les changements")
    assert "Quelqu'un Hors Carnet" in page.locator(".apercu").inner_text()


def test_212_relancer_la_recherche_pour_tous(page):
    page.click("nav.onglets a[aria-label='Photos']")
    page.wait_for_selector("nav[aria-label='Files'] .tuile")
    for tuile in ("Portraits", "Affiches"):
        page.locator("nav[aria-label='Files'] .tuile", has=page.locator(".nom-tuile", has_text=re.compile(f"^{tuile}$"))).click()
        bouton = page.get_by_role("button", name=re.compile(r"Relancer la recherche pour tous \(\d+\)"))
        if not bouton.count():
            pytest.skip("aucun contact relié à Immich dans le jeu de démonstration")
        bouton.click()                                                  # jamais en un seul geste
        groupe = page.get_by_role("group", name="Relancer la recherche")
        assert "Rien n'est posé" in groupe.inner_text()
        groupe.get_by_role("button", name="Non").click()
    page.get_by_role("button", name=re.compile(r"Relancer la recherche pour tous")).click()
    page.get_by_role("group", name="Relancer la recherche").get_by_role("button", name="Oui, relancer").click()
    page.get_by_text(re.compile(r"contact\(s\) relu\(s\) dans Immich")).first.wait_for(timeout=30000)


def test_213_cocher_tous_ceux_que_carnet_propose(page):
    """Un geste coche tous les contacts qui ont une proposition de carnet, sans rien poser."""
    page.click("nav.onglets a[aria-label='Photos']")
    page.wait_for_selector("nav[aria-label='Files'] .tuile")
    page.locator("nav[aria-label='Files'] .tuile", has=page.locator(".nom-tuile", has_text=re.compile("^Portraits$"))).click()
    oeil = page.get_by_role("button", name=re.compile(r"Afficher les \d+ déjà choisi"))
    if oeil.count():
        oeil.click()
    bouton = page.get_by_role("button", name=re.compile(r"Cocher tous ceux que carnet propose \((\d+)\)"))
    if not bouton.count():
        pytest.skip("aucune proposition de carnet dans le jeu de démonstration")
    nombre = int(re.search(r"\((\d+)\)", bouton.inner_text()).group(1))
    bouton.click()
    lot = 20
    attendu = f"{lot} sur {nombre}" if nombre > lot else str(nombre)
    page.get_by_role("button", name=re.compile(rf"Poser les photos cochées \({attendu}\)")).wait_for(timeout=20000)
    proposees = page.locator("li.fiche.choix", has=page.get_by_role("group", name=re.compile("Propositions pour")))
    assert proposees.count() and all(l.get_by_role("checkbox").is_checked() for l in proposees.all())
    sans = page.locator("li.fiche.choix", has_text="Pas encore cherché")
    assert not any(l.get_by_role("checkbox").is_checked() for l in sans.all())   # rien sans proposition
    page.get_by_role("button", name="Tout décocher").click()
    assert page.get_by_role("button", name=re.compile(r"Poser les photos cochées \(0\)")).is_disabled()


def test_216_propositions_qui_ne_s_affichent_plus(page):
    """Une proposition dont l'image ne se charge plus : la personne quitte la liste, un message le dit et propose la solution."""
    page.click("nav.onglets a[aria-label='Photos']")
    page.wait_for_selector("nav[aria-label='Files'] .tuile")
    page.locator("nav[aria-label='Files'] .tuile", has=page.locator(".nom-tuile", has_text=re.compile("^Portraits$"))).click()
    oeil = page.get_by_role("button", name=re.compile(r"Afficher les \d+ déjà choisi"))
    if oeil.count():
        oeil.click()
    if not page.locator(".propositions").count():
        try:
            page.locator(".propositions").first.wait_for(timeout=3000)
        except Exception:
            pytest.skip("aucune proposition dans le jeu de démonstration")
    avant = page.locator(".propositions").count()
    motif = re.compile(r"/propositions/photo/")
    page.route(motif, lambda route: route.fulfill(status=404, body=""))
    try:
        page.reload()
        page.click("nav.onglets a[aria-label='Photos']")
        page.locator("nav[aria-label='Files'] .tuile", has=page.locator(".nom-tuile", has_text=re.compile("^Portraits$"))).click()
        oeil = page.get_by_role("button", name=re.compile(r"Afficher les \d+ déjà choisi"))
        if oeil.count():
            oeil.click()
        message = page.get_by_role("status", name="Propositions qui ne s'affichent plus")
        message.wait_for()
        assert "problème d'affichage" in message.inner_text() and "n'est plus dans Immich" in message.inner_text()
        assert message.get_by_role("button", name=re.compile("Refaire la recherche pour")).is_enabled()
        page.wait_for_function("document.querySelectorAll('.propositions').length === 0")      # les personnes touchées sont retirées
        message.get_by_role("button", name="Les afficher quand même").click()
        page.locator(".propositions").first.wait_for()
        assert page.locator(".propositions").count() >= 1 and avant >= 1
        message.get_by_role("button", name="Les cacher").click()
        page.wait_for_function("document.querySelectorAll('.propositions').length === 0")
    finally:
        page.unroute(motif)


# ------------------------------------------------------------------ 2.18.1 : deux portables, deux icônes chacun

def test_2181_portables_travail_ou_mobile_par_icones(page):
    if not ouvrir_tuile(page, "Mise en forme"):
        pytest.skip("déjà réglé par l'autre appareil (serveur partagé)")
    point = page.locator("article.point", has_text="Plusieurs portables")
    if not point.count():
        pytest.skip("déjà réglé par l'autre appareil (serveur partagé)")
    lignes = point.locator("li.portable")
    assert lignes.count() == 2
    for i in range(2):
        groupe = lignes.nth(i).get_by_role("group")
        assert groupe.get_by_role("button", name="Travail").count() == 1
        assert groupe.get_by_role("button", name="Mobile").count() == 1
        assert lignes.nth(i).locator("button[aria-pressed='true']").count() == 1   # un seul choisi par numéro
    travail = lignes.nth(0).get_by_role("button", name="Travail")
    travail.click()
    assert travail.get_attribute("aria-pressed") == "true"
    assert lignes.nth(0).get_by_role("button", name="Mobile").get_attribute("aria-pressed") == "false"
    lignes.nth(1).get_by_role("button", name="Mobile").click()
    assert travail.bounding_box()["height"] >= 44
    point.get_by_role("button", name="Écrire dans iCloud").click()
    page.wait_for_selector(".message >> text=Types des portables")


def test_221_sans_anniversaire_et_millesime(page):
    """2.21 : tuile « Sans anniversaire » (hors compteur) lue dans Millésime ; une personne reliée ouvre sa fiche."""
    assert ouvrir_tuile(page, "Sans anniversaire")
    liste = page.locator("ul[aria-label='Personnes sans anniversaire'] li")
    liste.first.wait_for()
    assert liste.count() == 2
    assert "aucune fiche reliée" in liste.nth(1).inner_text()
    liste.nth(0).locator("a").click()
    page.wait_for_url("**/#/contacts/F-10")
    ouvrir_service(page, "Millésime")
    page.get_by_text("24 visage(s) à analyser", exact=False).first.wait_for()
    assert page.locator("table.verif").first.inner_text().count("Photos à dater") == 1


def test_222_genre_sur_la_fiche(page):
    """2.22 : la fiche porte un champ genre (femme, homme, autre) ; toucher le genre choisi le retire."""
    page.goto(page.url.split("#")[0] + "#/contacts/F-05")
    groupe = page.get_by_role("group", name="Genre")
    groupe.wait_for()
    homme = groupe.get_by_role("button", name="Homme", exact=True)
    assert [b.inner_text() for b in groupe.get_by_role("button").all()] == ["Femme", "Homme", "Autre"]
    if homme.get_attribute("aria-pressed") == "true":           # laissé par l'autre format d'écran
        homme.click()
        page.wait_for_selector(".message >> text=Genre retiré")
    homme.click()
    page.wait_for_selector(".message >> text=Genre enregistré")
    page.wait_for_function("document.querySelector('[aria-label=Genre] button:nth-of-type(2)').getAttribute('aria-pressed') === 'true'")
    homme.click()
    page.wait_for_selector(".message >> text=Genre retiré")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def test_222_frere_sans_genre_question_puis_lien_a_corriger(page):
    """2.22 : une personne notée « frère » sans genre connu : la question d'abord, puis le lien frère → sœur à corriger.
    2.22.3 : la question est dans la tuile « Genre à préciser », le lien dans « Liens à corriger »."""
    if not ouvrir_tuile(page, "Genre à préciser"):
        pytest.skip("déjà traité par l'autre format")
    question = page.locator("article", has_text="Noté « frère »").first
    if page.viewport_size["width"] >= 900:                       # PC : le point se choisit dans la liste de gauche
        for nom in ("Camille GARNIER", "Gaëlle PERRIN"):
            bouton = page.locator(".sommaire button", has_text=nom)
            if bouton.count():
                bouton.first.click()
                break
    if not question.count():
        pytest.skip("questions déjà traitées par l'autre format")
    # 2.22.2 : trois boutons, une couleur chacun (rose, bleu, violet)
    couleurs = [question.locator(f"button.genre-{g}").evaluate("e => getComputedStyle(e).color") for g in ("femme", "homme", "autre")]
    assert len(set(couleurs)) == 3
    question.get_by_role("button", name="Femme", exact=True).click()
    page.wait_for_selector(".message >> text=Genre enregistré")
    assert ouvrir_tuile(page, "Liens à corriger")
    lien = page.locator("article", has_text="Lien à accorder au genre").first
    lien.wait_for()
    assert "frère" in lien.locator(".avant").inner_text() and "sœur" in lien.locator(".apres").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    lien.get_by_role("button", name="Corriger", exact=True).click()
    page.wait_for_selector(".message >> text=Annuler")


def test_2223_genre_pour_tous_propositions_par_lot(page):
    """2.22.3 : toute personne sans genre a sa question, hors compteur ; les genres proposés d'après le prénom
    s'enregistrent par lot après annonce."""
    if not ouvrir_tuile(page, "Genre à préciser"):
        pytest.skip("déjà traité par l'autre format")
    lot = page.get_by_role("button", name=re.compile(r"^Enregistrer les genres proposés \(\d+\)$"))
    if not lot.count():
        pytest.skip("propositions déjà enregistrées par l'autre format")
    assert "D'après le prénom" in page.locator("article").first.inner_text() or "pas de proposition" in page.locator("article").first.inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    lot.click()
    annonce = page.locator(".lot .annonce")
    annonce.wait_for()
    assert "Rien n'est écrit dans iCloud" in annonce.inner_text()
    page.get_by_role("button", name="Confirmer", exact=True).click()
    page.wait_for_selector(".message >> text=traité")
    page.get_by_role("button", name=re.compile(r"^Enregistrer les genres proposés")).wait_for(state="detached")


def test_224_champs_de_l_iphone_lecture_et_ajouter_un_champ(page):
    """2.24 : la fiche montre les champs de l'iPhone ; en modification, les champs rares s'ajoutent par « Ajouter un champ »."""
    racine = page.url.split("#")[0]
    page.goto(racine + "#/contacts/IPHONE-224")
    page.wait_for_selector("dt:has-text('Nom de naissance')")
    lecture = page.locator(".lecture dl").inner_text()
    for attendu in ("Titre", "Second prénom", "Suffixe", "Skype", "Diplôme", "Sonnerie", "Shelter", "Son SMS"):
        assert attendu in lecture, attendu
    page.get_by_role("button", name="Modifier les informations").click()
    for visible in ("Titre", "Nom de naissance", "Prononciation du nom"):          # déjà remplis : visibles d'office
        assert page.locator(f"label:has-text('{visible}') input").count() == 1, visible
    assert page.get_by_role("group", name="Messageries instantanées").locator("select").count() == 3
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    # Une fiche simple : le titre n'est pas affiché tant qu'on ne l'ajoute pas
    page.goto(racine + "#/contacts/F-06")
    page.get_by_role("button", name="Modifier les informations").click()
    assert not page.locator("label:has-text('Titre') input").count()
    page.get_by_label("Ajouter un champ").select_option(label="Titre")
    page.locator("label:has-text('Titre') input").fill("Dr")
    page.click("text=Voir les changements")
    assert "Titre" in page.locator(".apercu").inner_text() and "Dr" in page.locator(".apercu").inner_text()
    page.click("text=Écrire dans iCloud")
    page.wait_for_selector(".message >> text=Annuler")
    page.click(".message >> text=Annuler")
    page.wait_for_selector(".message >> text=revenue")


# ------------------------------------------------------------------ 2.26 : réglages d'usage et restauration

def test_226_reglages_d_usage_puis_restaurer(page):
    page.click("nav.onglets a[aria-label='Réglages']")
    bloc = page.locator("#reglages-usage")
    bloc.wait_for()
    enregistrer = bloc.get_by_role("button", name="Enregistrer les réglages")
    assert enregistrer.is_disabled()                                   # rien de changé
    bloc.get_by_label("Heure de la nuit", exact=True).fill("04:20")
    enregistrer.click()
    page.wait_for_selector(".message:has-text('Réglages enregistrés')")
    assert bloc.get_by_label("Heure de la nuit", exact=True).input_value() == "04:20"
    # Restaurer : choisir une date, voir les différences (avant → sauvegardé), confirmer
    rest = page.locator("#restaurer")
    rest.get_by_role("button", name="Voir les sauvegardes").click()
    rest.get_by_label("Date de la sauvegarde").select_option("2026-11-15")
    rest.locator("table.diff").wait_for()
    texte = rest.locator("table.diff").inner_text()
    assert "Heure de la nuit" in texte and "05:45" in texte and "Vérifier le certificat de Synology" in texte
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    rest.get_by_role("button", name="Restaurer ces réglages").click()
    page.wait_for_selector(".message:has-text('Réglages restaurés')")
    assert bloc.get_by_label("Heure de la nuit", exact=True).input_value() == "05:45"
    # remis comme avant pour les autres tests (le serveur est partagé)
    bloc.get_by_label("Heure de la nuit", exact=True).fill("03:00")
    bloc.get_by_label("Vérifier le certificat de Synology").check()
    enregistrer.click()
    page.wait_for_selector(".message:has-text('Réglages enregistrés')")


def test_233_fiche_complete_pour_les_journaux(page):
    """2.33 : rubriques repliables, suggestion → pépite, vrac rangé, jauge en nombre, sujets interdits masqués."""
    uid = "F-06" if page.viewport_size["width"] > 500 else "F-07"      # serveur partagé : une fiche par taille
    page.goto(page.url.split("#")[0] + f"#/contacts/{uid}")
    page.get_by_role("tab", name=re.compile("Pépites")).click()          # 3.1 : dans la tuile Pépites du dossier
    fiche = page.locator("section[aria-label='Fiche complète pour les journaux']")
    fiche.locator(".jauge").wait_for()
    assert "0 pépite" in fiche.locator(".jauge").inner_text()
    # toutes les familles sont là, repliées
    for titre in ("Vie et entourage", "Goûts et passions", "Caractère et manies", "Histoires", "Pour les journaux"):
        assert fiche.locator("details.famille > summary", has_text=titre).count() == 1
    # une suggestion touchée remplit le champ ; « Ajouter » en fait une pépite
    fiche.locator("details.famille > summary", has_text="Goûts et passions").click()
    sports = fiche.locator("details.rubrique", has=page.locator("summary", has_text=re.compile(r"^\s*Sports")))
    sports.locator("summary").click()
    sports.get_by_role("button", name="Joue à la pétanque").click()
    sports.locator("form.ligne").get_by_role("button", name="Ajouter").click()
    sports.locator(".pepite", has_text="Joue à la pétanque").wait_for()
    assert "1 pépite" in fiche.locator(".jauge").inner_text()
    # vrac : rangé par mots-clés, la rubrique est dite et reste modifiable
    fiche.get_by_label("Détail en vrac").fill("A peur des araignées")
    fiche.get_by_role("button", name="Ranger").click()
    fiche.locator(".rangee").wait_for()
    assert "Peurs et phobies" in fiche.locator(".rangee").inner_text()
    assert fiche.locator(".rangee select").input_value() == "peurs"
    fiche.locator(".jauge", has_text="2 pépites").wait_for()
    # sujets interdits : masqués par défaut, ne comptent pas dans la jauge
    interdits = fiche.locator(".interdits")
    assert not interdits.get_by_label("Ajouter un sujet interdit").is_visible()
    interdits.get_by_role("button", name="Afficher").click()
    interdits.get_by_label("Ajouter un sujet interdit").fill("Son ancien travail")
    interdits.get_by_role("button", name="Ajouter").click()
    interdits.locator(".pepite", has_text="Son ancien travail").wait_for()
    assert "(1)" in interdits.locator("h3").inner_text() and "2 pépites" in fiche.locator(".jauge").inner_text()
    interdits.get_by_role("button", name="Masquer").click()
    assert not interdits.locator(".pepite").count()
    # iPhone : rien ne déborde sur le côté
    assert page.evaluate("document.documentElement.scrollWidth") <= page.viewport_size["width"]


def test_31_fiche_tuiles_et_photo(page):
    """3.1 (maquette A) : en-tête comme l'iPhone, six tuiles, la tuile choisie s'affiche dessous, la photo ouvre Photos."""
    uid = "F-06" if page.viewport_size["width"] > 500 else "F-07"
    page.goto(page.url.split("#")[0] + f"#/contacts/{uid}")
    onglets = page.get_by_role("tablist", name="Dossier de la personne")
    onglets.wait_for()
    noms = [t.inner_text() for t in onglets.get_by_role("tab").all()]
    for titre in ("Alimentation", "Pépites", "Livre d'or", "Gazette", "Famille", "Photos"):
        assert any(titre in n for n in noms), titre
    assert onglets.get_by_role("tab", name=re.compile("Alimentation")).get_attribute("aria-selected") == "true"
    onglets.get_by_role("tab", name=re.compile("Gazette")).click()
    page.locator("#dossier-panneau", has_text="photos scandale").wait_for()
    assert page.locator("#dossier-panneau").get_by_role("heading", name="Séjours et soirées").count() == 1
    page.get_by_role("button", name=re.compile("Photos : choisir la photo")).click()
    page.locator("#dossier-panneau").get_by_role("button", name="Choisir la photo et l'affiche").wait_for()
    assert onglets.get_by_role("tab", name=re.compile("Photos")).get_attribute("aria-selected") == "true"
    assert page.evaluate("document.documentElement.scrollWidth") <= page.viewport_size["width"]


# ------------------------------------------------------------------ 3.3 : fiches « Connexion » communes (contrat 3)

def test_33_fiches_connexion_communes(page):
    """Huit services : des tuiles à voyant ; la fiche s'ouvre au toucher (Ce qui est lu, Ce qui est écrit, Vérifier en
    contour, Synchroniser plein) ; un service non réglé montre sa variable ; les Outils restent dessous."""
    page.click("nav.onglets a[aria-label='Connexion']")
    tuiles = page.locator("ul[aria-label='Services'] button[aria-expanded]")
    tuiles.first.wait_for()
    assert tuiles.count() == 8
    assert page.locator("h1.titre", has_text="Connexion").count() == 1
    icloud = page.locator("#tuile-icloud")
    icloud.click()
    assert icloud.get_attribute("aria-expanded") == "true"
    fiche = page.locator("#fiche-ouverte")
    fiche.wait_for()
    texte = fiche.inner_text()
    assert "Ce qui est lu" in texte and "iCloud est la source" in texte and "Ce qui est écrit" in texte
    assert fiche.get_by_role("button", name="Synchroniser", exact=True).count() == 1
    fiche.get_by_role("button", name="Vérifier", exact=True).click()
    fiche.get_by_text("Vérifié", exact=False).wait_for()
    page.keyboard.press("Escape")
    page.locator("#fiche-ouverte").wait_for(state="detached")
    page.locator("#tuile-coffre-contacts").click()
    assert "CARNET_CONTACTS" in page.locator("#fiche-ouverte").inner_text()     # pas relié : la variable, sans bouton
    assert page.locator("#fiche-ouverte button").count() == 0
    assert page.locator("nav[aria-label='Outils'] .tuile").count() >= 10


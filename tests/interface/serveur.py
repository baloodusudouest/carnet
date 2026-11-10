"""Lance carnet pour les tests d'interface : contacts fictifs, faux iCloud, Immich et Treemich.
Usage : python -m tests.interface.serveur <dossier> <port>"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import uvicorn

from app import icloud, liaisons, main, reseaux
from app.carnet import Carnet
from tests.faux_icloud import FauxICloud
from tests.faux_services import FauxImmich, FauxTreemich
from tests.test_carnet import DONNEES, PAUL, _config, carte_simple

PRENOMS = ["Agnès Roux", "Bruno Lefèvre", "Camille Garnier", "Denis Fabre", "Élodie Chevalier", "François Muller",
           "Gaëlle Perrin", "Hugo Bonnet", "Inès Lambert", "Julien Moreau", "Karine Faure", "Louis Girard",
           "Manon Andre", "Nicolas Mercier", "Océane Blanc", "Pierre Guerin", "Quentin Boyer", "Romane Garcia",
           "Sophie Clement", "Thomas Robin", "Valérie Gauthier", "Yves Masson"]


def preparer(dossier: Path) -> tuple[Carnet, FauxICloud]:
    vcf = (DONNEES / "icloud.vcf").read_text(encoding="utf-8") + PAUL
    for i, nom in enumerate(PRENOMS):
        vcf += carte_simple(f"F-{i:02d}", nom, f"TEL;type=CELL:+33 6 {10 + i} 20 30 40\r\n")
    ic = FauxICloud(vcf)
    services = {"icloud": ic, "immich": FauxImmich(), "treemich": FauxTreemich(),
                "synology": FauxICloud("", utilisateur="carnet", mot_de_passe="syno")}
    cfg = _config(dossier, password="essai", static=Path(__file__).resolve().parents[2] / "app" / "static")
    c = Carnet(cfg, {k: v.transport() for k, v in services.items()})
    c.treemich().facteur_attente = 0
    with c.ecriture():
        icloud.relire(c, "démo")
    # Quelques points à traiter : une modification faite sur l'iPhone et une fiche nouvelle
    ic.modifier_sur_iphone("F-03", carte_simple("F-03", "Denis Fabre", "TEL;type=CELL:+33 6 99 88 77 66\r\n"))
    ic.modifier_sur_iphone("N-01", carte_simple("N-01", "Zoé Durand", "TEL;type=CELL:+33 6 55 44 33 22\r\n"))
    with c.ecriture():
        icloud.relire(c, "démo")
    liaisons.donnees(c)
    # Réseaux : un contact Telegram au même numéro qu'Agnès, deux comptes Instagram au pseudo prénom+nom
    reseaux.enregistrer(c, "telegram", [{"ext_id": "tg-1", "nom": "Agnès R.", "telephone": "+33610203040", "pseudo": "agnes"}])
    reseaux.enregistrer(c, "instagram", [{"ext_id": "brunolefevre", "nom": "", "pseudo": "brunolefevre"},
                                         {"ext_id": "camille.garnier", "nom": "", "pseudo": "camille.garnier"}])
    reseaux.proposer(c)
    c.transports["logos"] = faux_logos()
    return c, ic


def faux_logos():
    """Sites des réseaux simulés : une icône unie par site (pas d'accès à Internet dans la démo)."""
    import io
    import httpx
    from PIL import Image
    teintes = {"facebook": "#7f95e0", "instagram": "#e08fb3", "linkedin": "#6fa3d8", "whatsapp": "#7fcf98",
               "telegram": "#76c0e6", "icloud": "#8fa9c7", "x.com": "#d6d0c8"}

    def repondre(requete):
        hote = requete.url.host
        teinte = next((t for k, t in teintes.items() if k in hote), None)
        if not teinte or not requete.url.path.endswith(".png"):
            return httpx.Response(404)
        tampon = io.BytesIO()
        Image.new("RGBA", (128, 128), teinte).save(tampon, "PNG")
        return httpx.Response(200, content=tampon.getvalue(), headers={"content-type": "image/png"})
    return httpx.MockTransport(repondre)


if __name__ == "__main__":
    dossier, port = Path(sys.argv[1]), int(sys.argv[2])
    dossier.mkdir(parents=True, exist_ok=True)
    c, _ = preparer(dossier)
    main.ETAT["carnet"] = c
    threading.excepthook = lambda a: None
    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")

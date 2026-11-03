"""Lance carnet pour les tests d'interface : contacts fictifs, faux iCloud, Immich et Treemich.
Usage : python -m tests.interface.serveur <dossier> <port>"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import uvicorn

from app import icloud, liaisons, main
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
    return c, ic


if __name__ == "__main__":
    dossier, port = Path(sys.argv[1]), int(sys.argv[2])
    dossier.mkdir(parents=True, exist_ok=True)
    c, _ = preparer(dossier)
    main.ETAT["carnet"] = c
    threading.excepthook = lambda a: None
    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")

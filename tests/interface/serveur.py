"""Lance carnet pour les tests d'interface : données fictives, faux iCloud, Immich et Treemich.
Usage : python -m tests.interface.serveur <dossier> <port>"""
import os
import sys
import threading
import time

dossier, port = sys.argv[1], int(sys.argv[2])
os.environ.update(CARNET_DATA=f"{dossier}/data", CARNET_STATE=f"{dossier}/state", CARNET_PASSWORD="essai",
                  CARNET_DB_KEY="cle-essai", CARNET_KIT_CONFIG="", CARNET_ICLOUD_USER="moi@icloud.com",
                  CARNET_ICLOUD_PASSWORD="abcd-efgh-ijkl-mnop", CARNET_IMMICH_CLE="cle",
                  CARNET_TREEMICH_EMAIL="moi@x.fr", CARNET_TREEMICH_PASSWORD="tm")

import uvicorn  # noqa: E402

from app.main import app, etat  # noqa: E402
from tests.faux_icloud import FauxICloud  # noqa: E402
from tests.test_carnet import DONNEES, _faux_immich_treemich  # noqa: E402


def brancher():
    while "carnet" not in etat:
        time.sleep(0.05)
    cn = etat["carnet"]
    cn.transport_icloud = FauxICloud((DONNEES / "icloud.vcf").read_text()).transport()
    cn.transport_immich, cn.transport_treemich = _faux_immich_treemich()


threading.Thread(target=brancher, daemon=True).start()
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

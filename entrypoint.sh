#!/bin/sh
# Démarre en root, adopte le propriétaire du dossier /data (ton compte du NAS),
# puis lance carnet avec ses droits. Aucun UID/GID à configurer.
set -eu

DATA="${CARNET_DATA:-/data}"
STATE="${CARNET_STATE:-/state}"
mkdir -p "$DATA/depot" "$STATE/sauvegardes"

PUID="$(stat -c %u "$DATA")"
PGID="$(stat -c %g "$DATA")"
if [ "$PUID" = "0" ] && [ "${MAISON_ROOT_ACCEPTE:-}" != "oui" ]; then
  # /data appartient à root (dossier créé par Docker) : l'appli tournerait en root. Refus, avec le remède.
  echo "ERREUR : $DATA appartient à root ; l'appli ne tourne pas en root." >&2
  echo "Remède : donner le dossier à ton compte du NAS (File Station › Propriétés › Propriétaire, ou chown -R <UID>:<GID>)," >&2
  echo "puis redémarrer le conteneur. Dépannage seulement : MAISON_ROOT_ACCEPTE=oui dans la stack." >&2
  exit 1
fi
echo "carnet : exécution avec UID=$PUID GID=$PGID (propriétaire de $DATA)"

chown -R "$PUID:$PGID" "$DATA" "$STATE"
chmod 700 "$STATE"   # base et sauvegardes : lisibles par ton compte seulement
# Le dossier config/ du kit appartient déjà au même compte : rien à changer

export HOME="$STATE"
cd /app
exec gosu "$PUID:$PGID" uvicorn app.main:app --app-dir /app --host 0.0.0.0 --port 8096 --proxy-headers --no-access-log

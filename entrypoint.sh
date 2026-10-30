#!/bin/sh
# Démarre en root, adopte le propriétaire du dossier /data (ton compte du NAS),
# puis lance carnet avec ses droits. Aucun UID/GID à configurer.
set -eu

DATA="${CARNET_DATA:-/data}"
STATE="${CARNET_STATE:-/state}"
mkdir -p "$DATA/depot" "$DATA/archives" "$DATA/export" "$STATE"

PUID="$(stat -c %u "$DATA")"
PGID="$(stat -c %g "$DATA")"
echo "carnet : exécution avec UID=$PUID GID=$PGID (propriétaire de $DATA)"

chown -R "$PUID:$PGID" "$DATA" "$STATE"
chmod 700 "$STATE"
# Le dossier config/ du kit appartient déjà au même compte : rien à changer

export HOME="$STATE"
cd /app
exec gosu "$PUID:$PGID" uvicorn app.main:app --app-dir /app --host 0.0.0.0 --port 8096 --proxy-headers

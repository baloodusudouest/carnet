# syntax=docker/dockerfile:1
# ---------- Étape 1 : interface Svelte compilée ----------
FROM node:22-bookworm-slim AS interface
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite écrit dans ../app/static
RUN mkdir -p /app && npx vite build --outDir /app/static --emptyOutDir

# ---------- Étape 2 : dépendances Python en roues ----------
FROM python:3.12-slim-bookworm AS roues
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------- Étape 3 : image d'exécution ----------
FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="carnet" \
      org.opencontainers.image.description="Rassemble, vérifie et fusionne les contacts iCloud, Gmail et Outlook" \
      org.opencontainers.image.source="https://github.com/baloodusudouest/carnet"

# gosu : abandon des droits root ; tzdata : dates françaises
RUN apt-get update && apt-get install -y --no-install-recommends gosu tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=roues /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

WORKDIR /app
COPY app ./app
COPY --from=interface /app/static ./app/static
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

ENV TZ=Europe/Paris \
    CARNET_DATA=/data \
    CARNET_STATE=/state \
    CARNET_KIT_CONFIG=/kit-config \
    PYTHONUNBUFFERED=1

EXPOSE 8096
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8096/health')" || exit 1
ENTRYPOINT ["/entrypoint.sh"]

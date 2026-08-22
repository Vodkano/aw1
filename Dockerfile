# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# AW1 v3. Tres etapas: se compila la interfaz, se instala el backend en un
# venv, y la imagen final parte de la Playwright oficial (trae Chromium con
# todas sus librerias de sistema). La etapa "deps" usa la MISMA imagen base
# que "runtime" a proposito: un venv creado en una base distinta (p.ej.
# python:3.12-slim) enlaza su interprete a rutas de ESA imagen, y al copiarlo
# a una imagen distinta el simlink queda roto ("No module named aw1" al
# arrancar). Con la misma base en ambas etapas, el venv se copia intacto y de
# paso el compilador (build-essential) nunca llega a la imagen final.
# ---------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble AS deps
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential python3-venv \
 && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml ./
COPY backend/src ./src
# El paquete "playwright" debe coincidir con la version de Chromium que ya
# trae la imagen base (v1.56.0): si pip instala una version mas nueva del
# paquete, busca un build de navegador que no esta descargado en runtime.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install -U pip \
 && /opt/venv/bin/pip install playwright==1.56.0 \
 && /opt/venv/bin/pip install .

# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AW1_HOST=0.0.0.0 \
    AW1_DATA_DIR=/data \
    AW1_LOG_JSON=true \
    AW1_WEB_DIST=/app/frontend/dist
# AW1_PORT no se fija aqui a proposito: Railway/Render inyectan `PORT` en
# tiempo de ejecucion y Settings lo usa como respaldo (ver settings.py). Sin
# esa variable, el valor por defecto sigue siendo 8000.

RUN useradd --create-home --uid 10001 aw1 && mkdir -p /data && chown aw1:aw1 /data

COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY --from=web /web/dist ./frontend/dist
RUN chown -R aw1:aw1 /app /opt/venv

USER aw1
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import os,urllib.request,sys; port=os.environ.get('PORT') or os.environ.get('AW1_PORT') or '8000'; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).status==200 else 1)"

CMD ["python3", "-m", "aw1"]

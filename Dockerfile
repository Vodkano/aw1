# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# AW1 v3. Dos etapas: se compila la interfaz y la imagen final parte de la
# imagen oficial de Playwright, que ya trae Chromium con todas sus librerias
# de sistema. El backend se instala directo en esa misma imagen (no en un
# venv de otra imagen y copiado despues): un venv creado en una base distinta
# (p.ej. python:3.12-slim) enlaza su interprete a rutas de ESA imagen, y al
# copiarlo a la imagen de Playwright el simlink queda roto.
# ---------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
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

WORKDIR /app
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src
# El paquete "playwright" debe coincidir con la version de Chromium que ya
# trae esta imagen base (v1.56.0): si pip instala una version mas nueva del
# paquete, busca un build de navegador que no esta descargado aqui.
RUN pip install --break-system-packages --root-user-action=ignore playwright==1.56.0 \
 && pip install --break-system-packages --root-user-action=ignore ./backend
COPY --chown=aw1:aw1 --from=web /web/dist ./frontend/dist
RUN chown -R aw1:aw1 /app

USER aw1
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import os,urllib.request,sys; port=os.environ.get('PORT') or os.environ.get('AW1_PORT') or '8000'; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).status==200 else 1)"

CMD ["python3", "-m", "aw1"]

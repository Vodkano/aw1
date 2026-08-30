#!/usr/bin/env bash
set -euo pipefail

echo "== Instalando Ollama =="
curl -fsSL https://ollama.com/install.sh | sh

echo "== Arrancando Ollama para descargar el modelo =="
ollama serve > /tmp/ollama.log 2>&1 &
sleep 5
ollama pull llama3.2:3b

echo "== Instalando backend + frontend + Chromium =="
make install

echo "== Copiando .env de ejemplo =="
if [ ! -f .env ]; then
  cp .env.example .env
  {
    echo "AW1_ALLOW_PRIVATE_HOSTS=true"
    echo "AW1_OLLAMA_FAST_MODEL=llama3.2:3b"
  } >> .env
fi

echo "Listo. Para arrancar: make run  (o make dev para recarga en caliente)."

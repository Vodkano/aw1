"""Configuracion del servidor HTTP -- todo por variable de entorno, sin
archivo de config aparte (mismo criterio que ``backend/src/aw1/settings.py``
para las variables que aca importan: nada de leer un YAML propio para un
prototipo de un solo proceso)."""

from __future__ import annotations

import os
from dataclasses import dataclass

_OLLAMA_URL_DEFECTO = "http://127.0.0.1:11434"
_MODELO_CHAT_DEFECTO = "mistral"
_MODELO_EMBEDDINGS_DEFECTO = "nomic-embed-text"


@dataclass(frozen=True)
class Configuracion:
    database_url: str
    ollama_url: str = _OLLAMA_URL_DEFECTO
    modelo_chat: str = _MODELO_CHAT_DEFECTO
    modelo_embeddings: str = _MODELO_EMBEDDINGS_DEFECTO

    @classmethod
    def desde_entorno(cls) -> Configuracion:
        database_url = os.environ.get("AW1S_DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "Falta AW1S_DATABASE_URL "
                "(ej. postgresql://postgres:aw1s@127.0.0.1:5432/aw1s)."
            )
        return cls(
            database_url=database_url,
            ollama_url=os.environ.get("AW1S_OLLAMA_URL", _OLLAMA_URL_DEFECTO),
            modelo_chat=os.environ.get("AW1S_MODELO_CHAT", _MODELO_CHAT_DEFECTO),
            modelo_embeddings=os.environ.get(
                "AW1S_MODELO_EMBEDDINGS", _MODELO_EMBEDDINGS_DEFECTO
            ),
        )

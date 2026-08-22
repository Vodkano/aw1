"""Cual proveedor/modelo de LLM esta activo, en un solo lugar.

``AW1_LLM_PROVIDER`` (env) fija el valor de arranque, pero el panel admin
puede cambiarlo en caliente via ``SecretsStore`` sin reiniciar el proceso
(ver ``api/routes/admin.py``). Todo el codigo que necesita saber "que modelo
uso ahora mismo" -armar el cliente LLM, elegir el modelo del chat, el log de
arranque- pasa por estas tres funciones, para no repetir la logica de "DB
primero, env despues" en cada lugar por separado.
"""

from __future__ import annotations

from ..settings import Settings
from .secrets_store import SecretsStore

__all__ = ["effective_provider", "chat_model", "judge_model"]


def effective_provider(settings: Settings, secrets: SecretsStore) -> str:
    return secrets.get("llm_provider") or settings.llm_provider


def chat_model(settings: Settings, secrets: SecretsStore) -> str:
    if effective_provider(settings, secrets) == "groq":
        return settings.groq_model
    return settings.ollama_model


def judge_model(settings: Settings, secrets: SecretsStore) -> str:
    if effective_provider(settings, secrets) == "groq":
        return settings.groq_fast_model or settings.groq_model
    return settings.ollama_fast_model or settings.ollama_model

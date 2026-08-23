"""Cliente crudo de la API de Bots de Telegram.

Un solo httpx.AsyncClient compartido alcanza: el token de cada bot va en la
URL (``https://api.telegram.org/bot<TOKEN>/<metodo>``), nunca en un header,
asi que no hay nada especifico-por-token que fijar en la construccion del
cliente -a diferencia de OllamaClient, que si necesita un header fijo por
el tunel.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org"
# Margen bajo el limite duro de Telegram (4096 caracteres por mensaje).
_MAX_CHARS = 4000
# Limite real de Telegram: 1 mensaje por segundo por chat.
_CHUNK_DELAY = 1.05


class TelegramClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, token: str, method: str) -> str:
        return f"{_API}/bot{token}/{method}"

    async def get_me(self, token: str) -> dict[str, Any] | None:
        """Valida el token y trae los datos del bot (id, username). None si
        el token no sirve o Telegram no respondio."""
        try:
            response = await self._client.get(self._url(token, "getMe"))
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not payload.get("ok"):
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    async def set_webhook(self, token: str, url: str, secret_token: str) -> bool:
        try:
            response = await self._client.post(
                self._url(token, "setWebhook"),
                json={"url": url, "secret_token": secret_token, "allowed_updates": ["message"]},
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("No se pudo registrar el webhook de Telegram: %s", error)
            return False
        return bool(payload.get("ok"))

    async def delete_webhook(self, token: str) -> bool:
        try:
            response = await self._client.post(self._url(token, "deleteWebhook"))
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        return bool(payload.get("ok"))

    async def send_message(self, token: str, chat_id: int | str, text: str) -> None:
        """Trocea si hace falta y respeta el limite de 1 msg/seg por chat.
        Nunca lanza: un fallo al mandar la respuesta se registra, no tumba
        el turno (ya no hay nadie mas esperando este resultado)."""
        chunks = _split_message(text) or [""]
        for index, chunk in enumerate(chunks):
            if index > 0:
                await asyncio.sleep(_CHUNK_DELAY)
            try:
                response = await self._client.post(
                    self._url(token, "sendMessage"),
                    json={"chat_id": chat_id, "text": chunk},
                )
                payload = response.json()
                if not payload.get("ok"):
                    logger.warning("Telegram rechazo el mensaje: %s", payload.get("description"))
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("No se pudo mandar el mensaje a Telegram: %s", error)
                return


def _split_message(text: str) -> list[str]:
    """Corta en bloques de a lo sumo _MAX_CHARS, preferentemente por salto
    de linea o espacio para no partir una palabra a la mitad."""
    text = text.strip()
    if len(text) <= _MAX_CHARS:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > _MAX_CHARS:
        cut = remaining.rfind("\n", 0, _MAX_CHARS)
        if cut < _MAX_CHARS // 2:
            cut = remaining.rfind(" ", 0, _MAX_CHARS)
        if cut < _MAX_CHARS // 2:
            cut = _MAX_CHARS
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks

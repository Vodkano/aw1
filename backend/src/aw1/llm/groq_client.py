"""Cliente de Groq sobre su API compatible con OpenAI.

Groq expone inferencia sobre LPUs propios: mismo formato que
``/v1/chat/completions`` de OpenAI, pero ordenes de magnitud mas rapido y
barato que correr un modelo grande en CPU local. Implementa la misma interfaz
que ``OllamaClient`` (``chat``, ``stream``, ``json_call``, ``available``,
``models``, ``has_model``) para que ``ChatService`` y ``Judges`` puedan usar
cualquiera de los dos sin cambios.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..core.errors import ProviderError
from .client import extract_json

logger = logging.getLogger(__name__)

_HEALTH_TTL = 30.0


class GroqClient:
    def __init__(self, base_url: str, *, api_key: str) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=5.0),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        self._health: tuple[float, bool] = (0.0, False)
        self._models: list[str] = []

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- estado -------------------------------------------------------------
    async def available(self) -> bool:
        if not self._api_key:
            return False
        checked, value = self._health
        now = time.monotonic()
        if now - checked < _HEALTH_TTL:
            return value
        try:
            response = await self._client.get(f"{self._base}/models", timeout=5.0)
            response.raise_for_status()
            payload = response.json()
            self._models = [
                str(item.get("id", "")) for item in payload.get("data", []) if item.get("id")
            ]
            online = True
        except (httpx.HTTPError, ValueError):
            online = False
        self._health = (now, online)
        return online

    async def models(self) -> list[str]:
        await self.available()
        return list(self._models)

    async def has_model(self, name: str) -> bool:
        installed = await self.models()
        return not installed or name in installed

    # -- generacion ---------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.3,
        timeout: float = 60.0,
        max_tokens: int | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.post(
                f"{self._base}/chat/completions", json=body, timeout=timeout
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            raise ProviderError(self._explain(error)) from error
        except (httpx.HTTPError, ValueError) as error:
            raise ProviderError("Groq no respondio a tiempo.") from error
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            content = None
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Groq devolvio una respuesta vacia.")
        return content.strip()

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.6,
        timeout: float = 60.0,
    ) -> AsyncIterator[str]:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST", f"{self._base}/chat/completions", json=body, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ProviderError(
                        self._explain(
                            httpx.HTTPStatusError("", request=response.request, response=response)
                        )
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        parsed = json.loads(chunk)
                        piece = parsed["choices"][0]["delta"].get("content", "")
                    except (ValueError, KeyError, IndexError):
                        continue
                    if piece:
                        yield piece
        except httpx.HTTPError as error:
            raise ProviderError("Se perdio la conexion con Groq mientras respondia.") from error

    async def json_call(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float = 45.0,
        retries: int = 1,
    ) -> dict[str, Any] | None:
        for attempt in range(retries + 1):
            try:
                raw = await self.chat(
                    messages, model=model, json_mode=True, temperature=0.1, timeout=timeout
                )
            except ProviderError as error:
                logger.info("Juez sin respuesta de Groq: %s", error)
                return None
            parsed = extract_json(raw)
            if parsed is not None:
                return parsed
            logger.info("El modelo no devolvio JSON valido (intento %d).", attempt + 1)
        return None

    @staticmethod
    def _explain(error: httpx.HTTPStatusError) -> str:
        status = error.response.status_code
        if status == 401:
            return "La clave de Groq no es valida. Revisa AW1_GROQ_API_KEY."
        if status == 429:
            return "Groq rechazo la peticion por limite de uso. Reintenta en unos segundos."
        if status == 404:
            return "Groq no tiene ese modelo. Revisa AW1_GROQ_MODEL / AW1_GROQ_FAST_MODEL."
        return f"Groq respondio {status}."

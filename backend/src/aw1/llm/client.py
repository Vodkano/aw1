"""Cliente de Ollama sobre su API HTTP nativa.

Se habla directo con ``/api/chat`` en vez de arrastrar langchain: una dependencia
menos, control total del timeout, y acceso al modo ``format: json`` que obliga al
modelo a devolver un objeto valido. Tambien expone streaming token a token, que
es lo que alimenta el chat de la interfaz.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import httpx

from ..core.errors import ProviderError

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)
_HEALTH_TTL = 8.0


class OllamaClient:
    def __init__(self, base_url: str, *, num_ctx: int = 8192) -> None:
        self._base = base_url.rstrip("/")
        self._num_ctx = num_ctx
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0))
        self._health: tuple[float, bool] = (0.0, False)
        self._models: list[str] = []

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- estado -------------------------------------------------------------
    async def available(self) -> bool:
        checked, value = self._health
        now = time.monotonic()
        if now - checked < _HEALTH_TTL:
            return value
        try:
            response = await self._client.get(f"{self._base}/api/tags", timeout=3.0)
            response.raise_for_status()
            payload = response.json()
            self._models = [
                str(item.get("name", "")) for item in payload.get("models", []) if item.get("name")
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
        """Compara admitiendo que el usuario escriba ``mistral`` y tenga ``mistral:latest``."""
        installed = await self.models()
        wanted = name.split(":")[0]
        return any(item == name or item.split(":")[0] == wanted for item in installed)

    # -- generacion ---------------------------------------------------------
    def _body(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        temperature: float,
        stream: bool,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": temperature, "num_ctx": self._num_ctx}
        if max_tokens:
            options["num_predict"] = max_tokens
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        if json_mode:
            body["format"] = "json"
        return body

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
        body = self._body(
            model, messages, json_mode=json_mode, temperature=temperature,
            stream=False, max_tokens=max_tokens,
        )
        try:
            response = await self._client.post(
                f"{self._base}/api/chat", json=body, timeout=timeout
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            detail = self._explain(error)
            raise ProviderError(detail) from error
        except (httpx.HTTPError, ValueError) as error:
            raise ProviderError(
                "Ollama no respondio a tiempo. Comprueba que `ollama serve` este corriendo."
            ) from error
        message = payload.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Ollama devolvio una respuesta vacia.")
        return content.strip()

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.6,
        timeout: float = 180.0,
    ) -> AsyncIterator[str]:
        body = self._body(
            model, messages, json_mode=False, temperature=temperature,
            stream=True, max_tokens=None,
        )
        try:
            async with self._client.stream(
                "POST", f"{self._base}/api/chat", json=body, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ProviderError(
                        self._explain(
                            httpx.HTTPStatusError("", request=response.request, response=response)
                        )
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as error:
            raise ProviderError(
                "Se perdio la conexion con Ollama mientras respondia."
            ) from error

    async def json_call(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float = 45.0,
        retries: int = 1,
    ) -> dict[str, Any] | None:
        """Pide un objeto JSON y lo devuelve ya parseado, o ``None`` si no hubo forma.

        Nunca lanza por culpa del modelo: si Ollama alucina texto libre, el
        llamador decide como seguir sin IA.
        """
        for attempt in range(retries + 1):
            try:
                raw = await self.chat(
                    messages, model=model, json_mode=True, temperature=0.1, timeout=timeout
                )
            except ProviderError as error:
                logger.info("Juez sin respuesta de Ollama: %s", error)
                return None
            parsed = extract_json(raw)
            if parsed is not None:
                return parsed
            logger.info("El modelo no devolvio JSON valido (intento %d).", attempt + 1)
        return None

    @staticmethod
    def _explain(error: httpx.HTTPStatusError) -> str:
        status = error.response.status_code
        body = ""
        with suppress(Exception):  # el cuerpo es opcional: solo afina el mensaje
            body = error.response.text[:300]
        if status == 404 or "not found" in body.lower():
            return (
                "Ollama no tiene ese modelo descargado. Ejecuta `ollama pull <modelo>` "
                "o cambia AW1_OLLAMA_MODEL."
            )
        if status == 400 and "memory" in body.lower():
            return "El modelo no cabe en memoria. Prueba con uno mas pequeno."
        return f"Ollama respondio {status}."


def extract_json(raw: str) -> dict[str, Any] | None:
    """Rescata un objeto JSON de una respuesta que puede venir sucia.

    ``format: json`` casi siempre devuelve JSON limpio, pero los modelos
    pequenos a veces lo envuelven en un bloque de codigo o anaden una frase.
    """
    text = (raw or "").strip()
    if not text:
        return None
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None

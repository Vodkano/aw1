"""Cliente Ollama compartido -- chat con salida JSON estricta o texto libre.

Usado por Inteligencia (necesita JSON) y Procesamiento principal (necesita
texto libre). Vive en un paquete neutral -ni de Inteligencia ni de
Procesamiento principal- para que ninguno de los dos dependa del paquete
del otro solo por reusar este cliente: cada componente declara su propio
protocolo angosto (``GeneradorJSON`` / ``GeneradorTexto``) y
``OllamaChatClient`` satisface los dos por duck typing, sin heredar de
nada ni acoplar los paquetes entre si.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx

_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


class ClienteLLMError(Exception):
    pass


class GeneradorJSON(Protocol):
    async def generar_json(self, *, system: str, mensaje: str) -> dict[str, Any]: ...


class GeneradorTexto(Protocol):
    async def generar_texto(self, *, system: str, mensaje: str) -> str: ...


class OllamaChatClient:
    def __init__(
        self, base_url: str, *, modelo: str = "mistral", timeout: float = 45.0
    ) -> None:
        self._base = base_url.rstrip("/")
        self._modelo = modelo
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _chat(
        self, *, system: str, mensaje: str, json_mode: bool, temperature: float
    ) -> str:
        body: dict[str, Any] = {
            "model": self._modelo,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": mensaje},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            body["format"] = "json"
        try:
            response = await self._client.post(f"{self._base}/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ClienteLLMError(
                "Ollama no respondio. Comprueba que `ollama serve` este corriendo y que "
                f"'{self._modelo}' este descargado (`ollama pull {self._modelo}`)."
            ) from error
        return (payload.get("message") or {}).get("content", "")

    async def generar_json(self, *, system: str, mensaje: str) -> dict[str, Any]:
        contenido = await self._chat(
            system=system, mensaje=mensaje, json_mode=True, temperature=0.1
        )
        parsed = _extraer_json(contenido)
        if parsed is None:
            raise ClienteLLMError("Ollama no devolvio un JSON valido.")
        return parsed

    async def generar_texto(self, *, system: str, mensaje: str) -> str:
        contenido = await self._chat(
            system=system, mensaje=mensaje, json_mode=False, temperature=0.6
        )
        if not contenido.strip():
            raise ClienteLLMError("Ollama devolvio una respuesta vacia.")
        return contenido.strip()


def _extraer_json(texto: str) -> dict[str, Any] | None:
    """Igual que aw1.llm.client.extract_json en AW1 v3 (no se reusa directo
    porque aw1s esta aislado a proposito de backend/src/aw1): ``format:
    json`` casi siempre devuelve JSON limpio, pero modelos chicos a veces lo
    envuelven en un bloque de codigo o le agregan una frase."""
    texto = (texto or "").strip()
    if not texto:
        return None
    fence = _FENCE.search(texto)
    if fence:
        texto = fence.group(1).strip()
    try:
        parsed = json.loads(texto)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    start, end = texto.find("{"), texto.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(texto[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None

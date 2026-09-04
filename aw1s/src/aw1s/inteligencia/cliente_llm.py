"""Cliente LLM para Inteligencia -- chat con salida JSON obligatoria.

Mismo espiritu que aw1s.atajo_semantico.embeddings: protocolo +
implementacion real de Ollama, para poder cambiar de proveedor sin tocar
la logica de orquestacion (inteligencia.py).

Modelo por defecto: ``mistral``, el mismo default que ya usa AW1 v3
(ver backend/.env.example, AW1_OLLAMA_MODEL) -- reusa lo que el usuario ya
tiene descargado en vez de pedirle otro modelo mas.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx

_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


class ClienteLLMError(Exception):
    pass


class ClienteLLM(Protocol):
    async def generar_json(self, *, system: str, mensaje: str) -> dict[str, Any]: ...


class OllamaChatClient:
    def __init__(
        self, base_url: str, *, modelo: str = "mistral", timeout: float = 45.0
    ) -> None:
        self._base = base_url.rstrip("/")
        self._modelo = modelo
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generar_json(self, *, system: str, mensaje: str) -> dict[str, Any]:
        body = {
            "model": self._modelo,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": mensaje},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        try:
            response = await self._client.post(f"{self._base}/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ClienteLLMError(
                "Ollama no respondio al pedido de Inteligencia. Comprueba que "
                f"`ollama serve` este corriendo y que '{self._modelo}' este "
                f"descargado (`ollama pull {self._modelo}`)."
            ) from error
        contenido = (payload.get("message") or {}).get("content", "")
        parsed = _extraer_json(contenido)
        if parsed is None:
            raise ClienteLLMError("Ollama no devolvio un JSON valido para Inteligencia.")
        return parsed


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

"""Proveedor de embeddings para el paso 2 de la calibracion (similitud coseno).

Decision de implementacion (no estaba en la spec ni en los planos):
Ollama corriendo local via ``/api/embeddings``, modelo ``nomic-embed-text``
por defecto -reusa la misma infraestructura que ya tiene AW1 (Ollama local,
sin costo de API), consistente con que el usuario ya eligio a proposito no
gastar en proveedores de pago donde no hace falta (ver CLAUDE.md). Si esto
no es lo que se queria, es un default facil de cambiar: toda la logica de
``atajo.py`` depende solo del protocolo ``EmbeddingsProvider``, no de esta
clase en particular.
"""

from __future__ import annotations

import math
from typing import Protocol

import httpx


class ProveedorEmbeddingsError(Exception):
    pass


class EmbeddingsProvider(Protocol):
    async def vectorizar(self, texto: str) -> list[float]: ...


class OllamaEmbeddings:
    def __init__(
        self, base_url: str, *, modelo: str = "nomic-embed-text", timeout: float = 10.0
    ) -> None:
        self._base = base_url.rstrip("/")
        self._modelo = modelo
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def vectorizar(self, texto: str) -> list[float]:
        try:
            response = await self._client.post(
                f"{self._base}/api/embeddings",
                json={"model": self._modelo, "prompt": texto},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ProveedorEmbeddingsError(
                "Ollama no respondio al pedido de embedding. "
                "Comprueba que `ollama serve` este corriendo y que el modelo "
                f"'{self._modelo}' este descargado (`ollama pull {self._modelo}`)."
            ) from error
        vector = payload.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise ProveedorEmbeddingsError("Ollama no devolvio un embedding valido.")
        return [float(x) for x in vector]


def similitud_coseno(a: list[float], b: list[float]) -> float:
    """Sin numpy a proposito: los vectores son cortos, no vale la pena la dependencia."""
    if len(a) != len(b) or not a:
        return 0.0
    producto = sum(x * y for x, y in zip(a, b, strict=True))
    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(y * y for y in b))
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0
    return producto / (norma_a * norma_b)

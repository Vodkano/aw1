"""Doble de prueba para EmbeddingsProvider -- mismo espiritu que FakeOllama
en backend/tests/fakes.py: vectores controlados por texto, sin red real."""

from __future__ import annotations


class FakeEmbeddings:
    def __init__(
        self,
        vectores: dict[str, list[float]] | None = None,
        default: list[float] | None = None,
    ) -> None:
        self.vectores = vectores or {}
        self.default = default or [1.0, 0.0]
        self.calls: list[str] = []

    async def vectorizar(self, texto: str) -> list[float]:
        self.calls.append(texto)
        return self.vectores.get(texto, self.default)


def vector_con_similitud(score: float) -> list[float]:
    """Vector unitario 2D tal que su similitud coseno con [1.0, 0.0] es
    exactamente ``score`` (0 < score <= 1) -- para probar los umbrales sin
    depender de un modelo de embeddings real."""
    import math

    return [score, math.sqrt(max(0.0, 1.0 - score * score))]

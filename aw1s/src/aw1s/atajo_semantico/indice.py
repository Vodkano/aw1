"""Indice curado de frases conocidas -- NO es la Memoria (Postgres+pgvector).

Ver docs/aw1s/planos/0.1.0.2-atajo-semantico.md: este indice es chico,
mantenido a mano, y no crece solo con el uso como la memoria conversacional.
La implementacion de referencia es en memoria (pensada para el set inicial,
que es chico); una version respaldada en Postgres puede reemplazarla despues
sin tocar ``atajo.py``, que solo depende de este protocolo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .embeddings import EmbeddingsProvider, similitud_coseno
from .normalizar import normalizar_texto

CATEGORIA_DESPEDIDA = "despedida"


@dataclass
class EntradaIndice:
    frase: str
    respuesta: str
    categoria: str
    embedding: list[float] | None = None
    frase_normalizada: str = field(init=False)

    def __post_init__(self) -> None:
        self.frase_normalizada = normalizar_texto(self.frase)


@dataclass
class Coincidencia:
    entrada: EntradaIndice
    score: float  # 1.0 para match exacto


class IndiceFrasesConocidas(Protocol):
    async def buscar_exacto(self, texto_normalizado: str) -> EntradaIndice | None: ...
    async def mas_similar(self, vector: list[float]) -> Coincidencia | None: ...


class IndiceEnMemoria:
    def __init__(self, entradas: list[EntradaIndice] | None = None) -> None:
        self._entradas = list(entradas or [])

    def agregar(self, entrada: EntradaIndice) -> None:
        self._entradas.append(entrada)

    async def asegurar_embeddings(self, proveedor: EmbeddingsProvider) -> None:
        """Calcula el embedding de las entradas que todavia no lo tienen."""
        for entrada in self._entradas:
            if entrada.embedding is None:
                entrada.embedding = await proveedor.vectorizar(entrada.frase)

    async def buscar_exacto(self, texto_normalizado: str) -> EntradaIndice | None:
        for entrada in self._entradas:
            if entrada.frase_normalizada == texto_normalizado:
                return entrada
        return None

    async def mas_similar(self, vector: list[float]) -> Coincidencia | None:
        mejor: Coincidencia | None = None
        for entrada in self._entradas:
            if entrada.embedding is None:
                continue
            score = similitud_coseno(vector, entrada.embedding)
            if mejor is None or score > mejor.score:
                mejor = Coincidencia(entrada=entrada, score=score)
        return mejor


def indice_semilla() -> list[EntradaIndice]:
    """Set inicial minimo para probar el atajo. Se cura/amplia a mano -ver
    punto abierto 'como se puebla el indice' en el plano de origen."""
    return [
        EntradaIndice("hola", "Hola! En que te puedo ayudar?", "saludo"),
        EntradaIndice("buenas", "Buenas! En que te puedo ayudar?", "saludo"),
        EntradaIndice("buen dia", "Buen dia! En que te puedo ayudar?", "saludo"),
        EntradaIndice("gracias", "De nada!", "agradecimiento"),
        EntradaIndice("muchas gracias", "De nada, cualquier cosa avisame.", "agradecimiento"),
        EntradaIndice("chau", "Chau! Cualquier cosa aca estoy.", CATEGORIA_DESPEDIDA),
        EntradaIndice("adios", "Adios! Cualquier cosa aca estoy.", CATEGORIA_DESPEDIDA),
        EntradaIndice("hasta luego", "Hasta luego!", CATEGORIA_DESPEDIDA),
    ]

"""Implementacion de IndiceFrasesConocidas sobre Postgres + pgvector.

Mismo patron de arranque que almacenamiento/postgres.py, y por la misma
razon: el tipo `vector` no existe hasta que la extension se crea (via
``asegurar_schema()`` de almacenamiento/postgres.py, que carga TODO
db/schema.sql, tabla `frases_conocidas` incluida) -``crear()`` aca asume
que eso ya corrio antes, no lo hace de nuevo.

Distinto del indice de Memoria (``almacenamiento.RepositorioPostgres``):
esta es la tabla `frases_conocidas`, chica y curada a mano (ver
docs/aw1s/planos/0.1.0.2-atajo-semantico.md), no el historial dinamico de
conversaciones.
"""

from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

from .embeddings import EmbeddingsProvider
from .indice import Coincidencia, EntradaIndice, indice_semilla
from .normalizar import normalizar_texto


class IndiceFrasesConocidasPostgres:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def crear(cls, database_url: str) -> IndiceFrasesConocidasPostgres:
        """Requiere que la extension pgvector y la tabla `frases_conocidas`
        ya existan -llamar a
        ``aw1s.almacenamiento.postgres.asegurar_schema()`` antes, al menos
        una vez, en una base nueva (carga el schema entero, esta tabla
        incluida)."""

        async def _inicializar_conexion(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        pool = await asyncpg.create_pool(database_url, init=_inicializar_conexion)
        return cls(pool)

    async def cerrar(self) -> None:
        await self._pool.close()

    async def buscar_exacto(self, texto_normalizado: str) -> EntradaIndice | None:
        row = await self._pool.fetchrow(
            "SELECT frase, respuesta, categoria FROM frases_conocidas "
            "WHERE frase_normalizada = $1",
            texto_normalizado,
        )
        if row is None:
            return None
        return EntradaIndice(row["frase"], row["respuesta"], row["categoria"])

    async def mas_similar(self, vector: list[float]) -> Coincidencia | None:
        row = await self._pool.fetchrow(
            """
            SELECT frase, respuesta, categoria, 1 - (embedding <=> $1) AS score
            FROM frases_conocidas
            ORDER BY embedding <=> $1
            LIMIT 1
            """,
            vector,
        )
        if row is None:
            return None
        entrada = EntradaIndice(row["frase"], row["respuesta"], row["categoria"])
        return Coincidencia(entrada=entrada, score=float(row["score"]))

    async def agregar(
        self, frase: str, respuesta: str, categoria: str, embedding: list[float]
    ) -> None:
        """Alta o actualizacion (por `frase_normalizada`) de una entrada del
        indice curado -- pensado para el panel/script que lo puebla, no
        para que lo llame el ciclo de atajo en si."""
        await self._pool.execute(
            """
            INSERT INTO frases_conocidas
                (frase, frase_normalizada, respuesta, categoria, embedding)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (frase_normalizada) DO UPDATE SET
                respuesta = EXCLUDED.respuesta,
                categoria = EXCLUDED.categoria,
                embedding = EXCLUDED.embedding
            """,
            frase,
            normalizar_texto(frase),
            respuesta,
            categoria,
            embedding,
        )


async def poblar_semilla(
    indice: IndiceFrasesConocidasPostgres, embeddings: EmbeddingsProvider
) -> None:
    """Carga (o actualiza) el set inicial de ``indice.indice_semilla()``.
    Idempotente -correrlo de nuevo actualiza en vez de duplicar filas."""
    for entrada in indice_semilla():
        vector = await embeddings.vectorizar(entrada.frase)
        await indice.agregar(entrada.frase, entrada.respuesta, entrada.categoria, vector)

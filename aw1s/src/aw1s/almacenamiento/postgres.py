"""Implementacion de RepositorioAlmacenamiento sobre Postgres + pgvector.

ADVERTENCIA: este archivo no se pudo probar contra un Postgres real en el
entorno donde se escribio (sin Docker/Postgres disponibles). La logica de
orquestacion (aw1s.atajo_semantico, y lo que se construya despues sobre
este protocolo) se prueba con RepositorioEnMemoria (tests/fakes.py) sin
tocar este archivo. Antes de usarlo en serio, correr
``python -m aw1s.scripts.verificar_schema`` contra un Postgres+pgvector
real (ver README) para confirmar que el SQL de aca es correcto.
"""

from __future__ import annotations

import json
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from .modelos import Contexto, Embedding, Evento, Interaccion, Memoria, Sesion, Usuario

SCHEMA_SQL = Path(__file__).parent.parent / "db" / "schema.sql"


class RepositorioPostgres:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def crear(cls, database_url: str) -> RepositorioPostgres:
        async def _inicializar_conexion(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        pool = await asyncpg.create_pool(database_url, init=_inicializar_conexion)
        return cls(pool)

    async def cerrar(self) -> None:
        await self._pool.close()

    async def cargar_schema(self) -> None:
        """Ejecuta db/schema.sql entero como un solo script (protocolo
        simple de asyncpg: sin parametros, admite multiples sentencias)."""
        await self._pool.execute(SCHEMA_SQL.read_text())

    # -- usuarios / sesiones --------------------------------------------------

    async def obtener_o_crear_usuario(self, identificador_externo: str | None) -> Usuario:
        if identificador_externo is None:
            row = await self._pool.fetchrow(
                "INSERT INTO usuarios DEFAULT VALUES "
                "RETURNING id, identificador_externo, creado_en"
            )
        else:
            row = await self._pool.fetchrow(
                """
                INSERT INTO usuarios (identificador_externo) VALUES ($1)
                ON CONFLICT (identificador_externo)
                    DO UPDATE SET identificador_externo = EXCLUDED.identificador_externo
                RETURNING id, identificador_externo, creado_en
                """,
                identificador_externo,
            )
        return Usuario(**row)

    async def abrir_sesion(self, usuario_id: int | None) -> Sesion:
        row = await self._pool.fetchrow(
            """
            INSERT INTO sesiones (usuario_id) VALUES ($1)
            RETURNING id, usuario_id, iniciada_en, ultima_actividad_en
            """,
            usuario_id,
        )
        return Sesion(**row)

    async def obtener_sesion(self, sesion_id: int) -> Sesion | None:
        row = await self._pool.fetchrow(
            "SELECT id, usuario_id, iniciada_en, ultima_actividad_en "
            "FROM sesiones WHERE id = $1",
            sesion_id,
        )
        return Sesion(**row) if row else None

    # -- interacciones / eventos ------------------------------------------------

    async def crear_interaccion(
        self, sesion_id: int, mensaje_usuario: str, metadata: dict, ip: str | None
    ) -> Interaccion:
        row = await self._pool.fetchrow(
            """
            WITH nueva AS (
                INSERT INTO interacciones (sesion_id, mensaje_usuario, metadata, ip)
                VALUES ($1, $2, $3::jsonb, $4)
                RETURNING id, sesion_id, mensaje_usuario, metadata, ip, creada_en
            ),
            _ AS (
                UPDATE sesiones SET ultima_actividad_en = now() WHERE id = $1
            )
            SELECT * FROM nueva
            """,
            sesion_id,
            mensaje_usuario,
            json.dumps(metadata),
            ip,
        )
        return _fila_a_interaccion(row)

    async def interacciones_recientes(self, sesion_id: int, limite: int = 10) -> list[Interaccion]:
        rows = await self._pool.fetch(
            """
            SELECT id, sesion_id, mensaje_usuario, metadata, ip, creada_en
            FROM interacciones
            WHERE sesion_id = $1
            ORDER BY creada_en DESC
            LIMIT $2
            """,
            sesion_id,
            limite,
        )
        return [_fila_a_interaccion(row) for row in rows]

    async def registrar_evento(
        self, tipo: str, detalle: dict, interaccion_id: int | None = None
    ) -> Evento:
        row = await self._pool.fetchrow(
            """
            INSERT INTO eventos (interaccion_id, tipo, detalle)
            VALUES ($1, $2, $3::jsonb)
            RETURNING id, interaccion_id, tipo, detalle, ocurrido_en
            """,
            interaccion_id,
            tipo,
            json.dumps(detalle),
        )
        return _fila_a_evento(row)

    # -- contexto / memoria / embedding -----------------------------------------

    async def guardar_contexto(self, interaccion_id: int, contenido: dict) -> Contexto:
        row = await self._pool.fetchrow(
            """
            INSERT INTO contextos (interaccion_id, contenido)
            VALUES ($1, $2::jsonb)
            RETURNING id, interaccion_id, contenido, creado_en
            """,
            interaccion_id,
            json.dumps(contenido),
        )
        return _fila_a_contexto(row)

    async def guardar_memoria(self, interaccion_id: int, contenido: str) -> Memoria:
        row = await self._pool.fetchrow(
            """
            INSERT INTO memorias (interaccion_id, contenido)
            VALUES ($1, $2)
            RETURNING id, interaccion_id, contenido, creada_en
            """,
            interaccion_id,
            contenido,
        )
        return Memoria(**row)

    async def guardar_embedding(
        self, memoria_id: int, vector: list[float], modelo: str
    ) -> Embedding:
        row = await self._pool.fetchrow(
            """
            INSERT INTO embeddings (memoria_id, vector, modelo)
            VALUES ($1, $2, $3)
            RETURNING id, memoria_id, modelo, creado_en
            """,
            memoria_id,
            vector,
            modelo,
        )
        return Embedding(**row)

    async def buscar_memorias_similares(
        self, vector: list[float], limite: int = 5
    ) -> list[tuple[Memoria, float]]:
        rows = await self._pool.fetch(
            """
            SELECT m.id, m.interaccion_id, m.contenido, m.creada_en,
                   1 - (e.vector <=> $1) AS score
            FROM embeddings e
            JOIN memorias m ON m.id = e.memoria_id
            ORDER BY e.vector <=> $1
            LIMIT $2
            """,
            vector,
            limite,
        )
        return [
            (
                Memoria(
                    id=row["id"],
                    interaccion_id=row["interaccion_id"],
                    contenido=row["contenido"],
                    creada_en=row["creada_en"],
                ),
                float(row["score"]),
            )
            for row in rows
        ]


def _jsonb(valor: object) -> dict:
    """asyncpg devuelve JSONB como texto crudo salvo que se registre un
    codec aparte -- se parsea aca en vez de agregar otra registracion."""
    return json.loads(valor) if isinstance(valor, str) else valor


def _fila_a_interaccion(row: asyncpg.Record) -> Interaccion:
    return Interaccion(
        id=row["id"],
        sesion_id=row["sesion_id"],
        mensaje_usuario=row["mensaje_usuario"],
        metadata=_jsonb(row["metadata"]),
        ip=row["ip"],
        creada_en=row["creada_en"],
    )


def _fila_a_evento(row: asyncpg.Record) -> Evento:
    return Evento(
        id=row["id"],
        interaccion_id=row["interaccion_id"],
        tipo=row["tipo"],
        detalle=_jsonb(row["detalle"]),
        ocurrido_en=row["ocurrido_en"],
    )


def _fila_a_contexto(row: asyncpg.Record) -> Contexto:
    return Contexto(
        id=row["id"],
        interaccion_id=row["interaccion_id"],
        contenido=_jsonb(row["contenido"]),
        creado_en=row["creado_en"],
    )

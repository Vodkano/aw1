"""Repositorio Postgres, mismo contrato publico que ``Repository`` (SQLite).

Se usa en la nube via ``AW1_DATABASE_URL=postgres://...``: un solo pool de
conexiones con asyncpg. La forma de las tablas es identica a ``schema.sql``
(fechas como TEXT ISO-8601, payloads como TEXT JSON) para poder reutilizar
tal cual las mismas funciones ``_iso``/``_parse``/``json.dumps`` que ya usa el
repositorio SQLite, en vez de mantener dos formatos de fecha distintos.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg

_SCHEMA = Path(__file__).with_name("schema_postgres.sql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rowcount(status: str) -> int:
    """asyncpg devuelve el resultado de INSERT/UPDATE/DELETE como texto: 'DELETE 3'."""
    parts = status.split()
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0


class PostgresRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)
        raw = _SCHEMA.read_text(encoding="utf-8")
        statements = [s.strip() for s in raw.split(";") if s.strip()]
        async with self._pool.acquire() as conn:
            for statement in statements:
                await conn.execute(statement)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def _conn(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Repositorio no conectado; llama a connect() primero.")
        return self._pool

    async def healthy(self) -> bool:
        try:
            await self._conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    # -- conversaciones -----------------------------------------------------
    async def ensure_conversation(self, conversation_id: str, title: str = "") -> None:
        now = _iso(utcnow())
        await self._conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (id) DO UPDATE SET updated_at = excluded.updated_at",
            conversation_id, title[:120], now, now,
        )

    async def add_message(
        self, conversation_id: str, role: str, content: str, source: str = "local"
    ) -> None:
        await self.ensure_conversation(conversation_id, content if role == "user" else "")
        await self._conn.execute(
            "INSERT INTO messages (conversation_id, role, content, source, created_at) "
            "VALUES ($1, $2, $3, $4, $5)",
            conversation_id, role, content, source, _iso(utcnow()),
        )

    async def history(self, conversation_id: str, turns: int = 10) -> list[dict[str, str]]:
        if turns <= 0:
            return []
        rows = await self._conn.fetch(
            "SELECT role, content FROM messages WHERE conversation_id = $1 "
            "ORDER BY id DESC LIMIT $2",
            conversation_id, turns * 2,
        )
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def conversations(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT c.id, c.title, c.updated_at, COUNT(m.id) AS total "
            "FROM conversations c "
            "LEFT JOIN messages m ON m.conversation_id = c.id "
            "GROUP BY c.id HAVING COUNT(m.id) > 0 ORDER BY c.updated_at DESC LIMIT $1",
            limit,
        )
        return [
            {
                "id": row["id"],
                "title": row["title"] or "Conversacion",
                "updated_at": _parse(row["updated_at"]),
                "messages": row["total"],
            }
            for row in rows
        ]

    async def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT role, content, source, created_at FROM messages "
            "WHERE conversation_id = $1 ORDER BY id",
            conversation_id,
        )
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "source": row["source"],
                "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

    async def delete_conversation(self, conversation_id: str) -> int:
        status = await self._conn.execute(
            "DELETE FROM conversations WHERE id = $1", conversation_id
        )
        return _rowcount(status)

    # -- razonamiento interno ------------------------------------------------
    async def save_reasoning(
        self, conversation_id: str | None, kind: str, source_input: str, payload: Any
    ) -> int:
        if conversation_id:
            await self.ensure_conversation(conversation_id)
        row_id = await self._conn.fetchval(
            "INSERT INTO reasoning (conversation_id, kind, input, payload, created_at) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            conversation_id,
            kind,
            source_input[:2000],
            json.dumps(payload, ensure_ascii=False, default=str),
            _iso(utcnow()),
        )
        return int(row_id or 0)

    async def get_reasoning(self, reasoning_id: int) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT kind, input, payload FROM reasoning WHERE id = $1", reasoning_id
        )
        if row is None:
            return None
        return {"kind": row["kind"], "input": row["input"], "payload": json.loads(row["payload"])}

    # -- guardados ------------------------------------------------------------
    async def save_item(
        self,
        text: str,
        source: str = "local",
        kind: str = "note",
        meta: dict[str, Any] | None = None,
        *,
        max_items: int = 500,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._conn.acquire() as conn, conn.transaction():
            item_id = await conn.fetchval(
                "INSERT INTO saved_items (text, source, kind, meta, created_at) "
                "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                text, source, kind, json.dumps(meta or {}, ensure_ascii=False), _iso(now),
            )
            await conn.execute(
                "DELETE FROM saved_items WHERE id NOT IN "
                "(SELECT id FROM saved_items ORDER BY id DESC LIMIT $1)",
                max_items,
            )
        return {
            "id": int(item_id or 0), "text": text, "source": source, "kind": kind,
            "meta": meta or {}, "created_at": now,
        }

    async def list_items(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT id, text, source, kind, meta, created_at FROM saved_items "
            "ORDER BY id DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
        return [
            {
                "id": row["id"], "text": row["text"], "source": row["source"],
                "kind": row["kind"], "meta": json.loads(row["meta"]),
                "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

    async def count_items(self) -> int:
        return int(await self._conn.fetchval("SELECT COUNT(*) FROM saved_items") or 0)

    async def delete_item(self, item_id: int) -> bool:
        status = await self._conn.execute("DELETE FROM saved_items WHERE id = $1", item_id)
        return _rowcount(status) > 0

    # -- historial de busquedas ------------------------------------------------
    async def save_search(self, query: str, payload: Any) -> int:
        async with self._conn.acquire() as conn, conn.transaction():
            row_id = await conn.fetchval(
                "INSERT INTO searches (query, payload, created_at) VALUES ($1, $2, $3) "
                "RETURNING id",
                query, json.dumps(payload, ensure_ascii=False, default=str), _iso(utcnow()),
            )
            await conn.execute(
                "DELETE FROM searches WHERE id NOT IN "
                "(SELECT id FROM searches ORDER BY id DESC LIMIT 100)"
            )
        return int(row_id or 0)

    async def recent_searches(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT id, query, created_at FROM searches ORDER BY id DESC LIMIT $1", limit
        )
        return [
            {"id": row["id"], "query": row["query"], "created_at": _parse(row["created_at"])}
            for row in rows
        ]

    # -- cache ------------------------------------------------------------------
    async def cache_get(self, key: str) -> Any | None:
        row = await self._conn.fetchrow(
            "SELECT payload, expires_at FROM cache WHERE key = $1", key
        )
        if row is None:
            return None
        if _parse(row["expires_at"]) <= utcnow():
            await self._conn.execute("DELETE FROM cache WHERE key = $1", key)
            return None
        return json.loads(row["payload"])

    async def cache_set(self, key: str, payload: Any, ttl: int) -> None:
        if ttl <= 0:
            return
        await self._conn.execute(
            "INSERT INTO cache (key, payload, expires_at) VALUES ($1, $2, $3) "
            "ON CONFLICT (key) DO UPDATE SET payload = excluded.payload, "
            "expires_at = excluded.expires_at",
            key,
            json.dumps(payload, ensure_ascii=False, default=str),
            _iso(utcnow() + timedelta(seconds=ttl)),
        )

    # -- borrado total ------------------------------------------------------------
    async def purge(self, tables: Sequence[str] | None = None) -> dict[str, int]:
        allowed = ("messages", "reasoning", "saved_items", "searches", "conversations", "cache")
        targets = [table for table in (tables or allowed) if table in allowed]
        removed: dict[str, int] = {}
        async with self._conn.acquire() as conn, conn.transaction():
            for table in targets:
                status = await conn.execute(f"DELETE FROM {table}")  # noqa: S608
                removed[table] = _rowcount(status)
        return removed

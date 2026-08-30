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


def _item_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "text": row["text"], "source": row["source"],
        "kind": row["kind"], "meta": json.loads(row["meta"]),
        "created_at": _parse(row["created_at"]),
    }


def _telegram_agent_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "label": row["label"], "system_prompt": row["system_prompt"],
        "personality": row["personality"], "enabled": bool(row["enabled"]),
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _telegram_token_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"], "bot_token": row["bot_token"],
        "bot_token_hash": row["bot_token_hash"], "bot_username": row["bot_username"],
        "webhook_secret": row["webhook_secret"], "enabled": bool(row["enabled"]),
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _agent_file_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"], "filename": row["filename"],
        "content": row["content"], "char_count": row["char_count"],
        "created_at": _parse(row["created_at"]),
    }


def _agent_api_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"], "name": row["name"],
        "description": row["description"], "url": row["url"], "method": row["method"],
        "headers": json.loads(row["headers"]), "enabled": bool(row["enabled"]),
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _generated_tool_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"],
        "source_gap_reasoning_id": row["source_gap_reasoning_id"],
        "name": row["name"], "description": row["description"], "status": row["status"],
        "spec": json.loads(row["spec"]), "code": row["code"], "test_code": row["test_code"],
        "sandbox_result": json.loads(row["sandbox_result"]), "reject_reason": row["reject_reason"],
        "call_count": row["call_count"],
        "last_called_at": _parse(row["last_called_at"]) if row["last_called_at"] else None,
        "last_error": row["last_error"],
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _price_watch_from_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"], "token_id": row["token_id"], "chat_id": row["chat_id"],
        "product_label": row["product_label"], "urls": json.loads(row["urls"]),
        "last_price_clp": row["last_price_clp"], "last_best_url": row["last_best_url"],
        "last_checked_at": _parse(row["last_checked_at"]) if row["last_checked_at"] else None,
        "enabled": bool(row["enabled"]), "created_at": _parse(row["created_at"]),
    }


def _escape_like(value: str) -> str:
    """Ver repository.py:_escape_like -mismo motivo, misma logica."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PostgresRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)
        raw = _SCHEMA.read_text(encoding="utf-8")
        # Las lineas de comentario ("-- ...") se sacan ANTES de partir por
        # ";": un comentario en prosa normal casi siempre necesita alguna
        # coma o punto y coma, y un ";" suelto ahi corta el statement a la
        # mitad -paso real, tumbo el arranque en produccion una vez. Solo
        # hay comentarios de linea completa en este archivo (nunca al final
        # de una linea de SQL), asi que sacar la linea entera es seguro.
        without_comments = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("--")
        )
        statements = [s.strip() for s in without_comments.split(";") if s.strip()]
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

    async def history_since(
        self, conversation_id: str, since_iso: str, max_messages: int = 60
    ) -> list[dict[str, str]]:
        """Ver Repository.history_since (db/repository.py): mismo contrato."""
        if max_messages <= 0:
            return []
        rows = await self._conn.fetch(
            "SELECT role, content FROM messages WHERE conversation_id = $1 AND created_at >= $2 "
            "ORDER BY id DESC LIMIT $3",
            conversation_id, since_iso, max_messages,
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

    async def list_reasoning_by_kind(self, kind: str, limit: int = 200) -> list[dict[str, Any]]:
        """Ver repository.py:list_reasoning_by_kind -mismo motivo, misma logica."""
        rows = await self._conn.fetch(
            "SELECT id, conversation_id, kind, input, payload, created_at FROM reasoning "
            "WHERE kind = $1 ORDER BY id DESC LIMIT $2",
            kind, limit,
        )
        return [
            {
                "id": row["id"], "conversation_id": row["conversation_id"], "kind": row["kind"],
                "input": row["input"], "payload": json.loads(row["payload"]),
                "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

    # -- trazas de ejecucion ---------------------------------------------------
    async def save_execution_trace(
        self,
        trace_id: str,
        source: str,
        provider: str = "",
        model: str = "",
        tools_called: list[str] | None = None,
        status: str = "ok",
        latency_ms: int = 0,
        cost_estimate: float = 0.0,
        error: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        row_id = await self._conn.fetchval(
            "INSERT INTO execution_traces "
            "(trace_id, source, provider, model, tools_called, status, "
            " latency_ms, cost_estimate, error, meta, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id",
            trace_id,
            source,
            provider,
            model,
            json.dumps(tools_called or [], ensure_ascii=False),
            status,
            latency_ms,
            cost_estimate,
            error,
            json.dumps(meta or {}, ensure_ascii=False, default=str),
            _iso(utcnow()),
        )
        return int(row_id or 0)

    async def list_execution_traces(
        self, source: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if source:
            rows = await self._conn.fetch(
                "SELECT * FROM execution_traces WHERE source = $1 ORDER BY id DESC LIMIT $2",
                source, limit,
            )
        else:
            rows = await self._conn.fetch(
                "SELECT * FROM execution_traces ORDER BY id DESC LIMIT $1", limit
            )
        return [
            {
                "id": row["id"], "trace_id": row["trace_id"], "source": row["source"],
                "provider": row["provider"], "model": row["model"],
                "tools_called": json.loads(row["tools_called"]),
                "status": row["status"], "latency_ms": row["latency_ms"],
                "cost_estimate": row["cost_estimate"], "error": row["error"],
                "meta": json.loads(row["meta"]), "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

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
        return [_item_from_row(row) for row in rows]

    async def search_items(self, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
        """Ver Repository.search_items (db/repository.py): misma logica, LIKE
        con LOWER() forzado de los dos lados para que se comporte igual que en
        SQLite (Postgres no es case-insensitive por defecto)."""
        if not keywords:
            return []
        clauses = " OR ".join(
            f"LOWER(text) LIKE ${index + 1} ESCAPE '\\'" for index in range(len(keywords))
        )
        params = [f"%{_escape_like(keyword)}%" for keyword in keywords]
        rows = await self._conn.fetch(
            f"SELECT id, text, source, kind, meta, created_at FROM saved_items "  # noqa: S608
            f"WHERE {clauses} ORDER BY id DESC LIMIT ${len(keywords) + 1}",
            *params, limit,
        )
        return [_item_from_row(row) for row in rows]

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

    # -- panel admin: secretos --------------------------------------------------
    async def all_secrets(self) -> dict[str, str]:
        rows = await self._conn.fetch("SELECT key, value FROM secrets")
        return {row["key"]: row["value"] for row in rows}

    async def set_secret(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO secrets (key, value, updated_at) VALUES ($1, $2, $3) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            key, value, _iso(utcnow()),
        )

    async def delete_secret(self, key: str) -> None:
        await self._conn.execute("DELETE FROM secrets WHERE key = $1", key)

    # -- panel admin: claves de api ----------------------------------------------
    async def create_api_key(self, label: str, key_hash: str, key_preview: str) -> dict[str, Any]:
        now = utcnow()
        key_id = await self._conn.fetchval(
            "INSERT INTO api_keys (label, key_hash, key_preview, created_at) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            label, key_hash, key_preview, _iso(now),
        )
        return {
            "id": int(key_id or 0), "label": label,
            "key_preview": key_preview, "created_at": now,
        }

    async def list_api_keys(self) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT id, label, key_hash, key_preview, created_at FROM api_keys ORDER BY id DESC"
        )
        return [
            {
                "id": row["id"], "label": row["label"], "key_hash": row["key_hash"],
                "key_preview": row["key_preview"], "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

    async def get_api_key(self, key_id: int) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, label, key_hash, key_preview FROM api_keys WHERE id = $1", key_id
        )
        if row is None:
            return None
        return {
            "id": row["id"], "label": row["label"],
            "key_hash": row["key_hash"], "key_preview": row["key_preview"],
        }

    async def delete_api_key(self, key_id: int) -> bool:
        status = await self._conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)
        return _rowcount(status) > 0

    # -- panel admin: agentes de telegram (el "cerebro": prompt, personalidad) --
    async def create_telegram_agent(
        self, agent_id: str, label: str, system_prompt: str, personality: str,
    ) -> dict[str, Any]:
        now = utcnow()
        await self._conn.execute(
            "INSERT INTO telegram_agents (id, label, system_prompt, personality, enabled, "
            "created_at, updated_at) VALUES ($1, $2, $3, $4, 1, $5, $5)",
            agent_id, label, system_prompt, personality, _iso(now),
        )
        return {
            "id": agent_id, "label": label, "system_prompt": system_prompt,
            "personality": personality, "enabled": True, "created_at": now, "updated_at": now,
        }

    async def list_telegram_agents(self) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT id, label, system_prompt, personality, enabled, created_at, updated_at "
            "FROM telegram_agents ORDER BY created_at DESC"
        )
        return [_telegram_agent_from_row(row) for row in rows]

    async def get_telegram_agent(self, agent_id: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, label, system_prompt, personality, enabled, created_at, updated_at "
            "FROM telegram_agents WHERE id = $1",
            agent_id,
        )
        return _telegram_agent_from_row(row) if row else None

    async def update_telegram_agent(
        self, agent_id: str, *, label: str, system_prompt: str, enabled: bool,
    ) -> dict[str, Any] | None:
        now = utcnow()
        status = await self._conn.execute(
            "UPDATE telegram_agents SET label = $1, system_prompt = $2, enabled = $3, "
            "updated_at = $4 WHERE id = $5",
            label, system_prompt, int(enabled), _iso(now), agent_id,
        )
        if _rowcount(status) == 0:
            return None
        return await self.get_telegram_agent(agent_id)

    async def delete_telegram_agent(self, agent_id: str) -> bool:
        status = await self._conn.execute("DELETE FROM telegram_agents WHERE id = $1", agent_id)
        return _rowcount(status) > 0

    # -- panel admin: tokens de telegram (un bot de BotFather, de un agente) ----
    async def create_telegram_token(
        self, token_id: str, agent_id: str, bot_token: str, bot_token_hash: str,
        bot_username: str, webhook_secret: str,
    ) -> dict[str, Any]:
        now = utcnow()
        await self._conn.execute(
            "INSERT INTO telegram_tokens (id, agent_id, bot_token, bot_token_hash, "
            "bot_username, webhook_secret, enabled, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, 1, $7, $7)",
            token_id, agent_id, bot_token, bot_token_hash, bot_username,
            webhook_secret, _iso(now),
        )
        return {
            "id": token_id, "agent_id": agent_id, "bot_token": bot_token,
            "bot_token_hash": bot_token_hash, "bot_username": bot_username,
            "webhook_secret": webhook_secret, "enabled": True,
            "created_at": now, "updated_at": now,
        }

    async def list_telegram_tokens(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        if agent_id is not None:
            rows = await self._conn.fetch(
                "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, "
                "webhook_secret, enabled, created_at, updated_at FROM telegram_tokens "
                "WHERE agent_id = $1 ORDER BY created_at DESC",
                agent_id,
            )
        else:
            rows = await self._conn.fetch(
                "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, "
                "webhook_secret, enabled, created_at, updated_at FROM telegram_tokens "
                "ORDER BY created_at DESC"
            )
        return [_telegram_token_from_row(row) for row in rows]

    async def get_telegram_token(self, token_id: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "enabled, created_at, updated_at FROM telegram_tokens WHERE id = $1",
            token_id,
        )
        return _telegram_token_from_row(row) if row else None

    async def get_telegram_token_by_hash(self, bot_token_hash: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "enabled, created_at, updated_at FROM telegram_tokens WHERE bot_token_hash = $1",
            bot_token_hash,
        )
        return _telegram_token_from_row(row) if row else None

    async def set_telegram_token_enabled(
        self, token_id: str, enabled: bool
    ) -> dict[str, Any] | None:
        now = utcnow()
        status = await self._conn.execute(
            "UPDATE telegram_tokens SET enabled = $1, updated_at = $2 WHERE id = $3",
            int(enabled), _iso(now), token_id,
        )
        if _rowcount(status) == 0:
            return None
        return await self.get_telegram_token(token_id)

    async def delete_telegram_token(self, token_id: str) -> bool:
        status = await self._conn.execute("DELETE FROM telegram_tokens WHERE id = $1", token_id)
        return _rowcount(status) > 0

    # -- seguimiento de precios (bots de Telegram) -----------------------------
    async def create_price_watch(
        self, watch_id: str, token_id: str, chat_id: str, product_label: str,
        urls: list[str],
    ) -> dict[str, Any]:
        now = utcnow()
        await self._conn.execute(
            "INSERT INTO price_watches (id, token_id, chat_id, product_label, urls, "
            "enabled, created_at) VALUES ($1, $2, $3, $4, $5, 1, $6)",
            watch_id, token_id, chat_id, product_label,
            json.dumps(urls, ensure_ascii=False), _iso(now),
        )
        return {
            "id": watch_id, "token_id": token_id, "chat_id": chat_id,
            "product_label": product_label, "urls": urls, "last_price_clp": None,
            "last_best_url": None, "last_checked_at": None, "enabled": True,
            "created_at": now,
        }

    async def list_price_watches(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        query = (
            "SELECT id, token_id, chat_id, product_label, urls, last_price_clp, "
            "last_best_url, last_checked_at, enabled, created_at FROM price_watches"
        )
        if enabled_only:
            query += " WHERE enabled = 1"
        rows = await self._conn.fetch(query)
        return [_price_watch_from_row(row) for row in rows]

    async def update_price_watch_result(
        self, watch_id: str, price_clp: float, best_url: str
    ) -> None:
        await self._conn.execute(
            "UPDATE price_watches SET last_price_clp = $1, last_best_url = $2, "
            "last_checked_at = $3 WHERE id = $4",
            price_clp, best_url, _iso(utcnow()), watch_id,
        )

    async def delete_price_watch(self, watch_id: str) -> bool:
        status = await self._conn.execute("DELETE FROM price_watches WHERE id = $1", watch_id)
        return _rowcount(status) > 0

    # -- corte de conversacion (bots de Telegram) --------------------------------
    async def mute_telegram_chat(
        self, token_id: str, chat_id: str, reason: str, until_iso: str
    ) -> None:
        await self._conn.execute(
            "INSERT INTO telegram_mutes (token_id, chat_id, reason, muted_until, created_at) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (token_id, chat_id) DO UPDATE SET reason = excluded.reason, "
            "muted_until = excluded.muted_until",
            token_id, chat_id, reason, until_iso, _iso(utcnow()),
        )

    async def get_telegram_mute(self, token_id: str, chat_id: str) -> dict[str, Any] | None:
        """Ver Repository.get_telegram_mute (db/repository.py): mismo contrato."""
        row = await self._conn.fetchrow(
            "SELECT reason, muted_until FROM telegram_mutes "
            "WHERE token_id = $1 AND chat_id = $2 AND muted_until > $3",
            token_id, chat_id, _iso(utcnow()),
        )
        if row is None:
            return None
        return {"reason": row["reason"], "muted_until": _parse(row["muted_until"])}

    # -- archivos que un agente conoce de memoria ------------------------------
    async def create_telegram_agent_file(
        self, file_id: str, agent_id: str, filename: str, content: str, char_count: int
    ) -> dict[str, Any]:
        now = utcnow()
        await self._conn.execute(
            "INSERT INTO telegram_agent_files (id, agent_id, filename, content, "
            "char_count, created_at) VALUES ($1, $2, $3, $4, $5, $6)",
            file_id, agent_id, filename, content, char_count, _iso(now),
        )
        return {
            "id": file_id, "agent_id": agent_id, "filename": filename, "content": content,
            "char_count": char_count, "created_at": now,
        }

    async def list_telegram_agent_files(self, agent_id: str) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT id, agent_id, filename, content, char_count, created_at "
            "FROM telegram_agent_files WHERE agent_id = $1 ORDER BY created_at",
            agent_id,
        )
        return [_agent_file_from_row(row) for row in rows]

    async def get_telegram_agent_file(self, file_id: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, agent_id, filename, content, char_count, created_at "
            "FROM telegram_agent_files WHERE id = $1",
            file_id,
        )
        return _agent_file_from_row(row) if row else None

    async def delete_telegram_agent_file(self, file_id: str) -> bool:
        status = await self._conn.execute(
            "DELETE FROM telegram_agent_files WHERE id = $1", file_id
        )
        return _rowcount(status) > 0

    # -- APIs externas que un agente puede invocar en vivo ---------------------
    async def create_telegram_agent_api(
        self, api_id: str, agent_id: str, name: str, description: str, url: str,
        method: str, headers_json: str,
    ) -> dict[str, Any]:
        now = utcnow()
        await self._conn.execute(
            "INSERT INTO telegram_agent_apis (id, agent_id, name, description, url, "
            "method, headers, enabled, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, 1, $8, $8)",
            api_id, agent_id, name, description, url, method, headers_json, _iso(now),
        )
        return {
            "id": api_id, "agent_id": agent_id, "name": name, "description": description,
            "url": url, "method": method, "headers": json.loads(headers_json),
            "enabled": True, "created_at": now, "updated_at": now,
        }

    async def list_telegram_agent_apis(self, agent_id: str) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(
            "SELECT id, agent_id, name, description, url, method, headers, enabled, "
            "created_at, updated_at FROM telegram_agent_apis "
            "WHERE agent_id = $1 ORDER BY created_at",
            agent_id,
        )
        return [_agent_api_from_row(row) for row in rows]

    async def get_telegram_agent_api(self, api_id: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, agent_id, name, description, url, method, headers, enabled, "
            "created_at, updated_at FROM telegram_agent_apis WHERE id = $1",
            api_id,
        )
        return _agent_api_from_row(row) if row else None

    async def set_telegram_agent_api_enabled(
        self, api_id: str, enabled: bool
    ) -> dict[str, Any] | None:
        now = utcnow()
        status = await self._conn.execute(
            "UPDATE telegram_agent_apis SET enabled = $1, updated_at = $2 WHERE id = $3",
            int(enabled), _iso(now), api_id,
        )
        if _rowcount(status) == 0:
            return None
        return await self.get_telegram_agent_api(api_id)

    async def delete_telegram_agent_api(self, api_id: str) -> bool:
        status = await self._conn.execute(
            "DELETE FROM telegram_agent_apis WHERE id = $1", api_id
        )
        return _rowcount(status) > 0

    # -- herramientas generadas por IA a partir de un hueco detectado ----------
    async def create_generated_tool(
        self, tool_id: str, agent_id: str, name: str, description: str,
        source_gap_reasoning_id: int | None,
    ) -> dict[str, Any]:
        now = utcnow()
        await self._conn.execute(
            "INSERT INTO generated_tools (id, agent_id, source_gap_reasoning_id, name, "
            "description, status, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, 'PROPOSED', $6, $6)",
            tool_id, agent_id, source_gap_reasoning_id, name, description, _iso(now),
        )
        return {
            "id": tool_id, "agent_id": agent_id, "source_gap_reasoning_id": source_gap_reasoning_id,
            "name": name, "description": description, "status": "PROPOSED",
            "spec": {}, "code": "", "test_code": "", "sandbox_result": {}, "reject_reason": "",
            "call_count": 0, "last_called_at": None, "last_error": "",
            "created_at": now, "updated_at": now,
        }

    async def list_generated_tools(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        columns = (
            "id, agent_id, source_gap_reasoning_id, name, description, status, spec, code, "
            "test_code, sandbox_result, reject_reason, call_count, last_called_at, "
            "last_error, created_at, updated_at"
        )
        if agent_id is None:
            rows = await self._conn.fetch(
                f"SELECT {columns} FROM generated_tools ORDER BY created_at DESC"  # noqa: S608
            )
        else:
            rows = await self._conn.fetch(
                f"SELECT {columns} FROM generated_tools WHERE agent_id = $1 "  # noqa: S608
                "ORDER BY created_at DESC",
                agent_id,
            )
        return [_generated_tool_from_row(row) for row in rows]

    async def get_generated_tool(self, tool_id: str) -> dict[str, Any] | None:
        row = await self._conn.fetchrow(
            "SELECT id, agent_id, source_gap_reasoning_id, name, description, status, spec, "
            "code, test_code, sandbox_result, reject_reason, call_count, last_called_at, "
            "last_error, created_at, updated_at FROM generated_tools WHERE id = $1",
            tool_id,
        )
        return _generated_tool_from_row(row) if row else None

    async def set_generated_tool_generated(
        self, tool_id: str, spec_json: str, code: str, test_code: str
    ) -> dict[str, Any] | None:
        status = await self._conn.execute(
            "UPDATE generated_tools SET spec = $1, code = $2, test_code = $3, "
            "status = 'GENERATING', updated_at = $4 WHERE id = $5",
            spec_json, code, test_code, _iso(utcnow()), tool_id,
        )
        if _rowcount(status) == 0:
            return None
        return await self.get_generated_tool(tool_id)

    async def set_generated_tool_tested(
        self, tool_id: str, sandbox_result_json: str, *, passed: bool, reject_reason: str = ""
    ) -> dict[str, Any] | None:
        new_status = "PENDING_APPROVAL" if passed else "REJECTED"
        status = await self._conn.execute(
            "UPDATE generated_tools SET sandbox_result = $1, status = $2, "
            "reject_reason = $3, updated_at = $4 WHERE id = $5",
            sandbox_result_json, new_status, reject_reason, _iso(utcnow()), tool_id,
        )
        if _rowcount(status) == 0:
            return None
        return await self.get_generated_tool(tool_id)

    async def set_generated_tool_status(
        self, tool_id: str, status: str, reject_reason: str = ""
    ) -> dict[str, Any] | None:
        result = await self._conn.execute(
            "UPDATE generated_tools SET status = $1, reject_reason = $2, updated_at = $3 "
            "WHERE id = $4",
            status, reject_reason, _iso(utcnow()), tool_id,
        )
        if _rowcount(result) == 0:
            return None
        return await self.get_generated_tool(tool_id)

    async def record_generated_tool_call(self, tool_id: str, *, ok: bool, error: str) -> None:
        await self._conn.execute(
            "UPDATE generated_tools SET call_count = call_count + 1, last_called_at = $1, "
            "last_error = $2 WHERE id = $3",
            _iso(utcnow()), "" if ok else error[:500], tool_id,
        )

    async def delete_generated_tool(self, tool_id: str) -> bool:
        status = await self._conn.execute(
            "DELETE FROM generated_tools WHERE id = $1", tool_id
        )
        return _rowcount(status) > 0

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

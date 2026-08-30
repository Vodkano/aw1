"""Repositorio SQLite asincrono.

Una sola conexion en modo WAL, protegida por un lock: SQLite serializa las
escrituras de todos modos y asi se evita el error "database is locked" cuando el
pipeline de precios escribe mientras el chat lee.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA = Path(__file__).with_name("schema.sql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _item_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "text": row["text"], "source": row["source"],
        "kind": row["kind"], "meta": json.loads(row["meta"]),
        "created_at": _parse(row["created_at"]),
    }


def _telegram_agent_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "label": row["label"], "system_prompt": row["system_prompt"],
        "personality": row["personality"], "enabled": bool(row["enabled"]),
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _telegram_token_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"], "bot_token": row["bot_token"],
        "bot_token_hash": row["bot_token_hash"], "bot_username": row["bot_username"],
        "webhook_secret": row["webhook_secret"], "enabled": bool(row["enabled"]),
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _agent_file_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"], "filename": row["filename"],
        "content": row["content"], "char_count": row["char_count"],
        "created_at": _parse(row["created_at"]),
    }


def _agent_api_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "agent_id": row["agent_id"], "name": row["name"],
        "description": row["description"], "url": row["url"], "method": row["method"],
        "headers": json.loads(row["headers"]), "enabled": bool(row["enabled"]),
        "created_at": _parse(row["created_at"]), "updated_at": _parse(row["updated_at"]),
    }


def _generated_tool_from_row(row: aiosqlite.Row) -> dict[str, Any]:
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


def _price_watch_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "token_id": row["token_id"], "chat_id": row["chat_id"],
        "product_label": row["product_label"], "urls": json.loads(row["urls"]),
        "last_price_clp": row["last_price_clp"], "last_best_url": row["last_best_url"],
        "last_checked_at": _parse(row["last_checked_at"]) if row["last_checked_at"] else None,
        "enabled": bool(row["enabled"]), "created_at": _parse(row["created_at"]),
    }


def _escape_like(value: str) -> str:
    """Escapa los comodines de LIKE (%, _) para que un keyword literal no se
    interprete como patron -si no, una palabra con guion bajo (ej. de un
    modelo "rtx_4090") matchearia de mas ("rtxA4090" tambien calzaria)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Repository:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._db is not None:
            return
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA.read_text(encoding="utf-8"))
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Repositorio no conectado; llama a connect() primero.")
        return self._db

    async def healthy(self) -> bool:
        try:
            await self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    # -- conversaciones -----------------------------------------------------
    async def ensure_conversation(self, conversation_id: str, title: str = "") -> None:
        now = _iso(utcnow())
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at",
                (conversation_id, title[:120], now, now),
            )
            await self._conn.commit()

    async def add_message(
        self, conversation_id: str, role: str, content: str, source: str = "local"
    ) -> None:
        await self.ensure_conversation(conversation_id, content if role == "user" else "")
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO messages (conversation_id, role, content, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, source, _iso(utcnow())),
            )
            await self._conn.commit()

    async def history(self, conversation_id: str, turns: int = 10) -> list[dict[str, str]]:
        if turns <= 0:
            return []
        cursor = await self._conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, turns * 2),
        )
        rows = list(await cursor.fetchall())
        await cursor.close()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def history_since(
        self, conversation_id: str, since_iso: str, max_messages: int = 60
    ) -> list[dict[str, str]]:
        """Igual que history(), pero por ventana de tiempo en vez de turnos
        -lo usan los agentes de Telegram (memoria de 48h). max_messages es un
        tope duro ademas del tiempo, para no mandarle al modelo un historial
        gigante si alguien chateo sin parar durante toda la ventana."""
        if max_messages <= 0:
            return []
        cursor = await self._conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? AND created_at >= ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, since_iso, max_messages),
        )
        rows = list(await cursor.fetchall())
        await cursor.close()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def conversations(self, limit: int = 30) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT c.id, c.title, c.updated_at, COUNT(m.id) AS total "
            "FROM conversations c "
            "LEFT JOIN messages m ON m.conversation_id = c.id "
            "GROUP BY c.id HAVING total > 0 ORDER BY c.updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
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
        cursor = await self._conn.execute(
            "SELECT role, content, source, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
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
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            await self._conn.commit()
            return cursor.rowcount or 0

    # -- razonamiento interno ----------------------------------------------
    async def save_reasoning(
        self, conversation_id: str | None, kind: str, source_input: str, payload: Any
    ) -> int:
        # La fila referencia a conversations: si la conversacion aun no existe
        # (primer mensaje), se crea antes para no violar la clave foranea.
        if conversation_id:
            await self.ensure_conversation(conversation_id)
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT INTO reasoning (conversation_id, kind, input, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    kind,
                    source_input[:2000],
                    json.dumps(payload, ensure_ascii=False, default=str),
                    _iso(utcnow()),
                ),
            )
            await self._conn.commit()
            return int(cursor.lastrowid or 0)

    async def get_reasoning(self, reasoning_id: int) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT kind, input, payload FROM reasoning WHERE id = ?", (reasoning_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {"kind": row["kind"], "input": row["input"], "payload": json.loads(row["payload"])}

    async def list_reasoning_by_kind(self, kind: str, limit: int = 200) -> list[dict[str, Any]]:
        """Usado para listar los pedidos de capacidad detectados (kind=
        "capability_gap") en el panel admin -reasoning ya existe, no hace
        falta una tabla nueva para esto."""
        cursor = await self._conn.execute(
            "SELECT id, conversation_id, kind, input, payload, created_at FROM reasoning "
            "WHERE kind = ? ORDER BY id DESC LIMIT ?",
            (kind, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": row["id"], "conversation_id": row["conversation_id"], "kind": row["kind"],
                "input": row["input"], "payload": json.loads(row["payload"]),
                "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

    # -- trazas de ejecucion --------------------------------------------------
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
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT INTO execution_traces "
                "(trace_id, source, provider, model, tools_called, status, "
                " latency_ms, cost_estimate, error, meta, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
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
                ),
            )
            await self._conn.commit()
            return int(cursor.lastrowid or 0)

    async def list_execution_traces(
        self, source: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if source:
            cursor = await self._conn.execute(
                "SELECT * FROM execution_traces WHERE source = ? ORDER BY id DESC LIMIT ?",
                (source, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM execution_traces ORDER BY id DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        await cursor.close()
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

    # -- guardados ----------------------------------------------------------
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
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT INTO saved_items (text, source, kind, meta, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (text, source, kind, json.dumps(meta or {}, ensure_ascii=False), _iso(now)),
            )
            item_id = int(cursor.lastrowid or 0)
            await self._conn.execute(
                "DELETE FROM saved_items WHERE id NOT IN "
                "(SELECT id FROM saved_items ORDER BY id DESC LIMIT ?)",
                (max_items,),
            )
            await self._conn.commit()
        return {
            "id": item_id, "text": text, "source": source, "kind": kind,
            "meta": meta or {}, "created_at": now,
        }

    async def list_items(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, text, source, kind, meta, created_at FROM saved_items "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_item_from_row(row) for row in rows]

    async def search_items(self, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
        """Coincidencia simple por palabras clave, sin busqueda semantica -de
        sobra para el volumen esperado (max_saved_items, 500 por defecto).
        Los keywords deben venir ya en minuscula: LIKE es case-insensitive
        para ASCII en SQLite pero NO en Postgres, asi que se fuerza LOWER()
        de los dos lados en ambos repositorios para que se comporten igual.
        """
        if not keywords:
            return []
        clauses = " OR ".join(["LOWER(text) LIKE ? ESCAPE '\\'"] * len(keywords))
        params = [f"%{_escape_like(keyword)}%" for keyword in keywords]
        cursor = await self._conn.execute(
            f"SELECT id, text, source, kind, meta, created_at FROM saved_items "  # noqa: S608
            f"WHERE {clauses} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_item_from_row(row) for row in rows]

    async def count_items(self) -> int:
        cursor = await self._conn.execute("SELECT COUNT(*) AS total FROM saved_items")
        row = await cursor.fetchone()
        await cursor.close()
        return int(row["total"]) if row else 0

    async def delete_item(self, item_id: int) -> bool:
        async with self._lock:
            cursor = await self._conn.execute("DELETE FROM saved_items WHERE id = ?", (item_id,))
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- historial de busquedas --------------------------------------------
    async def save_search(self, query: str, payload: Any) -> int:
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT INTO searches (query, payload, created_at) VALUES (?, ?, ?)",
                (query, json.dumps(payload, ensure_ascii=False, default=str), _iso(utcnow())),
            )
            await self._conn.execute(
                "DELETE FROM searches WHERE id NOT IN "
                "(SELECT id FROM searches ORDER BY id DESC LIMIT 100)"
            )
            await self._conn.commit()
            return int(cursor.lastrowid or 0)

    async def recent_searches(self, limit: int = 10) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, query, created_at FROM searches ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {"id": row["id"], "query": row["query"], "created_at": _parse(row["created_at"])}
            for row in rows
        ]

    # -- cache --------------------------------------------------------------
    async def cache_get(self, key: str) -> Any | None:
        cursor = await self._conn.execute(
            "SELECT payload, expires_at FROM cache WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        if _parse(row["expires_at"]) <= utcnow():
            async with self._lock:
                await self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                await self._conn.commit()
            return None
        return json.loads(row["payload"])

    async def cache_set(self, key: str, payload: Any, ttl: int) -> None:
        if ttl <= 0:
            return
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO cache (key, payload, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, "
                "expires_at = excluded.expires_at",
                (
                    key,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    _iso(utcnow() + timedelta(seconds=ttl)),
                ),
            )
            await self._conn.commit()

    # -- panel admin: secretos ------------------------------------------------
    async def all_secrets(self) -> dict[str, str]:
        cursor = await self._conn.execute("SELECT key, value FROM secrets")
        rows = await cursor.fetchall()
        await cursor.close()
        return {row["key"]: row["value"] for row in rows}

    async def set_secret(self, key: str, value: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO secrets (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, _iso(utcnow())),
            )
            await self._conn.commit()

    async def delete_secret(self, key: str) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
            await self._conn.commit()

    # -- panel admin: claves de api -------------------------------------------
    async def create_api_key(self, label: str, key_hash: str, key_preview: str) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT INTO api_keys (label, key_hash, key_preview, created_at) "
                "VALUES (?, ?, ?, ?)",
                (label, key_hash, key_preview, _iso(now)),
            )
            await self._conn.commit()
            key_id = int(cursor.lastrowid or 0)
        return {"id": key_id, "label": label, "key_preview": key_preview, "created_at": now}

    async def list_api_keys(self) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, label, key_hash, key_preview, created_at FROM api_keys ORDER BY id DESC"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": row["id"], "label": row["label"], "key_hash": row["key_hash"],
                "key_preview": row["key_preview"], "created_at": _parse(row["created_at"]),
            }
            for row in rows
        ]

    async def get_api_key(self, key_id: int) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, label, key_hash, key_preview FROM api_keys WHERE id = ?", (key_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row["id"], "label": row["label"],
            "key_hash": row["key_hash"], "key_preview": row["key_preview"],
        }

    async def delete_api_key(self, key_id: int) -> bool:
        async with self._lock:
            cursor = await self._conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- panel admin: agentes de telegram (el "cerebro": prompt, personalidad) --
    async def create_telegram_agent(
        self, agent_id: str, label: str, system_prompt: str, personality: str,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO telegram_agents (id, label, system_prompt, personality, "
                "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (agent_id, label, system_prompt, personality, _iso(now), _iso(now)),
            )
            await self._conn.commit()
        return {
            "id": agent_id, "label": label, "system_prompt": system_prompt,
            "personality": personality, "enabled": True, "created_at": now, "updated_at": now,
        }

    async def list_telegram_agents(self) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, label, system_prompt, personality, enabled, created_at, updated_at "
            "FROM telegram_agents ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_telegram_agent_from_row(row) for row in rows]

    async def get_telegram_agent(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, label, system_prompt, personality, enabled, created_at, updated_at "
            "FROM telegram_agents WHERE id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _telegram_agent_from_row(row) if row else None

    async def update_telegram_agent(
        self, agent_id: str, *, label: str, system_prompt: str, enabled: bool,
    ) -> dict[str, Any] | None:
        now = utcnow()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE telegram_agents SET label = ?, system_prompt = ?, enabled = ?, "
                "updated_at = ? WHERE id = ?",
                (label, system_prompt, int(enabled), _iso(now), agent_id),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_telegram_agent(agent_id)

    async def delete_telegram_agent(self, agent_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM telegram_agents WHERE id = ?", (agent_id,)
            )
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- panel admin: tokens de telegram (un bot de BotFather, de un agente) ----
    async def create_telegram_token(
        self, token_id: str, agent_id: str, bot_token: str, bot_token_hash: str,
        bot_username: str, webhook_secret: str,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO telegram_tokens (id, agent_id, bot_token, bot_token_hash, "
                "bot_username, webhook_secret, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    token_id, agent_id, bot_token, bot_token_hash, bot_username,
                    webhook_secret, _iso(now), _iso(now),
                ),
            )
            await self._conn.commit()
        return {
            "id": token_id, "agent_id": agent_id, "bot_token": bot_token,
            "bot_token_hash": bot_token_hash, "bot_username": bot_username,
            "webhook_secret": webhook_secret, "enabled": True,
            "created_at": now, "updated_at": now,
        }

    async def list_telegram_tokens(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "enabled, created_at, updated_at FROM telegram_tokens"
        )
        params: tuple[Any, ...] = ()
        if agent_id is not None:
            query += " WHERE agent_id = ?"
            params = (agent_id,)
        query += " ORDER BY created_at DESC"
        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [_telegram_token_from_row(row) for row in rows]

    async def get_telegram_token(self, token_id: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "enabled, created_at, updated_at FROM telegram_tokens WHERE id = ?",
            (token_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _telegram_token_from_row(row) if row else None

    async def get_telegram_token_by_hash(self, bot_token_hash: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "enabled, created_at, updated_at FROM telegram_tokens WHERE bot_token_hash = ?",
            (bot_token_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _telegram_token_from_row(row) if row else None

    async def set_telegram_token_enabled(
        self, token_id: str, enabled: bool
    ) -> dict[str, Any] | None:
        now = utcnow()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE telegram_tokens SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _iso(now), token_id),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_telegram_token(token_id)

    async def delete_telegram_token(self, token_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM telegram_tokens WHERE id = ?", (token_id,)
            )
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- seguimiento de precios (bots de Telegram) ---------------------------
    async def create_price_watch(
        self, watch_id: str, token_id: str, chat_id: str, product_label: str,
        urls: list[str],
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO price_watches (id, token_id, chat_id, product_label, urls, "
                "enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (
                    watch_id, token_id, chat_id, product_label,
                    json.dumps(urls, ensure_ascii=False), _iso(now),
                ),
            )
            await self._conn.commit()
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
        cursor = await self._conn.execute(query)
        rows = await cursor.fetchall()
        await cursor.close()
        return [_price_watch_from_row(row) for row in rows]

    async def update_price_watch_result(
        self, watch_id: str, price_clp: float, best_url: str
    ) -> None:
        async with self._lock:
            await self._conn.execute(
                "UPDATE price_watches SET last_price_clp = ?, last_best_url = ?, "
                "last_checked_at = ? WHERE id = ?",
                (price_clp, best_url, _iso(utcnow()), watch_id),
            )
            await self._conn.commit()

    async def delete_price_watch(self, watch_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM price_watches WHERE id = ?", (watch_id,)
            )
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- corte de conversacion (bots de Telegram) ----------------------------
    async def mute_telegram_chat(
        self, token_id: str, chat_id: str, reason: str, until_iso: str
    ) -> None:
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO telegram_mutes (token_id, chat_id, reason, muted_until, "
                "created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(token_id, chat_id) DO UPDATE SET reason = excluded.reason, "
                "muted_until = excluded.muted_until",
                (token_id, chat_id, reason, until_iso, _iso(utcnow())),
            )
            await self._conn.commit()

    async def get_telegram_mute(self, token_id: str, chat_id: str) -> dict[str, Any] | None:
        """None si nunca se muteo o si el mute ya vencio -el llamador no
        necesita distinguir esos dos casos."""
        cursor = await self._conn.execute(
            "SELECT reason, muted_until FROM telegram_mutes "
            "WHERE token_id = ? AND chat_id = ? AND muted_until > ?",
            (token_id, chat_id, _iso(utcnow())),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {"reason": row["reason"], "muted_until": _parse(row["muted_until"])}

    # -- archivos que un agente conoce de memoria ----------------------------
    async def create_telegram_agent_file(
        self, file_id: str, agent_id: str, filename: str, content: str, char_count: int
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO telegram_agent_files (id, agent_id, filename, content, "
                "char_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (file_id, agent_id, filename, content, char_count, _iso(now)),
            )
            await self._conn.commit()
        return {
            "id": file_id, "agent_id": agent_id, "filename": filename, "content": content,
            "char_count": char_count, "created_at": now,
        }

    async def list_telegram_agent_files(self, agent_id: str) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, filename, content, char_count, created_at "
            "FROM telegram_agent_files WHERE agent_id = ? ORDER BY created_at",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_agent_file_from_row(row) for row in rows]

    async def get_telegram_agent_file(self, file_id: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, filename, content, char_count, created_at "
            "FROM telegram_agent_files WHERE id = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _agent_file_from_row(row) if row else None

    async def delete_telegram_agent_file(self, file_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM telegram_agent_files WHERE id = ?", (file_id,)
            )
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- APIs externas que un agente puede invocar en vivo -------------------
    async def create_telegram_agent_api(
        self, api_id: str, agent_id: str, name: str, description: str, url: str,
        method: str, headers_json: str,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO telegram_agent_apis (id, agent_id, name, description, url, "
                "method, headers, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (api_id, agent_id, name, description, url, method, headers_json,
                 _iso(now), _iso(now)),
            )
            await self._conn.commit()
        return {
            "id": api_id, "agent_id": agent_id, "name": name, "description": description,
            "url": url, "method": method, "headers": json.loads(headers_json),
            "enabled": True, "created_at": now, "updated_at": now,
        }

    async def list_telegram_agent_apis(self, agent_id: str) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, name, description, url, method, headers, enabled, "
            "created_at, updated_at FROM telegram_agent_apis "
            "WHERE agent_id = ? ORDER BY created_at",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_agent_api_from_row(row) for row in rows]

    async def get_telegram_agent_api(self, api_id: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, name, description, url, method, headers, enabled, "
            "created_at, updated_at FROM telegram_agent_apis WHERE id = ?",
            (api_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _agent_api_from_row(row) if row else None

    async def set_telegram_agent_api_enabled(
        self, api_id: str, enabled: bool
    ) -> dict[str, Any] | None:
        now = utcnow()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE telegram_agent_apis SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _iso(now), api_id),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_telegram_agent_api(api_id)

    async def delete_telegram_agent_api(self, api_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM telegram_agent_apis WHERE id = ?", (api_id,)
            )
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- herramientas generadas por IA a partir de un hueco detectado --------
    async def create_generated_tool(
        self, tool_id: str, agent_id: str, name: str, description: str,
        source_gap_reasoning_id: int | None,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO generated_tools (id, agent_id, source_gap_reasoning_id, name, "
                "description, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'PROPOSED', ?, ?)",
                (
                    tool_id, agent_id, source_gap_reasoning_id, name, description,
                    _iso(now), _iso(now),
                ),
            )
            await self._conn.commit()
        return {
            "id": tool_id, "agent_id": agent_id, "source_gap_reasoning_id": source_gap_reasoning_id,
            "name": name, "description": description, "status": "PROPOSED",
            "spec": {}, "code": "", "test_code": "", "sandbox_result": {}, "reject_reason": "",
            "call_count": 0, "last_called_at": None, "last_error": "",
            "created_at": now, "updated_at": now,
        }

    async def list_generated_tools(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        if agent_id is None:
            cursor = await self._conn.execute(
                "SELECT id, agent_id, source_gap_reasoning_id, name, description, status, "
                "spec, code, test_code, sandbox_result, reject_reason, call_count, "
                "last_called_at, last_error, created_at, updated_at FROM generated_tools "
                "ORDER BY created_at DESC"
            )
        else:
            cursor = await self._conn.execute(
                "SELECT id, agent_id, source_gap_reasoning_id, name, description, status, "
                "spec, code, test_code, sandbox_result, reject_reason, call_count, "
                "last_called_at, last_error, created_at, updated_at FROM generated_tools "
                "WHERE agent_id = ? ORDER BY created_at DESC",
                (agent_id,),
            )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_generated_tool_from_row(row) for row in rows]

    async def get_generated_tool(self, tool_id: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, agent_id, source_gap_reasoning_id, name, description, status, "
            "spec, code, test_code, sandbox_result, reject_reason, call_count, "
            "last_called_at, last_error, created_at, updated_at FROM generated_tools WHERE id = ?",
            (tool_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _generated_tool_from_row(row) if row else None

    async def set_generated_tool_generated(
        self, tool_id: str, spec_json: str, code: str, test_code: str
    ) -> dict[str, Any] | None:
        """PROPOSED -> GENERATING: Tool Designer + Code Agent ya
        produjeron una especificacion y codigo (ver core/tool_designer.py,
        core/code_agent.py)."""
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE generated_tools SET spec = ?, code = ?, test_code = ?, "
                "status = 'GENERATING', updated_at = ? WHERE id = ?",
                (spec_json, code, test_code, _iso(utcnow()), tool_id),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_generated_tool(tool_id)

    async def set_generated_tool_tested(
        self, tool_id: str, sandbox_result_json: str, *, passed: bool, reject_reason: str = ""
    ) -> dict[str, Any] | None:
        """GENERATING -> PENDING_APPROVAL (si el sandbox dio bien) o
        REJECTED (si no) -nunca pasa a ACTIVE sola, eso lo hace un humano
        (ver set_generated_tool_status)."""
        status = "PENDING_APPROVAL" if passed else "REJECTED"
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE generated_tools SET sandbox_result = ?, status = ?, "
                "reject_reason = ?, updated_at = ? WHERE id = ?",
                (sandbox_result_json, status, reject_reason, _iso(utcnow()), tool_id),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_generated_tool(tool_id)

    async def set_generated_tool_status(
        self, tool_id: str, status: str, reject_reason: str = ""
    ) -> dict[str, Any] | None:
        """Aprobar (-> ACTIVE) o rechazar (-> REJECTED) -la ruta admin es
        quien valida que la transicion tenga sentido antes de llamar esto."""
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE generated_tools SET status = ?, reject_reason = ?, updated_at = ? "
                "WHERE id = ?",
                (status, reject_reason, _iso(utcnow()), tool_id),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_generated_tool(tool_id)

    async def record_generated_tool_call(self, tool_id: str, *, ok: bool, error: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "UPDATE generated_tools SET call_count = call_count + 1, last_called_at = ?, "
                "last_error = ? WHERE id = ?",
                (_iso(utcnow()), "" if ok else error[:500], tool_id),
            )
            await self._conn.commit()

    async def delete_generated_tool(self, tool_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM generated_tools WHERE id = ?", (tool_id,)
            )
            await self._conn.commit()
            return bool(cursor.rowcount)

    # -- borrado total ------------------------------------------------------
    async def purge(self, tables: Sequence[str] | None = None) -> dict[str, int]:
        allowed = ("messages", "reasoning", "saved_items", "searches", "conversations", "cache")
        targets = [table for table in (tables or allowed) if table in allowed]
        removed: dict[str, int] = {}
        async with self._lock:
            for table in targets:
                cursor = await self._conn.execute(f"DELETE FROM {table}")  # noqa: S608
                removed[table] = cursor.rowcount or 0
            await self._conn.commit()
        return removed

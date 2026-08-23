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


def _telegram_profile_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "label": row["label"], "bot_token": row["bot_token"],
        "bot_token_hash": row["bot_token_hash"], "bot_username": row["bot_username"],
        "webhook_secret": row["webhook_secret"], "system_prompt": row["system_prompt"],
        "enabled": bool(row["enabled"]), "created_at": _parse(row["created_at"]),
        "updated_at": _parse(row["updated_at"]),
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

    # -- panel admin: perfiles de telegram -----------------------------------
    async def create_telegram_profile(
        self, profile_id: str, label: str, bot_token: str, bot_token_hash: str,
        bot_username: str, webhook_secret: str, system_prompt: str,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO telegram_profiles (id, label, bot_token, bot_token_hash, "
                "bot_username, webhook_secret, system_prompt, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    profile_id, label, bot_token, bot_token_hash, bot_username,
                    webhook_secret, system_prompt, _iso(now), _iso(now),
                ),
            )
            await self._conn.commit()
        return {
            "id": profile_id, "label": label, "bot_token": bot_token,
            "bot_token_hash": bot_token_hash, "bot_username": bot_username,
            "webhook_secret": webhook_secret, "system_prompt": system_prompt,
            "enabled": True, "created_at": now, "updated_at": now,
        }

    async def list_telegram_profiles(self) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(
            "SELECT id, label, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "system_prompt, enabled, created_at, updated_at FROM telegram_profiles "
            "ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_telegram_profile_from_row(row) for row in rows]

    async def get_telegram_profile(self, profile_id: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, label, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "system_prompt, enabled, created_at, updated_at FROM telegram_profiles WHERE id = ?",
            (profile_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _telegram_profile_from_row(row) if row else None

    async def get_telegram_profile_by_token_hash(
        self, bot_token_hash: str
    ) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            "SELECT id, label, bot_token, bot_token_hash, bot_username, webhook_secret, "
            "system_prompt, enabled, created_at, updated_at FROM telegram_profiles "
            "WHERE bot_token_hash = ?",
            (bot_token_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _telegram_profile_from_row(row) if row else None

    async def update_telegram_profile(
        self, profile_id: str, *, label: str, bot_token: str, bot_token_hash: str,
        bot_username: str, system_prompt: str, enabled: bool,
    ) -> dict[str, Any] | None:
        now = utcnow()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE telegram_profiles SET label = ?, bot_token = ?, bot_token_hash = ?, "
                "bot_username = ?, system_prompt = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (
                    label, bot_token, bot_token_hash, bot_username, system_prompt,
                    int(enabled), _iso(now), profile_id,
                ),
            )
            await self._conn.commit()
            if not cursor.rowcount:
                return None
        return await self.get_telegram_profile(profile_id)

    async def delete_telegram_profile(self, profile_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM telegram_profiles WHERE id = ?", (profile_id,)
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

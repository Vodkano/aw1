"""Claves de API emitidas desde el panel admin para llamar esta API desde afuera.

Ademas de ``AW1_API_TOKEN`` (fijo, de entorno), el panel admin puede emitir
claves adicionales -por ejemplo para el comparador de precios usado como API
propia-. Solo se guarda el hash; el valor completo se muestra una unica vez,
al crearla.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
from typing import Any, Protocol


class _ApiKeysRepo(Protocol):
    async def create_api_key(
        self, label: str, key_hash: str, key_preview: str
    ) -> dict[str, Any]: ...
    async def list_api_keys(self) -> list[dict[str, Any]]: ...
    async def get_api_key(self, key_id: int) -> dict[str, Any] | None: ...
    async def delete_api_key(self, key_id: int) -> bool: ...


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ApiKeyStore:
    def __init__(self, repo: Any) -> None:
        self._repo: _ApiKeysRepo = repo
        self._hashes: set[str] = set()

    async def load(self) -> None:
        rows = await self._repo.list_api_keys()
        self._hashes = {row["key_hash"] for row in rows}

    @property
    def configured(self) -> bool:
        return bool(self._hashes)

    def verify(self, presented: str) -> bool:
        return bool(presented) and hash_key(presented) in self._hashes

    async def create(self, label: str) -> dict[str, Any]:
        raw = pysecrets.token_urlsafe(32)
        key_hash = hash_key(raw)
        preview = raw[-4:]
        row = await self._repo.create_api_key(label.strip() or "sin nombre", key_hash, preview)
        self._hashes.add(key_hash)
        return {
            "id": row["id"],
            "label": row["label"],
            "key_preview": row["key_preview"],
            "created_at": row["created_at"],
            "value": raw,
        }

    async def list(self) -> list[dict[str, Any]]:
        rows = await self._repo.list_api_keys()
        return [
            {
                "id": row["id"],
                "label": row["label"],
                "key_preview": row["key_preview"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def delete(self, key_id: int) -> bool:
        row = await self._repo.get_api_key(key_id)
        ok = await self._repo.delete_api_key(key_id)
        if ok and row:
            self._hashes.discard(row["key_hash"])
        return ok

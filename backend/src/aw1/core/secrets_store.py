"""Claves de proveedores (OpenAI, Groq, host de Ollama) editables en caliente.

Se guardan en la base de datos, no en el entorno: el panel admin las cambia
sin reiniciar el proceso. En memoria hay una copia (``_cache``) para no ir a
la base de datos en cada peticion; se actualiza en cada escritura.
"""

from __future__ import annotations

from typing import Any, Protocol


class _SecretsRepo(Protocol):
    async def all_secrets(self) -> dict[str, str]: ...
    async def set_secret(self, key: str, value: str) -> None: ...
    async def delete_secret(self, key: str) -> None: ...


class SecretsStore:
    def __init__(self, repo: Any) -> None:
        self._repo: _SecretsRepo = repo
        self._cache: dict[str, str] = {}

    async def load(self) -> None:
        self._cache = await self._repo.all_secrets()

    def get(self, key: str) -> str | None:
        value = self._cache.get(key, "").strip()
        return value or None

    async def set(self, key: str, value: str) -> None:
        value = value.strip()
        if not value:
            await self.delete(key)
            return
        await self._repo.set_secret(key, value)
        self._cache[key] = value

    async def delete(self, key: str) -> None:
        await self._repo.delete_secret(key)
        self._cache.pop(key, None)

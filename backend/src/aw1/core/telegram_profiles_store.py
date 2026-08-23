"""Perfiles de Telegram: cada uno ES un bot independiente (su propio token),
gestionados en caliente desde el panel admin. Mismo patron que
``SecretsStore``/``ApiKeyStore`` -Protocol para el repositorio, cache en
memoria para no ir a la base de datos en el camino caliente del webhook.
"""

from __future__ import annotations

import logging
import secrets as pysecrets
import uuid
from typing import Any, Protocol

from ..settings import Settings
from ..telegram.client import TelegramClient
from .api_keys_store import hash_key
from .errors import ValidationError

logger = logging.getLogger(__name__)


class _TelegramProfilesRepo(Protocol):
    async def create_telegram_profile(
        self, profile_id: str, label: str, bot_token: str, bot_token_hash: str,
        bot_username: str, webhook_secret: str, system_prompt: str,
    ) -> dict[str, Any]: ...
    async def list_telegram_profiles(self) -> list[dict[str, Any]]: ...
    async def get_telegram_profile(self, profile_id: str) -> dict[str, Any] | None: ...
    async def get_telegram_profile_by_token_hash(
        self, bot_token_hash: str
    ) -> dict[str, Any] | None: ...
    async def update_telegram_profile(
        self, profile_id: str, *, label: str, bot_token: str, bot_token_hash: str,
        bot_username: str, system_prompt: str, enabled: bool,
    ) -> dict[str, Any] | None: ...
    async def delete_telegram_profile(self, profile_id: str) -> bool: ...


class TelegramProfileStore:
    def __init__(self, repo: Any, telegram: TelegramClient, settings: Settings) -> None:
        self._repo: _TelegramProfilesRepo = repo
        self._telegram = telegram
        self._settings = settings
        self._cache: dict[str, dict[str, Any]] = {}

    async def load(self) -> None:
        rows = await self._repo.list_telegram_profiles()
        self._cache = {row["id"]: row for row in rows}

    def get_cached(self, profile_id: str) -> dict[str, Any] | None:
        """Sync, en memoria -es lo que usa el camino caliente del webhook."""
        return self._cache.get(profile_id)

    def list(self) -> list[dict[str, Any]]:
        """Resumenes SIN el token completo -solo un preview, para no
        mandarlo de vuelta al navegador en cada carga del panel."""
        return [_summary(row) for row in self._cache.values()]

    async def get(self, profile_id: str) -> dict[str, Any] | None:
        """Fila completa (con el token) -para el formulario de edicion de
        UN perfil puntual, no para listados. Le suma token_preview (que
        TelegramProfileDetail exige via TelegramProfileSummary) y
        webhook_registered, que la fila cruda de la base no trae -son
        campos calculados, no columnas."""
        row = await self._repo.get_telegram_profile(profile_id)
        if row is None:
            return None
        return {**row, **_summary(row), "bot_token": row["bot_token"], "webhook_registered": True}

    async def test_token(self, bot_token: str) -> dict[str, Any]:
        """Dict {ok, detail}, no un modelo de la capa API -mismo criterio
        que el resto de este archivo (ver ApiKeyStore.create): el core no
        conoce los esquemas HTTP, la ruta admin envuelve el resultado."""
        info = await self._telegram.get_me(bot_token.strip())
        if info is None:
            return {"ok": False, "detail": "Telegram rechazo el token."}
        username = info.get("username", "")
        detail = f"Token valido: @{username}" if username else "Token valido."
        return {"ok": True, "detail": detail}

    async def create(self, *, label: str, bot_token: str, system_prompt: str) -> dict[str, Any]:
        if not self._settings.public_base_url.strip():
            raise ValidationError(
                "Define AW1_PUBLIC_BASE_URL antes de crear un perfil de Telegram "
                "(hace falta para registrar el webhook)."
            )
        bot_token = bot_token.strip()
        token_hash = hash_key(bot_token)
        if await self._repo.get_telegram_profile_by_token_hash(token_hash) is not None:
            raise ValidationError("Ese token ya lo usa otro perfil.")

        info = await self._telegram.get_me(bot_token)
        if info is None:
            raise ValidationError("Telegram rechazo el token.")
        bot_username = str(info.get("username") or "")

        profile_id = uuid.uuid4().hex
        webhook_secret = pysecrets.token_urlsafe(32)
        row = await self._repo.create_telegram_profile(
            profile_id, label.strip() or "sin nombre", bot_token, token_hash,
            bot_username, webhook_secret, system_prompt.strip(),
        )
        self._cache[profile_id] = row

        base = self._settings.public_base_url.rstrip("/")
        webhook_url = f"{base}/api/telegram/webhook/{profile_id}"
        registered = await self._telegram.set_webhook(bot_token, webhook_url, webhook_secret)
        if not registered:
            logger.warning("Perfil %s creado pero el webhook no quedo registrado.", profile_id)
        return {**row, "webhook_registered": registered}

    async def update(
        self, profile_id: str, *, label: str, bot_token: str, system_prompt: str, enabled: bool,
    ) -> dict[str, Any] | None:
        current = await self._repo.get_telegram_profile(profile_id)
        if current is None:
            return None

        bot_token = bot_token.strip()
        token_changed = bot_token != current["bot_token"]
        token_hash = hash_key(bot_token) if token_changed else current["bot_token_hash"]
        if token_changed:
            existing = await self._repo.get_telegram_profile_by_token_hash(token_hash)
            if existing is not None and existing["id"] != profile_id:
                raise ValidationError("Ese token ya lo usa otro perfil.")
            info = await self._telegram.get_me(bot_token)
            if info is None:
                raise ValidationError("Telegram rechazo el token.")
            bot_username = str(info.get("username") or "")
        else:
            bot_username = current["bot_username"]

        row = await self._repo.update_telegram_profile(
            profile_id, label=label.strip() or "sin nombre", bot_token=bot_token,
            bot_token_hash=token_hash, bot_username=bot_username,
            system_prompt=system_prompt.strip(), enabled=enabled,
        )
        if row is None:
            return None
        self._cache[profile_id] = row

        if token_changed:
            webhook_url = (
                f"{self._settings.public_base_url.rstrip('/')}/api/telegram/webhook/{profile_id}"
            )
            await self._telegram.set_webhook(bot_token, webhook_url, current["webhook_secret"])
        return row

    async def delete(self, profile_id: str) -> bool:
        row = self._cache.get(profile_id) or await self._repo.get_telegram_profile(profile_id)
        if row is not None:
            await self._telegram.delete_webhook(row["bot_token"])
        ok = await self._repo.delete_telegram_profile(profile_id)
        if ok:
            self._cache.pop(profile_id, None)
        return ok


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    token = row["bot_token"]
    return {
        "id": row["id"], "label": row["label"], "bot_username": row["bot_username"],
        "token_preview": token[-6:] if len(token) >= 6 else token,
        "system_prompt": row["system_prompt"], "enabled": row["enabled"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }

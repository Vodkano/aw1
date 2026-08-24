"""Agentes y tokens de Telegram.

Un agente es el "cerebro" (prompt, personalidad): no es un bot en si, sino la
logica que puede atender uno o varios bots. Un token es un bot de Telegram
concreto (su credencial de BotFather), enganchado a exactamente un agente -un
agente puede tener muchos tokens, un token es de un solo agente.

Mismo patron que ``SecretsStore``/``ApiKeyStore``: Protocol para el
repositorio, cache en memoria para no ir a la base de datos en el camino
caliente del webhook. ``get_cached_token`` devuelve una vista YA UNIDA
(token + los campos del agente que le pertenece) porque eso es exactamente
lo que necesita ese camino caliente -evita dos lookups separados por cada
mensaje que llega.
"""

from __future__ import annotations

import json
import logging
import random
import secrets as pysecrets
import uuid
from typing import Any, Protocol

from ..llm.prompts import TELEGRAM_PERSONALITIES
from ..settings import Settings
from ..telegram.client import TelegramClient
from . import netguard
from .api_keys_store import hash_key
from .errors import NotFoundError, ValidationError
from .file_extract import extract_text

logger = logging.getLogger(__name__)


class _TelegramRepo(Protocol):
    async def create_telegram_agent(
        self, agent_id: str, label: str, system_prompt: str, personality: str
    ) -> dict[str, Any]: ...
    async def list_telegram_agents(self) -> list[dict[str, Any]]: ...
    async def get_telegram_agent(self, agent_id: str) -> dict[str, Any] | None: ...
    async def update_telegram_agent(
        self, agent_id: str, *, label: str, system_prompt: str, enabled: bool
    ) -> dict[str, Any] | None: ...
    async def delete_telegram_agent(self, agent_id: str) -> bool: ...

    async def create_telegram_token(
        self, token_id: str, agent_id: str, bot_token: str, bot_token_hash: str,
        bot_username: str, webhook_secret: str,
    ) -> dict[str, Any]: ...
    async def list_telegram_tokens(self, agent_id: str | None = None) -> list[dict[str, Any]]: ...
    async def get_telegram_token(self, token_id: str) -> dict[str, Any] | None: ...
    async def get_telegram_token_by_hash(self, bot_token_hash: str) -> dict[str, Any] | None: ...
    async def set_telegram_token_enabled(
        self, token_id: str, enabled: bool
    ) -> dict[str, Any] | None: ...
    async def delete_telegram_token(self, token_id: str) -> bool: ...

    async def create_telegram_agent_file(
        self, file_id: str, agent_id: str, filename: str, content: str, char_count: int
    ) -> dict[str, Any]: ...
    async def list_telegram_agent_files(self, agent_id: str) -> list[dict[str, Any]]: ...
    async def delete_telegram_agent_file(self, file_id: str) -> bool: ...

    async def create_telegram_agent_api(
        self, api_id: str, agent_id: str, name: str, description: str, url: str,
        method: str, headers_json: str,
    ) -> dict[str, Any]: ...
    async def list_telegram_agent_apis(self, agent_id: str) -> list[dict[str, Any]]: ...
    async def set_telegram_agent_api_enabled(
        self, api_id: str, enabled: bool
    ) -> dict[str, Any] | None: ...
    async def delete_telegram_agent_api(self, api_id: str) -> bool: ...


class TelegramStore:
    def __init__(self, repo: Any, telegram: TelegramClient, settings: Settings) -> None:
        self._repo: _TelegramRepo = repo
        self._telegram = telegram
        self._settings = settings
        self._agents: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._files: dict[str, dict[str, Any]] = {}
        self._apis: dict[str, dict[str, Any]] = {}

    async def load(self) -> None:
        agents = await self._repo.list_telegram_agents()
        tokens = await self._repo.list_telegram_tokens()
        self._agents = {row["id"]: row for row in agents}
        self._tokens = {row["id"]: row for row in tokens}
        self._files = {}
        self._apis = {}
        for agent_id in self._agents:
            for row in await self._repo.list_telegram_agent_files(agent_id):
                self._files[row["id"]] = row
            for row in await self._repo.list_telegram_agent_apis(agent_id):
                self._apis[row["id"]] = row

    # ------------------------------------------------------------------
    # Camino caliente del webhook
    # ------------------------------------------------------------------
    def get_cached_token(self, token_id: str) -> dict[str, Any] | None:
        """Sync, en memoria: token + los campos del agente que le pertenece,
        ya unidos, mas sus archivos y APIs. None si el token no existe,
        esta deshabilitado, o su agente ya no existe o esta deshabilitado."""
        token = self._tokens.get(token_id)
        if token is None or not token.get("enabled", False):
            return None
        agent = self._agents.get(token["agent_id"])
        if agent is None or not agent.get("enabled", False):
            return None
        return {
            **token,
            "agent_label": agent["label"],
            "system_prompt": agent["system_prompt"],
            "personality": agent["personality"],
            "files": self.list_files(agent["id"]),
            "apis": [api for api in self.list_apis(agent["id"]) if api.get("enabled", True)],
        }

    # ------------------------------------------------------------------
    # Agentes
    # ------------------------------------------------------------------
    def _agent_extras(self, agent_id: str) -> dict[str, Any]:
        return {
            "tokens": self._token_summaries(agent_id),
            "files": self.list_files(agent_id),
            "apis": self.list_apis(agent_id),
        }

    async def create_agent(self, *, label: str, system_prompt: str) -> dict[str, Any]:
        agent_id = uuid.uuid4().hex
        personality = random.choice(list(TELEGRAM_PERSONALITIES))
        row = await self._repo.create_telegram_agent(
            agent_id, label.strip() or "sin nombre", system_prompt.strip(), personality
        )
        self._agents[agent_id] = row
        return {**row, "tokens": [], "files": [], "apis": []}

    def list_agents(self) -> list[dict[str, Any]]:
        """Resumenes de agentes, cada uno con sus tokens (sin el valor
        completo del token -solo el preview, ver TelegramStore.list_tokens),
        archivos y APIs."""
        return [
            {**agent, **self._agent_extras(agent["id"])}
            for agent in sorted(
                self._agents.values(), key=lambda row: row["created_at"], reverse=True
            )
        ]

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        row = await self._repo.get_telegram_agent(agent_id)
        if row is None:
            return None
        return {**row, **self._agent_extras(agent_id)}

    async def update_agent(
        self, agent_id: str, *, label: str, system_prompt: str, enabled: bool
    ) -> dict[str, Any] | None:
        row = await self._repo.update_telegram_agent(
            agent_id, label=label.strip() or "sin nombre",
            system_prompt=system_prompt.strip(), enabled=enabled,
        )
        if row is None:
            return None
        self._agents[agent_id] = row
        return {**row, **self._agent_extras(agent_id)}

    async def delete_agent(self, agent_id: str) -> bool:
        """Borra el agente y, en cascada, todos sus tokens, archivos y APIs
        (la base los borra solos por la FK, pero los webhooks de Telegram
        hay que avisarlos aparte -Telegram no sabe nada de nuestra base- y
        la cache en memoria hay que limpiarla a mano, la base no la toca)."""
        for token in list(self._tokens.values()):
            if token["agent_id"] == agent_id:
                await self._telegram.delete_webhook(token["bot_token"])
                self._tokens.pop(token["id"], None)
        ok = await self._repo.delete_telegram_agent(agent_id)
        if ok:
            self._agents.pop(agent_id, None)
            for file_id in [f["id"] for f in list(self._files.values()) if f["agent_id"] == agent_id]:
                self._files.pop(file_id, None)
            for api_id in [a["id"] for a in list(self._apis.values()) if a["agent_id"] == agent_id]:
                self._apis.pop(api_id, None)
        return ok

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------
    def _token_summaries(self, agent_id: str) -> list[dict[str, Any]]:
        return [_token_summary(row) for row in self._tokens.values() if row["agent_id"] == agent_id]

    async def test_token(self, bot_token: str) -> dict[str, Any]:
        """Dict {ok, detail}, no un modelo de la capa API -mismo criterio
        que el resto de este archivo: el core no conoce los esquemas HTTP."""
        info = await self._telegram.get_me(bot_token.strip())
        if info is None:
            return {"ok": False, "detail": "Telegram rechazo el token."}
        username = info.get("username", "")
        detail = f"Token valido: @{username}" if username else "Token valido."
        return {"ok": True, "detail": detail}

    async def create_token(self, agent_id: str, bot_token: str) -> dict[str, Any]:
        if agent_id not in self._agents:
            raise NotFoundError("Ese agente no existe.")
        if not self._settings.public_base_url.strip():
            raise ValidationError(
                "Define AW1_PUBLIC_BASE_URL antes de agregar un bot de Telegram "
                "(hace falta para registrar el webhook)."
            )
        bot_token = bot_token.strip()
        token_hash = hash_key(bot_token)
        if await self._repo.get_telegram_token_by_hash(token_hash) is not None:
            raise ValidationError("Ese token ya lo usa otro bot.")

        info = await self._telegram.get_me(bot_token)
        if info is None:
            raise ValidationError("Telegram rechazo el token.")
        bot_username = str(info.get("username") or "")

        token_id = uuid.uuid4().hex
        webhook_secret = pysecrets.token_urlsafe(32)
        row = await self._repo.create_telegram_token(
            token_id, agent_id, bot_token, token_hash, bot_username, webhook_secret
        )
        self._tokens[token_id] = row

        base = self._settings.public_base_url.rstrip("/")
        webhook_url = f"{base}/api/telegram/webhook/{token_id}"
        registered = await self._telegram.set_webhook(bot_token, webhook_url, webhook_secret)
        if not registered:
            logger.warning("Token %s creado pero el webhook no quedo registrado.", token_id)
        # _token_summary agrega token_preview -un campo calculado que
        # TelegramTokenCreated exige (via TelegramTokenSummary) y que la
        # fila cruda del repositorio no trae. Mismo bug que ya se dio una
        # vez con los perfiles de Telegram (ver TelegramProfileStore.get(),
        # ahora reemplazado): mejor prevenirlo aca de una que repetirlo.
        return {**row, **_token_summary(row), "webhook_registered": registered}

    async def set_token_enabled(self, token_id: str, enabled: bool) -> dict[str, Any] | None:
        row = await self._repo.set_telegram_token_enabled(token_id, enabled)
        if row is None:
            return None
        self._tokens[token_id] = row
        return {**row, **_token_summary(row)}

    async def delete_token(self, token_id: str) -> bool:
        row = self._tokens.get(token_id) or await self._repo.get_telegram_token(token_id)
        if row is not None:
            await self._telegram.delete_webhook(row["bot_token"])
        ok = await self._repo.delete_telegram_token(token_id)
        if ok:
            self._tokens.pop(token_id, None)
        return ok

    # ------------------------------------------------------------------
    # Archivos que un agente conoce de memoria (menu, catalogo, precios)
    # ------------------------------------------------------------------
    def list_files(self, agent_id: str) -> list[dict[str, Any]]:
        return [row for row in self._files.values() if row["agent_id"] == agent_id]

    async def add_file(self, agent_id: str, filename: str, content_bytes: bytes) -> dict[str, Any]:
        if agent_id not in self._agents:
            raise NotFoundError("Ese agente no existe.")
        text = extract_text(filename, content_bytes)
        file_id = uuid.uuid4().hex
        row = await self._repo.create_telegram_agent_file(file_id, agent_id, filename, text, len(text))
        self._files[file_id] = row
        return row

    async def delete_file(self, file_id: str) -> bool:
        ok = await self._repo.delete_telegram_agent_file(file_id)
        if ok:
            self._files.pop(file_id, None)
        return ok

    # ------------------------------------------------------------------
    # APIs externas que un agente puede invocar en vivo
    # ------------------------------------------------------------------
    def list_apis(self, agent_id: str) -> list[dict[str, Any]]:
        return [row for row in self._apis.values() if row["agent_id"] == agent_id]

    async def create_api(
        self, agent_id: str, *, name: str, description: str, url: str, method: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        if agent_id not in self._agents:
            raise NotFoundError("Ese agente no existe.")
        safe_url = netguard.normalize(url)
        api_id = uuid.uuid4().hex
        row = await self._repo.create_telegram_agent_api(
            api_id, agent_id, name.strip() or "api", description.strip(), safe_url,
            (method.strip() or "GET").upper(), json.dumps(headers or {}, ensure_ascii=False),
        )
        self._apis[api_id] = row
        return row

    async def set_api_enabled(self, api_id: str, enabled: bool) -> dict[str, Any] | None:
        """Solo activar/desactivar -no re-editar URL/headers, que pueden
        traer credenciales (ver UpdateTelegramAgentApiRequest)."""
        row = await self._repo.set_telegram_agent_api_enabled(api_id, enabled)
        if row is None:
            return None
        self._apis[api_id] = row
        return row

    async def delete_api(self, api_id: str) -> bool:
        ok = await self._repo.delete_telegram_agent_api(api_id)
        if ok:
            self._apis.pop(api_id, None)
        return ok


def _token_summary(row: dict[str, Any]) -> dict[str, Any]:
    token = row["bot_token"]
    return {
        "id": row["id"], "agent_id": row["agent_id"], "bot_username": row["bot_username"],
        "token_preview": token[-6:] if len(token) >= 6 else token,
        "enabled": row["enabled"], "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

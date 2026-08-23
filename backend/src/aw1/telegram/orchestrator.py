"""Orquestador de los bots de Telegram.

Un solo endpoint de webhook recibe el trafico de TODOS los perfiles (bots),
distinguidos por profile_id en la URL -no hay un loop de sondeo por bot, asi
que sumar un bot nuevo no crea ningun proceso ni tarea persistente adicional.
Cada mensaje se procesa en una tarea de fondo (fire-and-forget): la respuesta
al webhook de Telegram sale de inmediato, y la contestacion real se manda por
separado via ``sendMessage`` una vez que el chat termina de responder.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Any

from ..chat.service import ChatService
from ..core.errors import Aw1Error
from ..core.telegram_profiles_store import TelegramProfileStore
from .client import TelegramClient

logger = logging.getLogger(__name__)


class TelegramOrchestrator:
    def __init__(
        self, *, profiles: TelegramProfileStore, client: TelegramClient, chat: ChatService,
    ) -> None:
        self._profiles = profiles
        self._client = client
        self._chat = chat
        # Referencias fuertes a las tareas en vuelo: sin esto, asyncio puede
        # recolectar la tarea a mitad de camino y la respuesta simplemente
        # nunca llega, sin ningun error visible.
        self._tasks: set[asyncio.Task[None]] = set()

    def verify(self, profile_id: str, secret_header: str) -> dict[str, Any] | None:
        """Lookup en memoria + comparacion de tiempo constante, sin ir a la
        base de datos en el camino caliente del webhook."""
        profile = self._profiles.get_cached(profile_id)
        if profile is None or not profile.get("enabled", False):
            return None
        expected = profile.get("webhook_secret", "")
        if not secret_header or not hmac.compare_digest(secret_header, expected):
            return None
        return profile

    def enqueue(self, profile: dict[str, Any], update: dict[str, Any]) -> None:
        task = asyncio.create_task(self._handle(profile, update))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle(self, profile: dict[str, Any], update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text")
        if chat_id is None or not isinstance(text, str) or not text.strip():
            return

        conversation_id = f"telegram:{profile['id']}:{chat_id}"
        system_prompt = profile.get("system_prompt") or None
        answer = ""
        try:
            async for event in self._chat.stream(
                text, conversation_id=conversation_id, system_prompt=system_prompt
            ):
                if event.type == "done":
                    answer = str(event.data.get("answer", ""))
        except Aw1Error as error:
            answer = error.message
        except Exception:  # noqa: BLE001 - nadie mas esta esperando esta tarea
            logger.exception("Fallo procesando un mensaje de Telegram (perfil %s).", profile["id"])
            answer = "Hubo un problema respondiendo. Intenta de nuevo."

        if answer:
            await self._client.send_message(profile["bot_token"], chat_id, answer)

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

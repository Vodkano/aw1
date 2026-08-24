"""Orquestador de los bots de Telegram.

Un solo endpoint de webhook recibe el trafico de TODOS los tokens (bots),
distinguidos por token_id en la URL -no hay un loop de sondeo por bot, asi
que sumar un bot nuevo no crea ningun proceso ni tarea persistente adicional.
Cada mensaje se procesa en una tarea de fondo (fire-and-forget): la respuesta
al webhook de Telegram sale de inmediato, y la contestacion real se manda por
separado via ``sendMessage`` una vez que el chat termina de responder.

Un token pertenece a un agente (el "cerebro": prompt, personalidad); un
agente puede tener varios tokens. La memoria/conversacion, los seguimientos
de precio y el corte por mala intencion son todos por TOKEN (por bot), no
por agente -aunque dos bots compartan personalidad, cada uno tiene su propio
historial con cada persona.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ..chat.service import ChatService
from ..core import llm_provider, moderation
from ..core.errors import Aw1Error
from ..core.secrets_store import SecretsStore
from ..core.telegram_store import TelegramStore
from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.prompts import TELEGRAM_BASE_SYSTEM, TELEGRAM_CLOSE_SENTINEL, TELEGRAM_PERSONALITIES
from ..pricing.models import Offer
from ..pricing.pipeline import PricePipeline
from ..settings import Settings
from .client import TelegramClient

logger = logging.getLogger(__name__)

# Detecta URLs en el mensaje: es el disparador para armar un seguimiento de
# precio (ver _register_watch), no un flujo de conversacion con estado -mas
# simple y robusto que tener que recordar "en que paso estamos" por chat.
_URL_RE = re.compile(r"https?://\S+")

# El "escribiendo..." de Telegram expira solo si no se renueva -se reenvia
# cada 4s (bajo el limite de 5s de Telegram) mientras dure el turno.
_TYPING_INTERVAL = 4.0

# Cuanto dura el corte de conversacion despues de detectar mala intencion
# (ver TELEGRAM_CLOSE_SENTINEL en llm/prompts.py). Mientras dura, los
# mensajes de ese chat se responden con un texto fijo, sin llamar al modelo.
_MUTE_COOLDOWN_HOURS = 24.0

_MUTED_REPLY = (
    "Esta conversacion quedo cerrada por ahora. Si crees que es un error, "
    "escribenos mas tarde."
)
_MODERATED_REPLY = "No puedo ayudarte con eso. Si crees que es un error, escribenos mas tarde."
_NON_TEXT_REPLY = (
    "Por ahora solo puedo leer mensajes de texto -contame en palabras en "
    "que te ayudo."
)
_ERROR_REPLY = "Hubo un problema respondiendo. Intenta de nuevo."


def _compose_system_prompt(token: dict[str, Any]) -> str:
    """Base comun + personalidad (sorteada al crear el agente) + el prompt
    propio del agente, si tiene uno -se agrega sobre la base, nunca la
    reemplaza (ver llm/prompts.py:TELEGRAM_BASE_SYSTEM)."""
    parts = [TELEGRAM_BASE_SYSTEM, TELEGRAM_PERSONALITIES.get(token.get("personality") or "", "")]
    custom = str(token.get("system_prompt") or "").strip()
    if custom:
        parts.append(custom)
    return "\n\n".join(part for part in parts if part.strip())


class TelegramOrchestrator:
    def __init__(
        self, *, tokens: TelegramStore, client: TelegramClient, chat: ChatService,
        prices: PricePipeline, repo: Repository | PostgresRepository, settings: Settings,
        secrets: SecretsStore,
    ) -> None:
        self._tokens = tokens
        self._client = client
        self._chat = chat
        self._prices = prices
        self._repo = repo
        self._settings = settings
        self._secrets = secrets
        self._interval = settings.price_watch_interval_seconds
        # Referencias fuertes a las tareas en vuelo: sin esto, asyncio puede
        # recolectar la tarea a mitad de camino y la respuesta simplemente
        # nunca llega, sin ningun error visible.
        self._tasks: set[asyncio.Task[None]] = set()

    def verify(self, token_id: str, secret_header: str) -> dict[str, Any] | None:
        """Lookup en memoria + comparacion de tiempo constante, sin ir a la
        base de datos en el camino caliente del webhook."""
        token = self._tokens.get_cached_token(token_id)
        if token is None:
            return None
        expected = token.get("webhook_secret", "")
        if not secret_header or not hmac.compare_digest(secret_header, expected):
            return None
        return token

    def enqueue(self, token: dict[str, Any], update: dict[str, Any]) -> None:
        task = asyncio.create_task(self._handle(token, update))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle(self, token: dict[str, Any], update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        text = message.get("text")

        token_id = token["id"]
        typing = asyncio.create_task(self._keep_typing(token["bot_token"], chat_id))
        try:
            if not isinstance(text, str) or not text.strip():
                # Fotos, notas de voz, stickers, documentos: por ahora el
                # bot solo entiende texto. Mejor decirlo que dejar a la
                # persona esperando una respuesta que nunca llega.
                await self._client.send_message(token["bot_token"], chat_id, _NON_TEXT_REPLY)
                return

            # Corte de conversacion vigente: ni se llama al modelo. Es
            # exactamente lo que ahorra tokens en un chat que ya se
            # identifico como abusivo o sin sentido.
            if await self._repo.get_telegram_mute(token_id, str(chat_id)) is not None:
                await self._client.send_message(token["bot_token"], chat_id, _MUTED_REPLY)
                return

            # Todo lo que sigue puede fallar de formas que no se preveen
            # (un timeout raro, un bug); sea cual sea el motivo, la persona
            # del otro lado siempre tiene que recibir algo, no silencio.
            try:
                urls = _URL_RE.findall(text)
                if urls:
                    await self._register_watch(token, chat_id, text, urls)
                    return

                if await self._is_flagged(text):
                    until = (datetime.now(UTC) + timedelta(hours=_MUTE_COOLDOWN_HOURS)).isoformat()
                    await self._repo.mute_telegram_chat(
                        token_id, str(chat_id), "contenido marcado por moderacion", until
                    )
                    await self._client.send_message(
                        token["bot_token"], chat_id, _MODERATED_REPLY
                    )
                    return

                conversation_id = f"telegram:{token_id}:{chat_id}"
                system_prompt = _compose_system_prompt(token)
                answer = ""
                try:
                    # force_gpt: los agentes de Telegram usan GPT siempre,
                    # sin la heuristica "Ollama primero" de la web.
                    # history_hours: memoria por chat limitada a las
                    # ultimas 48h. fast_route: se salta la clasificacion
                    # por IA (viaja a Ollama, tunel incluido, hasta 25s)
                    # -era el principal cuello de botella de latencia del
                    # bot, y con force_gpt esa clasificacion ya no decide
                    # nada sobre que modelo responde.
                    async for event in self._chat.stream(
                        text, conversation_id=conversation_id, system_prompt=system_prompt,
                        force_gpt=True, history_hours=48.0, fast_route=True,
                    ):
                        if event.type == "done":
                            answer = str(event.data.get("answer", ""))
                except Aw1Error as error:
                    answer = error.message

                if TELEGRAM_CLOSE_SENTINEL in answer:
                    answer = answer.replace(TELEGRAM_CLOSE_SENTINEL, "").strip()
                    until = (datetime.now(UTC) + timedelta(hours=_MUTE_COOLDOWN_HOURS)).isoformat()
                    await self._repo.mute_telegram_chat(
                        token_id, str(chat_id), "mala intencion detectada por el modelo", until
                    )

                if answer:
                    await self._client.send_message(token["bot_token"], chat_id, answer)
            except Exception:  # noqa: BLE001 - nadie mas esta esperando esta tarea
                logger.exception("Fallo procesando un mensaje de Telegram (token %s).", token_id)
                await self._client.send_message(token["bot_token"], chat_id, _ERROR_REPLY)
        finally:
            typing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing

    async def _is_flagged(self, text: str) -> bool:
        """Filtro rapido y gratuito antes de gastar la llamada completa a
        GPT (ver core/moderation.py). Fail-open: si no hay clave o el
        servicio de moderacion falla, no bloquea la conversacion."""
        key = llm_provider.openai_key(self._settings, self._secrets)
        result = await moderation.check(text, api_key=key, base_url=self._settings.openai_base_url)
        if result.flagged:
            logger.info(
                "Moderacion marco un mensaje de Telegram: %s", ", ".join(result.categories)
            )
        return result.flagged

    async def _keep_typing(self, bot_token: str, chat_id: int) -> None:
        """Mientras el turno esta en curso, la persona ve "escribiendo...":
        sin esto, una respuesta que tarda 10-20s (GPT, o leer precios) se
        siente colgada en vez de ocupada."""
        try:
            while True:
                await self._client.send_chat_action(bot_token, chat_id, "typing")
                await asyncio.sleep(_TYPING_INTERVAL)
        except asyncio.CancelledError:
            raise

    async def _register_watch(
        self, token: dict[str, Any], chat_id: int, text: str, urls: list[str]
    ) -> None:
        """El mensaje trae URLs: se interpretan como las tiendas a comparar
        para UN producto, se lee el precio de cada una ahora mismo (misma
        lectura que usa el comparador normal, sin busqueda ni plan) y se
        guarda el seguimiento con ese primer resultado."""
        results = await asyncio.gather(*(self._read_price_safe(url) for url in urls))
        found = [offer for offer in results if offer is not None]
        if not found:
            await self._client.send_message(
                token["bot_token"], chat_id,
                "No pude leer el precio en esas paginas. Revisa los links e intenta de nuevo.",
            )
            return

        best = min(found, key=lambda offer: offer.price_clp)
        product_label = best.title or " ".join(text.split())[:120]
        watch_id = uuid.uuid4().hex
        await self._repo.create_price_watch(
            watch_id, token["id"], str(chat_id), product_label, urls
        )
        await self._repo.update_price_watch_result(watch_id, best.price_clp, best.url)

        reply = (
            f"Listo, voy a seguir el precio de «{product_label}» en {len(urls)} tienda(s).\n"
            f"Ahora mismo la mas barata es {best.store}: {best.price_label}\n{best.url}\n"
            "Te aviso cuando cambie."
        )
        await self._client.send_message(token["bot_token"], chat_id, reply)

    async def _read_price_safe(self, url: str) -> Offer | None:
        try:
            return await self._prices.read_price(url)
        except Exception:  # noqa: BLE001 - una URL mala no debe tumbar el resto
            logger.warning("No se pudo leer el precio de %s.", url)
            return None

    async def run_price_watch_loop(self) -> None:
        """Chequeo periodico de TODOS los seguimientos, de TODOS los
        tokens -mismo patron que browser_task en api/app.py (una tarea de
        fondo arrancada y cancelada en el lifespan), solo que este loop
        nunca termina."""
        while True:
            try:
                await self._check_all_watches()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - un fallo no debe tumbar el loop
                logger.exception("El chequeo periodico de precios fallo.")
            await asyncio.sleep(self._interval)

    async def _check_all_watches(self) -> None:
        # Secuencial (no en paralelo entre seguimientos): el navegador
        # comparte un pool chico de contextos (browser_max_contexts) con el
        # chat y la pestana Precios, no hace falta saturarlo aca.
        for watch in await self._repo.list_price_watches(enabled_only=True):
            best: Offer | None = None
            for url in watch["urls"]:
                offer = await self._read_price_safe(url)
                if offer is not None and (best is None or offer.price_clp < best.price_clp):
                    best = offer
            if best is None:
                continue

            changed = (
                watch["last_price_clp"] is None
                or best.price_clp != watch["last_price_clp"]
                or best.url != watch["last_best_url"]
            )
            await self._repo.update_price_watch_result(watch["id"], best.price_clp, best.url)
            if not changed:
                continue

            token = self._tokens.get_cached_token(watch["token_id"])
            if token is None:
                continue
            text = (
                f"Baja de precio en «{watch['product_label']}»: "
                f"{best.price_label} en {best.store}\n{best.url}"
            )
            await self._client.send_message(token["bot_token"], watch["chat_id"], text)

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

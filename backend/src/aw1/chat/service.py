"""Servicio de chat con respuesta en streaming.

Recorrido de un mensaje:

    1. Se limpia la entrada (las faltas de ortografia no rompen nada).
    2. El modelo decide la ruta; si no responde, manda la heuristica local.
    3. El razonamiento se guarda en la base de datos y **nunca** se envia al
       navegador.
    4. Codigo, analisis largo o actualidad ("heavy" / needs_fresh_data) ->
       GPT automaticamente si esta configurado, sin pedir permiso -la
       interfaz avisa despues, mostrando de que modelo vino la respuesta.
       Sin clave configurada, cae al modelo local y se explica por que.
    5. Biografia -> Wikipedia, y el modelo local redacta a partir de ese
       extracto citando la fuente.
    6. Precio -> se ofrece lanzar el comparador, que es quien sabe hacerlo.

Todo sale como eventos para que la interfaz escriba token a token.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from ..core import llm_provider
from ..core.errors import ProviderError, ValidationError
from ..core.secrets_store import SecretsStore
from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.client import OllamaClient
from ..llm.groq_client import GroqClient
from ..llm.judges import Judges
from ..llm.prompts import CHAT_SYSTEM
from ..settings import Settings
from . import heuristics
from .wikipedia import Wikipedia

logger = logging.getLogger(__name__)

MAX_MESSAGE = 4000

CLARIFY = (
    "No logre entender el mensaje. Puedes reformularlo? Por ejemplo: el nombre "
    "completo de la persona, el lenguaje de programacion, o el producto exacto."
)


@dataclass(slots=True)
class ChatEvent:
    type: str
    data: dict[str, Any]


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository | PostgresRepository,
        llm: OllamaClient | GroqClient,
        judges: Judges,
        wikipedia: Wikipedia,
        secrets: SecretsStore,
    ) -> None:
        self._settings = settings
        self._repo = repository
        self._llm = llm
        self._judges = judges
        self._wiki = wikipedia
        self._secrets = secrets

    def set_client(self, client: OllamaClient | GroqClient) -> None:
        """Cambia el cliente LLM en caliente (panel admin), sin reiniciar el proceso."""
        self._llm = client

    def _openai_key(self) -> str:
        override = self._secrets.get("openai_api_key")
        if override:
            return override
        key = self._settings.openai_api_key
        return key.get_secret_value() if key else ""

    def gpt_configured(self) -> bool:
        return bool(self._openai_key().strip())

    def _chat_model(self) -> str:
        return llm_provider.chat_model(self._settings, self._secrets)

    # ------------------------------------------------------------------
    async def stream(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        clean = " ".join(str(message or "").split())
        if not clean:
            raise ValidationError("Escribe un mensaje.")
        if len(clean) > MAX_MESSAGE:
            raise ValidationError(f"El mensaje supera los {MAX_MESSAGE} caracteres.")

        conversation = conversation_id or uuid.uuid4().hex
        yield ChatEvent("start", {"conversation_id": conversation})

        history = await self._repo.history(conversation, self._settings.max_history_turns)

        route = heuristics.merge(heuristics.route(clean), await self._safe_route(clean))
        await self._repo.save_reasoning(conversation, "chat_route", clean, route.model_dump())
        yield ChatEvent("route", {"intent": route.intent})

        # -- rutas que no llegan al modelo -------------------------------
        if route.intent == "confuso":
            async for event in self._say(conversation, clean, CLARIFY, "system"):
                yield event
            return

        if route.intent == "precio":
            product = route.search_terms or clean
            text = (
                f"Eso lo resuelve el comparador: abre la pestana Precios y busca "
                f"«{product}». Recorro varias tiendas con un navegador real y te "
                "traigo el precio y el enlace directo de cada una."
            )
            async for event in self._say(conversation, clean, text, "system"):
                yield event
            yield ChatEvent("action", {"kind": "search_prices", "query": product})
            return

        # -- tareas que se benefician de un modelo mas fuerte -------------
        # Automatico: no se pide confirmacion. La interfaz deja claro despues
        # de que modelo vino la respuesta (etiqueta "GPT" junto al mensaje).
        wants_gpt = route.heavy or route.needs_fresh_data
        if wants_gpt and self.gpt_configured():
            async for event in self._answer_with_gpt(conversation, clean, history):
                yield event
            return
        if wants_gpt and not self.gpt_configured():
            yield ChatEvent(
                "notice",
                {
                    "text": (
                        "Esto se beneficiaria de GPT, pero no esta configurado; "
                        "respondo con el modelo local."
                    ),
                },
            )

        # -- Wikipedia para biografias -----------------------------------
        context_block = ""
        sources: list[str] = []
        if route.intent == "biografia":
            term = route.person or route.search_terms or clean
            found = await self._wiki.lookup(term)
            if found:
                extract, url = found
                sources.append(url)
                context_block = (
                    "Extracto de Wikipedia sobre el tema preguntado. Usalo como "
                    "unica fuente de datos y cita el enlace al final:\n"
                    f"<<<DATOS>>>\n{extract}\n{url}\n<<<FIN>>>"
                )
                yield ChatEvent("source", {"url": url, "kind": "wikipedia"})

        async for event in self._answer_with_ollama(
            conversation, clean, history, context_block, sources
        ):
            yield event

    # ------------------------------------------------------------------
    async def _safe_route(self, message: str) -> Any:
        try:
            return await self._judges.route_chat(message)
        except Exception:  # noqa: BLE001 - el enrutado nunca tumba el chat
            logger.warning("El enrutador del modelo fallo; se usa la heuristica.")
            return None

    async def _answer_with_ollama(
        self,
        conversation: str,
        message: str,
        history: list[dict[str, str]],
        context_block: str,
        sources: list[str],
    ) -> AsyncIterator[ChatEvent]:
        messages = [{"role": "system", "content": CHAT_SYSTEM}]
        messages.extend(history)
        user_content = f"{context_block}\n\n{message}" if context_block else message
        messages.append({"role": "user", "content": user_content})

        collected: list[str] = []
        try:
            async for piece in self._llm.stream(
                messages,
                model=self._chat_model(),
                timeout=self._settings.ollama_chat_timeout,
            ):
                collected.append(piece)
                yield ChatEvent("token", {"text": piece})
        except ProviderError as error:
            model = self._chat_model()
            provider = llm_provider.effective_provider(self._settings, self._secrets)
            hint = (
                f"la clave de Groq y el modelo «{model}»"
                if provider == "groq"
                else f"que `ollama serve` este corriendo y que el modelo «{model}» este descargado"
            )
            text = f"{error.message} Comprueba {hint}."
            async for event in self._say(conversation, message, text, "system"):
                yield event
            return

        answer = "".join(collected).strip()
        if not answer:
            async for event in self._say(
                conversation, message, "El modelo local no devolvio contenido.", "system"
            ):
                yield event
            return

        await self._persist(conversation, message, answer, "wikipedia" if sources else "local")
        yield ChatEvent(
            "done",
            {
                "answer": answer,
                "source": "wikipedia" if sources else "local",
                "sources": sources,
                "conversation_id": conversation,
            },
        )

    async def _answer_with_gpt(
        self, conversation: str, message: str, history: list[dict[str, str]]
    ) -> AsyncIterator[ChatEvent]:
        payload = {
            "model": self._settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres el modo externo de AW1. La persona autorizo esta consulta "
                        "de forma explicita. Responde en espanol, breve y con datos "
                        "verificables. Si no tienes certeza, dilo."
                    ),
                },
                *history,
                {"role": "user", "content": message},
            ],
            "temperature": 0.4,
            "max_tokens": 900,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self._openai_key()}"}
        collected: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=60.0) as client, client.stream(
                "POST",
                f"{self._settings.openai_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    text = self._explain_gpt(response.status_code)
                    async for event in self._say(conversation, message, text, "system"):
                        yield event
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        import json

                        delta = json.loads(chunk)["choices"][0]["delta"]
                    except (ValueError, KeyError, IndexError):
                        continue
                    piece = delta.get("content", "")
                    if piece:
                        collected.append(piece)
                        yield ChatEvent("token", {"text": piece})
        except httpx.HTTPError:
            async for event in self._say(
                conversation, message, "No se pudo contactar con GPT.", "system"
            ):
                yield event
            return

        answer = "".join(collected).strip()
        if not answer:
            async for event in self._say(
                conversation, message, "GPT no devolvio contenido.", "system"
            ):
                yield event
            return
        await self._persist(conversation, message, answer, "gpt")
        yield ChatEvent(
            "done",
            {"answer": answer, "source": "gpt", "sources": [], "conversation_id": conversation},
        )

    @staticmethod
    def _explain_gpt(status: int) -> str:
        if status == 429:
            return (
                "GPT rechazo la consulta por limite de uso o saldo agotado. "
                "No se gasto nada y la conversacion sigue en local."
            )
        if status in (401, 403):
            return "La clave de GPT no es valida. Actualizala en el entorno."
        return f"GPT respondio {status}. La conversacion sigue en local."

    async def _say(
        self, conversation: str, message: str, text: str, source: str
    ) -> AsyncIterator[ChatEvent]:
        """Emite un mensaje del sistema como si se hubiera escrito, y lo persiste."""
        yield ChatEvent("token", {"text": text})
        await self._persist(conversation, message, text, source)
        yield ChatEvent(
            "done",
            {"answer": text, "source": source, "sources": [], "conversation_id": conversation},
        )

    async def _persist(self, conversation: str, message: str, answer: str, source: str) -> None:
        await self._repo.add_message(conversation, "user", message)
        await self._repo.add_message(conversation, "assistant", answer, source)

    # ------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        online = await self._llm.available()
        installed = await self._llm.models() if online else []
        wanted = self._chat_model()
        return {
            "ollama": "online" if online else "offline",
            "model": wanted,
            "model_ready": await self._llm.has_model(wanted) if online else False,
            "models": installed[:20],
            "gpt_configured": self.gpt_configured(),
            "database": "online" if await self._repo.healthy() else "offline",
            "env": self._settings.env,
            "auth_enabled": self._settings.auth_enabled,
        }

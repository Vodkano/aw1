"""Servicio de chat con respuesta en streaming.

Recorrido de un mensaje:

    1. Se limpia la entrada y se le quita una mencion "@algo" si trae una
       (fuerza esa ruta puntual: una herramienta, o el proveedor gpt/ollama).
    2. El modelo decide la ruta; si no responde, manda la heuristica local.
    3. El razonamiento se guarda en la base de datos y **nunca** se envia al
       navegador.
    4. Si el intent (o la mencion) coincide con una herramienta registrada
       (ver chat/tools/), se ejecuta directo -sin redirigir de pestana.
    5. Codigo, analisis largo o actualidad ("heavy" / needs_fresh_data) ->
       GPT automaticamente si esta configurado, sin pedir permiso -la
       interfaz avisa despues, mostrando de que modelo vino la respuesta.
       Sin clave configurada, cae al modelo local y se explica por que.
       Una mencion "@gpt"/"@ollama" fuerza esta decision para ese mensaje.
    6. Biografia -> Wikipedia. Charla/codigo -> se suma contexto de la
       memoria guardada a mano (solo lectura, ver chat/memory.py) si algo
       calza. El modelo local (o GPT, si aplica) redacta con ese contexto.

Todo sale como eventos para que la interfaz escriba token a token.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
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
from ..llm.prompts import CHAT_SYSTEM, GPT_SYSTEM, wrap_untrusted
from ..settings import Settings
from . import heuristics, memory
from .events import ChatEvent
from .tools.base import ChatTool, ToolRegistry
from .wikipedia import Wikipedia

logger = logging.getLogger(__name__)

MAX_MESSAGE = 4000

CLARIFY = (
    "No logre entender el mensaje. Puedes reformularlo? Por ejemplo: el nombre "
    "completo de la persona, el lenguaje de programacion, o el producto exacto."
)

# Coincide con "@algo" en cualquier parte del mensaje (no solo al inicio),
# pero exige que el "@" no venga pegado a otro caracter -sin el lookbehind,
# "contacto@ollama.dev" tambien "encontraria" una mencion "ollama" adentro
# de un correo. finditer (no search) porque puede haber mas de un "@algo" en
# el mensaje y el primero puede no ser uno conocido (ej. un correo antes del
# "@precios" real): hay que revisar todos, no solo el primero.
_MENTION = re.compile(r"(?<![^\s])@(\w+)\b")

# Unica fuente de verdad para los proveedores mencionables con "@": de aca
# salen tanto los ids validos para el parseo de la mencion como el texto que
# ve el menu de autocompletado (mentionable() los junta con las herramientas
# reales). Antes esto vivia repetido en tres lugares que podian desincronizarse.
_PROVIDER_INFO: dict[str, dict[str, Any]] = {
    "gpt": {"label": "gpt", "description": "Fuerza GPT para este mensaje.", "wants_gpt": True},
    "ollama": {
        "label": "ollama", "description": "Fuerza el modelo local para este mensaje.",
        "wants_gpt": False,
    },
}
PROVIDER_OVERRIDES: dict[str, bool] = {
    provider_id: info["wants_gpt"] for provider_id, info in _PROVIDER_INFO.items()
}
MENTION_PROVIDERS = tuple(
    {
        "id": provider_id, "label": info["label"],
        "description": info["description"], "kind": "provider",
    }
    for provider_id, info in _PROVIDER_INFO.items()
)


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
        tools: ToolRegistry,
    ) -> None:
        self._settings = settings
        self._repo = repository
        self._llm = llm
        self._judges = judges
        self._wiki = wikipedia
        self._secrets = secrets
        self._tools = tools

    def set_client(self, client: OllamaClient | GroqClient) -> None:
        """Cambia el cliente LLM en caliente (panel admin), sin reiniciar el proceso."""
        self._llm = client

    def _openai_key(self) -> str:
        return llm_provider.openai_key(self._settings, self._secrets)

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
        system_prompt: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        clean = " ".join(str(message or "").split())
        if not clean:
            raise ValidationError("Escribe un mensaje.")
        if len(clean) > MAX_MESSAGE:
            raise ValidationError(f"El mensaje supera los {MAX_MESSAGE} caracteres.")

        known_mentions = {*PROVIDER_OVERRIDES, *self._tools.ids()}
        clean, mention = self._extract_mention(clean, known_mentions)
        if not clean:
            raise ValidationError("Escribe un mensaje.")

        conversation = conversation_id or uuid.uuid4().hex
        yield ChatEvent("start", {"conversation_id": conversation})

        history = await self._repo.history(conversation, self._settings.max_history_turns)

        route = heuristics.merge(heuristics.route(clean), await self._safe_route(clean))
        await self._repo.save_reasoning(conversation, "chat_route", clean, route.model_dump())
        yield ChatEvent("route", {"intent": route.intent})

        # -- rutas que no llegan al modelo -------------------------------
        if route.intent == "confuso" and mention is None:
            async for event in self._say(conversation, clean, CLARIFY, "system"):
                yield event
            return

        # -- herramientas: por intent detectado, o por mencion explicita -
        # Si la mencion es un proveedor (gpt/ollama) NO se cae al intent
        # detectado: la persona pidio algo puntual y eso no se puede dejar
        # que una herramienta lo intercepte en silencio (ej. "@gpt cuanto
        # cuesta el iphone 15" no debe terminar en la herramienta de precios
        # solo porque el enrutador tambien clasifico el mensaje como precio).
        if mention is None or mention in self._tools.ids():
            tool = self._tools.get(mention or route.intent)
            if tool is not None:
                async for event in self._run_tool(tool, route, clean, conversation):
                    yield event
                return

        # -- tareas que se benefician de un modelo mas fuerte -------------
        # Automatico: no se pide confirmacion. La interfaz deja claro despues
        # de que modelo vino la respuesta (etiqueta "GPT" junto al mensaje).
        # Biografia queda afuera a proposito cuando es automatico: el modelo
        # puede marcar una pregunta como biografia Y heavy/needs_fresh_data a
        # la vez (ej. "quien es el actual presidente de Francia"), y ahi gana
        # Wikipedia -es la garantia de cita de fuente. Una mencion explicita
        # "@gpt"/"@ollama" SI puede aplicar incluso en biografia (la persona
        # lo pidio a proposito), pero la cita de Wikipedia se mantiene
        # -ver mas abajo, `sources` se le pasa igual a _answer_with_gpt.
        wants_gpt = (route.heavy or route.needs_fresh_data) and route.intent != "biografia"
        if mention in PROVIDER_OVERRIDES:
            wants_gpt = PROVIDER_OVERRIDES[mention]

        # -- contexto: Wikipedia para biografias, memoria guardada para el
        # resto -se calcula antes de decidir GPT/local porque ambos caminos
        # lo necesitan.
        context_block = ""
        sources: list[str] = []
        if route.intent == "biografia":
            term = route.person or route.search_terms or clean
            found = await self._wiki.lookup(term)
            if found:
                extract, url = found
                sources.append(url)
                context_block = wrap_untrusted(
                    "Extracto de Wikipedia sobre el tema preguntado. Usalo como "
                    "unica fuente de datos y cita el enlace al final:",
                    f"{extract}\n{url}",
                )
                yield ChatEvent("source", {"url": url, "kind": "wikipedia"})
        elif route.intent in {"charla", "codigo"}:
            try:
                context_block = await memory.recall(self._repo, route, clean)
            except Exception:  # noqa: BLE001 - un fallo de memoria no debe tumbar el chat
                logger.warning("El recuerdo de memoria fallo; se responde sin ese contexto.")

        if wants_gpt:
            if self.gpt_configured():
                async for event in self._answer_with_gpt(
                    conversation, clean, history, context_block, sources,
                    system_prompt=system_prompt,
                ):
                    yield event
                return
            yield ChatEvent(
                "notice",
                {
                    "text": (
                        "Esto se beneficiaria de GPT, pero no esta configurado; "
                        "respondo con el modelo local."
                    ),
                },
            )

        async for event in self._answer_with_ollama(
            conversation, clean, history, context_block, sources,
            system_prompt=system_prompt,
        ):
            yield event

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_mention(message: str, known: set[str]) -> tuple[str, str | None]:
        """Saca un "@algo" del mensaje si coincide con una herramienta o
        proveedor conocido, en cualquier parte del texto. Revisa TODAS las
        coincidencias de "@algo" (no solo la primera): un correo antes de la
        mencion real ("info@empresa.cl, dame @precios de esto") no debe tapar
        la mencion valida que viene despues. Devuelve el mensaje sin la
        mencion (y sin dobles espacios) y el id encontrado, o None."""
        for match in _MENTION.finditer(message):
            candidate = match.group(1).lower()
            if candidate in known:
                cleaned = message[: match.start()] + message[match.end() :]
                return " ".join(cleaned.split()), candidate
        return message, None

    async def _run_tool(
        self, tool: ChatTool, route: Any, message: str, conversation: str
    ) -> AsyncIterator[ChatEvent]:
        try:
            async for event in tool.run(route, message, conversation):
                if event.type == "tool_result":
                    async for said in self._say(
                        conversation, message, event.data["answer"],
                        event.data.get("source", "system"), event.data.get("sources"),
                    ):
                        yield said
                    return
                yield event
        except Exception:  # noqa: BLE001 - una herramienta no debe tumbar el chat
            logger.exception("La herramienta '%s' fallo.", tool.intent)
            async for event in self._say(
                conversation, message,
                "Hubo un problema ejecutando esa accion. Intenta de nuevo.", "system",
            ):
                yield event

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
        *,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        messages = [{"role": "system", "content": system_prompt or CHAT_SYSTEM}]
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
        self,
        conversation: str,
        message: str,
        history: list[dict[str, str]],
        context_block: str = "",
        sources: list[str] | None = None,
        *,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        sources = sources or []
        user_content = f"{context_block}\n\n{message}" if context_block else message
        payload = {
            "model": self._settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt or GPT_SYSTEM},
                *history,
                {"role": "user", "content": user_content},
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
            {
                "answer": answer, "source": "gpt", "sources": sources,
                "conversation_id": conversation,
            },
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
        self,
        conversation: str,
        message: str,
        text: str,
        source: str,
        sources: list[str] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Emite una respuesta ya conocida completa (no en streaming) como si
        se hubiera escrito, y la persiste. Lo usan tanto los mensajes de
        sistema (errores, aclaraciones) como el resultado final de una
        herramienta -mismo contrato de persistencia para toda respuesta que
        no llega token a token desde un modelo."""
        yield ChatEvent("token", {"text": text})
        await self._persist(conversation, message, text, source)
        yield ChatEvent(
            "done",
            {
                "answer": text, "source": source, "sources": sources or [],
                "conversation_id": conversation,
            },
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
            "mentions": [*MENTION_PROVIDERS, *self._tools.mentionable()],
        }

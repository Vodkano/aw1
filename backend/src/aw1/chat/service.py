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
    6. Biografia -> Wikipedia. Charla/codigo -> si el enrutador decide que
       conviene (route.needs_memory), se suma contexto de la memoria
       guardada a mano (solo lectura, ver chat/memory.py); si no, responde
       directo, sin tocar la base. El modelo local (o GPT, si aplica)
       redacta con ese contexto cuando existe.

Todo sale como eventos para que la interfaz escriba token a token.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..core import agent_apis as agent_apis_module
from ..core import image_gen, llm_provider, sandbox
from ..core.tracing import record_trace
from ..core.agent_apis import tool_name as _api_tool_name
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


def _api_tool_def(api: dict[str, Any]) -> dict[str, Any]:
    """Convierte una API configurada por el admin en una funcion invocable
    por el modelo (tool calling de OpenAI). "query" es generico a proposito
    -no todas las APIs necesitan un dato, y el admin decide si su URL lo
    usa (ver core/agent_apis.py: se sustituye si la URL trae "{query}")."""
    return {
        "type": "function",
        "function": {
            "name": _api_tool_name(str(api.get("name") or "api")),
            "description": str(api.get("description") or "")[:500],
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Dato que necesita la consulta, si aplica "
                            "(ej. un codigo, nombre o id)."
                        ),
                    }
                },
                "required": [],
            },
        },
    }


# Herramienta nativa (no configurada por el admin, siempre igual): el modelo
# la usa cuando la persona pide una imagen. Solo se ofrece cuando quien llama
# a _answer_with_gpt_tools pasa allow_image_generation=True -por ahora, solo
# los agentes de Telegram (ver TelegramOrchestrator), donde no hay streaming
# de por medio que perder.
_IMAGE_TOOL_NAME = "generar_imagen"
_IMAGE_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": _IMAGE_TOOL_NAME,
        "description": (
            "Genera una imagen a partir de una descripcion en texto y se la "
            "manda a la persona. Usala SOLO cuando piden explicitamente una "
            "imagen, dibujo, foto generada o algo visual -nunca para "
            "responder con texto normal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Descripcion detallada de la imagen a generar. En "
                        "ingles si es posible, da mejores resultados."
                    ),
                }
            },
            "required": ["prompt"],
        },
    },
}


# Herramienta nativa igual que la de arriba: le da al modelo una forma
# explicita de decir "esto no lo puedo hacer con lo que tengo" en vez de
# inventar una capacidad que no existe. Solo registra el pedido (ver
# ChatService._log_capability_gap) -nunca dispara la generacion de codigo
# sola; eso lo arranca un humano desde el panel admin. Solo se ofrece
# cuando quien llama pasa allow_capability_requests=True (por ahora, solo
# los agentes de Telegram).
_CAPABILITY_TOOL_NAME = "solicitar_nueva_capacidad"
_CAPABILITY_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": _CAPABILITY_TOOL_NAME,
        "description": (
            "Registra que te pidieron algo concreto y verificable (un dato "
            "en vivo, una accion) que no podes hacer con ninguna herramienta "
            "disponible ahora. Usala solo para eso -nunca para charla "
            "normal ni para algo que ya podes resolver conversando."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre corto en snake_case, ej: consultar_dolar_hoy",
                },
                "description": {
                    "type": "string",
                    "description": "Que deberia hacer esa herramienta.",
                },
                "why": {
                    "type": "string",
                    "description": "Que pidio la persona que disparo esto.",
                },
            },
            "required": ["name", "description", "why"],
        },
    },
}


def _generated_tool_def(tool_row: dict[str, Any]) -> dict[str, Any]:
    """Una herramienta generada y aprobada (ver core/code_agent.py,
    generated_tools en la base) se ofrece igual que una API configurada
    por el admin -misma forma de tool-calling, el modelo no distingue una
    de otra."""
    spec = tool_row.get("spec") or {}
    return {
        "type": "function",
        "function": {
            "name": _api_tool_name(str(tool_row.get("name") or "herramienta")),
            "description": str(tool_row.get("description") or "")[:500],
            "parameters": spec.get("parameters")
            or {"type": "object", "properties": {}, "required": []},
        },
    }


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
        force_gpt: bool = False,
        history_hours: float | None = None,
        history_max_messages: int = 60,
        fast_route: bool = False,
        agent_apis: list[dict[str, Any]] | None = None,
        allow_image_generation: bool = False,
        agent_id: str | None = None,
        allow_capability_requests: bool = False,
        generated_tools: list[dict[str, Any]] | None = None,
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
        trace_source = "telegram" if fast_route else "chat"
        yield ChatEvent("start", {"conversation_id": conversation})

        if history_hours is not None:
            since = datetime.now(UTC) - timedelta(hours=history_hours)
            history = await self._repo.history_since(
                conversation, since.isoformat(), max_messages=history_max_messages
            )
        else:
            history = await self._repo.history(conversation, self._settings.max_history_turns)

        # fast_route (Telegram, con force_gpt): se salta la clasificacion por
        # IA, que viaja a Ollama y puede tardar hasta 25s por el tunel -con
        # force_gpt esa clasificacion ya no decide el modelo de respuesta
        # (siempre GPT), y precio/biografia/codigo los detecta igual de bien
        # la heuristica local (merge() ya le da prioridad a "precio" sobre
        # cualquier cosa que diga el modelo).
        if fast_route:
            route = heuristics.route(clean)
        else:
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
        wants_gpt = force_gpt or (
            (route.heavy or route.needs_fresh_data) and route.intent != "biografia"
        )
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
        elif route.intent in {"charla", "codigo"} and route.needs_memory:
            try:
                context_block = await memory.recall(self._repo, route, clean)
            except Exception:  # noqa: BLE001 - un fallo de memoria no debe tumbar el chat
                logger.warning("El recuerdo de memoria fallo; se responde sin ese contexto.")

        if wants_gpt:
            if self.gpt_configured():
                try:
                    any_tool = (
                        agent_apis or allow_image_generation
                        or allow_capability_requests or generated_tools
                    )
                    if any_tool:
                        # Con alguna herramienta de tool-calling disponible
                        # (APIs configuradas, generacion de imagenes, pedido
                        # de capacidad nueva, o herramientas ya generadas y
                        # aprobadas) se resigna el streaming: el protocolo
                        # de tool calling de OpenAI necesita poder ir y
                        # volver con el resultado de cada llamada antes de
                        # la respuesta final -mas simple y confiable sin
                        # streaming a medio camino. En el caso normal (sin
                        # ninguna de estas) el camino de siempre no cambia.
                        async for event in self._answer_with_gpt_tools(
                            conversation, clean, history, context_block, sources,
                            system_prompt=system_prompt, agent_apis=agent_apis or [],
                            allow_image_generation=allow_image_generation,
                            agent_id=agent_id, allow_capability_requests=allow_capability_requests,
                            generated_tools=generated_tools or [], trace_source=trace_source,
                        ):
                            yield event
                    else:
                        async for event in self._answer_with_gpt(
                            conversation, clean, history, context_block, sources,
                            system_prompt=system_prompt, trace_source=trace_source,
                        ):
                            yield event
                    return
                except ProviderError as error:
                    # Clave configurada pero invalida, GPT caido, etc.: se
                    # avisa y se sigue en local -mismo trato que "GPT no
                    # configurado". El error nunca llego a emitir un token
                    # (se detecta antes de empezar a leer el stream de
                    # OpenAI), asi que no hay nada a medias que limpiar.
                    yield ChatEvent(
                        "notice", {"text": f"{error.message} Respondo con el modelo local."}
                    )
            else:
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
            system_prompt=system_prompt, trace_source=trace_source,
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
        trace_source: str = "chat",
    ) -> AsyncIterator[ChatEvent]:
        messages = [{"role": "system", "content": system_prompt or CHAT_SYSTEM}]
        messages.extend(history)
        user_content = f"{context_block}\n\n{message}" if context_block else message
        messages.append({"role": "user", "content": user_content})

        collected: list[str] = []
        model = self._chat_model()
        provider = llm_provider.effective_provider(self._settings, self._secrets)
        started = time.monotonic()
        try:
            async for piece in self._llm.stream(
                messages,
                model=model,
                timeout=self._settings.ollama_chat_timeout,
            ):
                collected.append(piece)
                yield ChatEvent("token", {"text": piece})
        except ProviderError as error:
            await record_trace(
                self._repo, trace_source, provider=provider, model=model, status="error",
                latency_ms=int((time.monotonic() - started) * 1000), error=error.message,
            )
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
            await record_trace(
                self._repo, trace_source, provider=provider, model=model, status="fallback",
                latency_ms=int((time.monotonic() - started) * 1000),
                error="El modelo local no devolvio contenido.",
            )
            async for event in self._say(
                conversation, message, "El modelo local no devolvio contenido.", "system"
            ):
                yield event
            return

        await record_trace(
            self._repo, trace_source, provider=provider, model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
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
        trace_source: str = "chat",
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
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client, client.stream(
                "POST",
                f"{self._settings.openai_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    # Nada se yieldeo todavia (el streaming de tokens
                    # empieza recien abajo): es seguro que el llamador
                    # capture esto y siga en el modelo local, en vez de
                    # cortar la conversacion con un mensaje de error -mismo
                    # trato que "GPT no configurado".
                    raise ProviderError(self._explain_gpt(response.status_code))
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"]
                    except (ValueError, KeyError, IndexError):
                        continue
                    piece = delta.get("content", "")
                    if piece:
                        collected.append(piece)
                        yield ChatEvent("token", {"text": piece})
        except httpx.HTTPError as error:
            await record_trace(
                self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
                status="error", latency_ms=int((time.monotonic() - started) * 1000),
                error=str(error),
            )
            raise ProviderError("No se pudo contactar con GPT.") from error

        answer = "".join(collected).strip()
        latency_ms = int((time.monotonic() - started) * 1000)
        if not answer:
            await record_trace(
                self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
                status="fallback", latency_ms=latency_ms, error="GPT no devolvio contenido.",
            )
            async for event in self._say(
                conversation, message, "GPT no devolvio contenido.", "system"
            ):
                yield event
            return
        await record_trace(
            self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
            latency_ms=latency_ms,
        )
        await self._persist(conversation, message, answer, "gpt")
        yield ChatEvent(
            "done",
            {
                "answer": answer, "source": "gpt", "sources": sources,
                "conversation_id": conversation,
            },
        )

    async def _answer_with_gpt_tools(
        self,
        conversation: str,
        message: str,
        history: list[dict[str, str]],
        context_block: str = "",
        sources: list[str] | None = None,
        *,
        system_prompt: str | None = None,
        agent_apis: list[dict[str, Any]],
        allow_image_generation: bool = False,
        agent_id: str | None = None,
        allow_capability_requests: bool = False,
        generated_tools: list[dict[str, Any]] | None = None,
        trace_source: str = "chat",
    ) -> AsyncIterator[ChatEvent]:
        """Como _answer_with_gpt, pero con herramientas de tool calling de
        OpenAI disponibles -el modelo decide si necesita llamar alguna
        antes de responder. Sin streaming: el protocolo de ida y vuelta con
        el resultado de cada llamada no es compatible con leer la
        respuesta token a token, y a diferencia del camino normal esto
        solo se usa cuando hace falta al menos una herramienta."""
        sources = sources or []
        user_content = f"{context_block}\n\n{message}" if context_block else message
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt or GPT_SYSTEM},
            *history,
            {"role": "user", "content": user_content},
        ]
        tools = [_api_tool_def(api) for api in agent_apis]
        apis_by_tool_name = {_api_tool_def(api)["function"]["name"]: api for api in agent_apis}
        if allow_image_generation:
            tools.append(_IMAGE_TOOL_DEF)
        if allow_capability_requests:
            tools.append(_CAPABILITY_TOOL_DEF)
        # Una herramienta generada podria terminar con el mismo nombre
        # saneado que una API del admin o una nativa -se omite (con aviso
        # en el log) en vez de dejar que una tape a la otra en silencio.
        reserved_names = {_IMAGE_TOOL_NAME, _CAPABILITY_TOOL_NAME, *apis_by_tool_name}
        generated_by_tool_name: dict[str, dict[str, Any]] = {}
        for tool_row in generated_tools or []:
            tool_def = _generated_tool_def(tool_row)
            tool_name = tool_def["function"]["name"]
            if tool_name in reserved_names or tool_name in generated_by_tool_name:
                logger.warning(
                    "Herramienta generada '%s' omitida por colision de nombre.", tool_name
                )
                continue
            tools.append(tool_def)
            generated_by_tool_name[tool_name] = tool_row
        headers = {"Authorization": f"Bearer {self._openai_key()}"}
        base = self._settings.openai_base_url.rstrip("/")
        image_sent = False
        tools_called: list[str] = []
        started = time.monotonic()

        # Tope de vueltas ida-y-vuelta con herramientas: un modelo que
        # insiste en llamar herramientas sin nunca responder no puede
        # dejar la conversacion colgada.
        for _ in range(3):
            payload = {
                "model": self._settings.openai_model,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": 900,
                "tools": tools,
                "stream": False,
            }
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{base}/chat/completions", json=payload, headers=headers
                    )
            except httpx.HTTPError as error:
                await record_trace(
                    self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
                    tools_called=tools_called, status="error",
                    latency_ms=int((time.monotonic() - started) * 1000), error=str(error),
                )
                raise ProviderError("No se pudo contactar con GPT.") from error
            if response.status_code >= 400:
                await record_trace(
                    self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
                    tools_called=tools_called, status="error",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=f"HTTP {response.status_code}",
                )
                raise ProviderError(self._explain_gpt(response.status_code))

            choice = response.json()["choices"][0]
            assistant_message = choice["message"]
            tool_calls = assistant_message.get("tool_calls") or []

            if not tool_calls:
                answer = str(assistant_message.get("content") or "").strip()
                if not answer:
                    # Algunos modelos no agregan texto despues de generar la
                    # imagen (la consideran la respuesta en si): eso no es
                    # un error si la imagen ya se mando.
                    if image_sent:
                        answer = "Listo, ahi tienes la imagen."
                    else:
                        await record_trace(
                            self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
                            tools_called=tools_called, status="fallback",
                            latency_ms=int((time.monotonic() - started) * 1000),
                            error="GPT no devolvio contenido.",
                        )
                        async for event in self._say(
                            conversation, message, "GPT no devolvio contenido.", "system"
                        ):
                            yield event
                        return
                yield ChatEvent("token", {"text": answer})
                await record_trace(
                    self._repo, trace_source, provider="gpt", model=self._settings.openai_model,
                    tools_called=tools_called,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                await self._persist(conversation, message, answer, "gpt")
                yield ChatEvent(
                    "done",
                    {
                        "answer": answer, "source": "gpt", "sources": sources,
                        "conversation_id": conversation,
                    },
                )
                return

            messages.append(assistant_message)
            for call in tool_calls:
                name = call.get("function", {}).get("name", "")
                tools_called.append(name)
                try:
                    args = json.loads(call.get("function", {}).get("arguments") or "{}")
                except ValueError:
                    args = {}
                if name == _IMAGE_TOOL_NAME:
                    result_text, image_url = await self._generate_image(str(args.get("prompt", "")))
                    if image_url:
                        image_sent = True
                        yield ChatEvent("image", {"url": image_url})
                elif name == _CAPABILITY_TOOL_NAME:
                    result_text = await self._log_capability_gap(
                        agent_id, conversation, message, args
                    )
                elif name in generated_by_tool_name:
                    result_text = await self._run_generated_tool(generated_by_tool_name[name], args)
                else:
                    api = apis_by_tool_name.get(name)
                    if api is None:
                        result_text = "Error: esa herramienta no existe."
                    else:
                        result_text = await agent_apis_module.call(api, str(args.get("query", "")))
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text}
                )

        async for event in self._say(
            conversation, message, "No pude completar la consulta a tiempo.", "system"
        ):
            yield event

    async def _generate_image(self, prompt: str) -> tuple[str, str | None]:
        """Nunca lanza -un fallo se convierte en el texto que ve el modelo
        como resultado de la herramienta, mismo trato que agent_apis.call.
        Devuelve (texto para el modelo, URL de la imagen o None si fallo)."""
        prompt = prompt.strip()
        if not prompt:
            return "Error: hace falta una descripcion para generar la imagen.", None
        try:
            url = await image_gen.generate(
                prompt, api_key=self._openai_key(), base_url=self._settings.openai_base_url,
                model=self._settings.openai_image_model,
            )
        except (httpx.HTTPError, RuntimeError) as error:
            return f"Error generando la imagen: {error}", None
        return "Imagen generada y ya se le mando a la persona.", url

    async def _log_capability_gap(
        self, agent_id: str | None, conversation: str, message: str, args: dict[str, Any]
    ) -> str:
        """Nunca lanza -solo registra el pedido para que el administrador
        lo vea en el panel. Generar la herramienta es un paso aparte que
        arranca un humano desde ahi, nunca esto -detectar el hueco no
        dispara la generacion de codigo sola."""
        payload = {
            "agent_id": agent_id,
            "name": str(args.get("name", ""))[:80],
            "description": str(args.get("description", ""))[:500],
            "why": str(args.get("why", ""))[:500],
            "triggering_message": message[:1000],
        }
        try:
            await self._repo.save_reasoning(conversation, "capability_gap", message, payload)
        except Exception:  # noqa: BLE001 - un fallo al registrar no debe tumbar el turno
            logger.warning("No se pudo registrar el pedido de capacidad.")
        return (
            "Anotado: no tengo esa capacidad todavia. Quedo registrado para "
            "revision del administrador."
        )

    async def _run_generated_tool(self, tool_row: dict[str, Any], args: dict[str, Any]) -> str:
        """Corre en la MISMA sandbox restringida que se uso para probar la
        herramienta antes de aprobarla -nunca gana mas privilegios al
        activarse (ver core/sandbox.py). Nunca lanza, mismo contrato que
        agent_apis.call."""
        result = await sandbox.run_in_sandbox(
            tool_row.get("code", ""), args,
            timeout_seconds=self._settings.sandbox_timeout_seconds,
            cpu_seconds=self._settings.sandbox_cpu_seconds,
            memory_mb=self._settings.sandbox_memory_mb,
        )
        tool_id = tool_row.get("id")
        if tool_id:
            try:
                await self._repo.record_generated_tool_call(
                    tool_id, ok=result.ok, error=result.error
                )
            except Exception:  # noqa: BLE001 - registrar el uso no debe tumbar la respuesta
                logger.warning(
                    "No se pudo registrar el uso de la herramienta generada '%s'.", tool_id
                )
        if not result.ok:
            return f"Error ejecutando la herramienta: {result.error}"
        return json.dumps(result.output)

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

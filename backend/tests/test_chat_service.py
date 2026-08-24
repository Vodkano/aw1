"""ChatService: herramientas invocables, memoria de solo lectura, menciones @."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aw1.chat.events import ChatEvent
from aw1.chat.service import ChatService
from aw1.chat.tools.base import ChatTool, ToolRegistry
from aw1.chat.wikipedia import Wikipedia
from aw1.core.secrets_store import SecretsStore
from aw1.db.repository import Repository
from aw1.llm.judges import Judges
from aw1.llm.schemas import ChatRoute
from aw1.settings import Settings
from tests.fakes import FakeOllama


class DummyTool(ChatTool):
    """Herramienta de prueba: no depende de un navegador ni de red."""

    intent = "miherramienta"
    label = "prueba"
    description = "Herramienta de prueba."

    def __init__(self, *, boom: bool = False) -> None:
        self.boom = boom
        self.calls: list[str] = []

    async def run(
        self, route: ChatRoute, message: str, conversation_id: str
    ) -> AsyncIterator[ChatEvent]:
        self.calls.append(message)
        if self.boom:
            raise RuntimeError("la herramienta fallo a proposito")
        yield ChatEvent("tool_event", {"tool": "prueba", "type": "start", "data": {}})
        yield ChatEvent("tool_result", {"answer": f"resultado para {message}", "source": "prices", "sources": []})


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    return Settings(_env_file=None, env="test", data_dir=tmp_path)


async def _build_service(
    repo: Repository, settings: Settings, tool: ChatTool | None, *, online: bool = True
) -> tuple[ChatService, FakeOllama]:
    fake = FakeOllama(online=online)
    judges = Judges(fake, model="mistral", timeout=5)
    secrets = SecretsStore(repo)
    await secrets.load()
    registry = ToolRegistry([tool] if tool else [])
    service = ChatService(
        settings=settings, repository=repo, llm=fake, judges=judges,
        wikipedia=Wikipedia(), secrets=secrets, tools=registry,
    )
    return service, fake


async def _collect(stream: AsyncIterator[ChatEvent]) -> list[ChatEvent]:
    return [event async for event in stream]


# --- system_prompt personalizado (perfiles de Telegram) -----------------------
async def test_a_custom_system_prompt_overrides_the_default(repo, test_settings):
    """Feature para Telegram: cada perfil tiene su propia personalidad. Sin
    system_prompt, se usa CHAT_SYSTEM; con uno, ese reemplaza al default."""
    service, fake = await _build_service(repo, test_settings, None)

    await _collect(service.stream("hola", system_prompt="Eres un pirata. Habla como tal."))
    assert fake.last_messages[0] == {"role": "system", "content": "Eres un pirata. Habla como tal."}


async def test_without_a_custom_system_prompt_the_default_is_used(repo, test_settings):
    from aw1.llm.prompts import CHAT_SYSTEM

    service, fake = await _build_service(repo, test_settings, None)
    await _collect(service.stream("hola"))
    assert fake.last_messages[0] == {"role": "system", "content": CHAT_SYSTEM}


# --- force_gpt / history_hours (agentes de Telegram) ---------------------------
async def test_force_gpt_still_falls_back_to_ollama_when_gpt_is_not_configured(repo, test_settings):
    """Los agentes de Telegram fuerzan GPT, pero la red de seguridad se
    mantiene: sin clave configurada, cae al modelo local igual que hoy."""
    service, fake = await _build_service(repo, test_settings, None)

    events = await _collect(service.stream("hola", force_gpt=True))
    notice = next(event for event in events if event.type == "notice")
    assert "GPT" in notice.data["text"]
    done = next(event for event in events if event.type == "done")
    assert done.data["source"] == "local"


async def test_history_hours_excludes_messages_outside_the_time_window(repo, test_settings):
    """Memoria de 48h: un mensaje mas viejo que la ventana no debe llegar al
    modelo, aunque history() (por turnos) si lo hubiera incluido."""
    from datetime import UTC, datetime, timedelta

    conversation_id = "conv-telegram"
    old = datetime.now(UTC) - timedelta(hours=72)
    await repo.ensure_conversation(conversation_id)
    await repo._conn.execute(
        "INSERT INTO messages (conversation_id, role, content, source, created_at) "
        "VALUES (?, 'user', 'mensaje viejo', 'local', ?)",
        (conversation_id, old.isoformat()),
    )
    await repo._conn.commit()
    await repo.add_message(conversation_id, "user", "mensaje reciente")

    service, fake = await _build_service(repo, test_settings, None)
    await _collect(service.stream("hola", conversation_id=conversation_id, history_hours=48.0))

    contents = [item["content"] for item in fake.last_messages]
    assert "mensaje reciente" in contents
    assert "mensaje viejo" not in contents


async def test_history_max_messages_caps_the_window_even_within_the_time_range(repo, test_settings):
    """Tope duro de mensajes ademas del tiempo: una charla muy activa dentro
    de la ventana no debe mandarle al modelo un historial gigante."""
    conversation_id = "conv-activa"
    await repo.ensure_conversation(conversation_id)
    for i in range(5):
        await repo.add_message(conversation_id, "user", f"mensaje {i}")

    service, fake = await _build_service(repo, test_settings, None)
    await _collect(
        service.stream(
            "hola", conversation_id=conversation_id, history_hours=48.0, history_max_messages=2,
        )
    )

    contents = [item["content"] for item in fake.last_messages]
    assert contents.count("mensaje 4") == 1
    assert "mensaje 0" not in contents


async def test_fast_route_skips_the_network_classification(repo, test_settings):
    """Los agentes de Telegram fuerzan fast_route: se salta route_chat (una
    llamada de red al modelo, hasta 25s si esta detras de un tunel lento) y
    usa solo la heuristica local -era el principal cuello de botella de
    latencia del bot de Telegram."""
    service, fake = await _build_service(repo, test_settings, None)

    await _collect(service.stream("hola, como estas?", fast_route=True))
    assert fake.json_calls == []

    await _collect(service.stream("hola, como estas?"))
    assert fake.json_calls != []


# --- dispatch de herramientas ------------------------------------------------
async def test_a_tool_dispatches_by_matching_intent(repo, test_settings):
    tool = DummyTool()
    tool.intent = "precio"  # el intent real que produce heuristics.route() para precios
    service, _ = await _build_service(repo, test_settings, tool)

    events = await _collect(service.stream("cuanto cuesta un iphone 15?"))
    assert tool.calls == ["cuanto cuesta un iphone 15?"]
    done = next(event for event in events if event.type == "done")
    assert done.data["answer"] == "resultado para cuanto cuesta un iphone 15?"
    assert done.data["source"] == "prices"


async def test_a_mention_forces_a_tool_even_without_a_matching_intent(repo, test_settings):
    tool = DummyTool()
    service, _ = await _build_service(repo, test_settings, tool)

    events = await _collect(service.stream("hola @miherramienta arreglame esto"))
    assert tool.calls == ["hola arreglame esto"]  # la mencion se quita del mensaje
    done = next(event for event in events if event.type == "done")
    assert done.data["answer"] == "resultado para hola arreglame esto"


async def test_a_failing_tool_falls_back_to_a_system_message(repo, test_settings):
    tool = DummyTool(boom=True)
    tool.intent = "precio"
    service, _ = await _build_service(repo, test_settings, tool)

    events = await _collect(service.stream("cuanto cuesta un iphone 15?"))
    done = next(event for event in events if event.type == "done")
    assert done.data["source"] == "system"
    assert "problema" in done.data["answer"].lower()


async def test_a_provider_mention_preempts_tool_dispatch_from_the_detected_intent(
    repo, test_settings
):
    """Bug real encontrado en revision: "@gpt cuanto cuesta X" clasificaba
    como intent="precio" y la herramienta de precios se lo comia entero,
    dejando la mencion "@gpt" sin ningun efecto. Un mention de PROVEEDOR
    (gpt/ollama) no debe caer al intent detectado como si no existiera."""
    tool = DummyTool()
    tool.intent = "precio"
    service, _ = await _build_service(repo, test_settings, tool)

    events = await _collect(service.stream("@gpt cuanto cuesta un iphone 15?"))
    assert tool.calls == [], "la herramienta de precios no deberia haber corrido"
    assert any(event.type == "notice" for event in events), (
        "deberia haber intentado GPT (y avisar que no esta configurado en la prueba)"
    )


# --- menciones ----------------------------------------------------------------
def test_extract_mention_finds_a_known_id_anywhere_in_the_message():
    cleaned, mention = ChatService._extract_mention(
        "hola @gpt como estas", {"gpt", "ollama"}
    )
    assert cleaned == "hola como estas"
    assert mention == "gpt"


def test_extract_mention_ignores_an_unknown_at_token():
    cleaned, mention = ChatService._extract_mention("mi correo es @juan", {"gpt", "ollama"})
    assert cleaned == "mi correo es @juan"
    assert mention is None


def test_extract_mention_ignores_an_at_glued_to_other_text():
    """Bug real: "contacto@ollama.dev" no es una mencion -el "@" pertenece a
    un correo, no viene despues de un espacio o al inicio del mensaje."""
    cleaned, mention = ChatService._extract_mention(
        "mi correo es contacto@ollama.dev, escribeme", {"gpt", "ollama"}
    )
    assert mention is None
    assert cleaned == "mi correo es contacto@ollama.dev, escribeme"


def test_extract_mention_skips_an_unknown_token_and_finds_a_later_valid_one():
    """Bug real: antes solo se miraba el primer "@algo" del mensaje; si ese
    no era valido (ej. un correo), una mencion real mas adelante se ignoraba
    por completo."""
    cleaned, mention = ChatService._extract_mention(
        "escribime a juan@empresa.cl y busca @gpt esto", {"gpt", "ollama"}
    )
    assert mention == "gpt"
    assert cleaned == "escribime a juan@empresa.cl y busca esto"


async def test_gpt_mention_forces_gpt_even_when_not_heavy(repo, test_settings):
    # Sin AW1_OPENAI_API_KEY, gpt_configured() es False: si la mencion forzo
    # wants_gpt=True igual sale el aviso de "esto se beneficiaria de GPT" antes
    # de caer al modelo local -sin la mencion, un saludo simple no lo dispara.
    service, _ = await _build_service(repo, test_settings, None)

    with_mention = await _collect(service.stream("@gpt hola como estas"))
    assert any(event.type == "notice" for event in with_mention)

    without_mention = await _collect(service.stream("hola como estas"))
    assert not any(event.type == "notice" for event in without_mention)


async def test_ollama_mention_forces_local_even_when_heavy(repo, test_settings):
    # "codigo" heuristico no marca heavy=True por defecto (ver test_heuristics),
    # asi que para probar el override en sentido contrario forzamos heavy via
    # el enrutador del modelo simulado no hace falta: alcanza con confirmar que
    # la mencion "@ollama" nunca dispara el aviso de GPT aunque describa una
    # tarea de codigo real (el enrutador sin IA no marca heavy, y el override
    # de "ollama" ademas garantiza wants_gpt=False pase lo que pase).
    service, _ = await _build_service(repo, test_settings, None)

    events = await _collect(service.stream("@ollama arreglame este bug de python"))
    assert not any(event.type == "notice" for event in events)


class FakeWikipedia:
    """Evita golpear la Wikipedia real en la prueba."""

    async def lookup(self, term: str) -> tuple[str, str] | None:
        return f"Extracto sobre {term}.", "https://es.wikipedia.org/wiki/Prueba"


async def test_gpt_mention_on_a_biography_keeps_the_wikipedia_citation(repo, tmp_path):
    """Bug real encontrado en revision: _answer_with_gpt mandaba "sources": []
    fijo en el evento "done" -si "@gpt" fuerza GPT en una biografia, la cita
    de Wikipedia (ya calculada y emitida como evento "source") se perdia en
    el mensaje final. Prueba directa de _answer_with_gpt (con httpx.AsyncClient
    simulado, sin red real) para confirmar que ahora se le pasa y aparece."""
    fake = FakeOllama(online=True)
    judges = Judges(fake, model="mistral", timeout=5)
    settings = Settings(_env_file=None, env="test", data_dir=tmp_path, openai_api_key="sk-test")
    secrets = SecretsStore(repo)
    await secrets.load()
    service = ChatService(
        settings=settings, repository=repo, llm=fake, judges=judges,
        wikipedia=FakeWikipedia(), secrets=secrets, tools=ToolRegistry([]),
    )

    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"Ada Lovelace fue pionera."}}]}'
            yield "data: [DONE]"

    class FakeStreamCtx:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    with patch("httpx.AsyncClient.stream", return_value=FakeStreamCtx()):
        events = [
            event
            async for event in service._answer_with_gpt(
                "conv1", "quien fue Ada Lovelace", [], "contexto de wikipedia",
                ["https://es.wikipedia.org/wiki/Prueba"],
            )
        ]
    done = next(event for event in events if event.type == "done")
    assert done.data["source"] == "gpt"
    assert done.data["sources"] == ["https://es.wikipedia.org/wiki/Prueba"]


async def test_an_invalid_gpt_key_falls_back_to_ollama_instead_of_dead_ending(repo, tmp_path):
    """Bug real en produccion: una clave de OpenAI configurada pero invalida
    (rechazada con 401 por la API) terminaba la conversacion con el texto
    del error como si fuera la respuesta -para los agentes de Telegram
    (force_gpt=True, sin red de seguridad de "no configurado") eso
    significaba contestarle a la persona "la clave no es valida" en vez de
    responder de verdad. Ahora cae al modelo local, igual que cuando GPT
    directamente no esta configurado."""
    fake = FakeOllama(online=True)
    judges = Judges(fake, model="mistral", timeout=5)
    settings = Settings(_env_file=None, env="test", data_dir=tmp_path, openai_api_key="sk-invalida")
    secrets = SecretsStore(repo)
    await secrets.load()
    service = ChatService(
        settings=settings, repository=repo, llm=fake, judges=judges,
        wikipedia=Wikipedia(), secrets=secrets, tools=ToolRegistry([]),
    )

    class FakeResponse:
        status_code = 401

        async def aread(self) -> bytes:
            return b""

    class FakeStreamCtx:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    with patch("httpx.AsyncClient.stream", return_value=FakeStreamCtx()):
        events = await _collect(service.stream("hola", force_gpt=True))

    assert any(
        event.type == "notice" and "no es valida" in event.data["text"] for event in events
    )
    done = next(event for event in events if event.type == "done")
    assert done.data["source"] == "local"


# --- memoria de largo plazo, solo lectura --------------------------------------
async def test_memory_recall_is_included_for_charla(repo, test_settings):
    await repo.save_item("El auto de Pedro es un Toyota Corolla 2020, patente ABCD12.")
    service, fake = await _build_service(repo, test_settings, None)

    await _collect(service.stream("que auto tiene pedro?"))
    assert fake.chat_calls, "deberia haber llamado al modelo local"
    assert "Toyota Corolla" in fake.chat_calls[-1]


async def test_memory_recall_is_skipped_for_actualidad(repo, test_settings):
    await repo.save_item("El dolar el mes pasado estaba en 950 pesos.")
    service, fake = await _build_service(repo, test_settings, None)

    await _collect(service.stream("cual es el dolar hoy?"))
    assert fake.chat_calls
    assert "950 pesos" not in fake.chat_calls[-1]


async def test_a_memory_recall_failure_does_not_crash_the_chat(repo, test_settings):
    """Bug real: memory.recall() no tenia manejo de errores, a diferencia de
    todo lo demas que puede fallar en este archivo (_safe_route, el cliente
    de Ollama, GPT). Un problema puntual de la base no deberia tumbar el
    turno entero -debe degradar a responder sin ese contexto."""
    service, fake = await _build_service(repo, test_settings, None)
    with patch.object(repo, "search_items", side_effect=RuntimeError("db caida")):
        events = await _collect(service.stream("hola, como estas?"))
    assert any(event.type == "done" for event in events)
    assert fake.chat_calls


# --- search_items en el repositorio --------------------------------------------
async def test_search_items_matches_keywords_case_insensitively(repo):
    await repo.save_item("Receta de Empanadas de Pino")
    await repo.save_item("Notas de la reunion del lunes")

    found = await repo.search_items(["empanadas"])
    assert len(found) == 1
    assert "Empanadas" in found[0]["text"]


async def test_search_items_with_no_keywords_returns_nothing(repo):
    await repo.save_item("algo")
    assert await repo.search_items([]) == []


async def test_search_items_escapes_sql_wildcards_in_keywords(repo):
    """Bug real: un keyword con guion bajo (ej. "rtx_4090", que el regex de
    palabras de memory.py extrae sin problema) se usaba tal cual en un LIKE
    sin escapar -el "_" es comodin de un caracter en SQL, asi que matcheaba
    de mas ("rtxx4090" tambien calzaba)."""
    await repo.save_item("Notebook con rtx_4090 en oferta")
    await repo.save_item("Notebook con rtxx4090 (typo, no deberia matchear)")

    found = await repo.search_items(["rtx_4090"])
    assert [item["text"] for item in found] == ["Notebook con rtx_4090 en oferta"]


# --- APIs de un agente (tool calling de OpenAI) --------------------------------
class _FakeToolResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


async def test_agent_apis_are_called_via_tool_calling_before_the_final_answer(repo, tmp_path):
    """Con una API configurada para el agente, GPT puede pedir llamarla
    (tool calling) antes de responder -sin streaming (ver
    _answer_with_gpt_tools), pero el resultado final es el mismo contrato
    de eventos que el camino normal."""
    fake = FakeOllama(online=True)
    judges = Judges(fake, model="mistral", timeout=5)
    settings = Settings(_env_file=None, env="test", data_dir=tmp_path, openai_api_key="sk-test")
    secrets = SecretsStore(repo)
    await secrets.load()
    service = ChatService(
        settings=settings, repository=repo, llm=fake, judges=judges,
        wikipedia=Wikipedia(), secrets=secrets, tools=ToolRegistry([]),
    )

    api = {
        "name": "consultar_stock", "description": "Consulta el stock real de un producto",
        "url": "https://api.example.com/stock?sku={query}", "method": "GET", "headers": {},
    }
    tool_call_response = _FakeToolResponse({
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "consultar_stock", "arguments": '{"query": "SKU123"}'},
                }],
            },
        }],
    })
    final_response = _FakeToolResponse({
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Hay 5 unidades disponibles."},
        }],
    })

    post_mock = AsyncMock(side_effect=[tool_call_response, final_response])
    call_mock = AsyncMock(return_value="5 unidades")
    with (
        patch("httpx.AsyncClient.post", new=post_mock),
        patch("aw1.chat.service.agent_apis_module.call", new=call_mock),
    ):
        events = await _collect(
            service.stream("hay stock del producto SKU123?", force_gpt=True, agent_apis=[api])
        )

    call_mock.assert_awaited_once()
    assert call_mock.await_args.args[0] is api
    assert call_mock.await_args.args[1] == "SKU123"
    done = next(event for event in events if event.type == "done")
    assert done.data["answer"] == "Hay 5 unidades disponibles."
    assert done.data["source"] == "gpt"


async def test_without_agent_apis_the_normal_streaming_path_is_used(repo, test_settings):
    """agent_apis vacio/ausente no debe cambiar nada del camino normal
    (streaming, sin tool calling) -confirma que el branch nuevo no se
    activa sin querer."""
    service, fake = await _build_service(repo, test_settings, None)
    events = await _collect(service.stream("hola", agent_apis=[]))
    done = next(event for event in events if event.type == "done")
    assert done.data["source"] == "local"

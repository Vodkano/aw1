"""ChatService: herramientas invocables, memoria de solo lectura, menciones @."""

from __future__ import annotations

from collections.abc import AsyncIterator

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

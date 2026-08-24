"""Telegram: cliente de la API de bots, y el store de agentes/tokens (un
agente puede tener varios tokens/bots; un token es de un solo agente)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aw1.core.errors import NotFoundError, ValidationError
from aw1.core.telegram_store import TelegramStore
from aw1.settings import Settings
from aw1.telegram.client import TelegramClient, _split_message


# --- TelegramClient: _split_message (pura, sin red) ----------------------------
def test_split_message_returns_a_single_chunk_when_short():
    assert _split_message("hola") == ["hola"]


def test_split_message_returns_nothing_for_empty_text():
    assert _split_message("   ") == []


def test_split_message_splits_long_text_under_the_chunk_limit():
    long_text = "palabra " * 1000  # bien sobre los 4000 caracteres
    chunks = _split_message(long_text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == long_text.replace(" ", "")


# --- TelegramClient: llamadas HTTP, con httpx mockeado (sin red real) ----------
class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


async def test_get_me_returns_the_bot_info_on_success():
    client = TelegramClient()
    fake_response = _FakeResponse({"ok": True, "result": {"id": 1, "username": "aw1s_bot"}})
    with patch.object(client._client, "get", new=AsyncMock(return_value=fake_response)):
        info = await client.get_me("fake-token")
    assert info == {"id": 1, "username": "aw1s_bot"}
    await client.aclose()


async def test_get_me_returns_none_when_telegram_rejects_the_token():
    client = TelegramClient()
    fake_response = _FakeResponse({"ok": False, "error_code": 401})
    with patch.object(client._client, "get", new=AsyncMock(return_value=fake_response)):
        info = await client.get_me("bad-token")
    assert info is None
    await client.aclose()


async def test_send_message_splits_and_paces_long_replies():
    client = TelegramClient()
    calls: list[dict[str, Any]] = []

    async def fake_post(url: str, json: dict[str, Any]) -> _FakeResponse:
        calls.append(json)
        return _FakeResponse({"ok": True})

    long_text = "palabra " * 1000
    with (
        patch.object(client._client, "post", new=fake_post),
        patch("aw1.telegram.client.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        await client.send_message("fake-token", 123, long_text)
    assert len(calls) > 1
    assert all(call["chat_id"] == 123 for call in calls)
    assert sleep_mock.await_count == len(calls) - 1
    await client.aclose()


# --- TelegramStore: agentes y tokens --------------------------------------------
class FakeTelegramClient:
    """Doble de TelegramClient: nunca pega a la red real."""

    def __init__(self, *, bot_username: str = "aw1s_bot") -> None:
        self.bot_username = bot_username
        self.webhooks_set: list[tuple[str, str, str]] = []
        self.sent: list[tuple[str, Any, str]] = []
        self.typing_calls: list[tuple[str, Any]] = []

    async def get_me(self, token: str) -> dict[str, Any] | None:
        if token == "bad-token":
            return None
        return {"id": 1, "username": self.bot_username}

    async def set_webhook(self, token: str, url: str, secret_token: str) -> bool:
        self.webhooks_set.append((token, url, secret_token))
        return True

    async def delete_webhook(self, token: str) -> bool:
        return True

    async def send_message(self, token: str, chat_id: Any, text: str) -> None:
        self.sent.append((token, chat_id, text))

    async def send_chat_action(self, token: str, chat_id: Any, action: str = "typing") -> None:
        self.typing_calls.append((token, chat_id))


@pytest.fixture
def telegram_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None, env="test", data_dir=tmp_path,
        public_base_url="https://app.aw1s.online",
    )


async def _make_token(
    repo, telegram_settings, *, system_prompt: str = "", bot_token: str = "123:ABC"
) -> tuple[TelegramStore, dict[str, Any]]:
    """Crea un agente y un token, y devuelve el token YA UNIDO con los
    campos del agente -la misma forma que usa el camino caliente del
    webhook (TelegramStore.get_cached_token)."""
    store = TelegramStore(repo, FakeTelegramClient(), telegram_settings)
    agent = await store.create_agent(label="Bot", system_prompt=system_prompt)
    created = await store.create_token(agent["id"], bot_token)
    token = store.get_cached_token(created["id"])
    assert token is not None
    return store, token


async def test_create_token_registers_the_webhook_and_hides_it_in_the_agent_list(
    repo, telegram_settings
):
    store, token = await _make_token(repo, telegram_settings)
    assert token["bot_username"] == "aw1s_bot"

    agents = store.list_agents()
    assert len(agents) == 1
    assert len(agents[0]["tokens"]) == 1
    assert "bot_token" not in agents[0]["tokens"][0]
    assert agents[0]["tokens"][0]["token_preview"] == "23:ABC"


async def test_an_agent_can_have_more_than_one_token(repo, telegram_settings):
    """La regla de negocio: un agente puede tener varios tokens (bots); un
    token es de un solo agente."""
    store, _first = await _make_token(repo, telegram_settings, bot_token="111:AAA")
    agent_id = _first["agent_id"]
    await store.create_token(agent_id, "222:BBB")

    agents = store.list_agents()
    assert len(agents) == 1
    assert len(agents[0]["tokens"]) == 2


async def test_create_token_rejects_one_already_used_by_another_agent(repo, telegram_settings):
    store, token = await _make_token(repo, telegram_settings, bot_token="123:ABC")
    other_agent = await store.create_agent(label="Otro", system_prompt="")

    with pytest.raises(ValidationError, match="ya lo usa"):
        await store.create_token(other_agent["id"], "123:ABC")


async def test_create_token_rejects_one_telegram_does_not_recognize(repo, telegram_settings):
    store = TelegramStore(repo, FakeTelegramClient(), telegram_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    with pytest.raises(ValidationError, match="rechazo el token"):
        await store.create_token(agent["id"], "bad-token")


async def test_get_agent_returns_a_row_the_admin_api_schema_accepts(repo, telegram_settings):
    from aw1.api.schemas import TelegramAgentSummary

    store, token = await _make_token(repo, telegram_settings)
    detail = await store.get_agent(token["agent_id"])
    assert detail is not None
    TelegramAgentSummary(**detail)  # no debe lanzar


async def test_create_agent_does_not_require_a_public_base_url(repo, tmp_path):
    """El agente (el prompt/personalidad) no necesita webhook; solo agregarle
    un token si lo necesita -recien ahi hace falta AW1_PUBLIC_BASE_URL."""
    settings = Settings(_env_file=None, env="test", data_dir=tmp_path)
    store = TelegramStore(repo, FakeTelegramClient(), settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    assert agent["id"]

    with pytest.raises(ValidationError, match="AW1_PUBLIC_BASE_URL"):
        await store.create_token(agent["id"], "123:ABC")


# --- TelegramStore: archivos y APIs de un agente --------------------------------
async def test_add_file_extracts_text_and_lists_it_under_the_agent(repo, telegram_settings):
    store = TelegramStore(repo, FakeTelegramClient(), telegram_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")

    row = await store.add_file(agent["id"], "menu.txt", "Empanada de pino: $2000".encode())
    assert row["content"] == "Empanada de pino: $2000"
    assert row["char_count"] == len(row["content"])

    files = store.list_files(agent["id"])
    assert [f["filename"] for f in files] == ["menu.txt"]

    assert await store.delete_file(row["id"]) is True
    assert store.list_files(agent["id"]) == []


async def test_add_file_rejects_an_unknown_agent(repo, telegram_settings):
    store = TelegramStore(repo, FakeTelegramClient(), telegram_settings)
    with pytest.raises(NotFoundError):
        await store.add_file("no-existe", "menu.txt", b"hola")


async def test_create_api_normalizes_the_method_and_can_be_toggled(repo, telegram_settings):
    # La validacion de la URL en si (rechazar redes privadas) es
    # responsabilidad de core.netguard.normalize -ya cubierta en
    # test_agent_apis.py- y create_api solo la reusa.
    store = TelegramStore(repo, FakeTelegramClient(), telegram_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")

    api = await store.create_api(
        agent["id"], name="stock", description="Consulta stock real",
        url="https://api.example.com/stock", method="get", headers={"X-Key": "abc"},
    )
    assert api["method"] == "GET"
    assert api["enabled"] is True
    assert store.list_apis(agent["id"]) == [api]

    disabled = await store.set_api_enabled(api["id"], False)
    assert disabled["enabled"] is False

    assert await store.delete_api(api["id"]) is True
    assert store.list_apis(agent["id"]) == []


async def test_get_cached_token_includes_files_and_only_enabled_apis(repo, telegram_settings):
    store, token = await _make_token(repo, telegram_settings)
    await store.add_file(token["agent_id"], "menu.txt", b"Empanada: $2000")
    enabled_api = await store.create_api(
        token["agent_id"], name="activa", description="d", url="https://api.example.com/a",
        method="GET", headers={},
    )
    disabled_api = await store.create_api(
        token["agent_id"], name="inactiva", description="d", url="https://api.example.com/b",
        method="GET", headers={},
    )
    await store.set_api_enabled(disabled_api["id"], False)

    cached = store.get_cached_token(token["id"])
    assert cached is not None
    assert [f["filename"] for f in cached["files"]] == ["menu.txt"]
    assert [a["id"] for a in cached["apis"]] == [enabled_api["id"]]


# --- TelegramOrchestrator: deteccion de URLs y seguimiento de precios ----------
class FakeChatService:
    """Doble de ChatService: registra con que parametros se la llamo, sin
    tocar ningun modelo real."""

    def __init__(self, *, answer: str = "ok") -> None:
        self.calls: list[dict[str, Any]] = []
        self.answer = answer

    async def stream(self, message, *, conversation_id=None, system_prompt=None, force_gpt=False,
                      history_hours=None, fast_route=False, agent_apis=None):
        self.calls.append(
            {
                "message": message, "system_prompt": system_prompt, "force_gpt": force_gpt,
                "history_hours": history_hours, "fast_route": fast_route,
                "agent_apis": agent_apis,
            }
        )
        from aw1.chat.events import ChatEvent

        yield ChatEvent("done", {"answer": self.answer})


class FakePricePipeline:
    """Doble de PricePipeline.read_price: devuelve una oferta fija por URL,
    sin abrir ningun navegador."""

    def __init__(self, offers_by_url: dict[str, Any]) -> None:
        self.offers_by_url = offers_by_url

    async def read_price(self, url: str, product_label: str = "") -> Any:
        return self.offers_by_url.get(url)


def _offer(url: str, store: str, price_clp: float) -> Any:
    from aw1.pricing.models import Offer

    return Offer(
        store=store, store_slug=store.lower(), domain=url, url=url, title="Zeta 12",
        price=price_clp, price_clp=price_clp, price_label=f"${price_clp:,.0f}",
    )


async def _make_orchestrator(repo, telegram_settings, *, store, chat=None, prices=None, client=None):
    from aw1.core.secrets_store import SecretsStore
    from aw1.telegram.orchestrator import TelegramOrchestrator

    secrets = SecretsStore(repo)
    await secrets.load()
    return TelegramOrchestrator(
        tokens=store, client=client or FakeTelegramClient(),
        chat=chat or FakeChatService(), prices=prices or FakePricePipeline({}),
        repo=repo, settings=telegram_settings, secrets=secrets,
    )


async def test_a_message_with_urls_registers_a_watch_instead_of_chatting(repo, telegram_settings):
    store, token = await _make_token(repo, telegram_settings)
    client = FakeTelegramClient()
    prices = FakePricePipeline({
        "https://a.cl/p": _offer("https://a.cl/p", "Tienda A", 549990),
        "https://b.cl/p": _offer("https://b.cl/p", "Tienda B", 479990),
    })
    chat = FakeChatService()
    orchestrator = await _make_orchestrator(repo, telegram_settings, store=store, chat=chat,
                                       prices=prices, client=client)

    update = {
        "message": {
            "chat": {"id": 999},
            "text": "siguela aca: https://a.cl/p y https://b.cl/p",
        }
    }
    await orchestrator._handle(token, update)

    assert chat.calls == []
    watches = await repo.list_price_watches()
    assert len(watches) == 1
    assert watches[0]["urls"] == ["https://a.cl/p", "https://b.cl/p"]
    assert watches[0]["last_price_clp"] == 479990.0
    assert watches[0]["last_best_url"] == "https://b.cl/p"
    assert client.sent


async def test_a_message_without_urls_goes_through_the_normal_chat_path(repo, telegram_settings):
    store, token = await _make_token(repo, telegram_settings, system_prompt="Vende zapatillas.")
    client = FakeTelegramClient()
    chat = FakeChatService()
    orchestrator = await _make_orchestrator(repo, telegram_settings, store=store, chat=chat, client=client)

    update = {"message": {"chat": {"id": 999}, "text": "hola, como estas?"}}
    await orchestrator._handle(token, update)

    assert len(chat.calls) == 1
    call = chat.calls[0]
    assert call["force_gpt"] is True
    assert call["history_hours"] == 48.0
    assert call["fast_route"] is True
    # El prompt final es base + personalidad + lo propio del agente, no solo
    # lo que escribio el admin.
    assert "Vende zapatillas." in call["system_prompt"]
    assert "atencion al cliente" in call["system_prompt"]
    assert client.sent == [("123:ABC", 999, "ok")]
    assert client.typing_calls  # "escribiendo..." mientras se generaba la respuesta


async def test_a_close_sentinel_from_the_model_mutes_the_chat(repo, telegram_settings):
    """Si el modelo detecta mala intencion y agrega el sentinel de cierre,
    el orquestador lo saca del texto, mutea el chat y NO vuelve a llamar al
    modelo en el siguiente mensaje de ese mismo chat -asi se ahorran tokens."""
    from aw1.llm.prompts import TELEGRAM_CLOSE_SENTINEL

    store, token = await _make_token(repo, telegram_settings)
    client = FakeTelegramClient()
    chat = FakeChatService(answer=f"No puedo ayudarte con eso.\n{TELEGRAM_CLOSE_SENTINEL}")
    orchestrator = await _make_orchestrator(repo, telegram_settings, store=store, chat=chat, client=client)

    update = {"message": {"chat": {"id": 999}, "text": "mensaje abusivo"}}
    await orchestrator._handle(token, update)

    assert len(chat.calls) == 1
    assert TELEGRAM_CLOSE_SENTINEL not in client.sent[-1][2]
    assert await repo.get_telegram_mute(token["id"], "999") is not None

    # Segundo mensaje del mismo chat: no debe llamar al modelo de nuevo.
    await orchestrator._handle(token, {"message": {"chat": {"id": 999}, "text": "hola de nuevo"}})
    assert len(chat.calls) == 1
    assert len(client.sent) == 2


async def test_a_non_text_message_gets_a_reply_instead_of_silence(repo, telegram_settings):
    """Una foto, nota de voz o sticker no trae "text" -antes esto se
    descartaba en silencio y la persona se quedaba sin ninguna respuesta."""
    from aw1.telegram.orchestrator import _NON_TEXT_REPLY

    store, token = await _make_token(repo, telegram_settings)
    client = FakeTelegramClient()
    chat = FakeChatService()
    orchestrator = await _make_orchestrator(
        repo, telegram_settings, store=store, chat=chat, client=client
    )

    update = {"message": {"chat": {"id": 999}, "photo": [{"file_id": "abc"}]}}
    await orchestrator._handle(token, update)

    assert chat.calls == []
    assert client.sent == [("123:ABC", 999, _NON_TEXT_REPLY)]


async def test_a_message_flagged_by_moderation_is_muted_without_calling_gpt(
    repo, telegram_settings
):
    """La API de moderacion de OpenAI (gratis, casi instantanea) corre
    antes de gastar la llamada completa a GPT -si marca el mensaje, se
    corta ahi mismo, sin ni siquiera pasar por ChatService."""
    from aw1.core.moderation import ModerationResult
    from aw1.telegram.orchestrator import _MODERATED_REPLY

    store, token = await _make_token(repo, telegram_settings)
    client = FakeTelegramClient()
    chat = FakeChatService()
    orchestrator = await _make_orchestrator(
        repo, telegram_settings, store=store, chat=chat, client=client
    )

    flagged = AsyncMock(return_value=ModerationResult(flagged=True, categories=["harassment"]))
    with patch("aw1.telegram.orchestrator.moderation.check", flagged):
        update = {"message": {"chat": {"id": 999}, "text": "mensaje feo"}}
        await orchestrator._handle(token, update)

    assert chat.calls == []
    assert client.sent == [("123:ABC", 999, _MODERATED_REPLY)]
    assert await repo.get_telegram_mute(token["id"], "999") is not None


async def test_an_unexpected_error_still_replies_instead_of_leaving_silence(
    repo, telegram_settings
):
    """Antes, un fallo fuera del camino de chat normal (un bug no previsto
    en el registro de un seguimiento de precio, por ejemplo) no tenia
    ningun manejo: la tarea de fondo terminaba en silencio y la persona se
    quedaba sin respuesta. Ahora todo el cuerpo esta bajo un mismo
    try/except que siempre contesta algo."""
    from aw1.telegram.orchestrator import _ERROR_REPLY

    class BoomChatService:
        async def stream(self, *args, **kwargs):
            raise RuntimeError("boom")
            yield  # pragma: no cover - nunca se ejecuta, hace de esto un generador

    store, token = await _make_token(repo, telegram_settings)
    client = FakeTelegramClient()
    orchestrator = await _make_orchestrator(
        repo, telegram_settings, store=store, chat=BoomChatService(), client=client
    )

    await orchestrator._handle(token, {"message": {"chat": {"id": 999}, "text": "hola"}})

    assert client.sent == [("123:ABC", 999, _ERROR_REPLY)]


async def test_price_watch_loop_notifies_only_when_the_winner_changes(repo, telegram_settings):
    store, token = await _make_token(repo, telegram_settings)
    await repo.create_price_watch("watch1", token["id"], "999", "Zeta 12", ["https://a.cl/p"])

    client = FakeTelegramClient()
    prices = FakePricePipeline({"https://a.cl/p": _offer("https://a.cl/p", "Tienda A", 549990)})
    orchestrator = await _make_orchestrator(repo, telegram_settings, store=store, prices=prices,
                                       client=client)

    await orchestrator._check_all_watches()
    assert len(client.sent) == 1  # primer chequeo: no habia precio previo -> avisa

    await orchestrator._check_all_watches()
    assert len(client.sent) == 1  # mismo resultado -> no un segundo aviso

    prices.offers_by_url["https://a.cl/p"] = _offer("https://a.cl/p", "Tienda A", 399990)
    await orchestrator._check_all_watches()
    assert len(client.sent) == 2  # bajo el precio -> avisa de nuevo

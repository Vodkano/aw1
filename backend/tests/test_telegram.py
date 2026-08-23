"""Telegram: cliente de la API de bots, y el store de perfiles (cada perfil
ES un bot independiente, con su propio token)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aw1.core.errors import ValidationError
from aw1.core.telegram_profiles_store import TelegramProfileStore
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


# --- TelegramProfileStore -------------------------------------------------------
class FakeTelegramClient:
    """Doble de TelegramClient: nunca pega a la red real."""

    def __init__(self, *, bot_username: str = "aw1s_bot") -> None:
        self.bot_username = bot_username
        self.webhooks_set: list[tuple[str, str, str]] = []

    async def get_me(self, token: str) -> dict[str, Any] | None:
        if token == "bad-token":
            return None
        return {"id": 1, "username": self.bot_username}

    async def set_webhook(self, token: str, url: str, secret_token: str) -> bool:
        self.webhooks_set.append((token, url, secret_token))
        return True

    async def delete_webhook(self, token: str) -> bool:
        return True


@pytest.fixture
def telegram_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None, env="test", data_dir=tmp_path,
        public_base_url="https://app.aw1s.online",
    )


async def test_create_registers_the_webhook_and_hides_the_token_in_list(repo, telegram_settings):
    store = TelegramProfileStore(repo, FakeTelegramClient(), telegram_settings)
    row = await store.create(label="Bot personal", bot_token="123:ABC", system_prompt="Eres util.")

    assert row["bot_username"] == "aw1s_bot"
    assert row["webhook_registered"] is True

    summaries = store.list()
    assert len(summaries) == 1
    assert "bot_token" not in summaries[0]
    assert summaries[0]["token_preview"] == "23:ABC"


async def test_create_rejects_a_token_already_used_by_another_profile(repo, telegram_settings):
    store = TelegramProfileStore(repo, FakeTelegramClient(), telegram_settings)
    await store.create(label="Bot uno", bot_token="123:ABC", system_prompt="")

    with pytest.raises(ValidationError, match="ya lo usa"):
        await store.create(label="Bot dos", bot_token="123:ABC", system_prompt="")


async def test_create_rejects_a_token_telegram_does_not_recognize(repo, telegram_settings):
    store = TelegramProfileStore(repo, FakeTelegramClient(), telegram_settings)
    with pytest.raises(ValidationError, match="rechazo el token"):
        await store.create(label="Bot", bot_token="bad-token", system_prompt="")


async def test_get_returns_a_row_the_admin_api_schema_accepts(repo, telegram_settings):
    """Bug real: get() devolvia la fila cruda de la base, sin token_preview
    -un campo calculado que TelegramProfileDetail exige (via
    TelegramProfileSummary) y que rompia GET /telegram-profiles/{id} con un
    error de validacion apenas se intentaba abrir un perfil ya creado."""
    from aw1.api.schemas import TelegramProfileDetail

    store = TelegramProfileStore(repo, FakeTelegramClient(), telegram_settings)
    created = await store.create(label="Bot", bot_token="123:ABC", system_prompt="hola")

    detail = await store.get(created["id"])
    assert detail is not None
    TelegramProfileDetail(**detail)  # no debe lanzar


async def test_create_requires_a_public_base_url(repo, tmp_path):
    settings = Settings(_env_file=None, env="test", data_dir=tmp_path)
    store = TelegramProfileStore(repo, FakeTelegramClient(), settings)
    with pytest.raises(ValidationError, match="AW1_PUBLIC_BASE_URL"):
        await store.create(label="Bot", bot_token="123:ABC", system_prompt="")

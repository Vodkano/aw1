"""Configuracion y persistencia."""

import asyncio

import pytest
from pydantic import ValidationError as PydanticError

from aw1.settings import Settings


def test_production_token_is_optional_but_must_be_valid_if_set():
    # Sin token: el chat y el comparador de precios son de uso libre por diseno.
    assert not Settings(_env_file=None, env="production").auth_enabled
    with pytest.raises(PydanticError, match="AW1_API_TOKEN"):
        Settings(_env_file=None, env="production", api_token="corto")
    assert Settings(_env_file=None, env="production", api_token="x" * 32).auth_enabled


def test_production_refuses_the_private_host_escape_hatch():
    with pytest.raises(PydanticError, match="ALLOW_PRIVATE_HOSTS"):
        Settings(_env_file=None, env="production", api_token="x" * 32, allow_private_hosts=True)


def test_rates_are_parsed_and_clp_is_pinned():
    settings = Settings(_env_file=None, fx_rates_to_clp='{"clp": 7, "usd": 900}')
    assert settings.fx_rates_to_clp == {"CLP": 1.0, "USD": 900.0}


def test_origins_accept_a_comma_separated_string():
    settings = Settings(_env_file=None, allowed_origins="http://a.cl, http://b.cl")
    assert settings.allowed_origins == ["http://a.cl", "http://b.cl"]


def test_the_judge_model_falls_back_to_the_main_model():
    assert Settings(_env_file=None, ollama_model="mistral").judge_model == "mistral"
    assert (
        Settings(_env_file=None, ollama_model="mistral", ollama_fast_model="qwen2.5:1.5b").judge_model
        == "qwen2.5:1.5b"
    )


def test_the_api_key_never_appears_in_the_repr():
    settings = Settings(_env_file=None, openai_api_key="sk-no-debe-verse")
    assert "sk-no-debe-verse" not in repr(settings)
    assert settings.gpt_configured is True


# --- repositorio ------------------------------------------------------------
async def test_saved_items_are_listed_newest_first(repo):
    await repo.save_item("primero")
    await repo.save_item("segundo", kind="offer", meta={"url": "https://t.cl"})
    items = await repo.list_items()
    assert [item["text"] for item in items] == ["segundo", "primero"]
    assert items[0]["meta"]["url"] == "https://t.cl"


async def test_the_item_cap_is_enforced(repo):
    for index in range(6):
        await repo.save_item(f"nota {index}", max_items=3)
    assert await repo.count_items() == 3


async def test_history_is_ordered_and_limited(repo):
    for index in range(5):
        await repo.add_message("conv", "user", f"p{index}")
        await repo.add_message("conv", "assistant", f"r{index}")
    history = await repo.history("conv", turns=2)
    assert [turn["content"] for turn in history] == ["p3", "r3", "p4", "r4"]


async def test_history_since_only_returns_messages_inside_the_time_window(repo):
    """Memoria de 48h de los agentes de Telegram: history_since filtra por
    tiempo, no por cantidad de turnos como history()."""
    from datetime import UTC, datetime, timedelta

    await repo.add_message("conv", "user", "viejo")
    old = datetime.now(UTC) - timedelta(hours=72)
    await repo._conn.execute(
        "UPDATE messages SET created_at = ? WHERE content = 'viejo'", (old.isoformat(),)
    )
    await repo._conn.commit()
    await repo.add_message("conv", "user", "reciente")

    since = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    history = await repo.history_since("conv", since)
    assert [turn["content"] for turn in history] == ["reciente"]


async def test_history_since_caps_at_max_messages(repo):
    for index in range(5):
        await repo.add_message("conv", "user", f"p{index}")
    since = "2000-01-01T00:00:00+00:00"
    history = await repo.history_since("conv", since, max_messages=2)
    assert len(history) == 2
    assert history[-1]["content"] == "p4"


async def _make_token(repo, *, agent_id: str = "agent1", token_id: str = "tok1"):
    await repo.create_telegram_agent(agent_id, "Bot", "", "calida")
    return await repo.create_telegram_token(
        token_id, agent_id, "123:ABC", "hash1", "aw1s_bot", "secret"
    )


async def test_telegram_agent_and_token_round_trip(repo):
    agent = await repo.create_telegram_agent("agent1", "Bot", "Se breve.", "directa")
    assert agent["personality"] == "directa"

    token = await repo.create_telegram_token(
        "tok1", "agent1", "123:ABC", "hash1", "aw1s_bot", "secret"
    )
    assert token["agent_id"] == "agent1"
    assert await repo.get_telegram_token_by_hash("hash1") == token

    tokens = await repo.list_telegram_tokens("agent1")
    assert [item["id"] for item in tokens] == ["tok1"]

    updated = await repo.update_telegram_agent(
        "agent1", label="Bot renombrado", system_prompt="Nuevo prompt.", enabled=False
    )
    assert updated["label"] == "Bot renombrado"
    assert updated["enabled"] is False

    disabled = await repo.set_telegram_token_enabled("tok1", False)
    assert disabled["enabled"] is False

    assert await repo.delete_telegram_token("tok1") is True
    assert await repo.list_telegram_tokens("agent1") == []
    assert await repo.delete_telegram_agent("agent1") is True


async def test_telegram_mute_round_trips(repo):
    from datetime import UTC, datetime, timedelta

    await _make_token(repo)
    assert await repo.get_telegram_mute("tok1", "999") is None

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    await repo.mute_telegram_chat("tok1", "999", "abuso", future)
    mute = await repo.get_telegram_mute("tok1", "999")
    assert mute["reason"] == "abuso"

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    await repo.mute_telegram_chat("tok1", "999", "vencido", past)
    assert await repo.get_telegram_mute("tok1", "999") is None


async def test_price_watch_round_trips(repo):
    await _make_token(repo)
    watch = await repo.create_price_watch(
        "watch1", "tok1", "999", "Zeta 12", ["https://a.cl/p", "https://b.cl/p"]
    )
    assert watch["last_price_clp"] is None

    watches = await repo.list_price_watches()
    assert len(watches) == 1
    assert watches[0]["urls"] == ["https://a.cl/p", "https://b.cl/p"]

    await repo.update_price_watch_result("watch1", 549990.0, "https://a.cl/p")
    watches = await repo.list_price_watches()
    assert watches[0]["last_price_clp"] == 549990.0
    assert watches[0]["last_best_url"] == "https://a.cl/p"

    assert await repo.delete_price_watch("watch1") is True
    assert await repo.list_price_watches() == []


async def test_list_price_watches_excludes_disabled_ones_by_default(repo):
    await _make_token(repo)
    await repo.create_price_watch("watch1", "tok1", "999", "Zeta 12", ["https://a.cl/p"])
    await repo._conn.execute("UPDATE price_watches SET enabled = 0 WHERE id = 'watch1'")
    await repo._conn.commit()

    assert await repo.list_price_watches(enabled_only=True) == []
    assert len(await repo.list_price_watches(enabled_only=False)) == 1


async def test_reasoning_round_trips_and_stays_internal(repo):
    reasoning_id = await repo.save_reasoning("conv", "chat_route", "hola", {"intent": "charla"})
    stored = await repo.get_reasoning(reasoning_id)
    assert stored["payload"]["intent"] == "charla"


async def test_deleting_a_conversation_cascades(repo):
    await repo.add_message("conv", "user", "hola")
    await repo.save_reasoning("conv", "chat_route", "hola", {})
    await repo.delete_conversation("conv")
    assert await repo.history("conv") == []


async def test_conversations_list_only_shows_the_ones_with_messages(repo):
    await repo.ensure_conversation("vacia")
    await repo.add_message("llena", "user", "hola")
    ids = [item["id"] for item in await repo.conversations()]
    assert ids == ["llena"]


async def test_the_cache_expires(repo):
    await repo.cache_set("k", {"v": 1}, ttl=1)
    assert await repo.cache_get("k") == {"v": 1}
    await asyncio.sleep(1.1)
    assert await repo.cache_get("k") is None


async def test_a_zero_ttl_disables_the_cache(repo):
    await repo.cache_set("k", {"v": 1}, ttl=0)
    assert await repo.cache_get("k") is None


async def test_purge_only_touches_known_tables(repo):
    await repo.save_item("nota")
    removed = await repo.purge(["saved_items", "tabla_inventada"])
    assert removed == {"saved_items": 1}

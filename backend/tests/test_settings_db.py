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

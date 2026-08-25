"""Herramientas generadas por IA: la maquina de estados completa
(PROPOSED -> GENERATING -> PENDING_APPROVAL -> ACTIVE|REJECTED), siempre
con un click humano antes de cada paso -nunca automatico."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aw1.core.errors import NotFoundError, ValidationError
from aw1.core.secrets_store import SecretsStore
from aw1.core.telegram_store import TelegramStore
from aw1.settings import Settings


class _FakeTelegramClient:
    async def get_me(self, token: str):
        return {"id": 1, "username": "bot"}

    async def set_webhook(self, token, url, secret_token):
        return True

    async def delete_webhook(self, token):
        return True


@pytest.fixture
def gt_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None, env="test", data_dir=tmp_path, openai_api_key="sk-test",
        public_base_url="https://app.aw1s.online",
    )


async def _make_store(repo, settings) -> TelegramStore:
    secrets = SecretsStore(repo)
    await secrets.load()
    return TelegramStore(repo, _FakeTelegramClient(), settings, secrets)


async def test_create_generated_tool_starts_as_proposed(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")

    tool = await store.create_generated_tool(agent["id"], name="dolar", description="Consulta el dolar")
    assert tool["status"] == "PROPOSED"
    assert store.get_generated_tool(tool["id"]) == tool


async def test_create_generated_tool_rejects_an_unknown_agent(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    with pytest.raises(NotFoundError):
        await store.create_generated_tool("no-existe", name="x", description="x")


async def test_generate_tool_code_requires_openai_to_be_configured(repo, tmp_path):
    settings = Settings(_env_file=None, env="test", data_dir=tmp_path)  # sin openai_api_key
    store = await _make_store(repo, settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="dolar", description="Consulta el dolar")

    with pytest.raises(ValidationError, match="GPT no esta configurado"):
        await store.generate_tool_code(tool["id"])


async def test_generate_tool_code_moves_proposed_to_generating(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="dolar", description="Consulta el dolar")

    spec = {"parameters": {"type": "object", "properties": {}, "required": []}, "example_inputs": [{}]}
    code = "def run(input: dict) -> dict:\n    return {'valor': 950}\n"
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch("aw1.core.telegram_store.code_agent.generate_code", new=AsyncMock(return_value=(code, "tests"))),
    ):
        updated = await store.generate_tool_code(tool["id"])

    assert updated["status"] == "GENERATING"
    assert updated["code"] == code
    assert store.get_generated_tool(tool["id"])["status"] == "GENERATING"


async def test_generate_tool_code_rejects_a_tool_that_already_has_code(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="dolar", description="x")
    spec = {"parameters": {}, "example_inputs": [{}]}
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch("aw1.core.telegram_store.code_agent.generate_code", new=AsyncMock(return_value=("code", "t"))),
    ):
        await store.generate_tool_code(tool["id"])

    with pytest.raises(ValidationError):
        await store.generate_tool_code(tool["id"])


async def test_test_generated_tool_moves_to_pending_approval_when_the_sandbox_passes(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="dolar", description="x")
    spec = {"parameters": {}, "example_inputs": [{}]}
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch(
            "aw1.core.telegram_store.code_agent.generate_code",
            new=AsyncMock(return_value=("def run(input: dict) -> dict:\n    return {'valor': 950}\n", "t")),
        ),
    ):
        await store.generate_tool_code(tool["id"])

    tested = await store.test_generated_tool(tool["id"])
    assert tested["status"] == "PENDING_APPROVAL"
    assert tested["sandbox_result"]["ok"] is True


async def test_test_generated_tool_rejects_when_the_sandbox_fails(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="malo", description="x")
    spec = {"parameters": {}, "example_inputs": [{}]}
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch(
            "aw1.core.telegram_store.code_agent.generate_code",
            new=AsyncMock(return_value=("def run(input: dict) -> dict:\n    return 1 / 0\n", "t")),
        ),
    ):
        await store.generate_tool_code(tool["id"])

    tested = await store.test_generated_tool(tool["id"])
    assert tested["status"] == "REJECTED"
    assert tested["sandbox_result"]["ok"] is False


async def test_cannot_test_a_tool_that_has_no_code_yet(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="x", description="x")
    with pytest.raises(ValidationError):
        await store.test_generated_tool(tool["id"])


async def test_approve_requires_pending_approval_status(repo, gt_settings):
    """El corazon de la maquina de estados: nada llega a ACTIVE sin pasar
    primero por la prueba de sandbox, sin importar que tan simple parezca."""
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="x", description="x")

    with pytest.raises(ValidationError):
        await store.approve_generated_tool(tool["id"])


async def test_approve_activates_the_tool_and_it_becomes_visible_to_the_webhook(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    token = await store.create_token(agent["id"], "123:ABC")
    tool = await store.create_generated_tool(agent["id"], name="dolar", description="x")
    spec = {"parameters": {}, "example_inputs": [{}]}
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch(
            "aw1.core.telegram_store.code_agent.generate_code",
            new=AsyncMock(return_value=("def run(input: dict) -> dict:\n    return {'v': 1}\n", "t")),
        ),
    ):
        await store.generate_tool_code(tool["id"])
    await store.test_generated_tool(tool["id"])

    # Antes de aprobar: la herramienta NO se ofrece en el camino caliente.
    cached_before = store.get_cached_token(token["id"])
    assert cached_before["generated_tools"] == []

    approved = await store.approve_generated_tool(tool["id"])
    assert approved["status"] == "ACTIVE"

    # Aprobada: el cache se actualizo al toque, sin reiniciar nada.
    cached_after = store.get_cached_token(token["id"])
    assert [t["id"] for t in cached_after["generated_tools"]] == [tool["id"]]


async def test_reject_a_pending_tool(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="x", description="x")
    spec = {"parameters": {}, "example_inputs": [{}]}
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch(
            "aw1.core.telegram_store.code_agent.generate_code",
            new=AsyncMock(return_value=("def run(input: dict) -> dict:\n    return {}\n", "t")),
        ),
    ):
        await store.generate_tool_code(tool["id"])
    await store.test_generated_tool(tool["id"])

    rejected = await store.reject_generated_tool(tool["id"], "no hace falta")
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "no hace falta"


async def test_cannot_reject_an_already_active_tool(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="x", description="x")
    spec = {"parameters": {}, "example_inputs": [{}]}
    with (
        patch("aw1.core.telegram_store.tool_designer.design_spec", new=AsyncMock(return_value=spec)),
        patch(
            "aw1.core.telegram_store.code_agent.generate_code",
            new=AsyncMock(return_value=("def run(input: dict) -> dict:\n    return {}\n", "t")),
        ),
    ):
        await store.generate_tool_code(tool["id"])
    await store.test_generated_tool(tool["id"])
    await store.approve_generated_tool(tool["id"])

    with pytest.raises(ValidationError):
        await store.reject_generated_tool(tool["id"])


async def test_delete_generated_tool(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    tool = await store.create_generated_tool(agent["id"], name="x", description="x")

    assert await store.delete_generated_tool(tool["id"]) is True
    assert store.get_generated_tool(tool["id"]) is None


async def test_list_capability_gaps_cross_references_a_tool_already_created(repo, gt_settings):
    store = await _make_store(repo, gt_settings)
    agent = await store.create_agent(label="Bot", system_prompt="")
    gap_id = await repo.save_reasoning(
        None, "capability_gap", "cual es el dolar?",
        {"agent_id": agent["id"], "name": "dolar", "description": "x", "why": "y", "triggering_message": "z"},
    )

    gaps_before = await store.list_capability_gaps()
    assert gaps_before[0]["tool_id"] is None

    tool = await store.create_generated_tool(
        agent["id"], name="dolar", description="x", source_gap_reasoning_id=gap_id,
    )
    gaps_after = await store.list_capability_gaps()
    assert gaps_after[0]["tool_id"] == tool["id"]
    assert gaps_after[0]["tool_status"] == "PROPOSED"

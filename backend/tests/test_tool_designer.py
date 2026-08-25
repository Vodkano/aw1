"""Tool Designer: convierte un pedido de capacidad en una especificacion
tecnica -no escribe codigo (eso es core/code_agent.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aw1.core import llm_client, tool_designer
from aw1.core.errors import ProviderError

_GAP = {
    "name": "consultar_dolar_hoy",
    "description": "Consultar el valor del dolar observado",
    "why": "El cliente pregunto cuanto esta el dolar",
    "triggering_message": "cual es el dolar hoy?",
}


async def test_design_spec_returns_the_parsed_specification():
    completion = llm_client.Completion(
        text='{"parameters": {"type": "object", "properties": {}, "required": []}, '
        '"example_inputs": [{}], "summary": "Consulta el dolar de hoy"}',
        prompt_tokens=10, completion_tokens=20, total_tokens=30,
    )
    with patch("aw1.core.tool_designer.llm_client.complete", new=AsyncMock(return_value=completion)):
        spec = await tool_designer.design_spec(_GAP, api_key="sk-test", base_url="https://x", model="gpt-4o-mini")
    assert spec["parameters"] == {"type": "object", "properties": {}, "required": []}
    assert spec["example_inputs"] == [{}]


async def test_the_gap_text_is_wrapped_as_untrusted_data():
    """El pedido lo escribio quien le hablo al bot -no puede colarse como
    si fueran instrucciones para el modelo que disena la especificacion."""
    completion = llm_client.Completion(
        text='{"parameters": {}, "example_inputs": [{}]}',
        prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    complete_mock = AsyncMock(return_value=completion)
    with patch("aw1.core.tool_designer.llm_client.complete", new=complete_mock):
        await tool_designer.design_spec(_GAP, api_key="sk-test", base_url="https://x", model="m")

    messages = complete_mock.await_args.args[0]
    user_message = messages[-1]["content"]
    assert "<<<DATOS>>>" in user_message
    assert _GAP["description"] in user_message


async def test_design_spec_raises_when_gpt_returns_no_parameters():
    completion = llm_client.Completion(
        text='{"summary": "algo"}', prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    with patch("aw1.core.tool_designer.llm_client.complete", new=AsyncMock(return_value=completion)):
        with pytest.raises(ProviderError):
            await tool_designer.design_spec(_GAP, api_key="sk-test", base_url="https://x", model="m")


async def test_design_spec_raises_on_unparseable_json():
    completion = llm_client.Completion(
        text="esto no es json", prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    with patch("aw1.core.tool_designer.llm_client.complete", new=AsyncMock(return_value=completion)):
        with pytest.raises(ProviderError):
            await tool_designer.design_spec(_GAP, api_key="sk-test", base_url="https://x", model="m")

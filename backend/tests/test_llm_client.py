"""llm_client: llamada compartida a GPT para el codigo nuevo del sistema
de agentes auto-extensibles -a diferencia de los otros 5 lugares que ya
llaman a OpenAI en el proyecto, esta registra el uso de tokens."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aw1.core import llm_client
from aw1.core.errors import ProviderError


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


async def test_complete_extracts_the_token_usage():
    payload = {
        "choices": [{"message": {"content": "hola"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(200, payload))):
        completion = await llm_client.complete(
            [{"role": "user", "content": "hola"}], api_key="sk-test", base_url="https://x", model="m",
        )
    assert completion.text == "hola"
    assert completion.prompt_tokens == 12
    assert completion.completion_tokens == 3
    assert completion.total_tokens == 15


async def test_json_mode_sets_the_response_format():
    payload = {"choices": [{"message": {"content": "{}"}}], "usage": {}}
    post_mock = AsyncMock(return_value=_FakeResponse(200, payload))
    with patch("httpx.AsyncClient.post", new=post_mock):
        await llm_client.complete(
            [{"role": "user", "content": "hola"}], api_key="sk-test", base_url="https://x",
            model="m", json_mode=True,
        )
    sent_payload = post_mock.await_args.kwargs["json"]
    assert sent_payload["response_format"] == {"type": "json_object"}


async def test_complete_raises_on_a_non_200_status():
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(401, {"error": {}}))):
        with pytest.raises(ProviderError):
            await llm_client.complete(
                [{"role": "user", "content": "hola"}], api_key="bad", base_url="https://x", model="m",
            )


async def test_parse_json_object_strips_markdown_fences():
    parsed = llm_client.parse_json_object('```json\n{"a": 1}\n```')
    assert parsed == {"a": 1}


async def test_parse_json_object_raises_on_invalid_json():
    with pytest.raises(ProviderError):
        llm_client.parse_json_object("no es json")


async def test_parse_json_object_raises_when_the_top_level_is_not_an_object():
    with pytest.raises(ProviderError):
        llm_client.parse_json_object("[1, 2, 3]")

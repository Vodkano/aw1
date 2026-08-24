"""Generacion de imagenes via la API de OpenAI (DALL-E), invocada como
herramienta por los agentes de Telegram."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aw1.core import image_gen

_URL = "https://api.openai.com/v1"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


async def test_generate_returns_the_image_url_on_success():
    payload = {"data": [{"url": "https://cdn.openai.com/img.png"}]}
    fake = AsyncMock(return_value=_FakeResponse(200, payload))
    with patch("httpx.AsyncClient.post", new=fake):
        url = await image_gen.generate(
            "un gato", api_key="sk-test", base_url=_URL, model="dall-e-3"
        )
    assert url == "https://cdn.openai.com/img.png"


async def test_generate_raises_on_a_non_200_status():
    fake = AsyncMock(return_value=_FakeResponse(400, {}))
    with patch("httpx.AsyncClient.post", new=fake):
        with pytest.raises(RuntimeError, match="400"):
            await image_gen.generate("un gato", api_key="sk-test", base_url=_URL, model="dall-e-3")


async def test_generate_raises_when_the_response_has_no_image():
    fake = AsyncMock(return_value=_FakeResponse(200, {"data": []}))
    with patch("httpx.AsyncClient.post", new=fake):
        with pytest.raises(RuntimeError):
            await image_gen.generate("un gato", api_key="sk-test", base_url=_URL, model="dall-e-3")

"""Llamada en vivo a una API externa configurada para un agente."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from aw1.core import agent_apis
from aw1.core.agent_apis import tool_name


def test_tool_name_only_keeps_safe_characters():
    assert tool_name("consultar stock (real)") == "consultar_stock__real"


def test_tool_name_falls_back_when_nothing_survives():
    assert tool_name("???") == "api"


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


async def test_call_returns_the_response_body_on_success():
    api = {"name": "clima", "url": "https://api.example.com/clima", "method": "GET"}
    fake = AsyncMock(return_value=_FakeResponse(200, "18 grados, despejado"))
    with (
        patch("httpx.AsyncClient.request", new=fake),
        patch("aw1.core.agent_apis.asyncio.to_thread", new=AsyncMock(return_value=True)),
    ):
        result = await agent_apis.call(api, "")
    assert result == "18 grados, despejado"


async def test_call_substitutes_the_query_placeholder_in_the_url():
    api = {"name": "stock", "url": "https://api.example.com/stock?sku={query}", "method": "GET"}
    captured: dict[str, Any] = {}

    async def fake_request(self: object, method: str, url: str, headers: dict[str, str]) -> _FakeResponse:
        captured["url"] = url
        return _FakeResponse(200, "5 unidades")

    with (
        patch("httpx.AsyncClient.request", new=fake_request),
        patch("aw1.core.agent_apis.asyncio.to_thread", new=AsyncMock(return_value=True)),
    ):
        await agent_apis.call(api, "ABC123")
    assert captured["url"] == "https://api.example.com/stock?sku=ABC123"


async def test_call_refuses_a_url_pointing_at_a_private_ip():
    api = {"name": "interna", "url": "http://192.168.1.1/admin", "method": "GET"}
    result = await agent_apis.call(api, "")
    assert "no es valida" in result.lower()


async def test_call_refuses_a_host_that_no_longer_resolves_to_a_public_ip():
    """Defensa contra DNS rebinding: aunque la URL en si es valida (no es
    un literal de IP privada), se vuelve a resolver el host en cada
    llamada -si para entonces apunta a la red local, se corta igual."""
    api = {"name": "externa", "url": "https://api.example.com/datos", "method": "GET"}
    with patch("aw1.core.agent_apis.asyncio.to_thread", new=AsyncMock(return_value=False)):
        result = await agent_apis.call(api, "")
    assert "segura" in result.lower()


async def test_call_reports_an_http_error_status_without_raising():
    api = {"name": "roto", "url": "https://api.example.com/roto", "method": "GET"}
    fake = AsyncMock(return_value=_FakeResponse(500, "internal error"))
    with (
        patch("httpx.AsyncClient.request", new=fake),
        patch("aw1.core.agent_apis.asyncio.to_thread", new=AsyncMock(return_value=True)),
    ):
        result = await agent_apis.call(api, "")
    assert "500" in result


async def test_call_never_raises_on_a_network_error():
    api = {"name": "caida", "url": "https://api.example.com/caida", "method": "GET"}

    async def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
        import httpx

        raise httpx.ConnectError("no se pudo conectar")

    with (
        patch("httpx.AsyncClient.request", new=fake_request),
        patch("aw1.core.agent_apis.asyncio.to_thread", new=AsyncMock(return_value=True)),
    ):
        result = await agent_apis.call(api, "")
    assert "no se pudo contactar" in result.lower()

"""Busqueda web general (@buscar): Brave Search API y la herramienta de chat
que la envuelve."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from aw1.chat.tools.websearch import WebSearchTool
from aw1.core import websearch
from aw1.core.secrets_store import SecretsStore
from aw1.llm.schemas import ChatRoute
from aw1.settings import Settings

_URL = "https://api.search.brave.com/res/v1/web/search"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _secrets(value: str | None = None) -> SecretsStore:
    store = SecretsStore(repo=None)
    if value is not None:
        store._cache["brave_search_api_key"] = value
    return store


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, env="test", data_dir=tmp_path)


def _route() -> ChatRoute:
    return ChatRoute(intent="buscar", confidence=0.5, reason="prueba")


async def _run(tool: WebSearchTool, message: str) -> dict:
    events = [event async for event in tool.run(_route(), message, "conv-1")]
    assert len(events) == 1
    assert events[0].type == "tool_result"
    return events[0].data


async def test_search_returns_title_url_and_snippet_for_each_result():
    payload = {
        "web": {
            "results": [
                {
                    "title": "Zapatillas Zeta 12",
                    "url": "https://tienda.cl/zeta12",
                    "description": "Modelo running, tallas 38 a 45.",
                }
            ]
        }
    }
    fake = AsyncMock(return_value=_FakeResponse(200, payload))
    with patch("httpx.AsyncClient.get", new=fake):
        results = await websearch.search("zeta 12", api_key="clave", base_url=_URL)
    assert len(results) == 1
    assert results[0].title == "Zapatillas Zeta 12"
    assert results[0].url == "https://tienda.cl/zeta12"
    assert results[0].snippet == "Modelo running, tallas 38 a 45."


async def test_search_skips_results_missing_a_title_or_a_url():
    payload = {"web": {"results": [{"title": "", "url": "https://x.cl"}, {"title": "ok", "url": ""}]}}
    fake = AsyncMock(return_value=_FakeResponse(200, payload))
    with patch("httpx.AsyncClient.get", new=fake):
        results = await websearch.search("algo", api_key="clave", base_url=_URL)
    assert results == []


async def test_search_raises_on_a_non_200_status():
    fake = AsyncMock(return_value=_FakeResponse(401, {}))
    with patch("httpx.AsyncClient.get", new=fake):
        try:
            await websearch.search("algo", api_key="mala", base_url=_URL)
        except RuntimeError as error:
            assert "401" in str(error)
        else:
            raise AssertionError("deberia haber lanzado RuntimeError")


async def test_the_tool_asks_to_configure_a_key_when_none_is_set(tmp_path):
    tool = WebSearchTool(_settings(tmp_path), _secrets())
    data = await _run(tool, "zapatillas para correr")
    assert "clave" in data["answer"].lower()
    assert data["sources"] == []


async def test_the_tool_formats_results_as_links_with_their_snippet(tmp_path):
    payload = {
        "web": {
            "results": [
                {"title": "Zeta 12", "url": "https://a.cl/zeta12", "description": "Zapatilla running."},
                {"title": "Zeta 12 review", "url": "https://b.cl/review", "description": ""},
            ]
        }
    }
    fake = AsyncMock(return_value=_FakeResponse(200, payload))
    tool = WebSearchTool(_settings(tmp_path), _secrets("clave-valida"))
    with patch("httpx.AsyncClient.get", new=fake):
        data = await _run(tool, "zeta 12")
    assert "[Zeta 12](https://a.cl/zeta12): Zapatilla running." in data["answer"]
    assert "[Zeta 12 review](https://b.cl/review)" in data["answer"]
    assert data["sources"] == ["https://a.cl/zeta12", "https://b.cl/review"]


async def test_the_tool_reports_no_results_without_treating_it_as_an_error(tmp_path):
    fake = AsyncMock(return_value=_FakeResponse(200, {"web": {"results": []}}))
    tool = WebSearchTool(_settings(tmp_path), _secrets("clave-valida"))
    with patch("httpx.AsyncClient.get", new=fake):
        data = await _run(tool, "algo muy raro")
    assert "no encontre" in data["answer"].lower()


async def test_the_tool_recovers_from_a_search_failure_instead_of_crashing_the_chat(tmp_path):
    async def fake_get(self: object, *args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(500, {})

    tool = WebSearchTool(_settings(tmp_path), _secrets("clave-valida"))
    with patch("httpx.AsyncClient.get", new=fake_get):
        data = await _run(tool, "algo")
    assert "no pude buscar" in data["answer"].lower()

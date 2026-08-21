"""La capa HTTP contra la aplicacion ASGI real."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from aw1.api.app import create_app
from aw1.settings import Settings


async def test_healthz_is_public(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_status_describes_every_dependency(client):
    payload = (await client.get("/api/status")).json()
    assert payload["version"]
    assert payload["env"] == "test"
    assert "browser" in payload
    assert "model_ready" in payload


async def test_security_headers_are_always_present(client):
    headers = (await client.get("/healthz")).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-request-id"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": ""}, {"message": 123}, {"message": "hola", "extra": 1}, {"message": "x" * 5000}],
)
async def test_bad_chat_payloads_get_400(client, payload):
    response = await client.post("/api/chat", json=payload)
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.parametrize(
    "payload", [{}, {"query": ""}, {"query": "x" * 300}, {"query": "iphone", "extra": True}]
)
async def test_bad_price_payloads_get_400(client, payload):
    assert (await client.post("/api/prices/compare", json=payload)).status_code == 400


async def test_the_store_catalog_is_served(client):
    stores = (await client.get("/api/prices/stores")).json()["stores"]
    slugs = {store["slug"] for store in stores}
    assert {"mercadolibre", "falabella", "ripley", "paris"} <= slugs


async def test_the_memory_lifecycle(client):
    created = await client.post("/api/memory", json={"text": "recordar esto"})
    assert created.status_code == 201
    item_id = created.json()["id"]

    assert (await client.get("/api/memory")).json()["total"] == 1
    assert (await client.delete(f"/api/memory/{item_id}")).status_code == 200
    assert (await client.delete(f"/api/memory/{item_id}")).status_code == 404


async def test_purge_everything_empties_the_database(client):
    await client.post("/api/memory", json={"text": "uno"})
    assert (await client.delete("/api/memory?everything=true")).status_code == 200
    assert (await client.get("/api/memory")).json()["total"] == 0


async def test_an_offer_can_be_saved_with_its_link(client):
    created = await client.post(
        "/api/memory",
        json={"text": "Zeta 12", "kind": "offer", "meta": {"url": "https://t.cl/p/1"}},
    )
    assert created.json()["meta"]["url"] == "https://t.cl/p/1"


async def test_a_missing_conversation_is_404(client):
    assert (await client.get("/api/chat/no-existe")).status_code == 404


async def test_the_price_search_streams_sse(client):
    """El contrato del stream: eventos con nombre y JSON, terminando en done."""
    async with client.stream(
        "POST", "/api/prices/search", json={"query": "zeta 12 256gb"}
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        seen = []
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                seen.append(line.split(":", 1)[1].strip())
            if seen and seen[-1] in {"done", "error"}:
                break
    assert seen[0] == "start"
    assert "plan" in seen
    assert seen[-1] in {"done", "error"}


async def test_the_stream_payloads_are_valid_json(client):
    async with client.stream("POST", "/api/prices/search", json={"query": "zeta 12"}) as response:
        payloads = []
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                payloads.append(json.loads(line.split(":", 1)[1].strip()))
            if len(payloads) >= 3:
                break
    assert all(isinstance(item, dict) for item in payloads)


async def test_an_unknown_api_route_is_404(client):
    assert (await client.get("/api/no-existe")).status_code == 404


# --- seguridad --------------------------------------------------------------
def secured_app(tmp_path, **overrides):
    return create_app(
        Settings(
            _env_file=None,
            env="test",
            data_dir=tmp_path,
            api_token="t" * 32,
            allowed_origins=["http://127.0.0.1:8000"],
            **overrides,
        )
    )


async def run_with(app, call):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        async with app.router.lifespan_context(app):
            return await call(http)


async def test_a_token_is_required_when_configured(tmp_path):
    app = secured_app(tmp_path)

    async def check(http):
        assert (await http.get("/api/memory")).status_code == 401
        good = await http.get("/api/memory", headers={"Authorization": "Bearer " + "t" * 32})
        assert good.status_code == 200
        bad = await http.get("/api/memory", headers={"Authorization": "Bearer malo"})
        assert bad.status_code == 401

    await run_with(app, check)


async def test_the_token_can_travel_in_the_query_for_sse(tmp_path):
    """EventSource no permite cabeceras: se acepta ?token= para ese caso."""
    app = secured_app(tmp_path)

    async def check(http):
        response = await http.get(f"/api/prices/recent?token={'t' * 32}")
        assert response.status_code == 200

    await run_with(app, check)


async def test_status_stays_public(tmp_path):
    app = secured_app(tmp_path)
    await run_with(app, lambda http: http.get("/api/status"))


async def test_a_foreign_origin_is_rejected(tmp_path):
    app = secured_app(tmp_path)

    async def check(http):
        response = await http.post(
            "/api/memory",
            json={"text": "hola"},
            headers={
                "Origin": "https://malicioso.example",
                "Authorization": "Bearer " + "t" * 32,
            },
        )
        assert response.status_code == 401

    await run_with(app, check)


async def test_the_rate_limit_kicks_in(tmp_path):
    app = secured_app(tmp_path, rate_limit_per_minute=3)
    headers = {"Authorization": "Bearer " + "t" * 32}

    async def check(http):
        return [(await http.get("/api/memory", headers=headers)).status_code for _ in range(5)]

    codes = await run_with(app, check)
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]

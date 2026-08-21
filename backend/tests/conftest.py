"""Fixtures compartidas.

Ninguna prueba necesita Ollama ni internet. El navegador si es real: se levanta
Chromium contra una tienda simulada que se sirve en localhost, porque probar el
comparador sin navegador no probaria nada de lo que importa.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from aw1.api.app import create_app
from aw1.browser.pool import BrowserPool
from aw1.core import netguard
from aw1.db.repository import Repository
from aw1.settings import Settings
from tests.fixtures.store import FakeStore


@pytest.fixture(scope="session")
def store() -> Iterator[FakeStore]:
    """Tienda simulada, compartida por toda la sesion de pruebas."""
    with FakeStore() as running:
        yield running


@pytest.fixture
def settings(tmp_path, store: FakeStore) -> Settings:
    netguard.set_allow_private_hosts(True)
    return Settings(
        _env_file=None,
        env="test",
        data_dir=tmp_path,
        allow_private_hosts=True,
        demo_store_url=store.base,
        stores_per_search=1,
        cache_ttl_seconds=0,
        browser_max_contexts=2,
        search_budget_seconds=60,
    )


@pytest_asyncio.fixture
async def repo(settings: Settings) -> AsyncIterator[Repository]:
    repository = Repository(settings.database_path)
    await repository.connect()
    try:
        yield repository
    finally:
        await repository.close()


@pytest_asyncio.fixture
async def browser() -> AsyncIterator[BrowserPool]:
    """Chromium real, uno por prueba.

    Compartirlo entre pruebas seria mas rapido, pero una fixture asincrona de
    sesion obliga a fijar el ambito del event loop en todo el proyecto y eso
    hace fragil el resto de la bateria. Arrancar Chromium cuesta ~1 s: se paga.
    """
    netguard.set_allow_private_hosts(True)
    pool = BrowserPool(
        Settings(_env_file=None, env="test", allow_private_hosts=True, browser_max_contexts=2)
    )
    await pool.start()
    if not pool.ready:
        pytest.skip("Chromium no esta instalado (playwright install chromium)")
    try:
        yield pool
    finally:
        await pool.stop()


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        async with app.router.lifespan_context(app):
            yield http

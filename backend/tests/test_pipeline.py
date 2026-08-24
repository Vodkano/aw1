"""El pipeline completo: navegador real + IA simulada.

Recorre de punta a punta buscar -> elegir -> leer ficha -> decidir precio ->
rankear, contra la tienda que se pinta con JavaScript.
"""

import asyncio

import pytest

from aw1.core.errors import NoResultsError, ValidationError
from aw1.llm.judges import Judges
from aw1.pricing.pipeline import PricePipeline
from aw1.settings import Settings
from tests import fakes


def make_pipeline(settings: Settings, browser, llm=None, repo=None) -> PricePipeline:
    ai = llm or fakes.FakeOllama(
        json_by_marker={
            fakes.PLAN_MARKER: fakes.plan_payload("Smartphone Zeta 12 256GB", ["256"]),
            fakes.CANDIDATES_MARKER: fakes.pick_first(2),
            fakes.PAGE_MARKER: fakes.choose_candidate("Precio internet"),
        },
        text_reply="El mas barato esta en Tienda Demo a $549.990.",
    )
    return PricePipeline(
        settings=settings, browser=browser, judges=Judges(ai, model="mistral"), repository=repo
    )


async def test_end_to_end_with_the_model_deciding(settings, browser):
    result = await make_pipeline(settings, browser).compare("zeta 12 256gb")

    assert result.product == "Smartphone Zeta 12 256GB"
    assert result.offers
    best = result.offers[0]
    assert best.store == "Tienda Demo"
    assert best.url.endswith("/producto/2") or best.url.endswith("/producto/1")
    assert best.price_clp == best.price
    assert best.decided_by == "ia"
    # El precio elegido es el de venta, no el tachado ni la cuota.
    assert all(offer.price_clp in {549990.0, 479990.0} for offer in result.offers)


async def test_the_link_points_to_the_exact_product_page(settings, browser):
    result = await make_pipeline(settings, browser).compare("zeta 12 256gb")
    for offer in result.offers:
        assert "/producto/" in offer.url
        assert offer.title


async def test_accessories_are_discarded(settings, browser):
    """Con una consulta amplia la funda SI aparece en el buscador, y se descarta."""
    llm = fakes.FakeOllama(
        json_by_marker={
            fakes.PLAN_MARKER: fakes.plan_payload("Zeta 12", []),
            fakes.CANDIDATES_MARKER: fakes.pick_first(2),
            fakes.PAGE_MARKER: fakes.choose_candidate("Precio internet"),
        }
    )
    result = await make_pipeline(settings, browser, llm=llm).compare("zeta 12")
    assert all("Funda" not in offer.title for offer in result.offers)
    assert result.discarded >= 1


async def test_it_still_works_without_ollama(settings, browser):
    """Sin IA el comparador degrada a heuristica, no se cae."""
    result = await make_pipeline(settings, browser, llm=fakes.FakeOllama(online=False)).compare(
        "zeta 12"
    )
    assert result.offers
    assert all(offer.decided_by == "heuristica" for offer in result.offers)
    assert result.ai["fallbacks"] > 0


async def test_the_events_describe_the_progress(settings, browser):
    seen: list[str] = []
    async for event in make_pipeline(settings, browser).run("zeta 12 256gb"):
        seen.append(event.type)

    assert seen[0] == "start"
    assert "plan" in seen
    assert "store_start" in seen
    assert "store_cards" in seen
    assert "store_picked" in seen
    assert "offer" in seen
    assert "store_done" in seen
    assert seen[-1] == "done"


async def test_offers_arrive_before_the_final_result(settings, browser):
    """La interfaz debe poder pintar precios sin esperar a que termine todo."""
    first_offer_at: int | None = None
    done_at: int | None = None
    for index, event in enumerate(
        [event async for event in make_pipeline(settings, browser).run("zeta 12 256gb")]
    ):
        if event.type == "offer" and first_offer_at is None:
            first_offer_at = index
        if event.type == "done":
            done_at = index
    assert first_offer_at is not None
    assert done_at is not None
    assert first_offer_at < done_at


@pytest.mark.parametrize("query", ["", "   ", "x" * 200])
async def test_invalid_queries_are_rejected(settings, browser, query):
    with pytest.raises(ValidationError):
        await make_pipeline(settings, browser).compare(query)


async def test_a_product_that_does_not_exist_says_so(settings, browser):
    llm = fakes.FakeOllama(
        json_by_marker={
            fakes.PLAN_MARKER: fakes.plan_payload("Tractor Hidraulico XYZ", ["tractor"]),
            fakes.CANDIDATES_MARKER: {"picks": [], "discarded_reason": "nada coincide"},
        }
    )
    with pytest.raises(NoResultsError):
        await make_pipeline(settings, browser, llm=llm).compare("tractor hidraulico xyz")


async def test_the_cache_avoids_a_second_round_trip(settings, browser, repo):
    cached_settings = settings.model_copy(update={"cache_ttl_seconds": 300})
    pipeline = make_pipeline(cached_settings, browser, repo=repo)

    first = await pipeline.compare("zeta 12 256gb")
    second = await pipeline.compare("zeta 12 256gb")

    assert first.from_cache is False
    assert second.from_cache is True
    assert second.offers[0].url == first.offers[0].url


async def test_refresh_skips_the_cache(settings, browser, repo):
    cached_settings = settings.model_copy(update={"cache_ttl_seconds": 300})
    pipeline = make_pipeline(cached_settings, browser, repo=repo)
    await pipeline.compare("zeta 12 256gb")
    again = await pipeline.compare("zeta 12 256gb", refresh=True)
    assert again.from_cache is False


async def test_the_time_budget_is_enforced(settings, browser):
    """Ninguna busqueda puede quedarse colgada indefinidamente."""
    tight = settings.model_copy(update={"search_budget_seconds": 6.0})
    pipeline = make_pipeline(tight, browser)

    original = pipeline._offer_from

    async def slow(store, plan, pick):
        await asyncio.sleep(30)
        return await original(store, plan, pick)

    pipeline._offer_from = slow
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(NoResultsError):
        await pipeline.compare("zeta 12 256gb")
    assert loop.time() - started < 15


async def test_the_search_is_recorded_in_history(settings, browser, repo):
    await make_pipeline(settings, browser, repo=repo).compare("zeta 12 256gb")
    history = await repo.recent_searches()
    assert history
    assert history[0]["query"] == "zeta 12 256gb"


async def test_read_price_reads_one_url_the_user_already_chose(settings, browser):
    """Lo usa el seguimiento de precios de los bots de Telegram: la persona
    ya eligio la pagina (no hay busqueda ni plan de por medio), asi que
    read_price debe leer el precio directo con solo la URL."""
    llm = fakes.FakeOllama(
        json_by_marker={fakes.PAGE_MARKER: fakes.choose_candidate("Precio internet")}
    )
    pipeline = make_pipeline(settings, browser, llm=llm)
    offer = await pipeline.read_price(f"{settings.demo_store_url}/producto/1", "Zeta 12")
    assert offer is not None
    assert offer.price_clp == 549990.0


async def test_read_price_returns_none_for_a_page_without_a_clear_price(settings, browser):
    llm = fakes.FakeOllama(json_by_marker={fakes.PAGE_MARKER: fakes.choose_candidate("nada")})
    pipeline = make_pipeline(settings, browser, llm=llm)
    offer = await pipeline.read_price(f"{settings.demo_store_url}/producto/1", "Zeta 12")
    assert offer is None

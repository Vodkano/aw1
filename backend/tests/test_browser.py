"""El navegador de verdad, contra una tienda que se pinta con JavaScript.

Estas pruebas son el corazon de la nueva arquitectura: si el extractor
funcionase solo con el HTML crudo, aqui obtendria cero resultados, que es
exactamente lo que le pasaba a la version anterior con Falabella, Ripley,
Paris y Lider.
"""

import pytest

from tests.fixtures.store import FakeStore


def test_the_search_page_has_no_products_in_the_raw_html(store: FakeStore):
    """Verifica la premisa: sin navegador no hay nada que extraer."""
    from urllib.request import urlopen

    with urlopen(store.search_url("Zeta 12"), timeout=10) as response:  # noqa: S310
        html = response.read().decode()
    assert "producto/1" not in html
    assert "Cargando resultados" in html


async def test_the_browser_sees_the_products_that_javascript_pinta(browser, store: FakeStore):
    cards = await browser.search_cards(
        store.search_url("Zeta 12"), url_patterns=["/producto/"], wait_selector="[data-state='ready']"
    )
    titles = [card["title"] for card in cards]
    assert any("Zeta 12 256GB" in title for title in titles)
    assert all(card["url"].startswith(store.base) for card in cards)


async def test_the_cards_carry_the_visible_price(browser, store: FakeStore):
    cards = await browser.search_cards(store.search_url("Zeta 12"), url_patterns=["/producto/"])
    prices = [card["price_text"] for card in cards]
    assert any("549" in price for price in prices)


async def test_the_product_page_context_is_complete(browser, store: FakeStore):
    page = await browser.read_product(f"{store.base}/producto/1")

    assert page["title"] == "Smartphone Zeta 12 256GB Negro"
    assert page["structured"]["brand"] == "Zeta"
    assert "InStock" in page["availability_text"]
    assert page["breadcrumb"]

    texts = [item["text"] for item in page["price_candidates"]]
    assert any("549990" in text or "549.990" in text for text in texts)


async def test_the_context_marks_struck_prices_and_installments(browser, store: FakeStore):
    """El modelo necesita esas etiquetas para no elegir el precio equivocado."""
    page = await browser.read_product(f"{store.base}/producto/1")
    by_text = {item["text"]: item for item in page["price_candidates"]}

    struck = next(item for text, item in by_text.items() if "699" in text)
    assert struck["struck"] is True

    installment = next(item for text, item in by_text.items() if "cuotas" in text.lower())
    assert installment["noisy"] is True


async def test_structured_data_is_the_most_prominent_candidate(browser, store: FakeStore):
    page = await browser.read_product(f"{store.base}/producto/1")
    structured = [item for item in page["price_candidates"] if item["kind"] == "structured"]
    assert structured
    assert structured[0]["prominence"] == 1


async def test_out_of_stock_is_detected(browser, store: FakeStore):
    page = await browser.read_product(f"{store.base}/producto/4")
    assert "OutOfStock" in page["availability_text"]


async def test_a_missing_page_raises_a_domain_error(browser, store: FakeStore):
    from aw1.core.errors import BrowserError

    with pytest.raises(BrowserError):
        await browser.read_product(f"{store.base}/producto/999")


async def test_the_browser_refuses_a_private_host_when_the_guard_is_on(browser):
    from aw1.core import netguard
    from aw1.core.errors import BrowserError

    netguard.set_allow_private_hosts(False)
    try:
        with pytest.raises(BrowserError):
            await browser.read_product("http://169.254.169.254/latest/meta-data/")
    finally:
        netguard.set_allow_private_hosts(True)

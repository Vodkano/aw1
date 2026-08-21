"""Los jueces: que la IA decida, pero que nunca decida sola sin verificacion.

Cada prueba comprueba una de las dos mitades del contrato: que la decision del
modelo se respete cuando es coherente, y que se corrija o se descarte cuando no
lo es.
"""

import pytest

from aw1.llm.judges import Judges
from aw1.llm.schemas import SearchPlan
from tests import fakes


def build(**kwargs) -> Judges:
    return Judges(fakes.FakeOllama(**kwargs), model="mistral", timeout=5)


PAGE = {
    "url": "https://tienda.cl/producto/zeta-12",
    "title": "Smartphone Zeta 12 256GB Negro",
    "price_candidates": [
        {"id": 1, "text": "$549.990", "value": 549990.0, "currency": "CLP", "value_clp": 549990.0,
         "kind": "structured", "context": "json-ld | Precio internet", "prominence": 1.0},
        {"id": 2, "text": "$699.990", "value": 699990.0, "currency": "CLP", "value_clp": 699990.0,
         "kind": "visual", "context": "[precio tachado] Precio normal", "prominence": 0.5},
        {"id": 3, "text": "$45.832", "value": 45832.0, "currency": "CLP", "value_clp": 45832.0,
         "kind": "visual", "context": "[posible cuota o descuento] 12 cuotas", "prominence": 0.4},
    ],
}
PLAN = SearchPlan(product="Smartphone Zeta 12 256GB", queries=["Zeta 12"], required=[], forbidden=[])


# --- plan de busqueda -------------------------------------------------------
async def test_plan_uses_the_model_when_it_answers():
    judges = build(json_by_marker={fakes.PLAN_MARKER: fakes.plan_payload("iPhone 15 128 GB", ["128"])})
    plan = await judges.plan_search("iphon 15 128")
    assert plan.product == "iPhone 15 128 GB"
    assert plan.required == ["128"]
    assert judges.stats.llm_used == 1


async def test_plan_falls_back_when_ollama_is_down():
    judges = build(online=False)
    plan = await judges.plan_search("iPhone 15 128 GB")
    assert plan.product == "iPhone 15 128 GB"
    assert plan.queries == ["iPhone 15 128 GB", "iPhone 15"]
    assert judges.stats.fallbacks == 1


async def test_plan_never_forbids_what_the_person_asked_for():
    """Si alguien busca una funda, el modelo no puede prohibir la palabra funda."""
    judges = build(
        json_by_marker={
            fakes.PLAN_MARKER: {
                "product": "Funda iPhone 15",
                "queries": ["Funda iPhone 15"],
                "required": [],
                "forbidden": ["funda", "case", "cable"],
            }
        }
    )
    plan = await judges.plan_search("funda iphone 15")
    assert "funda" not in [term.lower() for term in plan.forbidden]


async def test_plan_recovers_from_an_empty_model_answer():
    judges = build(json_by_marker={fakes.PLAN_MARKER: {"product": "", "queries": []}})
    plan = await judges.plan_search("Notebook Lenovo")
    assert plan.product == "Notebook Lenovo"
    assert plan.queries


# --- seleccion de candidatos ------------------------------------------------
CARDS = [
    {"title": "Smartphone Zeta 12 256GB Negro", "url": "https://t.cl/producto/1", "price_text": "$549.990"},
    {"title": "Funda para Zeta 12", "url": "https://t.cl/producto/3", "price_text": "$9.990"},
    {"title": "Smartphone Zeta 11 256GB", "url": "https://t.cl/producto/4", "price_text": "$399.990"},
]


async def test_picks_respect_the_model_choice():
    judges = build(json_by_marker={fakes.CANDIDATES_MARKER: fakes.pick_first(1)})
    picks = await judges.pick_products(PLAN, "Tienda", CARDS, limit=2)
    assert len(picks) == 1
    assert picks[0]["title"].startswith("Smartphone Zeta 12")


async def test_invented_ids_are_ignored():
    judges = build(
        json_by_marker={
            fakes.CANDIDATES_MARKER: {"picks": [{"id": 99, "confidence": 1.0}], "discarded_reason": ""}
        }
    )
    picks = await judges.pick_products(PLAN, "Tienda", CARDS, limit=2)
    assert judges.stats.corrections >= 1
    # Al no quedar nada elegido, se rescatan las coincidencias claras.
    assert all("Funda" not in pick["title"] for pick in picks)


async def test_picks_fall_back_to_matching_without_the_model():
    judges = build(online=False)
    picks = await judges.pick_products(PLAN, "Tienda", CARDS, limit=3)
    titles = [pick["title"] for pick in picks]
    assert any("Zeta 12 256GB" in title for title in titles)
    assert not any("Funda" in title for title in titles)


async def test_an_empty_card_list_short_circuits():
    judges = build()
    assert await judges.pick_products(PLAN, "Tienda", [], limit=2) == []
    assert judges.stats.llm_calls == 0


# --- lectura de la ficha ----------------------------------------------------
async def test_the_model_chooses_the_selling_price():
    judges = build(json_by_marker={fakes.PAGE_MARKER: fakes.choose_candidate("Precio internet")})
    verdict = await judges.read_page(PLAN, PAGE)
    assert verdict.is_match is True
    assert verdict.price == 549990.0
    assert judges.stats.corrections == 0


async def test_a_hallucinated_price_is_replaced_by_the_real_one():
    """El modelo dice 500000 pero el candidato 1 vale 549990: manda la pagina."""
    judges = build(
        json_by_marker={
            fakes.PAGE_MARKER: {
                "is_match": True, "candidate_id": 1, "price": 500000,
                "currency": "CLP", "confidence": 0.9, "reason": "inventado",
            }
        }
    )
    verdict = await judges.read_page(PLAN, PAGE)
    assert verdict.price == 549990.0
    assert judges.stats.corrections == 1


async def test_a_candidate_id_that_does_not_exist_falls_back():
    judges = build(
        json_by_marker={
            fakes.PAGE_MARKER: {"is_match": True, "candidate_id": 77, "price": 1, "confidence": 0.9}
        }
    )
    verdict = await judges.read_page(PLAN, PAGE)
    assert judges.stats.corrections >= 1
    assert verdict.price in {549990.0, 45832.0, 699990.0}


async def test_a_page_for_another_product_is_rejected():
    judges = build(json_by_marker={fakes.PAGE_MARKER: fakes.choose_candidate("Precio internet")})
    other = {**PAGE, "title": "Funda de silicona para Zeta 12"}
    verdict = await judges.read_page(PLAN, other)
    assert verdict.is_match is False


async def test_without_candidates_there_is_no_verdict():
    judges = build()
    verdict = await judges.read_page(PLAN, {"url": "x", "title": "y", "price_candidates": []})
    assert verdict.is_match is False
    assert judges.stats.llm_calls == 0


async def test_the_fallback_prefers_structured_data():
    judges = build(online=False)
    verdict = await judges.read_page(PLAN, PAGE)
    assert verdict.is_match is True
    assert verdict.price == 549990.0
    assert "sin IA" in verdict.reason


# --- veredicto final --------------------------------------------------------
OFFERS = [
    {"store": "Tienda A", "price": 479990.0, "price_clp": 479990.0, "currency": "CLP"},
    {"store": "Tienda B", "price": 549990.0, "price_clp": 549990.0, "currency": "CLP"},
]


async def test_the_written_verdict_is_used_when_the_prices_are_real():
    judges = build(text_reply="Lo mas barato esta en Tienda A a $479.990, contra $549.990 en Tienda B.")
    text = await judges.write_verdict("Zeta 12", OFFERS, visited=2, discarded=1)
    assert "Tienda A" in text
    assert judges.stats.corrections == 0


async def test_a_verdict_with_an_invented_price_is_rewritten():
    judges = build(text_reply="Lo mas barato son $399.000 en Tienda A.")
    text = await judges.write_verdict("Zeta 12", OFFERS, visited=2, discarded=1)
    assert "399.000" not in text
    assert "$479.990" in text
    assert judges.stats.corrections == 1


async def test_numbers_that_are_not_prices_do_not_invalidate_the_verdict():
    """El "256" de "256 GB" no es un precio y no debe disparar la correccion."""
    judges = build(text_reply="El Zeta 12 de 256 GB sale $479.990 en Tienda A.")
    text = await judges.write_verdict("Zeta 12 256 GB", OFFERS, visited=2, discarded=0)
    assert "Tienda A" in text
    assert judges.stats.corrections == 0


@pytest.mark.parametrize("reply", ["", "   "])
async def test_an_empty_verdict_falls_back(reply):
    judges = build(text_reply=reply)
    text = await judges.write_verdict("Zeta 12", OFFERS, visited=2, discarded=0)
    assert "Tienda A" in text


async def test_no_offers_no_verdict():
    judges = build()
    assert "No se encontraron" in await judges.write_verdict("Zeta", [], 0, 0)

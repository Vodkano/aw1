"""Coincidencia deterministica: el respaldo cuando la IA no esta.

Debe ser tolerante con como escriben las tiendas ("128GB" pegado, colores y
modelos extra en el titulo) y estricta con lo que cambia el producto (otra
generacion, otra capacidad, un accesorio).
"""

import pytest

from aw1.pricing import matching


@pytest.mark.parametrize(
    "title",
    [
        "iPhone 15 128GB Negro",
        "iPhone 15 128 GB Negro",
        "Apple iPhone 15 (128gb) liberado",
        "Celular Apple iPhone 15 128 GB Azul + audifonos",
    ],
)
def test_accepts_the_right_product(title):
    assert matching.matches(title, "iPhone 15 128 GB") is True


@pytest.mark.parametrize(
    "title",
    ["Funda de silicona para iPhone 15", "Cable USB-C para iPhone 15", "Case iPhone 15 128GB"],
)
def test_rejects_accessories(title):
    assert matching.matches(title, "iPhone 15 128 GB") is False


def test_accepts_an_accessory_word_when_it_is_not_the_head():
    """"AirPods Pro 2 con estuche de carga" sigue siendo los audifonos."""
    assert matching.matches("AirPods Pro 2 con estuche de carga", "AirPods Pro 2") is True


def test_does_not_reject_por_una_palabra_incidental():
    assert matching.matches("Notebook Lenovo IdeaPad con base de aluminio", "Notebook Lenovo")


def test_rejects_another_generation():
    assert matching.matches("AirPods 4", "AirPods Pro 2") is False


def test_required_terms_are_enforced():
    result = matching.score("iPhone 15 Pro Max 256GB", "iPhone 15", required=["128 GB"])
    assert result.ok is False
    assert "requisito" in result.reason


def test_forbidden_terms_from_the_plan_are_honoured():
    result = matching.score(
        "Reacondicionado iPhone 15 128GB", "iPhone 15 128 GB", forbidden=["reacondicionado"]
    )
    assert result.ok is False


def test_an_accessory_query_can_look_for_accessories():
    """Si la persona pide una funda, "funda" deja de ser motivo de descarte."""
    assert matching.matches("Funda de silicona para iPhone 15", "Funda iPhone 15") is True


def test_score_is_a_coverage_ratio():
    assert matching.score("Samsung Galaxy S24 Ultra 256GB", "Galaxy S24 Ultra").score == 1.0
    assert matching.score("Samsung Galaxy", "Galaxy S24 Ultra").score < 0.6


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("iPhone 15 128 GB", ["iPhone 15 128 GB", "iPhone 15"]),
        ("Notebook Lenovo", ["Notebook Lenovo"]),
    ],
)
def test_fallback_queries(product, expected):
    assert matching.fallback_queries(product) == expected


def test_expand_splits_alphanumeric_tokens():
    assert {"128gb", "128", "gb"} <= matching.expand(["128gb"])

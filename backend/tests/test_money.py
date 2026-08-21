"""Analisis de importes: el nucleo del comparador."""

import pytest

from aw1.pricing import money


@pytest.mark.parametrize(
    ("raw", "value", "currency"),
    [
        ("$1.290.000", 1_290_000.0, "CLP"),
        ("1.290.000", 1_290_000.0, "CLP"),
        ("CLP 14.990", 14_990.0, "CLP"),
        ("14,990", 14_990.0, "CLP"),
        ("US$ 899.99", 899.99, "USD"),
        ("1,299.50 USD", 1_299.50, "USD"),
        ("€1.030,50", 1_030.50, "EUR"),
        ("$ 2.499.990 IVA incluido", 2_499_990.0, "CLP"),
        ("Precio internet $549.990", 549_990.0, "CLP"),
        (189000, 189_000.0, "CLP"),
        ("189000.00", 189_000.0, "CLP"),
    ],
)
def test_parses_the_formats_that_aparecen_en_tiendas(raw, value, currency):
    amount = money.parse(raw)
    assert amount is not None
    assert amount.value == pytest.approx(value)
    assert amount.currency == currency


@pytest.mark.parametrize("raw", [None, "", "sin precio", 0, -5, "Agotado", True, False])
def test_rejects_lo_que_no_es_un_precio(raw):
    assert money.parse(raw) is None


def test_converts_to_clp():
    rates = {"CLP": 1.0, "USD": 950.0}
    assert money.to_clp(money.Amount(899.0, "USD"), rates) == pytest.approx(854_050.0)
    assert money.to_clp(money.Amount(10.0, "JPY"), rates) is None


def test_plausibility_filters_counters_and_placeholders():
    assert money.plausible(14_990) is True
    assert money.plausible(2) is False
    assert money.plausible(999_999_999) is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [(189_000, "$189.000"), (1_290_000, "$1.290.000"), (2_499_990, "$2.499.990")],
)
def test_format_clp_nunca_usa_notacion_cientifica(value, expected):
    assert money.format_clp(value) == expected
    assert "e+" not in money.format_clp(value)

"""Analisis de importes y conversion a pesos chilenos.

Comparar precios sin convertir la moneda produce resultados silenciosamente
incorrectos: 899 USD son unos 854.000 CLP y deben quedar por delante de una
oferta de 1.290.000 CLP, no detras.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CURRENCIES = {
    "CLP": "CLP", "$": "CLP", "CL$": "CLP", "CLP$": "CLP", "PESO": "CLP", "PESOS": "CLP",
    "USD": "USD", "US$": "USD", "U$S": "USD", "USD$": "USD", "DOLAR": "USD", "DOLARES": "USD",
    "EUR": "EUR", "€": "EUR", "EURO": "EUR", "EUROS": "EUR",
    "UF": "UF", "ARS": "ARS", "PEN": "PEN", "COP": "COP", "MXN": "MXN", "BRL": "BRL",
}

_AMOUNT = re.compile(r"\d{1,3}(?:[., \s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?")
_CURRENCY = re.compile(
    r"(?i)(us\$|u\$s|cl\$|clp\$|\bclp\b|\busd\b|\beur\b|\buf\b|\bars\b|\bpen\b|\bcop\b|"
    r"\bmxn\b|\bbrl\b|€|\$)"
)

MIN_CLP = 500.0
MAX_CLP = 300_000_000.0


@dataclass(frozen=True, slots=True)
class Amount:
    value: float
    currency: str


def detect_currency(text: str, default: str = "CLP") -> str:
    match = _CURRENCY.search(text or "")
    if not match:
        return default
    return CURRENCIES.get(match.group(1).upper().strip(), default)


def parse(raw: str | float | int | None, *, default_currency: str = "CLP") -> Amount | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        numeric = float(raw)
        return Amount(numeric, default_currency) if numeric > 0 else None

    text = str(raw).strip()
    if not text:
        return None
    currency = detect_currency(text, default_currency)
    match = _AMOUNT.search(text)
    if not match:
        return None
    value = _to_float(match.group(0))
    return Amount(value, currency) if value and value > 0 else None


def _to_float(token: str) -> float | None:
    """Resuelve la ambiguedad entre separador de miles y separador decimal."""
    cleaned = re.sub(r"[\s ]", "", token)
    separators = [char for char in cleaned if char in ".,"]
    if not separators:
        return _safe(cleaned)

    last = separators[-1]
    head, _, tail = cleaned.rpartition(last)

    if len(set(separators)) > 1:
        # Aparecen los dos signos: el ultimo es el decimal.
        return _safe(head.replace(".", "").replace(",", "") + "." + tail)
    if len(separators) > 1:
        # El mismo signo repetido siempre es separador de miles: 1.290.000
        return _safe(cleaned.replace(last, ""))
    if len(tail) == 3:
        # Un solo separador con tres cifras detras: en CLP son miles (14.990)
        return _safe(head + tail)
    return _safe(head + "." + tail)


def _safe(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def to_clp(amount: Amount, rates: dict[str, float]) -> float | None:
    rate = rates.get(amount.currency.upper())
    if not rate or rate <= 0:
        return None
    return round(amount.value * rate, 2)


def plausible(value_clp: float) -> bool:
    """Descarta el "2" de un selector de cuotas y los placeholders absurdos."""
    return MIN_CLP <= value_clp <= MAX_CLP


def format_clp(value: float) -> str:
    """Formato chileno: $1.290.000. Nunca notacion cientifica."""
    return f"${value:,.0f}".replace(",", ".")

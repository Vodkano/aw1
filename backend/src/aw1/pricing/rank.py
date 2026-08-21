"""Normalizacion, orden y avisos.

El orden es por precio real en pesos, no por moneda. Primero se muestra la mejor
oferta de cada tienda y despues se rellenan los huecos con el resto, para que la
lista no quede copada por un solo comercio.
"""

from __future__ import annotations

import math

from ..core.netguard import registrable_domain
from . import money
from .models import Offer


def normalize(offers: list[Offer], rates: dict[str, float]) -> tuple[list[Offer], list[str]]:
    valid: list[Offer] = []
    warnings: list[str] = []
    unknown: set[str] = set()

    for offer in offers:
        if not math.isfinite(offer.price) or offer.price <= 0:
            continue
        amount = money.Amount(float(offer.price), offer.currency.upper())
        converted = money.to_clp(amount, rates)
        if converted is None:
            unknown.add(amount.currency)
            continue
        if not money.plausible(converted):
            continue
        valid.append(
            offer.model_copy(
                update={"price_clp": converted, "price_label": money.format_clp(converted)}
            )
        )

    if unknown:
        warnings.append(
            "Se omitieron ofertas en "
            + ", ".join(sorted(unknown))
            + " porque no hay tasa de cambio configurada para esa moneda."
        )
    return valid, warnings


def rank(offers: list[Offer], limit: int) -> list[Offer]:
    ordered = sorted(offers, key=lambda offer: (offer.price_clp, offer.domain))
    best_per_store: list[Offer] = []
    seen: set[str] = set()
    for offer in ordered:
        key = registrable_domain(offer.domain)
        if key not in seen:
            seen.add(key)
            best_per_store.append(offer)
    chosen = {id(offer) for offer in best_per_store}
    best_per_store.extend(offer for offer in ordered if id(offer) not in chosen)
    return best_per_store[:limit]


def outlier_warning(offers: list[Offer]) -> str | None:
    """Avisa si la oferta mas barata se aleja demasiado de la mediana.

    Suele significar que esa pagina publicaba un accesorio, un repuesto o el
    precio de un plan, no el producto completo.
    """
    if len(offers) < 4:
        return None
    values = sorted(offer.price_clp for offer in offers)
    median = values[len(values) // 2]
    cheapest = values[0]
    if median > 0 and cheapest < median * 0.4:
        return (
            f"La oferta mas barata ({money.format_clp(cheapest)}) esta muy por debajo "
            f"del resto ({money.format_clp(median)} de mediana). Revisa esa ficha antes "
            "de darla por buena."
        )
    return None

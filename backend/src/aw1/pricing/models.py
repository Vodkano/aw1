"""Modelos del comparador."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Offer(BaseModel):
    """Una oferta concreta, con su enlace directo a la ficha."""

    store: str
    store_slug: str
    domain: str
    url: str
    title: str = ""
    price: float
    currency: str = "CLP"
    price_clp: float
    price_label: str = ""
    in_stock: bool | None = None
    confidence: float = 0.5
    decided_by: str = "ia"
    reason: str = ""
    fetched_at: datetime = Field(default_factory=utcnow)


class StoreOutcome(BaseModel):
    """Que paso en cada tienda. Se muestra tal cual en la interfaz."""

    slug: str
    name: str
    search_url: str = ""
    cards_found: int = 0
    picked: int = 0
    offers: int = 0
    elapsed: float = 0.0
    status: str = "ok"  # ok | vacio | error | timeout
    detail: str = ""


class Comparison(BaseModel):
    query: str
    product: str
    offers: list[Offer] = Field(default_factory=list)
    verdict: str = ""
    stores: list[StoreOutcome] = Field(default_factory=list)
    visited: int = 0
    discarded: int = 0
    elapsed: float = 0.0
    from_cache: bool = False
    warnings: list[str] = Field(default_factory=list)
    ai: dict[str, object] = Field(default_factory=dict)

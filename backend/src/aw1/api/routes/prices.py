"""Comparador de precios: catalogo, busqueda en vivo y busqueda simple."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from ...core.errors import Aw1Error
from ...stores.registry import catalog
from ..deps import Container, container
from ..schemas import PriceRequest

router = APIRouter(prefix="/api/prices", tags=["precios"])


@router.get("/stores")
async def stores() -> dict[str, list[dict[str, object]]]:
    return {"stores": catalog()}


@router.get("/recent")
async def recent(box: Container = Depends(container)) -> dict[str, list[dict[str, object]]]:
    return {"searches": await box.repo.recent_searches()}


@router.post("/search")
async def search(
    payload: PriceRequest, request: Request, box: Container = Depends(container)
) -> EventSourceResponse:
    """Busqueda con progreso en vivo: cada tienda emite eventos segun avanza."""

    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in box.prices.run(
                payload.query, payload.stores or None, refresh=payload.refresh
            ):
                if await request.is_disconnected():
                    break
                yield {"event": event.type, "data": json.dumps(event.data, ensure_ascii=False)}
        except Aw1Error as error:
            yield {"event": "error", "data": json.dumps({"message": error.message})}
        except Exception:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps({"message": "La busqueda no se pudo completar."}),
            }

    return EventSourceResponse(events())


@router.post("/compare")
async def compare(payload: PriceRequest, box: Container = Depends(container)) -> dict[str, object]:
    """Version sin streaming, util para scripts y para probar desde la terminal."""
    comparison = await box.prices.compare(
        payload.query, payload.stores or None, refresh=payload.refresh
    )
    return comparison.model_dump(mode="json")


@router.get("/stream")
async def search_via_get(
    request: Request,
    q: str = Query(min_length=1, max_length=180),
    stores: str = Query(default=""),
    refresh: bool = Query(default=False),
    box: Container = Depends(container),
) -> EventSourceResponse:
    """Igual que /search pero por GET, para EventSource nativo del navegador."""
    selected = [item.strip() for item in stores.split(",") if item.strip()]

    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in box.prices.run(q, selected or None, refresh=refresh):
                if await request.is_disconnected():
                    break
                yield {"event": event.type, "data": json.dumps(event.data, ensure_ascii=False)}
        except Aw1Error as error:
            yield {"event": "error", "data": json.dumps({"message": error.message})}
        except Exception:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps({"message": "La busqueda no se pudo completar."}),
            }

    return EventSourceResponse(events())

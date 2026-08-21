"""Memoria persistente."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...core.errors import NotFoundError
from ..deps import Container, container
from ..schemas import SavedItem, SavedList, SaveItemRequest

router = APIRouter(prefix="/api/memory", tags=["memoria"])


@router.get("", response_model=SavedList)
async def list_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    box: Container = Depends(container),
) -> SavedList:
    items = await box.repo.list_items(limit=limit, offset=offset)
    return SavedList(
        items=[SavedItem(**item) for item in items], total=await box.repo.count_items()
    )


@router.post("", response_model=SavedItem, status_code=201)
async def save_item(payload: SaveItemRequest, box: Container = Depends(container)) -> SavedItem:
    item = await box.repo.save_item(
        payload.text,
        payload.source,
        payload.kind,
        payload.meta,
        max_items=box.settings.max_saved_items,
    )
    return SavedItem(**item)


@router.delete("/{item_id}")
async def delete_item(item_id: int, box: Container = Depends(container)) -> dict[str, bool]:
    if not await box.repo.delete_item(item_id):
        raise NotFoundError("Ese elemento ya no existe.")
    return {"deleted": True}


@router.delete("")
async def purge(
    everything: bool = Query(default=False, description="Borra tambien chats, cache y busquedas"),
    box: Container = Depends(container),
) -> dict[str, object]:
    tables = None if everything else ["saved_items"]
    return {"removed": await box.repo.purge(tables)}

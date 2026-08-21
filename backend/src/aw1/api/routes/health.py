"""Estado del sistema."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ... import __version__
from ..deps import Container, container
from ..schemas import StatusResponse

router = APIRouter(tags=["estado"])


@router.get("/healthz", summary="Sonda de vida")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/status", response_model=StatusResponse)
async def status(box: Container = Depends(container)) -> StatusResponse:
    payload = await box.chat.status()
    return StatusResponse(version=__version__, browser=box.browser.status, **payload)

"""Webhook de Telegram: un solo endpoint compartido por todos los perfiles
(bots), distinguidos por el profile_id en la URL. Ver telegram/orchestrator.py
para la logica real -esta ruta solo valida y dispara, nunca espera al modelo.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...core.errors import AuthError
from ..deps import Container, container

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/webhook/{profile_id}")
async def webhook(
    profile_id: str, request: Request, box: Container = Depends(container)
) -> dict[str, bool]:
    secret_header = request.headers.get("x-telegram-bot-api-secret-token", "")
    profile = box.telegram.verify(profile_id, secret_header)
    if profile is None:
        raise AuthError("Webhook no reconocido.")
    payload = await request.json()
    box.telegram.enqueue(profile, payload)
    return {"ok": True}

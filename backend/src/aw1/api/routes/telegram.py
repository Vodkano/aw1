"""Webhook de Telegram: un solo endpoint compartido por todos los tokens
(bots), distinguidos por el token_id en la URL. Ver telegram/orchestrator.py
para la logica real -esta ruta solo valida y dispara, nunca espera al modelo.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...core.errors import AuthError
from ..deps import Container, container

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/webhook/{token_id}")
async def webhook(
    token_id: str, request: Request, box: Container = Depends(container)
) -> dict[str, bool]:
    secret_header = request.headers.get("x-telegram-bot-api-secret-token", "")
    token = box.telegram.verify(token_id, secret_header)
    if token is None:
        raise AuthError("Webhook no reconocido.")
    payload = await request.json()
    box.telegram.enqueue(token, payload)
    return {"ok": True}

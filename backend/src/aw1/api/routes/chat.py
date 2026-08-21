"""Chat con respuesta en streaming (SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from ...core.errors import Aw1Error, NotFoundError
from ..deps import Container, container
from ..schemas import ChatRequest, ConversationSummary, StoredMessage

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(
    payload: ChatRequest, request: Request, box: Container = Depends(container)
) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in box.chat.stream(
                payload.message,
                conversation_id=payload.conversation_id,
                allow_gpt=payload.allow_gpt,
            ):
                if await request.is_disconnected():
                    break
                yield {"event": event.type, "data": json.dumps(event.data, ensure_ascii=False)}
        except Aw1Error as error:
            yield {"event": "error", "data": json.dumps({"message": error.message})}
        except Exception:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps({"message": "No fue posible completar la respuesta."}),
            }

    return EventSourceResponse(events())


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(box: Container = Depends(container)) -> list[ConversationSummary]:
    rows = await box.repo.conversations()
    return [ConversationSummary(**row) for row in rows]


@router.get("/{conversation_id}", response_model=list[StoredMessage])
async def messages(
    conversation_id: str, box: Container = Depends(container)
) -> list[StoredMessage]:
    rows = await box.repo.messages(conversation_id)
    if not rows:
        raise NotFoundError("Esa conversacion no existe.")
    return [StoredMessage(**row) for row in rows]


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str, box: Container = Depends(container)
) -> dict[str, int]:
    return {"removed": await box.repo.delete_conversation(conversation_id)}

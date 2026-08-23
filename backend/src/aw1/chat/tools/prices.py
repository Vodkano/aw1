"""Herramienta de precios: la primera implementacion de ChatTool.

Corre el mismo PricePipeline que usa la pestana Precios, pero invocado
directo desde el chat -sin redirigir de pestana. Reenvia cada evento del
pipeline tal cual (envuelto en "tool_event") para que la interfaz pinte el
progreso tienda por tienda, igual que ya hace PricesView.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from ...llm.schemas import ChatRoute
from ...pricing.pipeline import PricePipeline
from ..events import ChatEvent
from .base import ChatTool

# Debe calzar con PriceRequest.query (api/schemas.py): el pipeline no
# recorta solo, y route.search_terms para intent="precio" es el mensaje
# completo canonicalizado, no un nombre de producto ya extraido.
MAX_QUERY_LENGTH = 180


class PriceSearchTool(ChatTool):
    intent = "precio"
    label = "precios"
    description = "Busca y compara precios reales en tiendas chilenas."

    def __init__(self, pipeline: PricePipeline) -> None:
        self._pipeline = pipeline

    async def run(
        self, route: ChatRoute, message: str, conversation_id: str
    ) -> AsyncIterator[ChatEvent]:
        query = (route.search_terms or message).strip()[:MAX_QUERY_LENGTH]
        comparison: dict | None = None
        async for event in self._pipeline.run(query):
            yield ChatEvent(
                "tool_event", {"tool": "prices", "type": event.type, "data": event.data}
            )
            if event.type == "done":
                comparison = event.data["comparison"]
            elif event.type == "error":
                yield ChatEvent(
                    "tool_result",
                    {"answer": event.data["message"], "source": "prices", "sources": []},
                )
                return

        offers = comparison["offers"] if comparison else []
        answer = (comparison or {}).get("verdict") or "No encontre precios para ese producto."
        if offers:
            best = offers[0]
            answer = f"{answer}\n\n[Ver en {best['store']}]({best['url']})"
        yield ChatEvent("tool_result", {"answer": answer, "source": "prices", "sources": []})

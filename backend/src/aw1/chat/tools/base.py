"""Herramientas invocables desde el chat.

Una herramienta se activa cuando ``ChatRoute.intent`` coincide con su
``intent`` (o cuando la persona la menciona a mano con ``@``, ver
``chat/service.py``). Sumar una herramienta nueva es escribir una clase que
implemente ``ChatTool`` y registrarla en ``api/deps.py`` -el loop central de
``ChatService.stream()`` no vuelve a tocarse.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ...llm.schemas import ChatRoute
from ..events import ChatEvent


class ChatTool(ABC):
    intent: str
    label: str
    description: str

    @abstractmethod
    def run(
        self, route: ChatRoute, message: str, conversation_id: str
    ) -> AsyncIterator[ChatEvent]:
        """Emite progreso libremente y termina con EXACTAMENTE un ChatEvent
        tipo "tool_result" -> {"answer": str, "source": str, "sources": list[str]}.
        Nunca escribe en la base de datos: eso lo hace ChatService, igual que
        para las demas rutas de respuesta."""


class ToolRegistry:
    def __init__(self, tools: list[ChatTool]) -> None:
        self._by_id = {tool.intent: tool for tool in tools}

    def get(self, tool_id: str) -> ChatTool | None:
        return self._by_id.get(tool_id)

    def ids(self) -> set[str]:
        return set(self._by_id)

    def mentionable(self) -> list[dict[str, str]]:
        return [
            {
                "id": tool.intent, "label": tool.label,
                "description": tool.description, "kind": "tool",
            }
            for tool in self._by_id.values()
        ]

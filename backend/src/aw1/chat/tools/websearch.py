"""Herramienta de busqueda web general (mencion "@buscar" o intent "buscar").

A diferencia de @precios (que solo compara tiendas chilenas ya
configuradas en el catalogo), esto busca en cualquier sitio: descripciones
de producto, comparativas, reviews, noticias. Usa Brave Search API -sin una
clave configurada, avisa con claridad en vez de fallar en silencio o tirar
un error generico.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from ...core import llm_provider, websearch
from ...core.secrets_store import SecretsStore
from ...llm.schemas import ChatRoute
from ...settings import Settings
from ..events import ChatEvent
from .base import ChatTool

MAX_QUERY_LENGTH = 300

_NOT_CONFIGURED = (
    "Todavia no tengo una clave de busqueda web configurada. Se agrega en "
    "el panel admin (Configuracion) o con AW1_BRAVE_SEARCH_API_KEY."
)
_FAILED = "No pude buscar en internet ahora mismo. Intenta de nuevo en un rato."


class WebSearchTool(ChatTool):
    intent = "buscar"
    label = "buscar"
    description = "Busca en internet: descripciones de producto, comparativas, noticias, lo que sea."

    def __init__(self, settings: Settings, secrets: SecretsStore) -> None:
        self._settings = settings
        self._secrets = secrets

    async def run(
        self, route: ChatRoute, message: str, conversation_id: str
    ) -> AsyncIterator[ChatEvent]:
        query = (route.search_terms or message).strip()[:MAX_QUERY_LENGTH]
        key = llm_provider.brave_key(self._settings, self._secrets)
        if not key.strip():
            yield ChatEvent(
                "tool_result", {"answer": _NOT_CONFIGURED, "source": "websearch", "sources": []}
            )
            return

        try:
            results = await websearch.search(
                query, api_key=key, base_url=self._settings.brave_search_base_url
            )
        except (httpx.HTTPError, RuntimeError):
            yield ChatEvent(
                "tool_result", {"answer": _FAILED, "source": "websearch", "sources": []}
            )
            return

        if not results:
            yield ChatEvent(
                "tool_result",
                {
                    "answer": f"No encontre resultados en internet para «{query}».",
                    "source": "websearch", "sources": [],
                },
            )
            return

        lines = [f"Esto encontre en internet sobre «{query}»:", ""]
        for item in results:
            snippet = f": {item.snippet}" if item.snippet else ""
            lines.append(f"- [{item.title}]({item.url}){snippet}")
        yield ChatEvent(
            "tool_result",
            {
                "answer": "\n".join(lines), "source": "websearch",
                "sources": [item.url for item in results],
            },
        )

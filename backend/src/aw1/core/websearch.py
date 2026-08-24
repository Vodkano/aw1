"""Busqueda web general via Brave Search API.

Complementa a la herramienta de precios (que solo compara tiendas chilenas
ya configuradas en el catalogo): esto trae resultados de cualquier sitio
-descripciones de producto, comparativas, reviews, noticias- para cuando la
pregunta no calza con ese catalogo. Requiere una clave (panel admin o
``AW1_BRAVE_SEARCH_API_KEY``); sin eso, quien llama debe avisar con
claridad en vez de intentar la peticion.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

MAX_RESULTS = 5
TIMEOUT_SECONDS = 10.0


@dataclass(slots=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str


async def search(
    query: str, *, api_key: str, base_url: str, count: int = MAX_RESULTS
) -> list[WebSearchResult]:
    """Puede lanzar httpx.HTTPError o RuntimeError -quien llama decide como
    convertir eso en un mensaje para la persona (ver chat/tools/websearch.py)."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.get(
            base_url,
            params={"q": query, "count": count, "country": "cl", "search_lang": "es"},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Brave Search respondio {response.status_code}.")

    data = response.json()
    web_results = (data.get("web") or {}).get("results") or []
    results: list[WebSearchResult] = []
    for item in web_results[:count]:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        snippet = str(item.get("description") or "").strip()
        results.append(WebSearchResult(title=title, url=url, snippet=snippet))
    return results

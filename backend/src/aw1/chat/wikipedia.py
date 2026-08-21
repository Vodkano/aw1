"""Wikipedia como fuente para preguntas sobre personas.

Se usa la REST API oficial, con la ``action API`` de busqueda como respaldo
cuando el titulo exacto no existe (que es lo normal si la persona escribio el
nombre con una falta). Siempre se devuelve la URL para poder citarla.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class Wikipedia:
    def __init__(self, language: str = "es", timeout: float = 8.0) -> None:
        self._lang = language
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "AW1/3.0 (asistente local; contacto via github)"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup(self, term: str) -> tuple[str, str] | None:
        term = " ".join(str(term or "").split())
        if not term:
            return None
        direct = await self._summary(term)
        if direct:
            return direct
        title = await self._search(term)
        if title and title.lower() != term.lower():
            return await self._summary(title)
        return None

    async def _summary(self, title: str) -> tuple[str, str] | None:
        url = (
            f"https://{self._lang}.wikipedia.org/api/rest_v1/page/summary/"
            f"{quote(title.replace(' ', '_'), safe='')}"
        )
        try:
            response = await self._client.get(url)
            if response.status_code != 200:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("type") == "disambiguation":
            return None
        extract = payload.get("extract")
        if not isinstance(extract, str) or len(extract.strip()) < 40:
            return None
        page_url = ""
        urls = payload.get("content_urls")
        if isinstance(urls, dict):
            page_url = str(urls.get("desktop", {}).get("page", ""))
        return extract.strip(), page_url or f"https://{self._lang}.wikipedia.org/wiki/{quote(title)}"

    async def _search(self, term: str) -> str | None:
        try:
            response = await self._client.get(
                f"https://{self._lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query", "list": "search", "srsearch": term,
                    "srlimit": 1, "format": "json", "utf8": 1,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        results = payload.get("query", {}).get("search", []) if isinstance(payload, dict) else []
        return str(results[0]["title"]) if results else None

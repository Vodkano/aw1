"""Llamada en vivo a una API externa configurada por el admin para un
agente. El modelo decide CUANDO llamarla (tool calling de OpenAI, ver
ChatService._answer_with_gpt_tools); esta funcion se limita a ejecutarla
de forma segura y devolver un texto que el modelo pueda leer.

Mismas protecciones SSRF que el navegador (core/netguard): la URL se
valida al configurar la API Y de nuevo aca, por si el DNS cambio entre
medio (rebinding) -el admin la eligio, pero el que decide llamarla en cada
turno es el modelo, asi que conviene la misma cautela que con cualquier
URL que no se navega en el momento en que se escribio.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from . import netguard
from .errors import ValidationError

logger = logging.getLogger(__name__)

MAX_RESPONSE_CHARS = 4000
TIMEOUT_SECONDS = 10.0


def tool_name(name: str) -> str:
    """El nombre que ve el modelo tiene que ser un identificador valido
    para la API de OpenAI -sin espacios ni acentos."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")
    return cleaned[:64] or "api"


async def call(api: dict[str, Any], query: str) -> str:
    """Nunca lanza: si algo falla, devuelve un texto explicando el fallo
    -esa tambien es una respuesta valida para que el modelo se la explique
    a la persona, en vez de un error que tumbe el turno entero."""
    raw_url = str(api.get("url", ""))
    try:
        url = raw_url.format(query=query) if "{query}" in raw_url else raw_url
        url = netguard.normalize(url)
    except ValidationError:
        return "Error interno: la URL configurada para esta API no es valida."

    host = httpx.URL(url).host
    if not host or not await asyncio.to_thread(netguard.resolves_public, host):
        return "Error interno: esa API no se pudo contactar de forma segura."

    headers = api.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    method = str(api.get("method") or "GET").upper()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, headers=headers)
    except httpx.HTTPError as error:
        logger.warning("Fallo llamando a la API '%s': %s", api.get("name"), error)
        return "Error: no se pudo contactar esa API ahora mismo."

    text = response.text
    if response.status_code >= 400:
        return f"La API respondio con error {response.status_code}: {text[:500]}"
    return text[:MAX_RESPONSE_CHARS] if text.strip() else "La API respondio sin contenido."

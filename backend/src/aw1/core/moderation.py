"""Moderacion de contenido via la API de OpenAI, antes de gastar una
llamada completa a chat completions.

Gratis y casi instantanea: cubre las categorias estandar (odio, violencia,
contenido sexual, autolesion, acoso). No reemplaza el corte por mala
intencion que ya hace el propio modelo dentro de la conversacion (ver
TELEGRAM_CLOSE_SENTINEL en llm/prompts.py) -ese sigue siendo necesario para
lo que esto no cubre: intentos de manipular el prompt, pedidos fuera del
alcance del agente, spam. Esto corta ANTES de gastar nada en los casos
obvios y explicitos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModerationResult:
    flagged: bool
    categories: list[str] = field(default_factory=list)


async def check(text: str, *, api_key: str, base_url: str) -> ModerationResult:
    """Nunca lanza: si la API de moderacion falla, no hay clave, o el
    formato de la respuesta cambia, se deja pasar el mensaje (fail-open).
    Un servicio auxiliar caido no puede bloquear el chat entero."""
    if not api_key.strip() or not text.strip():
        return ModerationResult(flagged=False)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/moderations",
                json={"input": text[:4000]},
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code != 200:
            return ModerationResult(flagged=False)
        result = response.json()["results"][0]
        flagged_categories = [
            name for name, value in result.get("categories", {}).items() if value
        ]
        return ModerationResult(flagged=bool(result.get("flagged")), categories=flagged_categories)
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("La moderacion de OpenAI fallo; se deja pasar el mensaje.")
        return ModerationResult(flagged=False)

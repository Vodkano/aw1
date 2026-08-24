"""Generacion de imagenes via la API de OpenAI (DALL-E).

Herramienta que el modelo puede invocar solo (tool-calling), cuando decide
que la persona pidio una imagen -ver chat/service.py:_answer_with_gpt_tools.
No la usa nadie mas: por ahora solo los agentes de Telegram, donde no hay
streaming que perder (la respuesta ya se manda entera, ver
telegram/orchestrator.py).
"""

from __future__ import annotations

import httpx

TIMEOUT_SECONDS = 60.0


async def generate(
    prompt: str, *, api_key: str, base_url: str, model: str, size: str = "1024x1024"
) -> str:
    """Devuelve la URL de la imagen generada. Puede lanzar httpx.HTTPError o
    RuntimeError -quien llama decide como convertirlo en un mensaje."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/images/generations",
            json={"model": model, "prompt": prompt[:4000], "size": size, "n": 1},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI Images respondio {response.status_code}.")

    data = response.json()
    items = data.get("data") or []
    url = str(items[0].get("url") or "") if items else ""
    if not url:
        raise RuntimeError("La respuesta no incluyo ninguna imagen.")
    return url

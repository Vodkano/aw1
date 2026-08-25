"""Llamada compartida a GPT para el codigo NUEVO del sistema de agentes
auto-extensibles (Tool Designer, Code Agent) -no reemplaza los llamados
crudos que ya existen en chat/service.py, api/routes/admin.py,
moderation.py e image_gen.py: esos funcionan y no forman parte de este
pedido. A diferencia de esos, este si lee y devuelve el uso de tokens de
la respuesta -hoy no se registra en ningun lado del proyecto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import ProviderError

TIMEOUT_SECONDS = 30.0


@dataclass(slots=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


async def complete(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float = 0.3,
    max_tokens: int = 1200,
    json_mode: bool = False,
) -> Completion:
    payload: dict[str, Any] = {
        "model": model, "messages": messages, "temperature": temperature,
        "max_tokens": max_tokens, "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        except httpx.HTTPError as error:
            raise ProviderError("No se pudo contactar a GPT.") from error

    if response.status_code != 200:
        detail = ""
        try:
            detail = str(response.json().get("error", {}).get("message", ""))
        except ValueError:
            pass
        raise ProviderError(f"GPT respondio con error ({response.status_code}). {detail}".strip())

    data = response.json()
    text = str(data["choices"][0]["message"].get("content") or "").strip()
    usage = data.get("usage") or {}
    return Completion(
        text=text,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
    )


def parse_json_object(text: str) -> dict[str, Any]:
    """Los modelos a veces envuelven el JSON en ```json ... ``` pese a
    pedirles "solo el JSON" -se saca eso antes de parsear en vez de fallar
    por un detalle de formato que no cambia el contenido real."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        parsed = json.loads(cleaned.strip())
    except ValueError as error:
        raise ProviderError("GPT no devolvio un JSON valido.") from error
    if not isinstance(parsed, dict):
        raise ProviderError("GPT no devolvio el formato esperado.")
    return parsed

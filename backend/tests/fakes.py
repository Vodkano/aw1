"""Dobles de prueba: un Ollama simulado y utilidades compartidas.

El objetivo es poder ejercitar el pipeline completo (navegador real incluido)
sin depender de que haya un modelo descargado en la maquina que corre las
pruebas. El doble responde con JSON valido, con JSON invalido o con nada, segun
lo que se quiera comprobar.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class FakeOllama:
    """Implementa la superficie de ``OllamaClient`` que usan los jueces."""

    def __init__(
        self,
        *,
        online: bool = True,
        json_by_marker: dict[str, Any] | None = None,
        text_reply: str = "Respuesta del modelo.",
        fail_json: bool = False,
    ) -> None:
        self.online = online
        self.json_by_marker = json_by_marker or {}
        self.text_reply = text_reply
        self.fail_json = fail_json
        self.json_calls: list[str] = []
        self.chat_calls: list[str] = []
        self.installed = ["mistral:latest"]

    async def available(self) -> bool:
        return self.online

    async def models(self) -> list[str]:
        return list(self.installed) if self.online else []

    async def has_model(self, name: str) -> bool:
        wanted = name.split(":")[0]
        return any(item.split(":")[0] == wanted for item in await self.models())

    async def aclose(self) -> None:
        return None

    def _match(self, messages: list[dict[str, str]]) -> Any:
        """Elige la respuesta segun una marca presente en el prompt del sistema."""
        system = messages[0]["content"] if messages else ""
        for marker, payload in self.json_by_marker.items():
            if marker in system:
                return payload(messages) if callable(payload) else payload
        return None

    async def json_call(
        self, messages: list[dict[str, str]], *, model: str, timeout: float = 45.0, retries: int = 1
    ) -> dict[str, Any] | None:
        self.json_calls.append(messages[-1]["content"])
        if not self.online or self.fail_json:
            return None
        return self._match(messages)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.3,
        timeout: float = 60.0,
        max_tokens: int | None = None,
    ) -> str:
        self.chat_calls.append(messages[-1]["content"])
        if not self.online:
            from aw1.core.errors import ProviderError

            raise ProviderError("Ollama apagado en la prueba.")
        return self.text_reply

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.6,
        timeout: float = 180.0,
    ) -> AsyncIterator[str]:
        self.chat_calls.append(messages[-1]["content"])
        if not self.online:
            from aw1.core.errors import ProviderError

            raise ProviderError("Ollama apagado en la prueba.")
        for piece in self.text_reply.split(" "):
            yield piece + " "


# Marcas para localizar cada prompt de sistema sin depender del texto completo.
PLAN_MARKER = "planificador de un comparador"
CANDIDATES_MARKER = "filtro de un comparador"
PAGE_MARKER = "analista de fichas"
ROUTE_MARKER = "enrutador interno"


def plan_payload(product: str, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "product": product,
        "brand": "",
        "model": "",
        "category": "celular",
        "queries": [product],
        "required": required or [],
        "forbidden": ["funda", "case", "cable"],
        "notes": "Plan de prueba.",
    }


def pick_first(count: int = 2) -> Any:
    """Elige los primeros ``count`` ids que aparezcan en el prompt."""

    def build(messages: list[dict[str, str]]) -> dict[str, Any]:
        import re

        ids = [int(value) for value in re.findall(r"^\[(\d+)\]", messages[-1]["content"], re.M)]
        return {
            "picks": [
                {"id": item, "confidence": 0.9, "reason": "coincide"} for item in ids[:count]
            ],
            "discarded_reason": "el resto no coincide",
        }

    return build


def choose_candidate(match: str) -> Any:
    """Elige el candidato de precio cuyo contexto contenga ``match``."""

    def build(messages: list[dict[str, str]]) -> dict[str, Any]:
        import re

        content = messages[-1]["content"]
        chosen_id, chosen_value = None, None
        for line in content.splitlines():
            found = re.match(r"\[(\d+)\] (.+?) \(valor ([\d.]+) (\w+)", line.strip())
            if not found:
                continue
            if match.lower() in line.lower() and chosen_id is None:
                chosen_id = int(found.group(1))
                chosen_value = float(found.group(3))
        if chosen_id is None:
            return {"is_match": False, "candidate_id": None, "price": None, "reason": "sin match"}
        title = ""
        for line in content.splitlines():
            if line.startswith("Titulo:"):
                title = line.split(":", 1)[1].strip()
        return {
            "is_match": True,
            "candidate_id": chosen_id,
            "price": chosen_value,
            "currency": "CLP",
            "product_title": title,
            "in_stock": True,
            "confidence": 0.92,
            "reason": f"elegido por contexto {match}",
        }

    return build

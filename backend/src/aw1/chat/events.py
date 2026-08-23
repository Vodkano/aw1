"""Eventos que emite el chat mientras responde, para que la interfaz los pinte
token a token. Vive en su propio modulo porque tanto ``service.py`` como
``chat/tools/*`` necesitan el mismo tipo sin crear un import circular entre
ambos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ChatEvent:
    type: str
    data: dict[str, Any]

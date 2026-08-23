"""Recuerdo de largo plazo: contexto de solo lectura tomado de saved_items.

Solo lee -nunca escribe. Las unicas filas que existen en saved_items son las
que la persona guardo a mano con el boton "Guardar" de la interfaz; esto no
cambia eso, solo deja que el chat las use como contexto para no re-derivar
algo que ya quedo guardado. Sin busqueda semantica: coincidencia simple por
palabras clave, de sobra para el volumen esperado de una app personal
(max_saved_items, 500 por defecto).
"""

from __future__ import annotations

import re

from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.prompts import SAVED_NOTES_NOTICE
from ..llm.schemas import ChatRoute

MIN_KEYWORD_LEN = 3
MAX_KEYWORDS = 4
MAX_ITEMS = 3
MAX_ITEM_CHARS = 600


def _keywords(route: ChatRoute, message: str) -> list[str]:
    words = re.findall(r"\w+", (route.search_terms or message).lower())
    found: list[str] = []
    for word in words:
        if len(word) >= MIN_KEYWORD_LEN and word not in found:
            found.append(word)
        if len(found) >= MAX_KEYWORDS:
            break
    return found


async def recall(repo: Repository | PostgresRepository, route: ChatRoute, message: str) -> str:
    keywords = _keywords(route, message)
    if not keywords:
        return ""
    items = await repo.search_items(keywords, limit=MAX_ITEMS)
    if not items:
        return ""
    lines = "\n".join(f"- {item['text'][:MAX_ITEM_CHARS]}" for item in items)
    return f"{SAVED_NOTES_NOTICE}\n<<<DATOS>>>\n{lines}\n<<<FIN>>>"

"""Enrutado sin IA, para cuando Ollama no esta disponible.

No pretende ser tan bueno como el modelo: pretende que el chat siga siendo util
si el modelo esta caido, y servir de respaldo cuando el JSON del enrutador no
llega bien.
"""

from __future__ import annotations

import re
import unicodedata

from ..llm.schemas import ChatRoute

_ABBREVIATIONS = {
    "q": "que", "xq": "por que", "pq": "por que", "k": "que", "ke": "que",
    "kien": "quien", "qien": "quien", "quen": "quien", "kual": "cual",
    "tb": "tambien", "tmb": "tambien", "dnd": "donde", "x": "por", "d": "de",
    "pa": "para", "porfa": "por favor", "info": "informacion", "wiki": "wikipedia",
    "presio": "precio", "presios": "precios", "kuanto": "cuanto", "cuanro": "cuanto",
    "biografa": "biografia", "biograia": "biografia",
}

_BIO = (
    r"\bquien(?:es)? (?:es|fue|era|son|fueron)\b",
    r"\bbiografia (?:de|del)\b",
    r"\bcuando (?:nacio|murio)\b",
    r"\bde que (?:pais|nacionalidad)\b",
    r"\bhabla(?:me)? (?:de|sobre)\b",
)
_PRICE = (r"\b(?:precio|precios|cuanto (?:cuesta|vale|sale)|comparar precios|mas barato)\b",)
_CODE = (
    r"\b(?:codigo|funcion|script|clase|metodo|snippet|bug|error|traceback)\b",
    r"\b(?:python|javascript|typescript|java|sql|bash|go|rust|php|html|css)\b",
)
_FRESH = (
    r"\b(?:hoy|ahora|actual|actualmente|ultimas?|reciente|noticias?|clima|dolar|euro|bitcoin)\b",
    r"\b20(?:2[6-9]|[3-9]\d)\b",
)


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def canonical(text: str) -> str:
    """Minusculas, sin acentos y con las abreviaturas frecuentes expandidas."""
    base = strip_accents(" ".join(str(text or "").split())).lower()
    words = re.findall(r"[\w']+|[^\w\s]", base)
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words).strip()


def looks_empty(text: str) -> bool:
    canon = canonical(text)
    if not canon:
        return True
    letters = re.sub(r"[^a-z]", "", canon)
    return len(letters) >= 8 and not re.search(r"[aeiou]", letters)


def extract_person(message: str) -> str:
    cleaned = " ".join(str(message or "").split()).rstrip("?.!")
    match = re.search(
        r"(?i)\b(?:quien(?:es)? (?:es|fue|era|son|fueron)|biografia de(?:l)?|"
        r"cuando (?:nacio|murio)|habla(?:me)? (?:de|sobre))\s+(.+)$",
        cleaned,
    )
    candidate = match.group(1) if match else cleaned
    candidate = re.sub(r"(?i)^(?:el|la|los|las|un|una)\s+", "", candidate)
    return " ".join(candidate.split()[:6]).strip(" ,.;:")


def route(message: str) -> ChatRoute:
    canon = canonical(message)
    if looks_empty(message):
        return ChatRoute(intent="confuso", confidence=0.3, reason="Entrada sin contenido legible.")
    if any(re.search(pattern, canon) for pattern in _PRICE):
        return ChatRoute(
            intent="precio", search_terms=canon, confidence=0.7,
            reason="Menciona precio o coste.",
        )
    if any(re.search(pattern, canon) for pattern in _BIO):
        person = extract_person(message)
        return ChatRoute(
            intent="biografia", person=person, search_terms=person,
            confidence=0.75 if person else 0.5, reason="Pregunta por una persona.",
        )
    if any(re.search(pattern, canon) for pattern in _CODE):
        return ChatRoute(intent="codigo", heavy=True, confidence=0.65, reason="Peticion tecnica.")
    if any(re.search(pattern, canon) for pattern in _FRESH):
        return ChatRoute(
            intent="actualidad", needs_fresh_data=True, search_terms=canon,
            confidence=0.6, reason="Necesita datos actuales.",
        )
    return ChatRoute(intent="charla", confidence=0.55, reason="Conversacion general.")


def merge(heuristic: ChatRoute, model: ChatRoute | None) -> ChatRoute:
    """Combina ambas capas. El precio siempre lo manda la heuristica: es una ruta
    de producto, no una opinion del modelo."""
    if model is None:
        return heuristic
    if heuristic.intent == "precio":
        return heuristic
    merged = model.model_copy()
    if merged.intent == "biografia" and not merged.person:
        merged.person = heuristic.person or extract_person(heuristic.search_terms)
    if not merged.search_terms:
        merged.search_terms = heuristic.search_terms
    return merged

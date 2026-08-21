"""Coincidencia deterministica entre lo pedido y lo encontrado.

Esta capa NO sustituye a la IA: la respalda. Ollama decide, pero si esta caido,
tarda demasiado o devuelve algo que no encaja en el esquema, el comparador sigue
funcionando con estas reglas. Tambien se usa para ordenar los candidatos antes
de enviarselos al modelo, de modo que lo mas prometedor entre primero en su
ventana de contexto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ACCESSORY_WORDS = frozenset({
    "funda", "fundas", "case", "carcasa", "cover", "protector", "protectora", "mica",
    "lamina", "vidrio", "templado", "correa", "correas", "pulsera", "cable", "cables",
    "cargador", "adaptador", "soporte", "estuche", "repuesto", "repuestos", "kit",
    "almohadilla", "almohadillas", "adhesivo", "organizador", "holder", "gancho",
    "compatible", "compatibles", "generico", "replica", "imitacion",
})
CONDITION_WORDS = frozenset(
    {"usado", "usada", "reacondicionado", "refurbished", "segunda", "outlet"}
)
STOPWORDS = frozenset({
    "de", "del", "la", "el", "los", "las", "un", "una", "con", "para", "y", "en", "a",
    "por", "the", "of",
})

_TOKEN = re.compile(r"[a-z0-9]+")
_SPLIT_ALNUM = re.compile(r"\d+|[a-z]+")

MIN_COVERAGE = 0.6


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(strip_accents(text).lower())


def expand(tokens: list[str]) -> set[str]:
    """Genera variantes: 128gb tambien cuenta como {128, gb}; quita plurales."""
    result: set[str] = set()
    for token in tokens:
        result.add(token)
        if token.endswith("s") and len(token) > 3:
            result.add(token[:-1])
        parts = _SPLIT_ALNUM.findall(token)
        if len(parts) > 1:
            result.update(part for part in parts if part)
    return result


@dataclass(frozen=True, slots=True)
class Match:
    ok: bool
    score: float
    reason: str
    #: Motivo del rechazo: ok, coverage, required o accessory.
    #: El motivo importa: que falte cobertura puede ser un titulo escueto y la
    #: IA tiene derecho a sobreescribirlo. Que sea un accesorio o que falte un
    #: requisito explicito es un no rotundo.
    kind: str = "ok"


def score(
    text: str,
    product: str,
    *,
    required: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> Match:
    """Puntua cuanto se parece ``text`` al producto pedido.

    La regla es de cobertura, no de exigencia total: pedir que aparezcan
    literalmente todos los terminos descarta fichas correctas cuando la tienda
    escribe "128GB" pegado o anade palabras de color y modelo.
    """
    wanted = [token for token in tokenize(product) if token not in STOPWORDS]
    if not wanted:
        return Match(False, 0.0, "La consulta no tiene terminos utiles.", "required")

    tokens = tokenize(text)
    present = expand(tokens)
    flat = "".join(tokens)

    hits = 0
    for token in set(wanted):
        singular = token[:-1] if token.endswith("s") and len(token) > 3 else token
        if token in present or singular in present or (len(singular) > 3 and singular in flat):
            hits += 1
    coverage = hits / len(set(wanted))

    for term in required or []:
        needle = strip_accents(str(term)).lower().strip()
        if not needle:
            continue
        needle_tokens = set(_TOKEN.findall(needle))
        if not needle_tokens <= present and needle.replace(" ", "") not in flat:
            return Match(False, coverage, f"Falta un requisito: {term}", "required")

    query_tokens = set(wanted)
    banned = {strip_accents(str(term)).lower() for term in (forbidden or [])}
    banned |= ACCESSORY_WORDS | CONDITION_WORDS
    banned -= query_tokens

    hit_words = banned & present
    if hit_words:
        # Solo descarta si la palabra prohibida manda: aparece antes que el
        # primer termino del producto. "Funda para AirPods" se descarta;
        # "AirPods con estuche de carga" no.
        first_bad = _first_index(tokens, hit_words)
        first_good = _first_index(tokens, query_tokens)
        if first_bad is not None and (first_good is None or first_bad < first_good):
            return Match(
                False, coverage, f"Parece {tokens[first_bad]}, no el producto.", "accessory"
            )

    if coverage < MIN_COVERAGE:
        return Match(False, coverage, "No menciona lo suficiente del producto buscado.", "coverage")
    return Match(True, coverage, "Coincide con el producto buscado.")


def _first_index(tokens: list[str], wanted: set[str]) -> int | None:
    for index, token in enumerate(tokens):
        singular = token[:-1] if token.endswith("s") and len(token) > 3 else token
        if token in wanted or singular in wanted:
            return index
        if any(part in wanted for part in _SPLIT_ALNUM.findall(token)):
            return index
    return None


def matches(text: str, product: str, **kwargs: object) -> bool:
    return score(text, product, **kwargs).ok  # type: ignore[arg-type]


def fallback_queries(product: str) -> list[str]:
    """Variantes de busqueda sin IA: la completa y otra sin la ultima unidad."""
    clean = " ".join(str(product).split())
    variants = [clean]
    without_units = re.sub(r"(?i)\b\d+\s?(gb|tb|mb|pulgadas|\")\b", "", clean).strip()
    without_units = " ".join(without_units.split())
    if without_units and without_units.lower() != clean.lower():
        variants.append(without_units)
    return variants[:2]

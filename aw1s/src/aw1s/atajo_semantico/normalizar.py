"""Paso 0 y paso 1 de la calibracion v1: filtro de longitud y normalizacion.

Ver docs/aw1s/planos/0.1.0.2-atajo-semantico.md -- ambos pasos son
deterministas, sin vectorizar nada, a proposito: son los mas baratos y
resuelven la mayoria del trafico trivial antes de llegar a un embedding.
"""

from __future__ import annotations

import re
import unicodedata

MAX_PALABRAS = 6
MAX_CARACTERES = 40

_PUNTUACION = re.compile(r"[^\w\s]", re.UNICODE)
_ESPACIOS = re.compile(r"\s+")


def normalizar_texto(texto: str) -> str:
    """Minusculas, sin tildes, sin signos de puntuacion, sin espacios de mas."""
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    sin_puntuacion = _PUNTUACION.sub(" ", sin_tildes)
    return _ESPACIOS.sub(" ", sin_puntuacion).strip()


def pasa_filtro_longitud(
    texto: str, *, max_palabras: int = MAX_PALABRAS, max_caracteres: int = MAX_CARACTERES
) -> bool:
    """False si el mensaje es demasiado largo para ser un caso trivial.

    Este filtro por si solo descarta el caso de riesgo que motivo la
    calibracion ("hola, tengo un problema urgente" son 8 palabras) sin
    necesidad de calcular ningun score de similitud.
    """
    texto = texto.strip()
    if not texto:
        return False
    if len(texto) > max_caracteres:
        return False
    return len(texto.split()) <= max_palabras

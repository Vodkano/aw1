"""Dataclasses del contexto ya armado -- lo que Contexto le entrega a
Procesamiento principal."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..almacenamiento.modelos import Interaccion, Memoria
from ..inteligencia.modelos import Necesidad


@dataclass(frozen=True)
class ResultadoBusqueda:
    necesidad: Necesidad
    """Interacciones recientes de la sesion -- solo si la necesidad pedia
    historial de sesion (fuente postgres/ambas + usa_historial_sesion)."""
    interacciones: list[Interaccion] = field(default_factory=list)
    """Memorias por similitud semantica, con su score -- solo si la
    necesidad pedia memoria semantica (fuente pgvector/ambas +
    usa_memoria_semantica)."""
    memorias: list[tuple[Memoria, float]] = field(default_factory=list)


@dataclass(frozen=True)
class ContextoArmado:
    resultados: list[ResultadoBusqueda]
    contexto_id: int

"""Dataclasses de la decision que produce Inteligencia -- reflejan el
esquema JSON de prompt.py, ya validado y tipado."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Necesidad:
    fuente: str  # "postgres" | "pgvector" | "ambas"
    que_buscar: str
    terminos_busqueda_semantica: str | None
    usa_historial_sesion: bool
    usa_memoria_semantica: bool
    cantidad_maxima: int
    prioridad: str  # "alta" | "media" | "baja"


@dataclass(frozen=True)
class EvaluacionContextoPrevio:
    alcanza: bool
    motivo: str


@dataclass(frozen=True)
class DecisionInteligencia:
    tipo_problema: str
    requiere_informacion_adicional: bool
    evaluacion_contexto_previo: EvaluacionContextoPrevio | None
    necesidades: list[Necesidad]
    listo_para_procesar: bool

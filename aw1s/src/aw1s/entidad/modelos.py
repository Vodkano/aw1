from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoEntidad:
    respuesta: str
    origen: str  # "atajo_semantico" | "ciclo_completo"
    sesion_id: int | None
    interaccion_id: int | None
    iteraciones_usadas: int

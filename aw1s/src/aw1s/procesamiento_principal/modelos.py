"""Dataclass del resultado interno -- la resolucion, antes de Humanizacion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoProcesamiento:
    resultado: str

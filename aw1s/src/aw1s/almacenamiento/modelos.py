"""Dataclasses que reflejan el modelo conceptual de
docs/aw1s/documentacion/arquitectura.md#3 -- una por entidad, sin logica.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Usuario:
    id: int
    identificador_externo: str | None
    creado_en: datetime


@dataclass(frozen=True)
class Sesion:
    id: int
    usuario_id: int | None
    iniciada_en: datetime
    ultima_actividad_en: datetime


@dataclass(frozen=True)
class Interaccion:
    id: int
    sesion_id: int
    mensaje_usuario: str
    metadata: dict
    ip: str | None
    creada_en: datetime


@dataclass(frozen=True)
class Contexto:
    id: int
    interaccion_id: int
    contenido: dict
    creado_en: datetime


@dataclass(frozen=True)
class Memoria:
    id: int
    interaccion_id: int
    contenido: str
    creada_en: datetime


@dataclass(frozen=True)
class Embedding:
    id: int
    memoria_id: int
    modelo: str
    creado_en: datetime


@dataclass(frozen=True)
class Evento:
    id: int
    interaccion_id: int | None
    tipo: str
    detalle: dict
    ocurrido_en: datetime

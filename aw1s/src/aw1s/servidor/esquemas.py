"""Modelos Pydantic del servidor HTTP -- el contrato con quien llame a la
API (validacion + serializacion JSON). A proposito separados de
``entidad/modelos.py`` (dataclasses, el contrato interno entre
componentes): no todo lo que necesita ``procesar_mensaje()`` tiene sentido
como parametro HTTP (``instrucciones``/``canal`` son pensados para cuando
un bot de Telegram llame a esto, no para que los escriba una persona)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MensajeEntrada(BaseModel):
    mensaje: str = Field(min_length=1)
    sesion_id: int | None = None
    identificador_externo: str | None = None
    metadata: dict | None = None
    ip: str | None = None
    instrucciones: str | None = None
    canal: str | None = None
    limite_iteraciones: int | None = Field(default=None, ge=1)


class MensajeSalida(BaseModel):
    respuesta: str
    origen: str
    sesion_id: int | None
    interaccion_id: int | None
    iteraciones_usadas: int

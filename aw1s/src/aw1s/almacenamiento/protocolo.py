"""Interfaz que separa la logica de persistencia de su implementacion.

Se llama ``RepositorioAlmacenamiento`` y no ``RepositorioMemoria`` a
proposito: cubre tanto lo que persiste Inteligencia (Usuario, Sesion,
Interaccion, Evento -- ver docs/aw1s/planos/0.1.0.3) como lo que persiste
el componente Memoria en si (Memoria, Embedding) -- son dos responsabilidades
distintas de la arquitectura sobre el mismo almacenamiento fisico, y este
protocolo no le pone nombre de una sola de ellas al conjunto.
"""

from __future__ import annotations

from typing import Protocol

from .modelos import Contexto, Embedding, Evento, Interaccion, Memoria, Sesion, Usuario


class RepositorioAlmacenamiento(Protocol):
    async def obtener_o_crear_usuario(self, identificador_externo: str | None) -> Usuario: ...

    async def abrir_sesion(self, usuario_id: int | None) -> Sesion: ...

    async def obtener_sesion(self, sesion_id: int) -> Sesion | None: ...

    async def crear_interaccion(
        self, sesion_id: int, mensaje_usuario: str, metadata: dict, ip: str | None
    ) -> Interaccion: ...

    async def interacciones_recientes(
        self, sesion_id: int, limite: int = 10
    ) -> list[Interaccion]: ...

    async def registrar_evento(
        self, tipo: str, detalle: dict, interaccion_id: int | None = None
    ) -> Evento: ...

    async def guardar_contexto(self, interaccion_id: int, contenido: dict) -> Contexto: ...

    async def guardar_memoria(self, interaccion_id: int, contenido: str) -> Memoria: ...

    async def guardar_embedding(
        self, memoria_id: int, vector: list[float], modelo: str
    ) -> Embedding: ...

    async def buscar_memorias_similares(
        self, vector: list[float], limite: int = 5
    ) -> list[tuple[Memoria, float]]: ...

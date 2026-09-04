"""Dobles de prueba -- mismo espiritu que backend/tests/fakes.py: nada de
red ni de Postgres real, solo lo minimo para ejercitar la logica propia."""

from __future__ import annotations

from datetime import UTC, datetime

from aw1s.almacenamiento.modelos import (
    Contexto,
    Embedding,
    Evento,
    Interaccion,
    Memoria,
    Sesion,
    Usuario,
)
from aw1s.atajo_semantico.embeddings import similitud_coseno
from aw1s.inteligencia.cliente_llm import ClienteLLMError


class FakeClienteLLM:
    """``respuestas``: un dict (siempre la misma respuesta) o una lista
    (una por llamada, en orden -- para probar el ciclo de Inteligencia
    pidiendo otra vuelta). ``lanza``: si se da, la proxima llamada lanza
    eso en vez de devolver una respuesta."""

    def __init__(
        self,
        respuestas: dict | list[dict] | None = None,
        *,
        lanza: Exception | None = None,
    ) -> None:
        self.respuestas = respuestas
        self.lanza = lanza
        self.llamadas: list[dict[str, str]] = []

    async def generar_json(self, *, system: str, mensaje: str) -> dict:
        self.llamadas.append({"system": system, "mensaje": mensaje})
        if self.lanza is not None:
            raise self.lanza
        if isinstance(self.respuestas, list):
            return self.respuestas[len(self.llamadas) - 1]
        if self.respuestas is None:
            raise ClienteLLMError("FakeClienteLLM sin respuesta configurada.")
        return self.respuestas


class FakeEmbeddings:
    def __init__(
        self,
        vectores: dict[str, list[float]] | None = None,
        default: list[float] | None = None,
    ) -> None:
        self.vectores = vectores or {}
        self.default = default or [1.0, 0.0]
        self.calls: list[str] = []

    async def vectorizar(self, texto: str) -> list[float]:
        self.calls.append(texto)
        return self.vectores.get(texto, self.default)


def vector_con_similitud(score: float) -> list[float]:
    """Vector unitario 2D tal que su similitud coseno con [1.0, 0.0] es
    exactamente ``score`` (0 < score <= 1) -- para probar los umbrales sin
    depender de un modelo de embeddings real."""
    import math

    return [score, math.sqrt(max(0.0, 1.0 - score * score))]


class RepositorioEnMemoria:
    """Implementa RepositorioAlmacenamiento sin Postgres -- para probar
    componentes que dependen del protocolo (Inteligencia, Memoria, etc.)
    sin una base de datos real. No valida el SQL de
    almacenamiento/postgres.py -- esa parte se prueba aparte, contra un
    Postgres+pgvector real, con scripts/verificar_schema.py."""

    def __init__(self) -> None:
        self._usuarios: dict[int, Usuario] = {}
        self._usuarios_por_externo: dict[str, int] = {}
        self._sesiones: dict[int, Sesion] = {}
        self._interacciones: dict[int, Interaccion] = {}
        self._contextos: dict[int, Contexto] = {}
        self._memorias: dict[int, Memoria] = {}
        self._embeddings: dict[int, tuple[Embedding, list[float]]] = {}
        self._eventos: dict[int, Evento] = {}
        self._siguiente_id: dict[str, int] = {}

    def _nuevo_id(self, tabla: str) -> int:
        self._siguiente_id[tabla] = self._siguiente_id.get(tabla, 0) + 1
        return self._siguiente_id[tabla]

    async def obtener_o_crear_usuario(self, identificador_externo: str | None) -> Usuario:
        if identificador_externo is not None:
            existente = self._usuarios_por_externo.get(identificador_externo)
            if existente is not None:
                return self._usuarios[existente]
        usuario = Usuario(
            id=self._nuevo_id("usuarios"),
            identificador_externo=identificador_externo,
            creado_en=datetime.now(UTC),
        )
        self._usuarios[usuario.id] = usuario
        if identificador_externo is not None:
            self._usuarios_por_externo[identificador_externo] = usuario.id
        return usuario

    async def abrir_sesion(self, usuario_id: int | None) -> Sesion:
        ahora = datetime.now(UTC)
        sesion = Sesion(
            id=self._nuevo_id("sesiones"),
            usuario_id=usuario_id,
            iniciada_en=ahora,
            ultima_actividad_en=ahora,
        )
        self._sesiones[sesion.id] = sesion
        return sesion

    async def obtener_sesion(self, sesion_id: int) -> Sesion | None:
        return self._sesiones.get(sesion_id)

    async def crear_interaccion(
        self, sesion_id: int, mensaje_usuario: str, metadata: dict, ip: str | None
    ) -> Interaccion:
        interaccion = Interaccion(
            id=self._nuevo_id("interacciones"),
            sesion_id=sesion_id,
            mensaje_usuario=mensaje_usuario,
            metadata=metadata,
            ip=ip,
            creada_en=datetime.now(UTC),
        )
        self._interacciones[interaccion.id] = interaccion
        if sesion_id in self._sesiones:
            previa = self._sesiones[sesion_id]
            self._sesiones[sesion_id] = Sesion(
                id=previa.id,
                usuario_id=previa.usuario_id,
                iniciada_en=previa.iniciada_en,
                ultima_actividad_en=interaccion.creada_en,
            )
        return interaccion

    async def interacciones_recientes(self, sesion_id: int, limite: int = 10) -> list[Interaccion]:
        de_la_sesion = [i for i in self._interacciones.values() if i.sesion_id == sesion_id]
        de_la_sesion.sort(key=lambda i: i.creada_en, reverse=True)
        return de_la_sesion[:limite]

    async def registrar_evento(
        self, tipo: str, detalle: dict, interaccion_id: int | None = None
    ) -> Evento:
        evento = Evento(
            id=self._nuevo_id("eventos"),
            interaccion_id=interaccion_id,
            tipo=tipo,
            detalle=detalle,
            ocurrido_en=datetime.now(UTC),
        )
        self._eventos[evento.id] = evento
        return evento

    async def guardar_contexto(self, interaccion_id: int, contenido: dict) -> Contexto:
        contexto = Contexto(
            id=self._nuevo_id("contextos"),
            interaccion_id=interaccion_id,
            contenido=contenido,
            creado_en=datetime.now(UTC),
        )
        self._contextos[contexto.id] = contexto
        return contexto

    async def guardar_memoria(self, interaccion_id: int, contenido: str) -> Memoria:
        memoria = Memoria(
            id=self._nuevo_id("memorias"),
            interaccion_id=interaccion_id,
            contenido=contenido,
            creada_en=datetime.now(UTC),
        )
        self._memorias[memoria.id] = memoria
        return memoria

    async def guardar_embedding(
        self, memoria_id: int, vector: list[float], modelo: str
    ) -> Embedding:
        embedding = Embedding(
            id=self._nuevo_id("embeddings"), memoria_id=memoria_id, modelo=modelo,
            creado_en=datetime.now(UTC),
        )
        self._embeddings[embedding.id] = (embedding, vector)
        return embedding

    async def buscar_memorias_similares(
        self, vector: list[float], limite: int = 5
    ) -> list[tuple[Memoria, float]]:
        resultados = [
            (self._memorias[embedding.memoria_id], similitud_coseno(vector, guardado))
            for embedding, guardado in self._embeddings.values()
            if embedding.memoria_id in self._memorias
        ]
        resultados.sort(key=lambda par: par[1], reverse=True)
        return resultados[:limite]

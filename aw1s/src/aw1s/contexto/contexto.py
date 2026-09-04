"""Orquesta Contexto: ejecuta las necesidades que decidio Inteligencia.

Regla de la spec que este modulo respeta a proposito: Contexto no decide
QUE hace falta -- eso ya lo decidio Inteligencia (ver
docs/aw1s/documentacion/arquitectura.md#22-contexto). Este modulo solo
ejecuta cada `Necesidad` tal cual llega: recupera historial de sesion
desde Postgres, memoria semantica desde pgvector, o ambas segun lo que
diga `necesidad.fuente`, y arma el resultado. No filtra por su cuenta mas
alla de lo que la propia `Necesidad` ya especifica (cantidad_maxima, que
fuente).
"""

from __future__ import annotations

from ..almacenamiento.modelos import Interaccion, Memoria
from ..almacenamiento.protocolo import RepositorioAlmacenamiento
from ..atajo_semantico.embeddings import EmbeddingsProvider
from ..inteligencia.modelos import Necesidad
from .modelos import ContextoArmado, ResultadoBusqueda


async def construir_contexto(
    necesidades: list[Necesidad],
    *,
    sesion_id: int,
    interaccion_id: int,
    repositorio: RepositorioAlmacenamiento,
    embeddings: EmbeddingsProvider,
    persistir: bool = True,
) -> ContextoArmado:
    """``persistir=False``: no guarda fila en `contextos` -- para las
    rondas intermedias del ciclo de Inteligencia (el flujo original
    distingue "Contexto: recupera" de "Contexto: construye el contexto
    final", ver docs/aw1s/documentacion/arquitectura.md#4; solo la ronda
    final corresponde a esa segunda accion). Bug real encontrado al armar
    el orquestador: antes, cada ronda intermedia dejaba una fila de
    `contextos` para la misma interaccion, rompiendo la relacion 1-a-1
    que describe el modelo de datos (arquitectura.md#3)."""
    resultados = [
        await _ejecutar_necesidad(
            necesidad, sesion_id=sesion_id, repositorio=repositorio, embeddings=embeddings
        )
        for necesidad in necesidades
    ]

    contexto_id = None
    if persistir:
        contexto = await repositorio.guardar_contexto(interaccion_id, _serializar(resultados))
        contexto_id = contexto.id

    return ContextoArmado(resultados=resultados, contexto_id=contexto_id)


async def _ejecutar_necesidad(
    necesidad: Necesidad,
    *,
    sesion_id: int,
    repositorio: RepositorioAlmacenamiento,
    embeddings: EmbeddingsProvider,
) -> ResultadoBusqueda:
    usa_postgres = necesidad.fuente in ("postgres", "ambas")
    usa_pgvector = necesidad.fuente in ("pgvector", "ambas")

    interacciones: list[Interaccion] = []
    if usa_postgres and necesidad.usa_historial_sesion:
        interacciones = await repositorio.interacciones_recientes(
            sesion_id, limite=necesidad.cantidad_maxima
        )

    memorias: list[tuple[Memoria, float]] = []
    if usa_pgvector and necesidad.usa_memoria_semantica:
        texto_busqueda = necesidad.terminos_busqueda_semantica or necesidad.que_buscar
        vector = await embeddings.vectorizar(texto_busqueda)
        memorias = await repositorio.buscar_memorias_similares(
            vector, limite=necesidad.cantidad_maxima
        )

    return ResultadoBusqueda(necesidad=necesidad, interacciones=interacciones, memorias=memorias)


def contexto_a_dict(contexto: ContextoArmado) -> dict:
    """Version dict de un ContextoArmado ya construido -- para pasarlo
    como ``contexto_recuperado`` a ``inteligencia.reevaluar()`` sin
    depender de que se haya persistido (funciona igual con
    ``persistir=False``)."""
    return _serializar(contexto.resultados)


def _serializar(resultados: list[ResultadoBusqueda]) -> dict:
    """A dict JSON-serializable, para guardar_contexto (columna JSONB)."""
    return {
        "resultados": [
            {
                "necesidad": {
                    "fuente": r.necesidad.fuente,
                    "que_buscar": r.necesidad.que_buscar,
                    "prioridad": r.necesidad.prioridad,
                },
                "interacciones": [
                    {
                        "id": i.id,
                        "mensaje_usuario": i.mensaje_usuario,
                        "creada_en": i.creada_en.isoformat(),
                    }
                    for i in r.interacciones
                ],
                "memorias": [
                    {"id": m.id, "contenido": m.contenido, "score": score}
                    for m, score in r.memorias
                ],
            }
            for r in resultados
        ]
    }

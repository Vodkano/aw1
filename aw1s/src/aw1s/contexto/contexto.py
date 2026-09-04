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
) -> ContextoArmado:
    resultados = [
        await _ejecutar_necesidad(
            necesidad, sesion_id=sesion_id, repositorio=repositorio, embeddings=embeddings
        )
        for necesidad in necesidades
    ]

    contexto = await repositorio.guardar_contexto(interaccion_id, _serializar(resultados))

    return ContextoArmado(resultados=resultados, contexto_id=contexto.id)


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

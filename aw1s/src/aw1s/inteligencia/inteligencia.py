"""Orquesta la capa de Inteligencia.

Dos responsabilidades separadas, en el orden que documenta
docs/aw1s/planos/0.1.0.3-inteligencia-recoleccion-datos.md:

1. Persistir los datos crudos de la interaccion (Usuario, Sesion,
   Interaccion, Evento) apenas llegan -- efecto de lado deterministico,
   nada de esto lo decide el LLM.
2. Recien despues, armar el prompt y pedirle al modelo que clasifique y
   decida que informacion hace falta.

Si el LLM devuelve algo con forma invalida, la interaccion ya quedo
persistida igual (no se pierde el dato crudo por un fallo de clasificacion)
y se propaga ``DecisionInvalidaError`` para que el llamador decida como
seguir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from ..almacenamiento.protocolo import RepositorioAlmacenamiento
from .cliente_llm import ClienteLLM
from .modelos import DecisionInteligencia, EvaluacionContextoPrevio, Necesidad
from .prompt import SYSTEM_PROMPT

LIMITE_HISTORIAL_BREVE = 5


class DecisionInvalidaError(Exception):
    pass


@dataclass(frozen=True)
class ResultadoAnalisis:
    decision: DecisionInteligencia
    interaccion_id: int
    sesion_id: int
    usuario_id: int | None


async def analizar(
    mensaje_usuario: str,
    *,
    cliente: ClienteLLM,
    repositorio: RepositorioAlmacenamiento,
    identificador_externo: str | None = None,
    sesion_id: int | None = None,
    metadata: dict | None = None,
    ip: str | None = None,
    contexto_recuperado: dict | None = None,
) -> ResultadoAnalisis:
    """``sesion_id``: pasar el de una sesion ya abierta para que la
    interaccion se agrupe ahi (charla en curso). Sin esto, abre una sesion
    nueva para ``identificador_externo`` (o anonima, si es None)."""
    metadata = dict(metadata or {})
    metadata.setdefault("hora", datetime.now(UTC).isoformat())

    if sesion_id is not None:
        sesion = await repositorio.obtener_sesion(sesion_id)
        if sesion is None:
            raise ValueError(f"No existe la sesion {sesion_id}.")
        usuario_id = sesion.usuario_id
    else:
        usuario = await repositorio.obtener_o_crear_usuario(identificador_externo)
        usuario_id = usuario.id
        sesion = await repositorio.abrir_sesion(usuario_id)

    interaccion = await repositorio.crear_interaccion(sesion.id, mensaje_usuario, metadata, ip)
    await repositorio.registrar_evento("interaccion_recibida", {}, interaccion.id)

    historial_previo = await repositorio.interacciones_recientes(
        sesion.id, limite=LIMITE_HISTORIAL_BREVE + 1
    )
    historial_breve = [
        {"mensaje": i.mensaje_usuario, "creada_en": i.creada_en.isoformat()}
        for i in historial_previo
        if i.id != interaccion.id
    ][:LIMITE_HISTORIAL_BREVE]

    entrada = {
        "mensaje_usuario": mensaje_usuario,
        "metadata": metadata,
        "historial_breve": historial_breve,
        "contexto_recuperado": contexto_recuperado,
    }
    payload = await cliente.generar_json(
        system=SYSTEM_PROMPT, mensaje=json.dumps(entrada, ensure_ascii=False)
    )
    decision = _parsear_decision(payload)

    return ResultadoAnalisis(
        decision=decision,
        interaccion_id=interaccion.id,
        sesion_id=sesion.id,
        usuario_id=usuario_id,
    )


def _parsear_decision(payload: dict) -> DecisionInteligencia:
    try:
        necesidades = [
            Necesidad(
                fuente=n["fuente"],
                que_buscar=n["que_buscar"],
                terminos_busqueda_semantica=n.get("terminos_busqueda_semantica"),
                usa_historial_sesion=bool(n["usa_historial_sesion"]),
                usa_memoria_semantica=bool(n["usa_memoria_semantica"]),
                cantidad_maxima=int(n["cantidad_maxima"]),
                prioridad=n["prioridad"],
            )
            for n in payload.get("necesidades", [])
        ]
        evaluacion = None
        crudo = payload.get("evaluacion_contexto_previo")
        if crudo:
            evaluacion = EvaluacionContextoPrevio(
                alcanza=bool(crudo["alcanza"]), motivo=crudo["motivo"]
            )
        return DecisionInteligencia(
            tipo_problema=payload["tipo_problema"],
            requiere_informacion_adicional=bool(payload["requiere_informacion_adicional"]),
            evaluacion_contexto_previo=evaluacion,
            necesidades=necesidades,
            listo_para_procesar=bool(payload["listo_para_procesar"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DecisionInvalidaError(
            f"El LLM devolvio una decision con forma invalida: {error}"
        ) from error

"""Orquesta la Entidad AW1S completa -- encadena los componentes en el
orden que describe docs/aw1s/documentacion/arquitectura.md#4:

    Entrada
      -> Atajo semantico (corto-circuito si hay match, sin LLM)
      -> Inteligencia (persiste Usuario/Sesion/Interaccion/Evento + clasifica)
      -> ciclo: Contexto (recupera, sin persistir) <-> Inteligencia.reevaluar
      -> Contexto (construye el contexto final, persiste)
      -> Procesamiento principal (resuelve)
      -> Humanizacion (redacta la respuesta)
      -> Memoria: NO IMPLEMENTADO ACA. La spec no define todavia la regla
         de que interaccion se conserva como memoria semantica (ver punto
         pendiente en documentacion/arquitectura.md#8) -inventar una
         politica por defecto (ej. "guardar siempre") seria una decision
         de producto que nadie pidio. Queda marcado a proposito, no en
         silencio: este orquestador termina en Humanizacion.

Dos decisiones propias, no definidas por la spec, que hacen falta para
que esto funcione y quedan documentadas aca en vez de en un doc aparte
por ser detalles de implementacion del orquestador en si:

- ``sesion_activa`` para el Atajo semantico (regla de sesion activa, ver
  docs/aw1s/planos/0.1.0.2-atajo-semantico.md) se aproxima como
  "se paso un sesion_id" -no es la definicion real de "interaccion
  reciente sin resolver" que la spec deja pendiente, es lo minimo
  disponible en esta firma sin agregar otra llamada a la base.
- ``limite_iteraciones`` (tope duro del ciclo Inteligencia<->Contexto,
  pedido explicitamente en docs/aw1s/prompts/inteligencia.md pero sin
  numero definido): 3 por defecto, valor de partida sin medir.
"""

from __future__ import annotations

from ..almacenamiento.protocolo import RepositorioAlmacenamiento
from ..atajo_semantico.atajo import evaluar_atajo
from ..atajo_semantico.embeddings import EmbeddingsProvider
from ..atajo_semantico.indice import IndiceFrasesConocidas
from ..contexto import construir_contexto, contexto_a_dict
from ..contexto.modelos import ContextoArmado
from ..humanizacion import humanizar
from ..inteligencia import ClienteLLM, analizar, reevaluar
from ..llm.ollama import GeneradorTexto
from ..procesamiento_principal import resolver
from .modelos import ResultadoEntidad

LIMITE_ITERACIONES_POR_DEFECTO = 3


async def procesar_mensaje(
    mensaje_usuario: str,
    *,
    indice: IndiceFrasesConocidas,
    embeddings: EmbeddingsProvider,
    cliente_json: ClienteLLM,
    cliente_texto: GeneradorTexto,
    repositorio: RepositorioAlmacenamiento,
    identificador_externo: str | None = None,
    sesion_id: int | None = None,
    metadata: dict | None = None,
    ip: str | None = None,
    instrucciones: str | None = None,
    canal: str | None = None,
    limite_iteraciones: int = LIMITE_ITERACIONES_POR_DEFECTO,
) -> ResultadoEntidad:
    if limite_iteraciones < 1:
        raise ValueError("limite_iteraciones tiene que ser al menos 1.")

    decision_atajo = await evaluar_atajo(
        mensaje_usuario,
        indice=indice,
        embeddings=embeddings,
        sesion_activa=sesion_id is not None,
    )
    if decision_atajo.autoriza:
        return ResultadoEntidad(
            respuesta=decision_atajo.respuesta or "",
            origen="atajo_semantico",
            sesion_id=sesion_id,
            interaccion_id=None,
            iteraciones_usadas=0,
        )

    resultado_analisis = await analizar(
        mensaje_usuario,
        cliente=cliente_json,
        repositorio=repositorio,
        identificador_externo=identificador_externo,
        sesion_id=sesion_id,
        metadata=metadata,
        ip=ip,
    )
    decision = resultado_analisis.decision
    sesion_id = resultado_analisis.sesion_id
    interaccion_id = resultado_analisis.interaccion_id

    contexto: ContextoArmado | None = None
    iteraciones = 0
    for iteraciones in range(1, limite_iteraciones + 1):
        es_ultima_permitida = iteraciones == limite_iteraciones
        contexto = await construir_contexto(
            decision.necesidades,
            sesion_id=sesion_id,
            interaccion_id=interaccion_id,
            repositorio=repositorio,
            embeddings=embeddings,
            persistir=decision.listo_para_procesar or es_ultima_permitida,
        )
        if decision.listo_para_procesar or es_ultima_permitida:
            break
        decision = await reevaluar(
            mensaje_usuario,
            cliente=cliente_json,
            repositorio=repositorio,
            sesion_id=sesion_id,
            interaccion_id=interaccion_id,
            contexto_recuperado=contexto_a_dict(contexto),
            metadata=metadata,
        )

    assert contexto is not None  # el for corre al menos una vez (limite_iteraciones >= 1)

    resultado_procesamiento = await resolver(
        mensaje_usuario,
        contexto=contexto,
        cliente=cliente_texto,
        instrucciones=instrucciones,
    )
    resultado_humanizacion = await humanizar(
        resultado_procesamiento.resultado,
        mensaje_usuario=mensaje_usuario,
        cliente=cliente_texto,
        canal=canal,
    )

    return ResultadoEntidad(
        respuesta=resultado_humanizacion.respuesta,
        origen="ciclo_completo",
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        iteraciones_usadas=iteraciones,
    )

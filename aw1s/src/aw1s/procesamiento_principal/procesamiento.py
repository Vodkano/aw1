"""Orquesta Procesamiento principal: resuelve el problema con SOLO la
consulta y el contexto ya armado por Contexto -- nunca memoria cruda (ver
docs/aw1s/documentacion/arquitectura.md#23-procesamiento-principal).

No persiste nada: a diferencia de Inteligencia, este componente es
stateless -recibe, resuelve, devuelve.
"""

from __future__ import annotations

from ..contexto.modelos import ContextoArmado, ResultadoBusqueda
from ..llm.ollama import GeneradorTexto
from .modelos import ResultadoProcesamiento
from .prompt import SYSTEM_PROMPT


async def resolver(
    mensaje_usuario: str,
    *,
    contexto: ContextoArmado,
    cliente: GeneradorTexto,
    instrucciones: str | None = None,
) -> ResultadoProcesamiento:
    """``instrucciones``: guia adicional especifica del caso (ej. la
    personalidad/alcance de un agente puntual, como ya hace AW1 v3 por
    bot de Telegram) -se suma al system prompt base, no lo reemplaza."""
    system = SYSTEM_PROMPT if not instrucciones else f"{SYSTEM_PROMPT}\n\n{instrucciones}"
    mensaje = _formatear_entrada(mensaje_usuario, contexto)

    resultado = await cliente.generar_texto(system=system, mensaje=mensaje)

    return ResultadoProcesamiento(resultado=resultado)


def _formatear_entrada(mensaje_usuario: str, contexto: ContextoArmado) -> str:
    partes = [f"Consulta del usuario: {mensaje_usuario}"]

    if not contexto.resultados:
        partes.append("\nContexto disponible: ninguno.")
        return "\n".join(partes)

    partes.append("\nContexto disponible:")
    for r in contexto.resultados:
        partes.append(f"- Sobre \"{r.necesidad.que_buscar}\":")
        partes.append(_formatear_resultado(r))
    return "\n".join(partes)


def _formatear_resultado(r: ResultadoBusqueda) -> str:
    lineas: list[str] = []
    if r.interacciones:
        lineas.append("  Historial reciente de la sesion:")
        for i in r.interacciones:
            lineas.append(f"  - {i.mensaje_usuario}")
    if r.memorias:
        lineas.append("  Memoria relacionada:")
        for memoria, score in r.memorias:
            lineas.append(f"  - {memoria.contenido} (similitud: {score:.2f})")
    if not lineas:
        lineas.append("  (sin resultados)")
    return "\n".join(lineas)

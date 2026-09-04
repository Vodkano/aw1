"""Orquesta Humanizacion: convierte el resultado interno en una respuesta
para el usuario, sin cambiar la decision (ver
docs/aw1s/documentacion/arquitectura.md#24-humanizacion).

Stateless, como Procesamiento principal -no persiste nada.
"""

from __future__ import annotations

from ..llm.ollama import GeneradorTexto
from .modelos import ResultadoHumanizacion
from .prompt import SYSTEM_PROMPT


async def humanizar(
    resultado_interno: str,
    *,
    mensaje_usuario: str,
    cliente: GeneradorTexto,
    historial_breve: list[dict] | None = None,
    canal: str | None = None,
) -> ResultadoHumanizacion:
    mensaje = _formatear_entrada(
        resultado_interno,
        mensaje_usuario=mensaje_usuario,
        historial_breve=historial_breve or [],
        canal=canal,
    )
    respuesta = await cliente.generar_texto(system=SYSTEM_PROMPT, mensaje=mensaje)
    return ResultadoHumanizacion(respuesta=respuesta)


def _formatear_entrada(
    resultado_interno: str,
    *,
    mensaje_usuario: str,
    historial_breve: list[dict],
    canal: str | None,
) -> str:
    partes = [
        f"Mensaje del usuario: {mensaje_usuario}",
        f"\nResultado a comunicar:\n{resultado_interno}",
        f"\nCanal: {canal or 'no especificado'}",
    ]
    if historial_breve:
        partes.append("\nHistorial reciente:")
        partes.extend(f"- {h.get('mensaje', '')}" for h in historial_breve)
    return "\n".join(partes)

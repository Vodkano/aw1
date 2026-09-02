"""Orquesta la calibracion v1 del Atajo semantico.

Tres pasos, del mas barato al mas caro -- se sale apenas uno autoriza o
descarta. Ver docs/aw1s/planos/0.1.0.2-atajo-semantico.md para el porque de
cada umbral.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .embeddings import EmbeddingsProvider
from .indice import CATEGORIA_DESPEDIDA, EntradaIndice, IndiceFrasesConocidas
from .normalizar import normalizar_texto, pasa_filtro_longitud

UMBRAL_AUTORIZA = 0.93
UMBRAL_CASI_MATCH = 0.85


class MotivoDecision(StrEnum):
    DEMASIADO_LARGO = "demasiado_largo"
    MATCH_EXACTO = "match_exacto"
    SIMILITUD_ALTA = "similitud_alta"
    CASI_MATCH = "casi_match"
    SIN_MATCH = "sin_match"
    BLOQUEADO_POR_SESION_ACTIVA = "bloqueado_por_sesion_activa"


@dataclass
class DecisionAtajo:
    autoriza: bool
    motivo: MotivoDecision
    respuesta: str | None = None
    score: float | None = None
    """Para observabilidad: True si cayo en la zona gris 0.85-0.93 y se
    descarto solo por eso (util para decidir si el indice deberia crecer)."""
    es_casi_match: bool = False


async def evaluar_atajo(
    mensaje: str,
    *,
    indice: IndiceFrasesConocidas,
    embeddings: EmbeddingsProvider,
    sesion_activa: bool = False,
) -> DecisionAtajo:
    """``sesion_activa``: True si hay una interaccion previa reciente sin
    resolver en la sesion (la regla de "reciente" en si queda a cargo del
    llamador -- no definida todavia, ver plano de origen)."""
    if not pasa_filtro_longitud(mensaje):
        return DecisionAtajo(autoriza=False, motivo=MotivoDecision.DEMASIADO_LARGO)

    texto_normalizado = normalizar_texto(mensaje)

    exacto = await indice.buscar_exacto(texto_normalizado)
    if exacto is not None:
        return _autorizar_o_bloquear(exacto, score=1.0, sesion_activa=sesion_activa)

    vector = await embeddings.vectorizar(mensaje)
    coincidencia = await indice.mas_similar(vector)
    if coincidencia is None:
        return DecisionAtajo(autoriza=False, motivo=MotivoDecision.SIN_MATCH)

    if coincidencia.score >= UMBRAL_AUTORIZA:
        return _autorizar_o_bloquear(
            coincidencia.entrada, score=coincidencia.score, sesion_activa=sesion_activa
        )
    if coincidencia.score >= UMBRAL_CASI_MATCH:
        return DecisionAtajo(
            autoriza=False,
            motivo=MotivoDecision.CASI_MATCH,
            score=coincidencia.score,
            es_casi_match=True,
        )
    return DecisionAtajo(autoriza=False, motivo=MotivoDecision.SIN_MATCH, score=coincidencia.score)


def _autorizar_o_bloquear(
    entrada: EntradaIndice, *, score: float, sesion_activa: bool
) -> DecisionAtajo:
    if sesion_activa and entrada.categoria != CATEGORIA_DESPEDIDA:
        return DecisionAtajo(
            autoriza=False, motivo=MotivoDecision.BLOQUEADO_POR_SESION_ACTIVA, score=score
        )
    motivo = MotivoDecision.MATCH_EXACTO if score == 1.0 else MotivoDecision.SIMILITUD_ALTA
    return DecisionAtajo(autoriza=True, motivo=motivo, respuesta=entrada.respuesta, score=score)

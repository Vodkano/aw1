from __future__ import annotations

import pytest

from aw1s.atajo_semantico import EntradaIndice, IndiceEnMemoria, MotivoDecision, evaluar_atajo
from aw1s.atajo_semantico.normalizar import normalizar_texto, pasa_filtro_longitud
from tests.fakes import FakeEmbeddings, vector_con_similitud


def _indice() -> IndiceEnMemoria:
    return IndiceEnMemoria(
        [
            EntradaIndice("hola", "Hola! En que te puedo ayudar?", "saludo", embedding=[1.0, 0.0]),
            EntradaIndice("chau", "Chau!", "despedida", embedding=[1.0, 0.0]),
        ]
    )


# -- normalizar / filtro de longitud ----------------------------------------


def test_normalizar_texto_saca_tildes_mayusculas_y_puntuacion() -> None:
    assert normalizar_texto("¡Holaaa!  ¿Qué tal?") == "holaaa que tal"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("hola", True),
        ("muchas gracias por todo", True),  # 4 palabras
        ("hola, tengo un problema urgente con mi pedido", False),  # 8 palabras
        ("", False),
    ],
)
def test_pasa_filtro_longitud(texto: str, esperado: bool) -> None:
    assert pasa_filtro_longitud(texto) is esperado


# -- paso 0: filtro de longitud descarta sin vectorizar ----------------------


async def test_mensaje_largo_no_vectoriza() -> None:
    embeddings = FakeEmbeddings()
    decision = await evaluar_atajo(
        "hola, tengo un problema urgente con mi pedido",
        indice=_indice(),
        embeddings=embeddings,
    )
    assert decision.autoriza is False
    assert decision.motivo is MotivoDecision.DEMASIADO_LARGO
    assert embeddings.calls == []  # nunca llego a pedir un embedding


# -- paso 1: match exacto normalizado -----------------------------------------


async def test_match_exacto_autoriza_sin_vectorizar() -> None:
    embeddings = FakeEmbeddings()
    decision = await evaluar_atajo("¡Hola!", indice=_indice(), embeddings=embeddings)
    assert decision.autoriza is True
    assert decision.motivo is MotivoDecision.MATCH_EXACTO
    assert decision.respuesta == "Hola! En que te puedo ayudar?"
    assert embeddings.calls == []


# -- paso 2: similitud coseno --------------------------------------------------


async def test_similitud_alta_autoriza() -> None:
    embeddings = FakeEmbeddings(vectores={"holaa": vector_con_similitud(0.95)})
    decision = await evaluar_atajo("holaa", indice=_indice(), embeddings=embeddings)
    assert decision.autoriza is True
    assert decision.motivo is MotivoDecision.SIMILITUD_ALTA
    assert decision.score == pytest.approx(0.95, abs=1e-6)


async def test_zona_gris_no_autoriza_pero_marca_casi_match() -> None:
    embeddings = FakeEmbeddings(vectores={"que tal": vector_con_similitud(0.90)})
    decision = await evaluar_atajo("que tal", indice=_indice(), embeddings=embeddings)
    assert decision.autoriza is False
    assert decision.motivo is MotivoDecision.CASI_MATCH
    assert decision.es_casi_match is True
    assert decision.score == pytest.approx(0.90, abs=1e-6)


async def test_sin_match_no_autoriza() -> None:
    embeddings = FakeEmbeddings(vectores={"vino": vector_con_similitud(0.5)})
    decision = await evaluar_atajo("vino", indice=_indice(), embeddings=embeddings)
    assert decision.autoriza is False
    assert decision.motivo is MotivoDecision.SIN_MATCH
    assert decision.es_casi_match is False


# -- regla de sesion activa ----------------------------------------------------


async def test_sesion_activa_bloquea_saludo() -> None:
    decision = await evaluar_atajo(
        "hola", indice=_indice(), embeddings=FakeEmbeddings(), sesion_activa=True
    )
    assert decision.autoriza is False
    assert decision.motivo is MotivoDecision.BLOQUEADO_POR_SESION_ACTIVA


async def test_sesion_activa_no_bloquea_despedida() -> None:
    decision = await evaluar_atajo(
        "chau", indice=_indice(), embeddings=FakeEmbeddings(), sesion_activa=True
    )
    assert decision.autoriza is True
    assert decision.motivo is MotivoDecision.MATCH_EXACTO

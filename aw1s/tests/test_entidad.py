from __future__ import annotations

import pytest

from aw1s.atajo_semantico.indice import EntradaIndice, IndiceEnMemoria
from aw1s.entidad import procesar_mensaje
from tests.fakes import FakeClienteLLM, FakeEmbeddings, FakeGeneradorTexto, RepositorioEnMemoria

DECISION_LISTA = {
    "tipo_problema": "consulta",
    "requiere_informacion_adicional": False,
    "evaluacion_contexto_previo": None,
    "necesidades": [],
    "listo_para_procesar": True,
}


def _necesidad_pendiente() -> dict:
    return {
        "fuente": "postgres",
        "que_buscar": "algo",
        "terminos_busqueda_semantica": None,
        "usa_historial_sesion": True,
        "usa_memoria_semantica": False,
        "cantidad_maxima": 3,
        "prioridad": "alta",
    }


DECISION_PRIMERA_RONDA = {
    "tipo_problema": "consulta_precio",
    "requiere_informacion_adicional": True,
    "evaluacion_contexto_previo": None,
    "necesidades": [_necesidad_pendiente()],
    "listo_para_procesar": False,
}


async def test_atajo_autoriza_no_llama_a_ningun_llm() -> None:
    repo = RepositorioEnMemoria()
    indice = IndiceEnMemoria(
        [EntradaIndice("hola", "Hola! En que te ayudo?", "saludo", embedding=[1.0, 0.0])]
    )
    cliente_json = FakeClienteLLM()
    cliente_texto = FakeGeneradorTexto()

    resultado = await procesar_mensaje(
        "hola",
        indice=indice,
        embeddings=FakeEmbeddings(),
        cliente_json=cliente_json,
        cliente_texto=cliente_texto,
        repositorio=repo,
        identificador_externo="tg:1",
    )

    assert resultado.origen == "atajo_semantico"
    assert resultado.respuesta == "Hola! En que te ayudo?"
    assert resultado.interaccion_id is None
    assert cliente_json.llamadas == []
    assert cliente_texto.llamadas == []


async def test_ciclo_completo_una_ronda() -> None:
    repo = RepositorioEnMemoria()
    cliente_json = FakeClienteLLM(DECISION_LISTA)
    cliente_texto = FakeGeneradorTexto("respuesta final")

    resultado = await procesar_mensaje(
        "cual es la capital de Francia",
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=cliente_json,
        cliente_texto=cliente_texto,
        repositorio=repo,
        identificador_externo="tg:2",
    )

    assert resultado.origen == "ciclo_completo"
    assert resultado.respuesta == "respuesta final"
    assert resultado.iteraciones_usadas == 1
    assert len(cliente_json.llamadas) == 1  # solo analizar(), sin reevaluar
    assert len(cliente_texto.llamadas) == 2  # resolver() + humanizar()
    assert len(repo._contextos) == 1  # noqa: SLF001 -- se persiste igual, aunque vacio


async def test_ciclo_con_reevaluacion_solo_persiste_el_contexto_final() -> None:
    repo = RepositorioEnMemoria()
    cliente_json = FakeClienteLLM([DECISION_PRIMERA_RONDA, DECISION_LISTA])
    cliente_texto = FakeGeneradorTexto("respuesta final")

    resultado = await procesar_mensaje(
        "cuanto sale",
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=cliente_json,
        cliente_texto=cliente_texto,
        repositorio=repo,
        identificador_externo="tg:3",
    )

    assert resultado.iteraciones_usadas == 2
    assert len(cliente_json.llamadas) == 2  # analizar() + una reevaluar()
    assert len(repo._contextos) == 1  # noqa: SLF001 -- solo la ronda final quedo guardada

    # la interaccion sigue siendo una sola pese a las dos vueltas de Inteligencia
    interacciones = await repo.interacciones_recientes(resultado.sesion_id)
    assert len(interacciones) == 1


async def test_limite_iteraciones_corta_el_ciclo_y_sigue_igual() -> None:
    repo = RepositorioEnMemoria()
    cliente_json = FakeClienteLLM(DECISION_PRIMERA_RONDA)  # nunca listo_para_procesar
    cliente_texto = FakeGeneradorTexto("respuesta final igual")

    resultado = await procesar_mensaje(
        "pregunta dificil",
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=cliente_json,
        cliente_texto=cliente_texto,
        repositorio=repo,
        identificador_externo="tg:4",
        limite_iteraciones=2,
    )

    assert resultado.iteraciones_usadas == 2
    assert resultado.respuesta == "respuesta final igual"
    assert len(cliente_json.llamadas) == 2  # analizar() + 1 reevaluar(), no una tercera
    assert len(repo._contextos) == 1  # noqa: SLF001 -- la ronda de corte igual persiste


async def test_limite_iteraciones_invalido_lanza_value_error() -> None:
    with pytest.raises(ValueError):
        await procesar_mensaje(
            "hola",
            indice=IndiceEnMemoria([]),
            embeddings=FakeEmbeddings(),
            cliente_json=FakeClienteLLM(),
            cliente_texto=FakeGeneradorTexto(),
            repositorio=RepositorioEnMemoria(),
            limite_iteraciones=0,
        )

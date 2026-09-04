from __future__ import annotations

import json

import pytest

from aw1s.inteligencia import DecisionInvalidaError, analizar
from tests.fakes import FakeClienteLLM, RepositorioEnMemoria

DECISION_TRIVIAL = {
    "tipo_problema": "saludo",
    "requiere_informacion_adicional": False,
    "evaluacion_contexto_previo": None,
    "necesidades": [],
    "listo_para_procesar": True,
}

DECISION_CON_NECESIDAD = {
    "tipo_problema": "consulta_precio",
    "requiere_informacion_adicional": True,
    "evaluacion_contexto_previo": None,
    "necesidades": [
        {
            "fuente": "pgvector",
            "que_buscar": "precios guardados de este producto",
            "terminos_busqueda_semantica": "precio del producto mencionado",
            "usa_historial_sesion": False,
            "usa_memoria_semantica": True,
            "cantidad_maxima": 3,
            "prioridad": "alta",
        }
    ],
    "listo_para_procesar": False,
}


async def test_analizar_persiste_usuario_sesion_interaccion() -> None:
    repo = RepositorioEnMemoria()
    cliente = FakeClienteLLM(DECISION_TRIVIAL)

    resultado = await analizar(
        "hola", cliente=cliente, repositorio=repo, identificador_externo="tg:1"
    )

    sesion = await repo.obtener_sesion(resultado.sesion_id)
    assert sesion is not None
    interacciones = await repo.interacciones_recientes(resultado.sesion_id)
    assert len(interacciones) == 1
    assert interacciones[0].mensaje_usuario == "hola"


async def test_analizar_persiste_aunque_la_decision_sea_invalida() -> None:
    """La interaccion no se pierde por un fallo de clasificacion -- ver
    docstring de inteligencia.py."""
    repo = RepositorioEnMemoria()
    cliente = FakeClienteLLM({"tipo_problema": "algo"})  # faltan campos obligatorios

    with pytest.raises(DecisionInvalidaError):
        await analizar("hola", cliente=cliente, repositorio=repo, identificador_externo="tg:1")

    guardadas = repo._interacciones  # noqa: SLF001 -- inspeccion directa en el test
    assert any(i.mensaje_usuario == "hola" for i in guardadas.values())


async def test_decision_parseada_conserva_las_necesidades() -> None:
    repo = RepositorioEnMemoria()
    cliente = FakeClienteLLM(DECISION_CON_NECESIDAD)

    resultado = await analizar(
        "cuanto sale el producto X",
        cliente=cliente,
        repositorio=repo,
        identificador_externo="tg:2",
    )

    assert resultado.decision.tipo_problema == "consulta_precio"
    assert resultado.decision.listo_para_procesar is False
    assert len(resultado.decision.necesidades) == 1
    necesidad = resultado.decision.necesidades[0]
    assert necesidad.fuente == "pgvector"
    assert necesidad.cantidad_maxima == 3


async def test_historial_breve_no_incluye_la_interaccion_actual() -> None:
    repo = RepositorioEnMemoria()
    cliente = FakeClienteLLM([DECISION_TRIVIAL, DECISION_TRIVIAL])

    primera = await analizar(
        "hola", cliente=cliente, repositorio=repo, identificador_externo="tg:3"
    )
    await analizar(
        "de nuevo", cliente=cliente, repositorio=repo, sesion_id=primera.sesion_id
    )

    entrada_segunda_llamada = json.loads(cliente.llamadas[1]["mensaje"])
    mensajes_en_historial = [h["mensaje"] for h in entrada_segunda_llamada["historial_breve"]]
    assert mensajes_en_historial == ["hola"]


async def test_reutiliza_sesion_existente_sin_crear_usuario_nuevo() -> None:
    repo = RepositorioEnMemoria()
    cliente = FakeClienteLLM(DECISION_TRIVIAL)

    primera = await analizar(
        "hola", cliente=cliente, repositorio=repo, identificador_externo="tg:4"
    )
    segunda = await analizar(
        "otra vez", cliente=cliente, repositorio=repo, sesion_id=primera.sesion_id
    )

    assert segunda.sesion_id == primera.sesion_id
    assert segunda.usuario_id == primera.usuario_id


async def test_sesion_inexistente_lanza_value_error() -> None:
    repo = RepositorioEnMemoria()
    cliente = FakeClienteLLM(DECISION_TRIVIAL)

    with pytest.raises(ValueError):
        await analizar("hola", cliente=cliente, repositorio=repo, sesion_id=999)

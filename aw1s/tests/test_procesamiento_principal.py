from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aw1s.almacenamiento.modelos import Interaccion, Memoria
from aw1s.contexto.modelos import ContextoArmado, ResultadoBusqueda
from aw1s.inteligencia.modelos import Necesidad
from aw1s.llm.ollama import ClienteLLMError
from aw1s.procesamiento_principal import resolver
from tests.fakes import FakeGeneradorTexto


def _necesidad(que_buscar: str = "el precio") -> Necesidad:
    return Necesidad(
        fuente="ambas",
        que_buscar=que_buscar,
        terminos_busqueda_semantica=None,
        usa_historial_sesion=True,
        usa_memoria_semantica=True,
        cantidad_maxima=5,
        prioridad="alta",
    )


async def test_resolver_devuelve_el_resultado_del_modelo() -> None:
    contexto = ContextoArmado(resultados=[], contexto_id=1)
    cliente = FakeGeneradorTexto("El precio es $1000.")

    resultado = await resolver("cuanto sale", contexto=contexto, cliente=cliente)

    assert resultado.resultado == "El precio es $1000."


async def test_resolver_manda_la_consulta_en_el_mensaje() -> None:
    contexto = ContextoArmado(resultados=[], contexto_id=1)
    cliente = FakeGeneradorTexto("ok")

    await resolver("cuanto sale el producto X", contexto=contexto, cliente=cliente)

    assert "cuanto sale el producto X" in cliente.llamadas[0]["mensaje"]


async def test_resolver_sin_contexto_lo_dice_explicitamente() -> None:
    contexto = ContextoArmado(resultados=[], contexto_id=1)
    cliente = FakeGeneradorTexto("ok")

    await resolver("hola", contexto=contexto, cliente=cliente)

    assert "ninguno" in cliente.llamadas[0]["mensaje"]


async def test_resolver_incluye_historial_y_memorias_en_el_mensaje() -> None:
    interaccion = Interaccion(
        id=1, sesion_id=1, mensaje_usuario="pregunta anterior", metadata={}, ip=None,
        creada_en=datetime.now(UTC),
    )
    memoria = Memoria(
        id=1, interaccion_id=1, contenido="dato guardado", creada_en=datetime.now(UTC)
    )
    resultado_busqueda = ResultadoBusqueda(
        necesidad=_necesidad(), interacciones=[interaccion], memorias=[(memoria, 0.91)]
    )
    contexto = ContextoArmado(resultados=[resultado_busqueda], contexto_id=1)
    cliente = FakeGeneradorTexto("ok")

    await resolver("cuanto sale", contexto=contexto, cliente=cliente)

    mensaje = cliente.llamadas[0]["mensaje"]
    assert "pregunta anterior" in mensaje
    assert "dato guardado" in mensaje
    assert "0.91" in mensaje


async def test_resolver_suma_instrucciones_al_system_prompt_base() -> None:
    contexto = ContextoArmado(resultados=[], contexto_id=1)
    cliente = FakeGeneradorTexto("ok")

    await resolver(
        "hola", contexto=contexto, cliente=cliente, instrucciones="Sos un agente de ventas."
    )

    system = cliente.llamadas[0]["system"]
    assert "Procesamiento principal de AW1S" in system
    assert "Sos un agente de ventas." in system


async def test_resolver_propaga_el_error_del_cliente() -> None:
    contexto = ContextoArmado(resultados=[], contexto_id=1)
    cliente = FakeGeneradorTexto(lanza=ClienteLLMError("no disponible"))

    with pytest.raises(ClienteLLMError):
        await resolver("hola", contexto=contexto, cliente=cliente)

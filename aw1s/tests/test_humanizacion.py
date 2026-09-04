from __future__ import annotations

import pytest

from aw1s.humanizacion import humanizar
from aw1s.llm.ollama import ClienteLLMError
from tests.fakes import FakeGeneradorTexto


async def test_humanizar_devuelve_la_respuesta_del_modelo() -> None:
    cliente = FakeGeneradorTexto("Claro, el precio es $1000!")

    resultado = await humanizar("precio=1000", mensaje_usuario="cuanto sale", cliente=cliente)

    assert resultado.respuesta == "Claro, el precio es $1000!"


async def test_humanizar_manda_el_resultado_interno_y_la_consulta() -> None:
    cliente = FakeGeneradorTexto("ok")

    await humanizar("precio=1000", mensaje_usuario="cuanto sale", cliente=cliente)

    mensaje = cliente.llamadas[0]["mensaje"]
    assert "precio=1000" in mensaje
    assert "cuanto sale" in mensaje


async def test_humanizar_sin_canal_dice_no_especificado() -> None:
    cliente = FakeGeneradorTexto("ok")

    await humanizar("algo", mensaje_usuario="hola", cliente=cliente)

    assert "no especificado" in cliente.llamadas[0]["mensaje"]


async def test_humanizar_incluye_canal_cuando_se_pasa() -> None:
    cliente = FakeGeneradorTexto("ok")

    await humanizar("algo", mensaje_usuario="hola", cliente=cliente, canal="telegram")

    assert "telegram" in cliente.llamadas[0]["mensaje"]


async def test_humanizar_incluye_historial_breve() -> None:
    cliente = FakeGeneradorTexto("ok")

    await humanizar(
        "algo",
        mensaje_usuario="hola",
        cliente=cliente,
        historial_breve=[{"mensaje": "mensaje anterior"}],
    )

    assert "mensaje anterior" in cliente.llamadas[0]["mensaje"]


async def test_humanizar_usa_el_system_prompt_de_humanizacion() -> None:
    cliente = FakeGeneradorTexto("ok")

    await humanizar("algo", mensaje_usuario="hola", cliente=cliente)

    assert "capa de Humanizacion" in cliente.llamadas[0]["system"]


async def test_humanizar_propaga_el_error_del_cliente() -> None:
    cliente = FakeGeneradorTexto(lanza=ClienteLLMError("no disponible"))

    with pytest.raises(ClienteLLMError):
        await humanizar("algo", mensaje_usuario="hola", cliente=cliente)

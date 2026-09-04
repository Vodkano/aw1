"""No se pudo probar OllamaChatClient contra un Ollama real (bloqueado el
acceso a ollama.com en el entorno donde se escribio, sin paquete apt como
alternativa -- mismo tipo de limitacion que ya tiene
atajo_semantico/embeddings.py). Se valida en cambio el contrato HTTP real
de Ollama con mocks, mismo patron que ya usa AW1 v3
(``patch("httpx.AsyncClient.post", new=AsyncMock(...))``, ver CLAUDE.md)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aw1s.inteligencia.cliente_llm import ClienteLLMError, OllamaChatClient


def _respuesta_ollama(contenido: str) -> MagicMock:
    respuesta = MagicMock()
    respuesta.raise_for_status = MagicMock()
    respuesta.json = MagicMock(
        return_value={"message": {"role": "assistant", "content": contenido}}
    )
    return respuesta


async def test_generar_json_parsea_respuesta_limpia() -> None:
    cliente = OllamaChatClient("http://127.0.0.1:11434", modelo="mistral")
    contenido = '{"tipo_problema": "saludo", "listo_para_procesar": true}'
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_respuesta_ollama(contenido))):
        resultado = await cliente.generar_json(system="sistema", mensaje="hola")
    assert resultado == {"tipo_problema": "saludo", "listo_para_procesar": True}


async def test_generar_json_extrae_de_bloque_de_codigo() -> None:
    """Modelos chicos a veces envuelven el JSON en ```json ... ``` pese a
    format:"json" -- caso real ya visto en AW1 v3 (extract_json)."""
    cliente = OllamaChatClient("http://127.0.0.1:11434")
    contenido = '```json\n{"tipo_problema": "saludo", "listo_para_procesar": true}\n```'
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_respuesta_ollama(contenido))):
        resultado = await cliente.generar_json(system="sistema", mensaje="hola")
    assert resultado["tipo_problema"] == "saludo"


async def test_body_de_la_peticion_pide_json_y_usa_el_modelo_configurado() -> None:
    cliente = OllamaChatClient("http://127.0.0.1:11434", modelo="llama3.2")
    mock_post = AsyncMock(return_value=_respuesta_ollama('{"listo_para_procesar": true}'))
    with patch("httpx.AsyncClient.post", new=mock_post):
        await cliente.generar_json(system="sistema", mensaje="hola")

    _, kwargs = mock_post.call_args
    body = kwargs["json"]
    assert body["model"] == "llama3.2"
    assert body["format"] == "json"
    assert body["messages"] == [
        {"role": "system", "content": "sistema"},
        {"role": "user", "content": "hola"},
    ]


async def test_generar_json_lanza_si_ollama_no_responde() -> None:
    cliente = OllamaChatClient("http://127.0.0.1:11434")
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("no se pudo conectar")),
    ), pytest.raises(ClienteLLMError):
        await cliente.generar_json(system="sistema", mensaje="hola")


async def test_generar_json_lanza_si_el_contenido_no_es_json() -> None:
    cliente = OllamaChatClient("http://127.0.0.1:11434")
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(return_value=_respuesta_ollama("esto no es json")),
    ), pytest.raises(ClienteLLMError):
        await cliente.generar_json(system="sistema", mensaje="hola")

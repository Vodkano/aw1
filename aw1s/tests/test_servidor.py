"""Prueba el ruteo HTTP del servidor (``servidor/app.py``), no la Entidad en
si (eso ya lo cubre ``test_entidad.py`` con los mismos Fakes). Se le pasa
``dependencias`` ya armado con Fakes a ``create_app()`` -sin esto, el
lifespan intentaria conectarse a un Postgres/Ollama real (ver
``servidor/app.py``)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aw1s.atajo_semantico.indice import EntradaIndice, IndiceEnMemoria
from aw1s.llm.ollama import ClienteLLMError
from aw1s.servidor.app import create_app
from aw1s.servidor.dependencias import Dependencias
from tests.fakes import FakeClienteLLM, FakeEmbeddings, FakeGeneradorTexto, RepositorioEnMemoria

DECISION_LISTA = {
    "tipo_problema": "consulta",
    "requiere_informacion_adicional": False,
    "evaluacion_contexto_previo": None,
    "necesidades": [],
    "listo_para_procesar": True,
}


def _cliente(dependencias: Dependencias) -> TestClient:
    app = create_app(dependencias=dependencias)
    return TestClient(app)


def test_healthz_no_necesita_dependencias() -> None:
    app = create_app(dependencias=Dependencias(
        repositorio=RepositorioEnMemoria(),
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=FakeClienteLLM(),
        cliente_texto=FakeGeneradorTexto(),
    ))
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mensaje_atajo_no_llama_al_llm() -> None:
    deps = Dependencias(
        repositorio=RepositorioEnMemoria(),
        indice=IndiceEnMemoria(
            [EntradaIndice("hola", "Hola! En que te ayudo?", "saludo", embedding=[1.0, 0.0])]
        ),
        embeddings=FakeEmbeddings(),
        cliente_json=FakeClienteLLM(),
        cliente_texto=FakeGeneradorTexto(),
    )
    with _cliente(deps) as client:
        response = client.post("/api/mensaje", json={"mensaje": "hola"})

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["origen"] == "atajo_semantico"
    assert cuerpo["respuesta"] == "Hola! En que te ayudo?"
    assert cuerpo["interaccion_id"] is None


def test_mensaje_ciclo_completo() -> None:
    deps = Dependencias(
        repositorio=RepositorioEnMemoria(),
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=FakeClienteLLM(DECISION_LISTA),
        cliente_texto=FakeGeneradorTexto("respuesta final"),
    )
    with _cliente(deps) as client:
        response = client.post(
            "/api/mensaje",
            json={"mensaje": "cual es la capital de Francia", "identificador_externo": "tg:1"},
        )

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["origen"] == "ciclo_completo"
    assert cuerpo["respuesta"] == "respuesta final"
    assert cuerpo["iteraciones_usadas"] == 1
    assert cuerpo["sesion_id"] is not None
    assert cuerpo["interaccion_id"] is not None


def test_mensaje_vacio_devuelve_422() -> None:
    deps = Dependencias(
        repositorio=RepositorioEnMemoria(),
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=FakeClienteLLM(),
        cliente_texto=FakeGeneradorTexto(),
    )
    with _cliente(deps) as client:
        response = client.post("/api/mensaje", json={"mensaje": ""})
    assert response.status_code == 422


def test_sesion_inexistente_devuelve_400() -> None:
    deps = Dependencias(
        repositorio=RepositorioEnMemoria(),
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=FakeClienteLLM(DECISION_LISTA),
        cliente_texto=FakeGeneradorTexto("respuesta final"),
    )
    with _cliente(deps) as client:
        response = client.post("/api/mensaje", json={"mensaje": "hola", "sesion_id": 999})
    assert response.status_code == 400


def test_ollama_caido_devuelve_502() -> None:
    deps = Dependencias(
        repositorio=RepositorioEnMemoria(),
        indice=IndiceEnMemoria([]),
        embeddings=FakeEmbeddings(),
        cliente_json=FakeClienteLLM(lanza=ClienteLLMError("Ollama no respondio.")),
        cliente_texto=FakeGeneradorTexto(),
    )
    with _cliente(deps) as client:
        response = client.post("/api/mensaje", json={"mensaje": "hola que tal"})
    assert response.status_code == 502

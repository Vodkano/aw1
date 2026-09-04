"""Servidor HTTP de la Entidad AW1S -- expone ``entidad.procesar_mensaje()``
(ver ``entidad/entidad.py``) como un endpoint. Antes de esto, la unica
forma de usar AW1S era invocar esa funcion a mano desde Python. Este
archivo no le agrega logica nueva a la Entidad: solo la conecta a
Postgres/Ollama reales (``Dependencias.crear()``) y la sirve por HTTP.

Sin autenticacion todavia -pensado para correr en localhost/red interna,
igual que el resto de los prototipos de este repo, no expuesto directo a
internet. Si esto se despliega junto con AW1 v3 hace falta revisar esto
(ver punto pendiente #4 de ``documentacion/arquitectura.md`` sobre la
relacion entre ambos sistemas -probablemente convenga compartir el mismo
esquema de auth que ya tiene ``backend/src/aw1/api/security.py`` en vez de
inventar uno nuevo aca)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from ..almacenamiento.protocolo import RepositorioAlmacenamiento
from ..atajo_semantico.embeddings import EmbeddingsProvider, ProveedorEmbeddingsError
from ..atajo_semantico.indice import IndiceFrasesConocidas
from ..entidad.entidad import LIMITE_ITERACIONES_POR_DEFECTO, procesar_mensaje
from ..inteligencia.inteligencia import DecisionInvalidaError
from ..llm.ollama import ClienteLLMError, GeneradorJSON, GeneradorTexto
from .configuracion import Configuracion
from .dependencias import Dependencias
from .esquemas import MensajeEntrada, MensajeSalida

logger = logging.getLogger(__name__)


def _dependencias(request: Request) -> Dependencias:
    return request.app.state.dependencias


def dep_repositorio(deps: Dependencias = Depends(_dependencias)) -> RepositorioAlmacenamiento:
    return deps.repositorio


def dep_indice(deps: Dependencias = Depends(_dependencias)) -> IndiceFrasesConocidas:
    return deps.indice


def dep_embeddings(deps: Dependencias = Depends(_dependencias)) -> EmbeddingsProvider:
    return deps.embeddings


def dep_cliente_json(deps: Dependencias = Depends(_dependencias)) -> GeneradorJSON:
    return deps.cliente_json


def dep_cliente_texto(deps: Dependencias = Depends(_dependencias)) -> GeneradorTexto:
    return deps.cliente_texto


def create_app(
    config: Configuracion | None = None, dependencias: Dependencias | None = None
) -> FastAPI:
    """``dependencias`` es solo para tests (ver ``tests/test_servidor.py``):
    saltea Postgres/Ollama reales pasando Fakes ya armados. En produccion se
    arman en el lifespan a partir de ``config`` (o de las variables de
    entorno si no se pasa ninguna) -recien ahi, no en ``create_app()``, para
    no exigir ``AW1S_DATABASE_URL`` solo por construir la app."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.dependencias = dependencias or await Dependencias.crear(
            config or Configuracion.desde_entorno()
        )
        try:
            yield
        finally:
            await app.state.dependencias.cerrar()

    app = FastAPI(
        title="AW1S",
        summary="Entidad computacional AW1S -- prototipo, sin wiring a AW1 v3 todavia.",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(ClienteLLMError)
    async def _llm_no_disponible(_request: Request, error: ClienteLLMError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"error": str(error)})

    @app.exception_handler(ProveedorEmbeddingsError)
    async def _embeddings_no_disponible(
        _request: Request, error: ProveedorEmbeddingsError
    ) -> JSONResponse:
        return JSONResponse(status_code=502, content={"error": str(error)})

    @app.exception_handler(DecisionInvalidaError)
    async def _decision_invalida(_request: Request, error: DecisionInvalidaError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"error": str(error)})

    @app.exception_handler(ValueError)
    async def _solicitud_invalida(_request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(error)})

    @app.post("/api/mensaje", response_model=MensajeSalida)
    async def mensaje(
        entrada: MensajeEntrada,
        request: Request,
        repositorio: RepositorioAlmacenamiento = Depends(dep_repositorio),
        indice: IndiceFrasesConocidas = Depends(dep_indice),
        embeddings: EmbeddingsProvider = Depends(dep_embeddings),
        cliente_json: GeneradorJSON = Depends(dep_cliente_json),
        cliente_texto: GeneradorTexto = Depends(dep_cliente_texto),
    ) -> MensajeSalida:
        resultado = await procesar_mensaje(
            entrada.mensaje,
            indice=indice,
            embeddings=embeddings,
            cliente_json=cliente_json,
            cliente_texto=cliente_texto,
            repositorio=repositorio,
            identificador_externo=entrada.identificador_externo,
            sesion_id=entrada.sesion_id,
            metadata=entrada.metadata,
            ip=entrada.ip or (request.client.host if request.client else None),
            instrucciones=entrada.instrucciones,
            canal=entrada.canal,
            limite_iteraciones=entrada.limite_iteraciones or LIMITE_ITERACIONES_POR_DEFECTO,
        )
        return MensajeSalida(
            respuesta=resultado.respuesta,
            origen=resultado.origen,
            sesion_id=resultado.sesion_id,
            interaccion_id=resultado.interaccion_id,
            iteraciones_usadas=resultado.iteraciones_usadas,
        )

    return app

"""Fabrica de la aplicacion."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

import os

from .. import __version__
from ..core import netguard
from ..core.errors import Aw1Error, ValidationError
from ..core.logging_setup import configure_logging, request_id
from ..settings import Settings, get_settings
from .deps import Container
from .routes import chat, health, memory, prices
from .security import check_origin, check_rate, check_token

logger = logging.getLogger(__name__)

# El frontend compilado. Si no existe, la API funciona igual y se avisa.
# La heuristica de parents() asume una instalacion editable (`pip install -e`,
# como en desarrollo local): sube desde este archivo hasta la raiz del repo y
# busca frontend/dist ahi. Con una instalacion real (wheel, como en Docker) el
# paquete se copia sin conservar esa estructura, asi que AW1_WEB_DIST permite
# fijar la ruta explicitamente.
_web_dist_override = os.environ.get("AW1_WEB_DIST", "")
WEB_DIST = (
    Path(_web_dist_override)
    if _web_dist_override
    else Path(__file__).resolve().parents[3].parent / "frontend" / "dist"
)
PUBLIC_PATHS = frozenset({"/healthz", "/api/status", "/docs", "/openapi.json"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    netguard.set_allow_private_hosts(settings.allow_private_hosts)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = await Container.build(settings)
        # El navegador tarda ~1 s en arrancar: se hace en segundo plano para no
        # bloquear el arranque del servidor.
        app.state.browser_task = asyncio.create_task(app.state.container.browser.start())
        logger.info(
            "AW1 %s en %s | proveedor %s | modelo %s | auth %s",
            __version__,
            settings.env,
            settings.llm_provider,
            settings.chat_model,
            settings.auth_enabled,
        )
        try:
            yield
        finally:
            task = getattr(app.state, "browser_task", None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await app.state.container.aclose()

    app = FastAPI(
        title="AW1",
        version=__version__,
        summary="Asistente local con Ollama y comparador que navega tiendas reales.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Api-Token", "Accept"],
        max_age=600,
    )

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = uuid.uuid4().hex[:12]
        token = request_id.set(rid)
        started = time.monotonic()
        try:
            length = request.headers.get("content-length")
            if length and int(length) > settings.max_request_bytes:
                raise ValidationError("El cuerpo de la solicitud es demasiado grande.")
            path = request.url.path
            if path.startswith("/api") and path not in PUBLIC_PATHS:
                check_origin(request, settings)
                check_token(request, settings)
                check_rate(request, request.app.state.container.limiter)
            response = await call_next(request)
        except Aw1Error as error:
            response = _error(error.status_code, error.message, rid)
        except ValueError:
            response = _error(400, "Cabeceras de la solicitud no validas.", rid)
        finally:
            request_id.reset(token)

        response.headers["X-Request-Id"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        elapsed = (time.monotonic() - started) * 1000
        if not request.url.path.startswith("/assets"):
            logger.info(
                "%s %s -> %s (%.0f ms)",
                request.method, request.url.path, response.status_code, elapsed,
            )
        return response

    @app.exception_handler(Aw1Error)
    async def domain_error(_request: Request, error: Aw1Error) -> JSONResponse:
        return _error(error.status_code, error.message, request_id.get())

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = str(first.get("msg", "Solicitud no valida."))
        return _error(400, f"{field}: {message}" if field else message, request_id.get())

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, error: Exception) -> JSONResponse:
        logger.exception("Error no controlado: %s", type(error).__name__)
        return _error(500, "No fue posible completar la solicitud.", request_id.get())

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(prices.router)
    app.include_router(memory.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    if not WEB_DIST.is_dir():
        logger.warning(
            "No hay frontend compilado en %s. Ejecuta `npm run build` en frontend/ "
            "o usa `npm run dev` en el puerto 5173.",
            WEB_DIST,
        )

        @app.get("/", include_in_schema=False)
        async def missing_ui() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "AW1 esta corriendo, pero la interfaz no esta compilada.",
                    "how_to_fix": "cd frontend && npm install && npm run build",
                    "docs": "/docs",
                }
            )

        return

    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        """Cualquier ruta desconocida devuelve la app: es una SPA."""
        if path.startswith(("api/", "assets/", "healthz", "docs", "openapi")):
            return JSONResponse({"error": "Recurso no encontrado."}, status_code=404)
        candidate = (WEB_DIST / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")


def _error(status: int, message: str, rid: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, "request_id": rid})

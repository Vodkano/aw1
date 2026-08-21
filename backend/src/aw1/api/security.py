"""Autenticacion opcional, control de origen y limite de uso.

Sin esto, un servidor escuchando en 127.0.0.1 es alcanzable desde cualquier
pestana del navegador: una web cualquiera podria lanzar busquedas usando el
equipo de la persona, o vaciarle la memoria.
"""

from __future__ import annotations

import hmac

from fastapi import Request

from ..core.errors import AuthError, RateLimitError
from ..core.ratelimit import RateLimiter
from ..settings import Settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "desconocido"


def check_origin(request: Request, settings: Settings) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return  # peticion no-CORS (curl, cliente nativo): la protege el token
    if origin not in settings.allowed_origins:
        raise AuthError("Origen no permitido.")


def check_token(request: Request, settings: Settings) -> None:
    if not settings.auth_enabled:
        return
    assert settings.api_token is not None
    expected = settings.api_token.get_secret_value()
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    presented = value.strip() if scheme.lower() == "bearer" else ""
    if not presented:
        presented = request.headers.get("x-api-token", "").strip()
    # En SSE el navegador no permite cabeceras: se acepta el token por query.
    if not presented:
        presented = str(request.query_params.get("token", "")).strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise AuthError("Se requiere un token valido para usar esta API.")


def check_rate(request: Request, limiter: RateLimiter) -> None:
    key = client_key(request)
    if not limiter.allow(key):
        raise RateLimitError(
            f"Limite de peticiones alcanzado. Reintenta en {limiter.retry_after(key)} segundos."
        )

"""Errores de dominio con traduccion directa a codigos HTTP.

Regla: lo que el usuario puede corregir se explica; lo que expone
infraestructura (proveedores, hosts internos, trazas) no sale al navegador.
"""

from __future__ import annotations


class Aw1Error(Exception):
    status_code = 500
    public_message = "No fue posible completar la solicitud."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)
        self.message = message or self.public_message


class ValidationError(Aw1Error):
    status_code = 400
    public_message = "La solicitud no es valida."


class AuthError(Aw1Error):
    status_code = 401
    public_message = "Credenciales invalidas o ausentes."


class NotFoundError(Aw1Error):
    status_code = 404
    public_message = "Recurso no encontrado."


class RateLimitError(Aw1Error):
    status_code = 429
    public_message = "Demasiadas solicitudes. Intenta de nuevo en un momento."


class NoResultsError(Aw1Error):
    status_code = 422
    public_message = "No se obtuvieron resultados utiles."


class ProviderError(Aw1Error):
    """Ollama, Wikipedia, GPT o una tienda no respondieron."""

    status_code = 503
    public_message = "El servicio externo no esta disponible en este momento."


class BrowserError(Aw1Error):
    status_code = 503
    public_message = "El navegador interno no pudo abrir la pagina."

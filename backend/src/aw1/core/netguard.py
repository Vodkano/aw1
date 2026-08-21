"""Validacion de URL y proteccion contra SSRF.

Dos funciones a proposito: ``normalize`` lanza (para lo que escribe el usuario,
que merece un mensaje claro) y ``sanitize`` devuelve ``None`` (para lo que
descubre el navegador solo, donde un enlace raro debe descartarse en silencio y
no tumbar la busqueda entera).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

from .errors import ValidationError

MAX_URL = 2048
SCHEMES = frozenset({"http", "https"})
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".home", ".lan", ".arpa", ".onion")
BLOCKED_HOSTS = frozenset({"localhost", "metadata.google.internal", "instance-data"})
BLOCKED_PORTS = frozenset({22, 23, 25, 445, 3306, 3389, 5432, 6379, 9200, 11211, 27017})

# Se activa solo en pruebas, para poder navegar a las tiendas simuladas locales.
_allow_private = False


def set_allow_private_hosts(value: bool) -> None:
    global _allow_private
    _allow_private = value


def is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def is_safe_host(host: str) -> bool:
    hostname = (host or "").strip().rstrip(".").lower()
    if not hostname:
        return False
    if _allow_private:
        return True
    if hostname in BLOCKED_HOSTS or hostname.endswith(BLOCKED_SUFFIXES):
        return False
    try:
        return is_public_ip(ipaddress.ip_address(hostname.strip("[]")))
    except ValueError:
        return "." in hostname


def resolves_public(host: str, timeout: float = 2.0) -> bool:
    """Resuelve el DNS antes de navegar, para frenar el rebinding a red interna."""
    if _allow_private:
        return True
    try:
        return is_public_ip(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    return bool(infos) and all(
        is_public_ip(ipaddress.ip_address(info[4][0])) for info in infos
    )


def normalize(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        raise ValidationError("La URL no puede estar vacia.")
    if len(url) > MAX_URL:
        raise ValidationError(f"La URL supera los {MAX_URL} caracteres.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in SCHEMES:
        raise ValidationError("La URL debe empezar por http:// o https://")
    if not parsed.hostname:
        raise ValidationError("La URL debe contener un dominio valido.")
    if parsed.username or parsed.password:
        raise ValidationError("La URL no puede incluir credenciales.")
    if parsed.port is not None and parsed.port in BLOCKED_PORTS and not _allow_private:
        raise ValidationError("La URL apunta a un puerto no permitido.")
    if not is_safe_host(parsed.hostname):
        raise ValidationError("La URL no puede apuntar a una red local o a un dominio interno.")
    return urlunparse(parsed._replace(fragment="", scheme=parsed.scheme.lower()))


def sanitize(value: object) -> str | None:
    try:
        return normalize(value)
    except ValidationError:
        return None


def registrable_domain(host: str) -> str:
    """Aproximacion suficiente para agrupar ofertas por tienda."""
    parts = (host or "").strip(".").lower().split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    if parts[-2] in {"com", "co", "net", "org", "gob", "edu"} and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])

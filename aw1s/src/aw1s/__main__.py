"""Punto de entrada: ``python -m aw1s`` o el comando ``aw1s``.

Variables de entorno (ver ``servidor/configuracion.py`` para las de la
Entidad -Postgres/Ollama- y las lineas de abajo para las del servidor en
si):

- ``AW1S_HOST`` (default ``127.0.0.1``)
- ``AW1S_PORT`` (default ``8100``, para no chocar con el 8000 de AW1 v3)
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "aw1s.servidor.app:create_app",
        factory=True,
        host=os.environ.get("AW1S_HOST", "127.0.0.1"),
        port=int(os.environ.get("AW1S_PORT", "8100")),
        log_level="info",
    )


if __name__ == "__main__":
    main()

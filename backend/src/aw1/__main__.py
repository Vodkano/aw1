"""Punto de entrada: `python -m aw1` o el comando `aw1`."""

from __future__ import annotations

import uvicorn

from .settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "aw1.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.env == "development",
        access_log=False,
    )


if __name__ == "__main__":
    main()

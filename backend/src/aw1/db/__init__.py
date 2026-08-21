"""Persistencia: SQLite en local, Postgres en la nube.

``create_repository`` elige el backend segun ``AW1_DATABASE_URL``: vacio usa
SQLite (archivo en ``AW1_DATA_DIR``), y un DSN ``postgres://`` o
``postgresql://`` usa Postgres. Ambos repositorios exponen el mismo contrato
publico, asi que el resto de la app (``ChatService``, ``PricePipeline``,
rutas) no necesita saber cual esta activo.
"""

from __future__ import annotations

from pathlib import Path

from .postgres_repository import PostgresRepository
from .repository import Repository

__all__ = ["Repository", "PostgresRepository", "create_repository"]


def create_repository(database_url: str, database_path: Path) -> Repository | PostgresRepository:
    if database_url.startswith(("postgres://", "postgresql://")):
        return PostgresRepository(database_url)
    return Repository(database_path)

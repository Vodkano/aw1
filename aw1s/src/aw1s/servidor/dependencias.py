"""Arma y cierra las dependencias reales (Postgres + Ollama) que necesita
``entidad.procesar_mensaje()`` -- un solo lugar para instanciarlas, en vez
de repetirlo en ``app.py``.

Los campos estan tipados por protocolo (``RepositorioAlmacenamiento``,
``IndiceFrasesConocidas``, etc.), no por la implementacion Postgres/Ollama
de produccion -- asi ``app.py`` puede armarse tanto con ``crear()`` (real)
como con Fakes ya construidos a mano en los tests del servidor (ver
``tests/test_servidor.py``), sin duplicar esta clase ni depender de
Postgres/Ollama reales solo para probar el ruteo HTTP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..almacenamiento.postgres import RepositorioPostgres, asegurar_schema
from ..almacenamiento.protocolo import RepositorioAlmacenamiento
from ..atajo_semantico.embeddings import EmbeddingsProvider, OllamaEmbeddings
from ..atajo_semantico.indice import IndiceFrasesConocidas
from ..atajo_semantico.indice_postgres import IndiceFrasesConocidasPostgres
from ..llm.ollama import GeneradorJSON, GeneradorTexto, OllamaChatClient
from .configuracion import Configuracion


async def _sin_cierre() -> None:
    return None


@dataclass
class Dependencias:
    repositorio: RepositorioAlmacenamiento
    indice: IndiceFrasesConocidas
    embeddings: EmbeddingsProvider
    cliente_json: GeneradorJSON
    cliente_texto: GeneradorTexto
    cerrar: Callable[[], Awaitable[None]] = _sin_cierre

    @classmethod
    async def crear(cls, config: Configuracion) -> Dependencias:
        """Requiere que ``asegurar_schema()`` haya corrido -lo hace aca
        mismo, es idempotente (``CREATE ... IF NOT EXISTS``)."""
        await asegurar_schema(config.database_url)
        repositorio = await RepositorioPostgres.crear(config.database_url)
        indice = await IndiceFrasesConocidasPostgres.crear(config.database_url)
        embeddings = OllamaEmbeddings(config.ollama_url, modelo=config.modelo_embeddings)
        cliente = OllamaChatClient(config.ollama_url, modelo=config.modelo_chat)

        async def cerrar_todo() -> None:
            await repositorio.cerrar()
            await indice.cerrar()
            await embeddings.aclose()
            await cliente.aclose()

        return cls(
            repositorio=repositorio,
            indice=indice,
            embeddings=embeddings,
            cliente_json=cliente,
            cliente_texto=cliente,
            cerrar=cerrar_todo,
        )

"""Smoke-test manual contra un Postgres+pgvector real.

Verificado en local (Postgres 16 + postgresql-16-pgvector, sin Docker --
alcanza con tener el paquete de pgvector instalado para el motor de
Postgres que uses). Uso:

    sudo apt-get install -y postgresql-16-pgvector
    sudo service postgresql start
    sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'aw1s';"
    sudo -u postgres createdb aw1s
    DATABASE_URL=postgresql://postgres:aw1s@127.0.0.1:5432/aw1s \
        .venv/bin/python -m scripts.verificar_schema

(O con Docker, si lo tenes: ``docker run --rm -e POSTGRES_PASSWORD=aw1s -e
POSTGRES_DB=aw1s -p 5433:5432 pgvector/pgvector:pg16`` y ajustar el puerto
en DATABASE_URL.)

Carga el schema, hace un ciclo completo (usuario -> sesion -> interaccion
-> contexto -> memoria -> embedding -> evento), lee todo de vuelta, prueba
la busqueda por similitud, y no deja nada corrupto en el proceso: al final
borra las filas que creo (no hace DROP de las tablas, para poder correrlo
mas de una vez sobre la misma base sin destruir nada).
"""

from __future__ import annotations

import asyncio
import os
import sys

from aw1s.almacenamiento.postgres import RepositorioPostgres, asegurar_schema


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Falta DATABASE_URL. Ver el docstring de este archivo.", file=sys.stderr)
        sys.exit(1)

    print("Cargando schema...")
    await asegurar_schema(database_url)

    repo = await RepositorioPostgres.crear(database_url)
    try:
        print("Usuario + sesion + interaccion...")
        usuario = await repo.obtener_o_crear_usuario("verificacion:1")
        usuario_repetido = await repo.obtener_o_crear_usuario("verificacion:1")
        assert usuario.id == usuario_repetido.id, "obtener_o_crear_usuario no es idempotente"

        sesion = await repo.abrir_sesion(usuario.id)
        interaccion = await repo.crear_interaccion(
            sesion.id, "hola, esto es una prueba", {"origen": "verificar_schema"}, "127.0.0.1"
        )
        recientes = await repo.interacciones_recientes(sesion.id)
        assert recientes and recientes[0].id == interaccion.id, "interacciones_recientes fallo"

        print("Contexto + evento...")
        await repo.guardar_contexto(interaccion.id, {"nota": "contexto de prueba"})
        evento = await repo.registrar_evento("verificacion", {"ok": True}, interaccion.id)

        print("Memoria + embedding + busqueda por similitud...")
        memoria = await repo.guardar_memoria(interaccion.id, "contenido de prueba")
        vector = [0.0] * 767 + [1.0]  # 768 dimensiones, no hace falta un modelo real para esto
        await repo.guardar_embedding(memoria.id, vector, "verificacion")
        resultados = await repo.buscar_memorias_similares(vector, limite=1)
        assert resultados and resultados[0][0].id == memoria.id, "buscar_memorias_similares fallo"
        assert resultados[0][1] > 0.99, f"score inesperado: {resultados[0][1]}"

        print("Limpiando filas de prueba...")
        # sesiones.usuario_id y eventos.interaccion_id son ON DELETE SET NULL
        # a proposito (no se quiere perder historial si se borra un usuario) --
        # eso significa que borrar solo la fila de usuarios NO arrastra el
        # resto: hay que borrar sesion y evento explicitamente. Bug real que
        # aparecio al correr este script dos veces seguidas: quedaban
        # memorias/embeddings huerfanos con el mismo vector de prueba, y
        # buscar_memorias_similares (empate exacto de distancia, sin
        # desempate) podia devolver la fila vieja en vez de la nueva.
        async with repo._pool.acquire() as conn:  # noqa: SLF001 -- limpieza puntual del script
            await conn.execute("DELETE FROM eventos WHERE id = $1", evento.id)
            await conn.execute("DELETE FROM sesiones WHERE id = $1", sesion.id)
            await conn.execute("DELETE FROM usuarios WHERE id = $1", usuario.id)

        print("Todo OK.")
    finally:
        await repo.cerrar()


if __name__ == "__main__":
    asyncio.run(main())

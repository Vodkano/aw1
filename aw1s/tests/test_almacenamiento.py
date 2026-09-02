"""Prueba el contrato de RepositorioAlmacenamiento contra el Fake.

No valida el SQL de almacenamiento/postgres.py -- eso necesita un
Postgres+pgvector real, ver scripts/verificar_schema.py."""

from __future__ import annotations

from tests.fakes import FakeEmbeddings, RepositorioEnMemoria, vector_con_similitud


async def test_obtener_o_crear_usuario_es_idempotente_por_externo() -> None:
    repo = RepositorioEnMemoria()
    a = await repo.obtener_o_crear_usuario("tg:123")
    b = await repo.obtener_o_crear_usuario("tg:123")
    assert a.id == b.id


async def test_usuarios_sin_identificador_son_independientes() -> None:
    repo = RepositorioEnMemoria()
    a = await repo.obtener_o_crear_usuario(None)
    b = await repo.obtener_o_crear_usuario(None)
    assert a.id != b.id


async def test_crear_interaccion_actualiza_ultima_actividad_de_la_sesion() -> None:
    repo = RepositorioEnMemoria()
    usuario = await repo.obtener_o_crear_usuario("tg:123")
    sesion = await repo.abrir_sesion(usuario.id)
    inicial = sesion.ultima_actividad_en

    interaccion = await repo.crear_interaccion(sesion.id, "hola", {}, None)

    actualizada = await repo.obtener_sesion(sesion.id)
    assert actualizada is not None
    assert actualizada.ultima_actividad_en >= inicial
    assert interaccion.sesion_id == sesion.id


async def test_interacciones_recientes_ordena_mas_nueva_primero() -> None:
    repo = RepositorioEnMemoria()
    sesion = await repo.abrir_sesion(None)
    primera = await repo.crear_interaccion(sesion.id, "uno", {}, None)
    segunda = await repo.crear_interaccion(sesion.id, "dos", {}, None)

    recientes = await repo.interacciones_recientes(sesion.id, limite=10)

    assert [i.id for i in recientes] == [segunda.id, primera.id]


async def test_buscar_memorias_similares_ordena_por_score_descendente() -> None:
    repo = RepositorioEnMemoria()
    sesion = await repo.abrir_sesion(None)
    interaccion = await repo.crear_interaccion(sesion.id, "hola", {}, None)

    memoria_lejana = await repo.guardar_memoria(interaccion.id, "algo poco relacionado")
    await repo.guardar_embedding(memoria_lejana.id, vector_con_similitud(0.4), "fake")

    memoria_cercana = await repo.guardar_memoria(interaccion.id, "algo muy relacionado")
    await repo.guardar_embedding(memoria_cercana.id, vector_con_similitud(0.95), "fake")

    resultados = await repo.buscar_memorias_similares([1.0, 0.0], limite=5)

    assert [memoria.id for memoria, _ in resultados] == [memoria_cercana.id, memoria_lejana.id]
    assert resultados[0][1] > resultados[1][1]


async def test_registrar_evento_admite_interaccion_opcional() -> None:
    repo = RepositorioEnMemoria()
    evento = await repo.registrar_evento("prueba", {"detalle": 1})
    assert evento.interaccion_id is None


async def test_fake_embeddings_registra_llamadas() -> None:
    proveedor = FakeEmbeddings()
    vector = await proveedor.vectorizar("hola")
    assert proveedor.calls == ["hola"]
    assert vector == [1.0, 0.0]

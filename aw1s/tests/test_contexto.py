from __future__ import annotations

from aw1s.contexto import construir_contexto, contexto_a_dict
from aw1s.inteligencia.modelos import Necesidad
from tests.fakes import FakeEmbeddings, RepositorioEnMemoria, vector_con_similitud


def _necesidad(
    *,
    fuente: str,
    usa_historial_sesion: bool = False,
    usa_memoria_semantica: bool = False,
    cantidad_maxima: int = 5,
) -> Necesidad:
    return Necesidad(
        fuente=fuente,
        que_buscar="algo",
        terminos_busqueda_semantica="algo relacionado" if usa_memoria_semantica else None,
        usa_historial_sesion=usa_historial_sesion,
        usa_memoria_semantica=usa_memoria_semantica,
        cantidad_maxima=cantidad_maxima,
        prioridad="alta",
    )


async def _preparar_sesion_con_historial(repo: RepositorioEnMemoria) -> tuple[int, int]:
    sesion = await repo.abrir_sesion(None)
    await repo.crear_interaccion(sesion.id, "primer mensaje", {}, None)
    interaccion_actual = await repo.crear_interaccion(sesion.id, "mensaje actual", {}, None)
    return sesion.id, interaccion_actual.id


async def test_necesidad_postgres_trae_historial() -> None:
    repo = RepositorioEnMemoria()
    sesion_id, interaccion_id = await _preparar_sesion_con_historial(repo)
    necesidad = _necesidad(fuente="postgres", usa_historial_sesion=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
    )

    assert len(contexto.resultados) == 1
    assert len(contexto.resultados[0].interacciones) == 2
    assert contexto.resultados[0].memorias == []


async def test_necesidad_postgres_sin_usa_historial_no_trae_nada() -> None:
    """fuente=postgres pero usa_historial_sesion=False: no hay que traer
    historial igual solo porque la fuente lo permite."""
    repo = RepositorioEnMemoria()
    sesion_id, interaccion_id = await _preparar_sesion_con_historial(repo)
    necesidad = _necesidad(fuente="postgres", usa_historial_sesion=False)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
    )

    assert contexto.resultados[0].interacciones == []


async def test_necesidad_pgvector_trae_memorias_similares() -> None:
    repo = RepositorioEnMemoria()
    sesion = await repo.abrir_sesion(None)
    interaccion = await repo.crear_interaccion(sesion.id, "hola", {}, None)
    memoria = await repo.guardar_memoria(interaccion.id, "algo muy relacionado")
    await repo.guardar_embedding(memoria.id, [1.0, 0.0], "fake")

    embeddings = FakeEmbeddings(vectores={"algo relacionado": [1.0, 0.0]})
    necesidad = _necesidad(fuente="pgvector", usa_memoria_semantica=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion.id,
        interaccion_id=interaccion.id,
        repositorio=repo,
        embeddings=embeddings,
    )

    assert len(contexto.resultados[0].memorias) == 1
    memoria_encontrada, score = contexto.resultados[0].memorias[0]
    assert memoria_encontrada.id == memoria.id
    assert score == 1.0
    assert embeddings.calls == ["algo relacionado"]


async def test_necesidad_ambas_combina_las_dos_fuentes() -> None:
    repo = RepositorioEnMemoria()
    sesion_id, interaccion_id = await _preparar_sesion_con_historial(repo)
    memoria = await repo.guardar_memoria(interaccion_id, "contenido guardado")
    await repo.guardar_embedding(memoria.id, [1.0, 0.0], "fake")

    embeddings = FakeEmbeddings(vectores={"algo relacionado": [1.0, 0.0]})
    necesidad = _necesidad(fuente="ambas", usa_historial_sesion=True, usa_memoria_semantica=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        repositorio=repo,
        embeddings=embeddings,
    )

    assert len(contexto.resultados[0].interacciones) == 2
    assert len(contexto.resultados[0].memorias) == 1


async def test_cantidad_maxima_limita_los_resultados() -> None:
    repo = RepositorioEnMemoria()
    sesion = await repo.abrir_sesion(None)
    for i in range(5):
        await repo.crear_interaccion(sesion.id, f"mensaje {i}", {}, None)
    ultima = await repo.crear_interaccion(sesion.id, "la mas nueva", {}, None)

    necesidad = _necesidad(fuente="postgres", usa_historial_sesion=True, cantidad_maxima=2)
    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion.id,
        interaccion_id=ultima.id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
    )

    assert len(contexto.resultados[0].interacciones) == 2


async def test_lista_de_necesidades_vacia_arma_contexto_vacio() -> None:
    repo = RepositorioEnMemoria()
    sesion = await repo.abrir_sesion(None)
    interaccion = await repo.crear_interaccion(sesion.id, "hola", {}, None)

    contexto = await construir_contexto(
        [],
        sesion_id=sesion.id,
        interaccion_id=interaccion.id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
    )

    assert contexto.resultados == []
    guardado = repo._contextos[contexto.contexto_id]  # noqa: SLF001 -- inspeccion directa
    assert guardado.contenido == {"resultados": []}


async def test_contexto_queda_persistido() -> None:
    repo = RepositorioEnMemoria()
    sesion_id, interaccion_id = await _preparar_sesion_con_historial(repo)
    necesidad = _necesidad(fuente="postgres", usa_historial_sesion=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
    )

    guardado = repo._contextos[contexto.contexto_id]  # noqa: SLF001 -- inspeccion directa
    assert guardado.interaccion_id == interaccion_id
    assert len(guardado.contenido["resultados"][0]["interacciones"]) == 2


async def test_similitud_baja_se_ordena_pero_no_se_descarta() -> None:
    """Contexto no filtra por score -- eso ya lo decidio Inteligencia via
    cantidad_maxima. Trae lo que buscar_memorias_similares devuelva."""
    repo = RepositorioEnMemoria()
    sesion = await repo.abrir_sesion(None)
    interaccion = await repo.crear_interaccion(sesion.id, "hola", {}, None)
    memoria = await repo.guardar_memoria(interaccion.id, "poco relacionado")
    await repo.guardar_embedding(memoria.id, vector_con_similitud(0.2), "fake")

    embeddings = FakeEmbeddings(vectores={"algo relacionado": [1.0, 0.0]})
    necesidad = _necesidad(fuente="pgvector", usa_memoria_semantica=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion.id,
        interaccion_id=interaccion.id,
        repositorio=repo,
        embeddings=embeddings,
    )

    assert len(contexto.resultados[0].memorias) == 1


async def test_persistir_false_no_guarda_fila_en_contextos() -> None:
    """Rondas intermedias del ciclo de Inteligencia -- ver docstring de
    construir_contexto(). Solo la ronda final debe dejar una fila real."""
    repo = RepositorioEnMemoria()
    sesion_id, interaccion_id = await _preparar_sesion_con_historial(repo)
    necesidad = _necesidad(fuente="postgres", usa_historial_sesion=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
        persistir=False,
    )

    assert contexto.contexto_id is None
    assert len(contexto.resultados[0].interacciones) == 2  # igual se ejecuta la busqueda
    assert repo._contextos == {}  # noqa: SLF001 -- nada quedo guardado


async def test_contexto_a_dict_funciona_sin_persistir() -> None:
    repo = RepositorioEnMemoria()
    sesion_id, interaccion_id = await _preparar_sesion_con_historial(repo)
    necesidad = _necesidad(fuente="postgres", usa_historial_sesion=True)

    contexto = await construir_contexto(
        [necesidad],
        sesion_id=sesion_id,
        interaccion_id=interaccion_id,
        repositorio=repo,
        embeddings=FakeEmbeddings(),
        persistir=False,
    )

    contenido = contexto_a_dict(contexto)
    assert len(contenido["resultados"][0]["interacciones"]) == 2

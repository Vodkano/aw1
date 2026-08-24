"""Heuristica de respaldo del chat (sin IA)."""

from __future__ import annotations

from aw1.chat import heuristics
from aw1.llm.schemas import ChatRoute


def test_charla_simple_no_es_heavy() -> None:
    route = heuristics.route("hola, como estas?")
    assert route.intent == "charla"
    assert route.heavy is False
    assert route.needs_fresh_data is False


def test_codigo_no_marca_heavy_por_defecto() -> None:
    """La heuristica es un regex sin matices: no distingue una pregunta
    trivial de un bug real, asi que por defecto se queda en el modelo local
    -GPT solo se consume cuando el enrutador con IA decide que hace falta."""
    route = heuristics.route("tengo un bug en mi script de python")
    assert route.intent == "codigo"
    assert route.heavy is False


def test_actualidad_marca_needs_fresh_data() -> None:
    route = heuristics.route("cual es el dolar hoy?")
    assert route.intent == "actualidad"
    assert route.needs_fresh_data is True


def test_precio_siempre_gana_en_merge() -> None:
    heuristic = heuristics.route("cuanto cuesta un iphone 15?")
    modelo = ChatRoute(intent="charla", heavy=True)
    merged = heuristics.merge(heuristic, modelo)
    assert merged.intent == "precio"


def test_merge_sin_respuesta_del_modelo_usa_heuristica() -> None:
    heuristic = heuristics.route("hola")
    merged = heuristics.merge(heuristic, None)
    assert merged is heuristic


def test_un_saludo_no_necesita_revisar_memoria() -> None:
    route = heuristics.route("hola, como estas?")
    assert route.needs_memory is False


def test_un_agradecimiento_no_necesita_revisar_memoria() -> None:
    route = heuristics.route("gracias!")
    assert route.needs_memory is False


def test_charla_generica_si_necesita_revisar_memoria_por_defecto() -> None:
    """Sin un enrutador con IA que lea la pregunta, el heuristico no puede
    saber si "que auto tiene pedro?" depende de una nota guardada -por eso
    el default sigue siendo intentarlo, igual que antes de esta decision.
    Solo lo trivial (saludos, charla vacia) se descarta con certeza."""
    route = heuristics.route("que auto tiene pedro?")
    assert route.needs_memory is True


def test_el_modelo_puede_decidir_no_revisar_memoria_para_charla() -> None:
    heuristic = heuristics.route("que auto tiene pedro?")
    modelo = ChatRoute(intent="charla", needs_memory=False)
    merged = heuristics.merge(heuristic, modelo)
    assert merged.needs_memory is False

"""Ejecucion aislada de codigo generado por IA -bateria red-team incluida
a pedido explicito: no alcanza con que la herramienta funcione, tiene que
resistir un intento deliberado de escapar del sandbox o leer algo que no
deberia."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

from aw1.core import sandbox

_SAFE_SOURCE = """
def run(input: dict) -> dict:
    return {"echo": input.get("value", "")}
"""


# --- check_module_safety(): rechazos esperados -----------------------------
def test_a_well_behaved_module_passes():
    assert sandbox.check_module_safety(_SAFE_SOURCE) == []


def test_a_module_without_run_is_rejected():
    problems = sandbox.check_module_safety("def helper(): return 1")
    assert any("run(" in p for p in problems)


def test_importing_os_is_rejected():
    problems = sandbox.check_module_safety("import os\ndef run(input): return {}")
    assert any("os" in p for p in problems)


def test_importing_socket_is_rejected():
    problems = sandbox.check_module_safety("import socket\ndef run(input): return {}")
    assert any("socket" in p for p in problems)


def test_importing_subprocess_is_rejected():
    problems = sandbox.check_module_safety("import subprocess\ndef run(input): return {}")
    assert any("subprocess" in p for p in problems)


def test_importing_httpx_directly_is_rejected():
    """La unica forma de pedir datos de internet es fetch(), inyectado por
    el runner -no un import propio de httpx/urllib."""
    problems = sandbox.check_module_safety("import httpx\ndef run(input): return {}")
    assert any("httpx" in p for p in problems)


def test_an_import_hidden_inside_a_function_is_still_rejected():
    """El chequeo recorre TODO el arbol, no solo el nivel superior -un
    import escondido adentro de una funcion cuenta igual."""
    source = "def run(input):\n    import os\n    return {'x': os.getcwd()}\n"
    problems = sandbox.check_module_safety(source)
    assert any("os" in p for p in problems)


def test_eval_is_rejected():
    problems = sandbox.check_module_safety("def run(input): return eval(input['x'])")
    assert any("eval" in p for p in problems)


def test_exec_is_rejected():
    problems = sandbox.check_module_safety("def run(input): exec(input['x']); return {}")
    assert any("exec" in p for p in problems)


def test_open_is_rejected():
    problems = sandbox.check_module_safety("def run(input): return {'x': open('/etc/passwd').read()}")
    assert any("open" in p for p in problems)


def test_os_system_via_attribute_is_rejected_even_without_a_direct_import():
    """os.system podria llegar via una variable ya importada en otro lado
    -el chequeo tambien mira el nombre del atributo, no solo el import."""
    source = "def run(input):\n    getattr(input, 'x').system('rm -rf /')\n    return {}\n"
    problems = sandbox.check_module_safety(source)
    assert any("system" in p for p in problems)


def test_the_class_bases_subclasses_escape_trick_is_rejected():
    """Prompt-injection tipico: sin ningun 'import', encadenar atributos
    dunder para llegar a builtins/os igual (().__class__.__bases__[0].
    __subclasses__()). Es el bypass mas conocido de un sandbox de Python
    basado solo en imports -por eso el chequeo tambien mira los atributos
    dunder, no solo los imports."""
    source = (
        "def run(input):\n"
        "    leak = ().__class__.__bases__[0].__subclasses__()\n"
        "    return {'leak': str(leak)}\n"
    )
    problems = sandbox.check_module_safety(source)
    assert problems


def test_reading_globals_via_dunder_is_rejected():
    source = "def run(input):\n    return {'g': str(run.__globals__)}\n"
    problems = sandbox.check_module_safety(source)
    assert any("__globals__" in p for p in problems)


def test_invalid_python_syntax_is_reported_instead_of_raising():
    problems = sandbox.check_module_safety("def run(input) return {}")
    assert problems


# --- run_in_sandbox(): aislamiento real, no solo el chequeo estatico -------
async def test_a_well_behaved_tool_round_trips_its_input():
    result = await sandbox.run_in_sandbox(_SAFE_SOURCE, {"value": "hola"})
    assert result.ok is True
    assert result.output == {"echo": "hola"}


async def test_unsafe_code_never_gets_to_run_a_process():
    """Si el chequeo estatico rechaza el codigo, ni siquiera se llega a
    lanzar un subproceso -se corta antes."""
    result = await sandbox.run_in_sandbox("import os\ndef run(input): return {}", {})
    assert result.ok is False
    assert "chequeo de seguridad" in result.error.lower()


async def test_an_infinite_loop_is_killed_by_the_wall_clock_timeout():
    source = "def run(input):\n    while True:\n        pass\n"
    result = await sandbox.run_in_sandbox(source, {}, timeout_seconds=2.0, cpu_seconds=1)
    assert result.ok is False
    assert result.duration_seconds < 5.0


async def test_a_cpu_heavy_loop_is_killed_by_the_cpu_limit():
    """Un bucle que consume CPU sin nunca hacer I/O deberia terminar por
    el limite de RLIMIT_CPU antes que por el timeout de pared."""
    source = "def run(input):\n    x = 0\n    while True:\n        x += 1\n"
    result = await sandbox.run_in_sandbox(source, {}, timeout_seconds=5.0, cpu_seconds=1)
    assert result.ok is False


async def test_a_memory_bomb_is_killed_by_the_memory_limit():
    """En Linux (produccion) esto lo corta RLIMIT_AS; en macOS (desarrollo
    local) esa llamada puede no aplicarse (ver _RUNNER_TEMPLATE) y termina
    cortandolo el timeout de pared -de cualquier forma no debe quedar
    "ok" ni consumir memoria sin limite, por eso el timeout va bajo."""
    source = "def run(input):\n    data = []\n    while True:\n        data.append('x' * 10_000_000)\n    return {}\n"
    result = await sandbox.run_in_sandbox(source, {}, timeout_seconds=2.0, memory_mb=64)
    assert result.ok is False


async def test_no_way_to_read_env_vars_passes_the_static_check():
    """Leer variables de entorno requiere el modulo os (u os.environ via
    un import equivalente) -bloqueado por check_module_safety. No existe
    ningun codigo que pase el chequeo Y pueda leer el entorno."""
    source = "def run(input):\n    import os\n    return {'env': dict(os.environ)}\n"
    assert sandbox.check_module_safety(source) != []


async def test_the_child_process_is_spawned_with_an_empty_environment():
    """Prueba directa e independiente del chequeo estatico: el subproceso
    en si nunca hereda el entorno real (credenciales de OpenAI, de la
    base de datos, etc.), sin importar que tan bien escrito este el
    codigo generado."""
    marker = "AW1_TEST_SECRET_MARKER"
    os.environ[marker] = "no-deberia-verse-nunca"
    captured_kwargs: dict = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b'{"ok": true}', b""

        def kill(self):
            pass

        async def wait(self):
            return None

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeProc()

    try:
        with patch(
            "aw1.core.sandbox.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=fake_create_subprocess_exec),
        ):
            await sandbox.run_in_sandbox(_SAFE_SOURCE, {})
    finally:
        os.environ.pop(marker, None)

    assert captured_kwargs.get("env") == {}


async def test_non_json_stdout_is_reported_as_a_failure():
    source = "def run(input):\n    print('esto no es json valido')\n    return {}\n"
    result = await sandbox.run_in_sandbox(source, {})
    assert result.ok is False


async def test_an_exception_inside_run_is_reported_as_a_failure_not_a_crash():
    source = "def run(input):\n    return 1 / 0\n"
    result = await sandbox.run_in_sandbox(source, {})
    assert result.ok is False
    assert result.stderr


async def test_fetch_rejects_a_private_url():
    """fetch() (el helper inyectado, no algo que el codigo generado
    importe) pasa por el mismo chequeo anti-SSRF que ya protege
    agent_apis.call() -no deberia poder golpear los otros contenedores del
    servidor (Postgres, Ollama)."""
    source = (
        "def run(input):\n"
        "    try:\n"
        "        return {'body': fetch('http://127.0.0.1:5432/')}\n"
        "    except Exception as error:\n"
        "        return {'blocked': True, 'reason': str(error)}\n"
    )
    result = await sandbox.run_in_sandbox(source, {})
    assert result.ok is True
    assert result.output.get("blocked") is True

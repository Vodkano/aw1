"""Ejecucion aislada de codigo generado por IA (ver core/code_agent.py).

Dos defensas independientes, ninguna alcanza sola:

1. ``check_module_safety()``: un chequeo estatico (AST) ANTES de ejecutar
   nada -si el codigo importa algo no permitido, llama algo peligroso, o
   intenta un truco conocido de escape (encadenar atributos dunder como
   ``().__class__.__bases__`` para llegar a modulos peligrosos sin
   importarlos), ni siquiera se llega a arrancar un proceso. No es una
   garantia -un chequeo estatico en Python nunca cierra el 100% de los
   trucos de escape posibles- por eso existe la segunda capa.

2. ``run_in_sandbox()``: lo que si pasa el chequeo corre en un subproceso
   aparte, sin ninguna variable de entorno real (ninguna credencial es
   alcanzable ahi dentro), con limite de CPU y memoria (modulo ``resource``
   de la libreria estandar, nada que instalar de mas), y con un limite de
   tiempo de pared ademas del de CPU -un proceso que se cuelga se mata, no
   cuelga el sandbox entero.

La unica forma de pedir datos de internet desde el codigo generado es la
funcion ``fetch()`` que este modulo le inyecta al proceso -el codigo
generado nunca puede importar ``httpx``/``socket``/``urllib`` directo (ver
ALLOWED_IMPORTS). ``fetch()`` pasa por ``core/netguard.py``, la misma
proteccion anti-SSRF que ya usan las APIs que configura el admin
(``core/agent_apis.py``): sin esto, una herramienta generada podria golpear
los otros contenedores de este mismo servidor (Postgres, Ollama) sin
ningun control.

Esta MISMA funcion se usa tanto para probar una herramienta recien
generada como para ejecutarla despues de aprobada -una herramienta activa
nunca corre con mas privilegios que los que tuvo en la prueba.
"""

from __future__ import annotations

import ast
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 4000

# Solo estas -nada que permita tocar el sistema de archivos, la red, el
# sistema operativo, u otro proceso. Si una herramienta necesita internet,
# usa fetch() (inyectado abajo), nunca un import propio.
ALLOWED_IMPORTS = frozenset({
    "json", "re", "math", "datetime", "typing", "decimal", "statistics",
})
DENIED_CALL_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input", "vars", "globals", "locals",
})
DENIED_ATTRS = frozenset({"system", "popen", "spawn", "fork", "kill"})
# Trucos conocidos para llegar a modulos peligrosos sin un "import" literal
# (ej. ().__class__.__bases__[0].__subclasses__() para llegar a builtins).
DENIED_DUNDER_ATTRS = frozenset({
    "__class__", "__bases__", "__subclasses__", "__globals__", "__builtins__",
    "__import__", "__loader__", "__spec__", "__code__", "__closure__",
    "__func__", "__self__", "__getattribute__", "__reduce__", "__reduce_ex__",
    "__mro__", "__base__",
})

_RUNNER_TEMPLATE = '''\
import json
import resource
import sys

# best-effort: en Linux (produccion) los dos limites aplican normal: en
# macOS (desarrollo local) RLIMIT_AS puede rechazar el cambio segun la
# version del SO -no critico, el timeout de pared y RLIMIT_CPU ya cubren
# un proceso colgado igual, y en produccion es donde de verdad importa.
for _limit, _value in (
    (resource.RLIMIT_CPU, ({cpu}, {cpu})),
    (resource.RLIMIT_AS, ({mem_bytes}, {mem_bytes})),
):
    try:
        resource.setrlimit(_limit, _value)
    except (ValueError, OSError):
        pass


def fetch(url: str, *, method: str = "GET", timeout: float = 8.0) -> str:
    """Unica forma de pedir datos de internet desde una herramienta
    generada -pasa por el mismo chequeo anti-SSRF que ya usan las APIs
    configuradas por el admin, para no poder golpear los otros
    contenedores de este mismo servidor (Postgres, Ollama)."""
    from urllib.parse import urlparse

    from aw1.core import netguard
    from aw1.core.errors import ValidationError

    try:
        normalized = netguard.normalize(url)
    except ValidationError as error:
        raise RuntimeError(str(error)) from error
    host = urlparse(normalized).hostname or ""
    if not netguard.resolves_public(host):
        raise RuntimeError("Esa URL no es segura.")
    import httpx

    response = httpx.request(method, normalized, timeout=timeout)
    return response.text[:4000]


sys.path.insert(0, {tooldir!r})
import tool  # noqa: E402 (tiene que ir despues de fijar los limites de recursos)

_input = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {{}}
_output = tool.run(_input)
print(json.dumps(_output))
'''


@dataclass(slots=True)
class SandboxResult:
    ok: bool
    output: Any = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    problems: list[str] = field(default_factory=list)


def check_module_safety(source: str) -> list[str]:
    """Recorre TODO el arbol del codigo (no solo el nivel superior: un
    import adentro de una funcion igual cuenta). Devuelve la lista de
    problemas encontrados -vacia si el codigo pasa este chequeo."""
    problems: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"El codigo no es Python valido: {error}"]

    defines_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            defines_run = True
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    problems.append(f"Import no permitido: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                problems.append(f"Import no permitido: {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DENIED_CALL_NAMES:
                problems.append(f"Llamada no permitida: {node.func.id}()")
        elif isinstance(node, ast.Attribute):
            if node.attr in DENIED_ATTRS:
                problems.append(f"Llamada no permitida: .{node.attr}(...)")
            elif node.attr in DENIED_DUNDER_ATTRS:
                problems.append(f"Acceso no permitido: .{node.attr}")

    if not defines_run:
        problems.append("El codigo debe definir una funcion run(input: dict) -> dict.")
    return problems


async def run_in_sandbox(
    source: str,
    input_data: dict[str, Any],
    *,
    timeout_seconds: float = 10.0,
    cpu_seconds: int = 5,
    memory_mb: int = 256,
) -> SandboxResult:
    """Nunca lanza -toda falla (codigo inseguro, timeout, crash, salida
    invalida) vuelve como un SandboxResult con ok=False y una explicacion,
    mismo contrato que el resto de las herramientas de este proyecto
    (agent_apis.call, image_gen.generate)."""
    problems = check_module_safety(source)
    if problems:
        return SandboxResult(
            ok=False,
            error="Codigo rechazado por el chequeo de seguridad: " + "; ".join(problems),
            problems=problems,
        )

    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="aw1_sandbox_") as tempdir:
        runner_path = Path(tempdir, "_runner.py")
        runner_source = _RUNNER_TEMPLATE.format(
            cpu=cpu_seconds, mem_bytes=memory_mb * 1024 * 1024, tooldir=tempdir
        )
        await asyncio.to_thread(Path(tempdir, "tool.py").write_text, source, encoding="utf-8")
        await asyncio.to_thread(runner_path.write_text, runner_source, encoding="utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(runner_path), json.dumps(input_data),
                cwd=tempdir, env={}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            return SandboxResult(ok=False, error=f"No se pudo iniciar el sandbox: {error}")

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                ok=False, error="Se agoto el tiempo limite de ejecucion.",
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start
        stdout_text = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
        stderr_text = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]

        if proc.returncode != 0:
            return SandboxResult(
                ok=False, stdout=stdout_text, stderr=stderr_text, duration_seconds=duration,
                error=f"El codigo termino con error (codigo de salida {proc.returncode}).",
            )
        try:
            output = json.loads(stdout_text)
        except ValueError:
            return SandboxResult(
                ok=False, stdout=stdout_text, stderr=stderr_text, duration_seconds=duration,
                error="La herramienta no devolvio un resultado valido (se esperaba JSON).",
            )
        return SandboxResult(
            ok=True, output=output, stdout=stdout_text, stderr=stderr_text,
            duration_seconds=duration,
        )

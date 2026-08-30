"""Traza operacional de una ejecucion con IA (chat, agentes de Telegram,
comparador de precios): que modelo/proveedor se uso, que herramientas, cuanto
tardo y el resultado. Es la base para ver costos y errores sin leer logs -no
reemplaza a `reasoning`, que guarda el contenido de lo que penso el modelo.

Uso tipico:

    async with Trace(repo, source="chat", model="mistral") as t:
        t.add_tool("buscar_precio")
        respuesta = await hacer_algo()
        t.cost_estimate = 0.0
"""

from __future__ import annotations

import time
import uuid
from typing import Any


async def record_trace(
    repo: Any,
    source: str,
    *,
    provider: str = "",
    model: str = "",
    tools_called: list[str] | None = None,
    status: str = "ok",
    latency_ms: int = 0,
    cost_estimate: float = 0.0,
    error: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    """Guarda una traza suelta. Pensado para puntos donde ya se midio la
    latencia a mano (ej. streaming token a token) y no conviene envolver todo
    el bloque en el context manager `Trace`. Nunca lanza: una traza que falla
    en guardarse no debe tumbar la ejecucion real."""
    try:
        await repo.save_execution_trace(
            trace_id=uuid.uuid4().hex,
            source=source,
            provider=provider,
            model=model,
            tools_called=tools_called or [],
            status=status,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            error=error,
            meta=meta or {},
        )
    except Exception:
        pass


class Trace:
    def __init__(
        self,
        repo: Any,
        source: str,
        provider: str = "",
        model: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._repo = repo
        self.trace_id = uuid.uuid4().hex
        self.source = source
        self.provider = provider
        self.model = model
        self.meta = meta or {}
        self.cost_estimate = 0.0
        self.tools_called: list[str] = []
        self._error = ""
        self._start = 0.0

    def add_tool(self, name: str) -> None:
        self.tools_called.append(name)

    async def __aenter__(self) -> "Trace":
        self._start = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        latency_ms = int((time.monotonic() - self._start) * 1000)
        status = "error" if exc is not None else "ok"
        error = f"{exc_type.__name__}: {exc}" if exc is not None else ""
        try:
            await self._repo.save_execution_trace(
                trace_id=self.trace_id,
                source=self.source,
                provider=self.provider,
                model=self.model,
                tools_called=self.tools_called,
                status=status,
                latency_ms=latency_ms,
                cost_estimate=self.cost_estimate,
                error=error,
                meta=self.meta,
            )
        except Exception:
            # Nunca dejar que un fallo al guardar la traza tumbe la
            # ejecucion real que estaba siendo trazada.
            pass
        return False

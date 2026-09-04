"""Re-exporta el cliente Ollama compartido (aw1s.llm.ollama).

Inteligencia solo necesita la capacidad de generar JSON -``ClienteLLM``
aca es un alias de ``GeneradorJSON``, el protocolo angosto que le
corresponde a este componente. Ver aw1s/src/aw1s/llm/ollama.py para el
porque de esta separacion (Procesamiento principal necesita texto libre,
no JSON, y no debe depender del paquete de Inteligencia para conseguirlo).
"""

from __future__ import annotations

from ..llm.ollama import ClienteLLMError, OllamaChatClient
from ..llm.ollama import GeneradorJSON as ClienteLLM

__all__ = ["ClienteLLM", "ClienteLLMError", "OllamaChatClient"]

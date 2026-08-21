"""Capa de IA: cliente de Ollama y los jueces que toman las decisiones."""

from .client import OllamaClient
from .judges import Judges

__all__ = ["Judges", "OllamaClient"]

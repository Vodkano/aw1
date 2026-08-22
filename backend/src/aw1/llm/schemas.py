"""Contratos que el modelo debe cumplir.

Cada juez valida la salida de Ollama contra uno de estos modelos. Si el modelo
inventa campos, se ignoran; si omite los obligatorios, la decision se descarta y
el pipeline continua con su heuristica.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchPlan(BaseModel):
    """Como interpretar lo que pidio el usuario."""

    model_config = ConfigDict(extra="ignore")

    product: str = ""
    brand: str = ""
    model_name: str = Field(default="", alias="model")
    category: str = ""
    queries: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("queries", "required", "forbidden", mode="before")
    @classmethod
    def _as_list(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("queries")
    @classmethod
    def _trim_queries(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            text = " ".join(str(item).split())[:120]
            if text and text.lower() not in {existing.lower() for existing in seen}:
                seen.append(text)
        return seen[:4]


class CandidatePick(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    confidence: float = 0.5
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    picks: list[CandidatePick] = Field(default_factory=list)
    discarded_reason: str = ""


class PriceVerdict(BaseModel):
    """Lo que el modelo concluye tras leer el contexto de una ficha."""

    model_config = ConfigDict(extra="ignore")

    is_match: bool = False
    candidate_id: int | None = None
    price: float | None = None
    currency: str = "CLP"
    product_title: str = ""
    in_stock: bool | None = None
    confidence: float = 0.5
    reason: str = ""

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: object) -> str:
        text = str(value or "CLP").strip().upper()
        return {"$": "CLP", "CLP$": "CLP", "US$": "USD", "USD$": "USD", "": "CLP"}.get(text, text)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5

    @field_validator("candidate_id", mode="before")
    @classmethod
    def _as_int(cls, value: object) -> int | None:
        if value in (None, "", "null"):
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None


class ChatRoute(BaseModel):
    """Decision del modelo sobre como atender un mensaje del chat."""

    model_config = ConfigDict(extra="ignore")

    intent: str = "charla"
    needs_fresh_data: bool = False
    # Tarea que se beneficia de un modelo mas fuerte (codigo, analisis largo,
    # razonamiento complejo): se responde con GPT automaticamente si esta
    # configurado, sin pedir confirmacion. Charla simple se queda en Ollama.
    heavy: bool = False
    person: str = ""
    search_terms: str = ""
    confidence: float = 0.5
    reason: str = ""

    @field_validator("intent", mode="before")
    @classmethod
    def _known(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        allowed = {"charla", "biografia", "codigo", "actualidad", "precio", "confuso"}
        return text if text in allowed else "charla"

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5

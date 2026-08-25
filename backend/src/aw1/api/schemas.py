"""Contratos de la API. Pydantic valida en el borde."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..pricing.pipeline import MAX_QUERY_LENGTH


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=64)


class PriceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    stores: list[str] = Field(default_factory=list, max_length=12)
    refresh: bool = False


class SaveItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000)
    source: str = Field(default="local", max_length=30)
    kind: str = Field(default="note", max_length=30)
    meta: dict[str, Any] = Field(default_factory=dict)


class SavedItem(BaseModel):
    id: int
    text: str
    source: str
    kind: str
    meta: dict[str, Any]
    created_at: datetime


class SavedList(BaseModel):
    items: list[SavedItem]
    total: int


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: datetime
    messages: int


class StoredMessage(BaseModel):
    role: str
    content: str
    source: str
    created_at: datetime


class SetSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=4000)


class AdminConfig(BaseModel):
    llm_provider: str
    ollama_host: str
    groq_configured: bool
    openai_configured: bool
    brave_configured: bool


class TestSecretResult(BaseModel):
    ok: bool
    detail: str


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)


class ApiKeySummary(BaseModel):
    id: int
    label: str
    key_preview: str
    created_at: datetime


class ApiKeyCreated(ApiKeySummary):
    value: str


class AdminStatus(BaseModel):
    llm_provider: str
    llm_model: str
    database: str
    api_token_configured: bool
    api_keys_issued: int
    conversations: int
    messages: int
    saved_items: int


class TelegramTokenSummary(BaseModel):
    id: str
    agent_id: str
    bot_username: str
    token_preview: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TelegramTokenCreated(TelegramTokenSummary):
    webhook_registered: bool = True


class CreateTelegramTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: str = Field(min_length=10, max_length=200)


class UpdateTelegramTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class CreateTelegramAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(default="", max_length=4000)
    # Opcional: crea de una el primer bot de este agente. Un agente puede
    # tener mas de un token -los siguientes se agregan aparte, ver
    # POST /admin/telegram-agents/{agent_id}/tokens.
    bot_token: str = Field(default="", max_length=200)


class UpdateTelegramAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(default="", max_length=4000)
    enabled: bool = True


class TelegramAgentFileSummary(BaseModel):
    id: str
    agent_id: str
    filename: str
    char_count: int
    created_at: datetime


class TelegramAgentApiSummary(BaseModel):
    id: str
    agent_id: str
    name: str
    description: str
    url: str
    method: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CreateTelegramAgentApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    method: str = Field(default="GET", max_length=10)
    headers: dict[str, str] = Field(default_factory=dict)


class UpdateTelegramAgentApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Solo activar/desactivar -no re-editar la URL o los headers, que
    # pueden traer credenciales: mismo criterio que los tokens de bots
    # (nunca se re-exponen al frontend despues de crearlos). Para cambiar
    # la URL/headers de una API, se borra y se crea de nuevo.
    enabled: bool = True


class CapabilityGapSummary(BaseModel):
    id: int
    conversation_id: str | None
    agent_id: str | None
    name: str
    description: str
    why: str
    triggering_message: str
    created_at: datetime
    tool_id: str | None
    tool_status: str | None


class GeneratedToolSummary(BaseModel):
    id: str
    agent_id: str
    source_gap_reasoning_id: int | None
    name: str
    description: str
    status: str
    call_count: int
    last_called_at: datetime | None
    last_error: str
    created_at: datetime
    updated_at: datetime


class GeneratedToolDetail(GeneratedToolSummary):
    spec: dict[str, Any]
    code: str
    test_code: str
    sandbox_result: dict[str, Any]
    reject_reason: str


class CreateGeneratedToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    source_gap_reasoning_id: int | None = None


class RejectGeneratedToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)


class TelegramAgentSummary(BaseModel):
    id: str
    label: str
    system_prompt: str
    personality: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    tokens: list[TelegramTokenSummary] = Field(default_factory=list)
    files: list[TelegramAgentFileSummary] = Field(default_factory=list)
    apis: list[TelegramAgentApiSummary] = Field(default_factory=list)


class GeneratePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)


class HumanizePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str = Field(min_length=1, max_length=6000)


class GeneratedPromptResult(BaseModel):
    system_prompt: str


class StatusResponse(BaseModel):
    version: str
    env: str
    ollama: str
    model: str
    model_ready: bool
    models: list[str]
    gpt_configured: bool
    database: str
    auth_enabled: bool
    browser: dict[str, Any]
    mentions: list[dict[str, str]] = []

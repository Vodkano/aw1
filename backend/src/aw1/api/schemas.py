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


class CreateTelegramProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    bot_token: str = Field(min_length=10, max_length=200)
    system_prompt: str = Field(default="", max_length=4000)


class UpdateTelegramProfileRequest(CreateTelegramProfileRequest):
    enabled: bool = True


class TelegramProfileSummary(BaseModel):
    id: str
    label: str
    bot_username: str
    token_preview: str
    system_prompt: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TelegramProfileDetail(TelegramProfileSummary):
    bot_token: str
    webhook_registered: bool = True


class GeneratePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)


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

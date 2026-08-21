"""Contratos de la API. Pydantic valida en el borde."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=64)
    allow_gpt: bool = False


class PriceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=180)
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

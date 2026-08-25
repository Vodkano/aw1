"""Contenedor de dependencias, construido una vez en el arranque."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import Request

from ..browser.pool import BrowserPool
from ..chat.service import ChatService
from ..chat.tools.base import ToolRegistry
from ..chat.tools.prices import PriceSearchTool
from ..chat.tools.websearch import WebSearchTool
from ..chat.wikipedia import Wikipedia
from ..core import llm_provider
from ..core.api_keys_store import ApiKeyStore
from ..core.ratelimit import RateLimiter
from ..core.secrets_store import SecretsStore
from ..core.telegram_store import TelegramStore
from ..db import create_repository
from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.client import OllamaClient
from ..llm.groq_client import GroqClient
from ..llm.judges import Judges
from ..pricing.pipeline import PricePipeline
from ..settings import Settings
from ..telegram.client import TelegramClient
from ..telegram.orchestrator import TelegramOrchestrator


def _build_llm_client(settings: Settings, secrets: SecretsStore) -> OllamaClient | GroqClient:
    """Elige Ollama o Groq y arma el cliente, con overrides del panel admin."""
    if llm_provider.effective_provider(settings, secrets) == "groq":
        key = secrets.get("groq_api_key")
        if not key and settings.groq_api_key:
            key = settings.groq_api_key.get_secret_value()
        return GroqClient(settings.groq_base_url, api_key=key or "")
    host = secrets.get("ollama_host") or settings.ollama_host
    tunnel_key = secrets.get("ollama_tunnel_key")
    if not tunnel_key and settings.ollama_tunnel_key:
        tunnel_key = settings.ollama_tunnel_key.get_secret_value()
    headers = {"X-Aw1-Tunnel-Key": tunnel_key} if tunnel_key else None
    return OllamaClient(host, num_ctx=settings.ollama_num_ctx, extra_headers=headers)


@dataclass(slots=True)
class Container:
    settings: Settings
    repo: Repository | PostgresRepository
    llm: OllamaClient | GroqClient
    judges: Judges
    browser: BrowserPool
    wikipedia: Wikipedia
    chat: ChatService
    prices: PricePipeline
    tools: ToolRegistry
    limiter: RateLimiter
    secrets: SecretsStore
    api_keys: ApiKeyStore
    telegram_client: TelegramClient
    telegram_store: TelegramStore
    telegram: TelegramOrchestrator

    @classmethod
    async def build(cls, settings: Settings) -> Container:
        repo = create_repository(settings.database_url, settings.database_path)
        await repo.connect()

        secrets = SecretsStore(repo)
        api_keys = ApiKeyStore(repo)
        telegram_client = TelegramClient()
        telegram_store = TelegramStore(repo, telegram_client, settings, secrets)
        await asyncio.gather(secrets.load(), api_keys.load(), telegram_store.load())

        llm = _build_llm_client(settings, secrets)
        judges = Judges(
            llm, model=llm_provider.judge_model(settings, secrets),
            timeout=settings.ollama_judge_timeout,
        )
        browser = BrowserPool(settings)
        wikipedia = Wikipedia()

        prices = PricePipeline(
            settings=settings, browser=browser, judges=judges, repository=repo
        )
        tools = ToolRegistry([PriceSearchTool(prices), WebSearchTool(settings, secrets)])
        chat = ChatService(
            settings=settings, repository=repo, llm=llm, judges=judges,
            wikipedia=wikipedia, secrets=secrets, tools=tools,
        )
        telegram = TelegramOrchestrator(
            tokens=telegram_store, client=telegram_client, chat=chat,
            prices=prices, repo=repo, settings=settings, secrets=secrets,
        )
        return cls(
            settings=settings, repo=repo, llm=llm, judges=judges, browser=browser,
            wikipedia=wikipedia, chat=chat, prices=prices, tools=tools,
            limiter=RateLimiter(settings.rate_limit_per_minute),
            secrets=secrets, api_keys=api_keys, telegram_client=telegram_client,
            telegram_store=telegram_store, telegram=telegram,
        )

    async def reload_llm(self) -> None:
        """Reconstruye el cliente LLM con la configuracion actual (panel admin)."""
        old_llm = self.llm
        new_llm = _build_llm_client(self.settings, self.secrets)
        self.llm = new_llm
        model = llm_provider.judge_model(self.settings, self.secrets)
        self.judges.set_client(new_llm, model=model)
        self.chat.set_client(new_llm)
        await old_llm.aclose()

    async def aclose(self) -> None:
        await self.telegram.aclose()
        await self.telegram_client.aclose()
        await self.browser.stop()
        await self.wikipedia.aclose()
        await self.llm.aclose()
        await self.repo.close()


def container(request: Request) -> Container:
    box: Container = request.app.state.container
    return box

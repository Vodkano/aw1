"""Contenedor de dependencias, construido una vez en el arranque."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..browser.pool import BrowserPool
from ..chat.service import ChatService
from ..chat.wikipedia import Wikipedia
from ..core.api_keys_store import ApiKeyStore
from ..core.ratelimit import RateLimiter
from ..core.secrets_store import SecretsStore
from ..db import create_repository
from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.client import OllamaClient
from ..llm.groq_client import GroqClient
from ..llm.judges import Judges
from ..pricing.pipeline import PricePipeline
from ..settings import Settings


def _effective_provider(settings: Settings, secrets: SecretsStore) -> str:
    return secrets.get("llm_provider") or settings.llm_provider


def _judge_model(settings: Settings, secrets: SecretsStore) -> str:
    if _effective_provider(settings, secrets) == "groq":
        return settings.groq_fast_model or settings.groq_model
    return settings.ollama_fast_model or settings.ollama_model


def _build_llm_client(settings: Settings, secrets: SecretsStore) -> OllamaClient | GroqClient:
    """Elige Ollama o Groq y arma el cliente, con overrides del panel admin."""
    if _effective_provider(settings, secrets) == "groq":
        key = secrets.get("groq_api_key")
        if not key and settings.groq_api_key:
            key = settings.groq_api_key.get_secret_value()
        return GroqClient(settings.groq_base_url, api_key=key or "")
    host = secrets.get("ollama_host") or settings.ollama_host
    return OllamaClient(host, num_ctx=settings.ollama_num_ctx)


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
    limiter: RateLimiter
    secrets: SecretsStore
    api_keys: ApiKeyStore

    @classmethod
    async def build(cls, settings: Settings) -> Container:
        repo = create_repository(settings.database_url, settings.database_path)
        await repo.connect()

        secrets = SecretsStore(repo)
        await secrets.load()
        api_keys = ApiKeyStore(repo)
        await api_keys.load()

        llm = _build_llm_client(settings, secrets)
        judges = Judges(
            llm, model=_judge_model(settings, secrets), timeout=settings.ollama_judge_timeout
        )
        browser = BrowserPool(settings)
        wikipedia = Wikipedia()

        chat = ChatService(
            settings=settings, repository=repo, llm=llm, judges=judges,
            wikipedia=wikipedia, secrets=secrets,
        )
        prices = PricePipeline(
            settings=settings, browser=browser, judges=judges, repository=repo
        )
        return cls(
            settings=settings, repo=repo, llm=llm, judges=judges, browser=browser,
            wikipedia=wikipedia, chat=chat, prices=prices,
            limiter=RateLimiter(settings.rate_limit_per_minute),
            secrets=secrets, api_keys=api_keys,
        )

    async def reload_llm(self) -> None:
        """Reconstruye el cliente LLM con la configuracion actual (panel admin)."""
        old_llm = self.llm
        new_llm = _build_llm_client(self.settings, self.secrets)
        self.llm = new_llm
        self.judges.set_client(new_llm, model=_judge_model(self.settings, self.secrets))
        self.chat.set_client(new_llm)
        await old_llm.aclose()

    async def aclose(self) -> None:
        await self.browser.stop()
        await self.wikipedia.aclose()
        await self.llm.aclose()
        await self.repo.close()


def container(request: Request) -> Container:
    box: Container = request.app.state.container
    return box

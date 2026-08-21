"""Contenedor de dependencias, construido una vez en el arranque."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..browser.pool import BrowserPool
from ..chat.service import ChatService
from ..chat.wikipedia import Wikipedia
from ..core.ratelimit import RateLimiter
from ..db import create_repository
from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.client import OllamaClient
from ..llm.groq_client import GroqClient
from ..llm.judges import Judges
from ..pricing.pipeline import PricePipeline
from ..settings import Settings


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

    @classmethod
    async def build(cls, settings: Settings) -> Container:
        repo = create_repository(settings.database_url, settings.database_path)
        await repo.connect()

        llm: OllamaClient | GroqClient
        if settings.uses_groq:
            key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else ""
            llm = GroqClient(settings.groq_base_url, api_key=key)
        else:
            llm = OllamaClient(settings.ollama_host, num_ctx=settings.ollama_num_ctx)
        judges = Judges(llm, model=settings.judge_model, timeout=settings.ollama_judge_timeout)
        browser = BrowserPool(settings)
        wikipedia = Wikipedia()

        chat = ChatService(
            settings=settings, repository=repo, llm=llm, judges=judges, wikipedia=wikipedia
        )
        prices = PricePipeline(
            settings=settings, browser=browser, judges=judges, repository=repo
        )
        return cls(
            settings=settings, repo=repo, llm=llm, judges=judges, browser=browser,
            wikipedia=wikipedia, chat=chat, prices=prices,
            limiter=RateLimiter(settings.rate_limit_per_minute),
        )

    async def aclose(self) -> None:
        await self.browser.stop()
        await self.wikipedia.aclose()
        await self.llm.aclose()
        await self.repo.close()


def container(request: Request) -> Container:
    box: Container = request.app.state.container
    return box

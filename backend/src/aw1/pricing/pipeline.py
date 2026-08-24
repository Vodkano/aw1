"""Orquestacion de una busqueda de precios.

El recorrido completo, y donde interviene la IA en cada paso:

    1. plan          IA  -> interpreta la peticion y decide que buscar
    2. buscar             -> Chromium abre el buscador de cada tienda
    3. candidatos    IA  -> elige cuales resultados son de verdad el producto
    4. leer ficha        -> Chromium abre cada ficha y extrae su contexto
    5. precio        IA  -> decide cual importe de la pagina es el precio
    6. verificar         -> el codigo comprueba que ese precio existe de verdad
    7. rankear           -> conversion a pesos y orden por precio real
    8. veredicto     IA  -> redacta la conclusion

Todo emite eventos mientras ocurre, de modo que la interfaz muestra el avance
tienda por tienda en lugar de un spinner de un minuto.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..browser.pool import BrowserPool
from ..core.errors import BrowserError, NoResultsError, ValidationError
from ..db.postgres_repository import PostgresRepository
from ..db.repository import Repository
from ..llm.judges import Judges
from ..llm.schemas import SearchPlan
from ..settings import Settings
from ..stores.registry import Store, demo_store, resolve, store_for_host
from . import money, rank
from .models import Comparison, Offer, StoreOutcome

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 180
MIN_CARDS_BEFORE_RETRY = 3


@dataclass(slots=True)
class Event:
    type: str
    data: dict[str, Any]


class PricePipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        browser: BrowserPool,
        judges: Judges,
        repository: Repository | PostgresRepository | None = None,
    ) -> None:
        self._settings = settings
        self._browser = browser
        self._judges = judges
        self._repo = repository

    # ------------------------------------------------------------------
    async def compare(
        self, query: str, stores: list[str] | None = None, *, refresh: bool = False
    ) -> Comparison:
        """Version sin streaming: consume los eventos y devuelve el resultado."""
        result: Comparison | None = None
        async for event in self.run(query, stores, refresh=refresh):
            if event.type == "done":
                result = Comparison.model_validate(event.data["comparison"])
            elif event.type == "error":
                raise NoResultsError(event.data["message"])
        if result is None:
            raise NoResultsError("La busqueda no produjo resultados.")
        return result

    async def read_price(self, url: str, product_label: str = "") -> Offer | None:
        """Lee el precio de UNA pagina que la persona ya eligio -sin buscar
        candidatos ni armar un plan de busqueda, la URL ya es la eleccion
        (la usa el seguimiento de precios de los bots de Telegram). Reusa
        _offer_from tal cual: misma lectura de ficha, mismo juez de precio,
        misma verificacion anti-alucinacion que el comparador normal."""
        host = (urlparse(url).hostname or url).lower()
        store = store_for_host(host) or Store(
            slug=host, name=host, domain=host, search_template="", url_patterns=()
        )
        plan = SearchPlan(product=product_label or host)
        return await self._offer_from(store, plan, {"url": url, "title": ""})

    async def run(
        self, query: str, stores: list[str] | None = None, *, refresh: bool = False
    ) -> AsyncIterator[Event]:
        started = time.monotonic()
        clean = self._clean_query(query)
        selected = self._stores_for(stores)

        cache_key = self._cache_key(clean, selected)
        if not refresh and self._repo is not None:
            cached = await self._repo.cache_get(cache_key)
            if cached:
                comparison = Comparison.model_validate(cached)
                comparison.from_cache = True
                comparison.elapsed = round(time.monotonic() - started, 2)
                yield Event("cache", {"hit": True})
                yield Event("done", {"comparison": comparison.model_dump(mode="json")})
                return

        yield Event("start", {"query": clean, "stores": [store.name for store in selected]})

        # --- paso 1: la IA decide que buscar ---------------------------------
        plan = await self._judges.plan_search(clean)
        yield Event(
            "plan",
            {
                "product": plan.product,
                "queries": plan.queries,
                "required": plan.required,
                "forbidden": plan.forbidden[:8],
                "notes": plan.notes,
            },
        )

        # --- pasos 2 a 6: una tarea por tienda, en paralelo ------------------
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        offers: list[Offer] = []
        outcomes: list[StoreOutcome] = []
        discarded = 0

        async def worker(store: Store) -> None:
            try:
                found, outcome, dropped = await self._process_store(store, plan, queue)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - una tienda no tumba la busqueda
                logger.warning("Tienda %s fallo: %s", store.slug, error)
                outcome = StoreOutcome(
                    slug=store.slug, name=store.name, status="error", detail=str(error)[:160]
                )
                found, dropped = [], 0
            offers.extend(found)
            outcomes.append(outcome)
            nonlocal discarded
            discarded += dropped
            await queue.put(Event("store_done", {"store": outcome.model_dump(mode="json")}))

        tasks = [asyncio.create_task(worker(store)) for store in selected]

        async def watchdog() -> None:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self._settings.search_budget_seconds,
                )
            except TimeoutError:
                logger.info("Presupuesto agotado: se cancelan las tiendas pendientes.")
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                await queue.put(None)

        watcher = asyncio.create_task(watchdog())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

        timed_out = {store.slug for store in selected} - {item.slug for item in outcomes}
        for slug in timed_out:
            store = next(item for item in selected if item.slug == slug)
            outcomes.append(
                StoreOutcome(
                    slug=slug,
                    name=store.name,
                    status="timeout",
                    detail="Se agoto el tiempo de la busqueda.",
                )
            )

        # --- paso 7: normalizar, convertir y ordenar -------------------------
        valid, warnings = rank.normalize(offers, self._settings.fx_rates_to_clp)
        discarded += len(offers) - len(valid)
        best = rank.rank(valid, self._settings.max_offers)

        if not best:
            message = self._explain_empty(outcomes)
            yield Event("error", {"message": message})
            return

        alert = rank.outlier_warning(best)
        if alert:
            warnings.append(alert)

        # --- paso 8: la IA redacta el veredicto ------------------------------
        yield Event("verdict_pending", {})
        verdict = await self._judges.write_verdict(
            plan.product,
            [offer.model_dump(mode="json") for offer in best],
            visited=len([item for item in outcomes if item.status == "ok"]),
            discarded=discarded,
        )

        comparison = Comparison(
            query=clean,
            product=plan.product,
            offers=best,
            verdict=verdict,
            stores=sorted(outcomes, key=lambda item: item.name),
            visited=len(outcomes),
            discarded=discarded,
            elapsed=round(time.monotonic() - started, 2),
            warnings=warnings,
            ai=self._judges.stats.as_dict(),
        )

        if self._repo is not None:
            payload = comparison.model_dump(mode="json")
            await self._repo.cache_set(cache_key, payload, self._settings.cache_ttl_seconds)
            await self._repo.save_search(clean, {"product": plan.product, "offers": len(best)})

        yield Event("done", {"comparison": comparison.model_dump(mode="json")})

    # ------------------------------------------------------------------
    async def _process_store(
        self, store: Store, plan: SearchPlan, queue: asyncio.Queue[Event | None]
    ) -> tuple[list[Offer], StoreOutcome, int]:
        started = time.monotonic()
        queries = plan.queries or [plan.product]
        search_url = store.search_url(queries[0])
        outcome = StoreOutcome(slug=store.slug, name=store.name, search_url=search_url)
        await queue.put(
            Event("store_start", {"slug": store.slug, "name": store.name, "url": search_url})
        )

        cards: list[dict[str, Any]] = []
        try:
            cards = await self._browser.search_cards(
                search_url,
                url_patterns=list(store.url_patterns),
                wait_selector=store.wait_selector,
            )
            # Si la primera consulta trae poco, se prueba la variante del plan.
            if len(cards) < MIN_CARDS_BEFORE_RETRY and len(queries) > 1:
                alternative = store.search_url(queries[1])
                extra = await self._browser.search_cards(
                    alternative,
                    url_patterns=list(store.url_patterns),
                    wait_selector=store.wait_selector,
                )
                known = {card["url"] for card in cards}
                cards.extend(card for card in extra if card["url"] not in known)
        except BrowserError as error:
            outcome.status = "error"
            outcome.detail = error.message
            outcome.elapsed = round(time.monotonic() - started, 2)
            return [], outcome, 0

        outcome.cards_found = len(cards)
        await queue.put(Event("store_cards", {"slug": store.slug, "found": len(cards)}))

        if not cards:
            outcome.status = "vacio"
            outcome.detail = "El buscador de la tienda no devolvio productos."
            outcome.elapsed = round(time.monotonic() - started, 2)
            return [], outcome, 0

        picks = await self._judges.pick_products(
            plan, store.name, cards, self._settings.products_per_store
        )
        outcome.picked = len(picks)
        dropped = len(cards) - len(picks)
        await queue.put(
            Event(
                "store_picked",
                {
                    "slug": store.slug,
                    "picked": [
                        {"title": pick["title"], "url": pick["url"], "why": pick.get("why", "")}
                        for pick in picks
                    ],
                },
            )
        )

        if not picks:
            outcome.status = "vacio"
            outcome.detail = "Ningun resultado correspondia al producto."
            outcome.elapsed = round(time.monotonic() - started, 2)
            return [], outcome, dropped

        found: list[Offer] = []
        for pick in picks:
            offer = await self._offer_from(store, plan, pick)
            if offer is None:
                dropped += 1
                continue
            found.append(offer)
            await queue.put(Event("offer", {"offer": offer.model_dump(mode="json")}))

        outcome.offers = len(found)
        outcome.elapsed = round(time.monotonic() - started, 2)
        if not found:
            outcome.status = "vacio"
            outcome.detail = "Se abrieron las fichas pero ninguna publicaba un precio claro."
        return found, outcome, dropped

    async def _offer_from(
        self, store: Store, plan: SearchPlan, pick: dict[str, Any]
    ) -> Offer | None:
        """Abre la ficha, deja que la IA decida el precio y verifica el resultado."""
        try:
            page = await self._browser.read_product(
                pick["url"], wait_selector=store.product_wait_selector
            )
        except BrowserError as error:
            logger.debug("Ficha no legible (%s): %s", store.slug, error)
            return None

        page["price_candidates"] = self._prepare_candidates(
            page.get("price_candidates", []), store.currency
        )
        if not page["price_candidates"]:
            return None

        verdict = await self._judges.read_page(plan, page)
        if not verdict.is_match or verdict.price is None:
            return None

        host = (urlparse(page.get("url") or pick["url"]).hostname or "").lower()
        resolved = store_for_host(host) or store
        amount = money.Amount(float(verdict.price), verdict.currency)
        clp = money.to_clp(amount, self._settings.fx_rates_to_clp)
        if clp is None or not money.plausible(clp):
            return None

        return Offer(
            store=resolved.name,
            store_slug=resolved.slug,
            domain=host or resolved.domain,
            url=page.get("url") or pick["url"],
            title=verdict.product_title or pick.get("title", ""),
            price=float(verdict.price),
            currency=verdict.currency,
            price_clp=clp,
            price_label=money.format_clp(clp),
            in_stock=verdict.in_stock,
            confidence=verdict.confidence,
            decided_by="heuristica" if "sin IA" in verdict.reason else "ia",
            reason=verdict.reason[:200],
        )

    def _prepare_candidates(
        self, raw: list[dict[str, Any]], default_currency: str
    ) -> list[dict[str, Any]]:
        """Convierte los importes crudos en numeros antes de que los vea el modelo.

        Asi el modelo elige entre valores ya validados y, sobre todo, podemos
        comprobar despues que el numero que devuelva existe de verdad.
        """
        prepared: list[dict[str, Any]] = []
        index: dict[tuple[float, str], dict[str, Any]] = {}

        for item in raw:
            amount = money.parse(
                item.get("raw") or item.get("text"),
                default_currency=(item.get("currency") or default_currency or "CLP"),
            )
            if amount is None:
                continue
            clp = money.to_clp(amount, self._settings.fx_rates_to_clp)
            if clp is None or not money.plausible(clp):
                continue

            context = str(item.get("context", ""))
            if item.get("struck"):
                context = f"[precio tachado] {context}"
            if item.get("noisy"):
                context = f"[posible cuota o descuento] {context}"

            key = (round(amount.value, 2), amount.currency)
            existing = index.get(key)
            if existing is not None:
                # El mismo importe aparece en json-ld y en pantalla. Se conserva
                # una sola entrada, marcada como estructurada (mas fiable) pero
                # con la etiqueta visible, que es la que permite distinguir un
                # "precio internet" de un "precio normal".
                existing["kind"] = "structured" if "structured" in (
                    existing["kind"], item.get("kind")
                ) else existing["kind"]
                existing["prominence"] = max(
                    float(existing["prominence"]), float(item.get("prominence") or 0)
                )
                if context and context not in existing["context"]:
                    existing["context"] = f"{existing['context']} | {context}"[:220]
                continue

            entry = {
                "id": len(prepared) + 1,
                "text": item.get("text", ""),
                "value": amount.value,
                "currency": amount.currency,
                "value_clp": clp,
                "kind": item.get("kind", "visual"),
                "context": context[:220],
                "prominence": float(item.get("prominence") or 0.5),
            }
            index[key] = entry
            prepared.append(entry)
        return prepared

    def _stores_for(self, requested: list[str] | None) -> list[Store]:
        """Tiendas a recorrer, con la de demostracion delante si esta configurada."""
        if self._settings.demo_store_url:
            demo = demo_store(self._settings.demo_store_url)
            if not requested or "demo" in {str(item).lower() for item in requested}:
                rest = resolve(requested, max(self._settings.stores_per_search - 1, 0))
                return [demo, *[store for store in rest if store.slug != "demo"]]
        return resolve(requested, self._settings.stores_per_search)

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_query(query: str) -> str:
        clean = " ".join(str(query or "").split())
        if not clean:
            raise ValidationError("Escribe que producto quieres comparar.")
        if len(clean) > MAX_QUERY_LENGTH:
            raise ValidationError(
                f"La busqueda no puede superar los {MAX_QUERY_LENGTH} caracteres."
            )
        return clean

    @staticmethod
    def _cache_key(query: str, stores: list[Store]) -> str:
        raw = query.lower() + "|" + ",".join(sorted(store.slug for store in stores))
        return "price:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _explain_empty(outcomes: list[StoreOutcome]) -> str:
        errors = [item for item in outcomes if item.status == "error"]
        if errors and len(errors) == len(outcomes):
            return (
                "Ninguna tienda respondio. Comprueba tu conexion y que el navegador "
                "interno este instalado (`playwright install chromium`)."
            )
        if any(item.status == "timeout" for item in outcomes):
            return (
                "Se agoto el tiempo antes de encontrar precios. Prueba con menos "
                "tiendas o con un nombre mas exacto."
            )
        return (
            "Se visitaron las tiendas pero ninguna publico un precio para ese producto. "
            "Prueba con el nombre exacto del modelo."
        )

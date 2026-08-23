"""Navegador compartido sobre Playwright.

Un solo Chromium para todo el proceso y un pool de contextos aislados. Cada
busqueda pide un contexto, lo usa y lo devuelve; el navegador nunca se relanza
por peticion, que es lo que haria inviable esta arquitectura.

Decisiones que importan:

* **Se bloquean imagenes, fuentes y video.** Una ficha de Falabella baja de ~4 MB
  a ~300 KB y de 6 s a menos de 2 s. No perdemos nada: solo queremos el texto.
* **Cada contexto es efimero y sin permisos.** No se comparten cookies entre
  tiendas y no se acepta geolocalizacion, camara ni notificaciones.
* **La guardia SSRF se aplica antes de navegar**, con resolucion DNS incluida,
  para que una redireccion no lleve al navegador a la red local del usuario.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..core import netguard
from ..core.errors import BrowserError
from ..settings import Settings

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_EXTRACT_JS = (_HERE / "extract.js").read_text(encoding="utf-8")
_CARDS_JS = (_HERE / "cards.js").read_text(encoding="utf-8")

_BLOCKED_RESOURCES = {"image", "media", "font"}
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class BrowserPool:
    """Ciclo de vida del navegador y acceso concurrente controlado."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(settings.browser_max_contexts)
        self._lock = asyncio.Lock()
        self._launch_error: str = ""

    # -- ciclo de vida ------------------------------------------------------
    async def start(self) -> None:
        """Arranca Chromium. Si falla, se registra y el resto de la app sigue viva."""
        async with self._lock:
            if self._browser is not None:
                return
            try:
                self._playwright = await async_playwright().start()
                launch_args: dict[str, Any] = {
                    "headless": self._settings.browser_headless,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-gpu",
                    ],
                }
                if self._settings.browser_executable_path:
                    launch_args["executable_path"] = self._settings.browser_executable_path
                proxy_url = self._settings.browser_proxy_url
                if proxy_url:
                    proxy = _parse_proxy(proxy_url.get_secret_value())
                    if proxy:
                        launch_args["proxy"] = proxy
                self._browser = await self._playwright.chromium.launch(**launch_args)
                self._launch_error = ""
                logger.info("Chromium listo (%d contextos)", self._settings.browser_max_contexts)
            except Exception as error:  # noqa: BLE001
                self._launch_error = str(error)[:300]
                logger.error(
                    "No se pudo iniciar Chromium. Ejecuta `playwright install chromium`. (%s)",
                    self._launch_error,
                )

    async def stop(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    @property
    def ready(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    @property
    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "headless": self._settings.browser_headless,
            "contexts": self._settings.browser_max_contexts,
            "error": self._launch_error,
            "proxy": bool(self._settings.browser_proxy_url),
        }

    # -- contextos ----------------------------------------------------------
    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        if not self.ready:
            await self.start()
        if self._browser is None:
            raise BrowserError(
                "El navegador interno no esta disponible. Instalalo con "
                "`playwright install chromium`."
            )
        async with self._semaphore:
            context: BrowserContext = await self._browser.new_context(
                locale=self._settings.browser_locale,
                timezone_id=self._settings.browser_timezone,
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 900},
                java_script_enabled=True,
                bypass_csp=True,
                extra_http_headers={"Accept-Language": "es-CL,es;q=0.9,en;q=0.6"},
            )
            context.set_default_navigation_timeout(self._settings.browser_nav_timeout * 1000)
            context.set_default_timeout(self._settings.browser_nav_timeout * 1000)
            if self._settings.browser_block_media:
                await context.route("**/*", _block_heavy_resources)
            page = await context.new_page()
            try:
                yield page
            finally:
                await context.close()

    # -- navegacion ---------------------------------------------------------
    async def _goto(self, page: Page, url: str) -> str:
        safe = netguard.sanitize(url)
        if safe is None:
            raise BrowserError("La direccion no es navegable.")
        host = safe.split("/")[2].split("@")[-1].split(":")[0]
        if not await asyncio.to_thread(netguard.resolves_public, host):
            raise BrowserError("El dominio no resuelve a una direccion publica.")
        try:
            response = await page.goto(safe, wait_until="domcontentloaded")
        except Exception as error:  # noqa: BLE001 - playwright lanza tipos variados
            raise BrowserError(f"No se pudo abrir la pagina: {type(error).__name__}") from error
        # Un 404 o un 503 tambien "cargan": sin esta comprobacion se acabaria
        # analizando la pagina de error de la tienda como si fuera una ficha.
        if response is not None and response.status >= 400:
            raise BrowserError(f"La tienda respondio {response.status}.")
        return safe

    @staticmethod
    async def _settle(page: Page, selector: str = "", extra_ms: int = 900) -> None:
        """Espera a que la tienda termine de pintar sus resultados.

        Las tiendas grandes cargan el catalogo por XHR despues del HTML inicial:
        sin esta espera el DOM esta vacio y no hay nada que extraer.
        """
        # Ninguna de las dos esperas es obligatoria: son pistas de que la tienda
        # ya pinto su contenido. Si expiran, se sigue con el margen fijo.
        if selector:
            with suppress(Exception):
                await page.wait_for_selector(selector, timeout=8000, state="attached")
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=6000)
        await page.wait_for_timeout(extra_ms)

    async def search_cards(
        self, url: str, *, url_patterns: list[str], wait_selector: str = "", scroll: bool = True
    ) -> list[dict[str, Any]]:
        """Abre una pagina de resultados y devuelve las tarjetas encontradas."""
        async with self.page() as page:
            await self._goto(page, url)
            await self._settle(page, wait_selector)
            if scroll:
                # Muchas tiendas cargan por scroll: dos saltos bastan.
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
                await page.wait_for_timeout(700)
            cards = await page.evaluate(_CARDS_JS, url_patterns)
        return [card for card in cards if isinstance(card, dict)]

    async def read_product(self, url: str, *, wait_selector: str = "") -> dict[str, Any]:
        """Abre una ficha y devuelve el paquete de contexto para el modelo."""
        async with self.page() as page:
            final_url = await self._goto(page, url)
            await self._settle(page, wait_selector, extra_ms=700)
            payload = await page.evaluate(_EXTRACT_JS)
        if not isinstance(payload, dict):
            raise BrowserError("La pagina no devolvio contenido analizable.")
        payload.setdefault("url", final_url)
        return payload


def _parse_proxy(url: str) -> dict[str, str] | None:
    """Convierte una URL de proxy estandar (http://usuario:clave@host:puerto)
    en el formato que espera Playwright. Usuario/clave van separados del
    server: algunos proveedores no los aceptan bien embebidos en la URL."""
    parsed = urlsplit(url)
    if not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    proxy: dict[str, str] = {"server": f"{parsed.scheme}://{parsed.hostname}{port}"}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


async def _block_heavy_resources(route: Any, request: Any) -> None:
    """Corta lo que no aporta texto: imagenes, fuentes, video y rastreadores."""
    if request.resource_type in _BLOCKED_RESOURCES:
        await route.abort()
        return
    url = request.url.lower()
    if any(
        marker in url
        for marker in (
            "googletagmanager", "google-analytics", "doubleclick", "facebook.net",
            "hotjar", "criteo", "newrelic", "segment.io", "optimizely",
        )
    ):
        await route.abort()
        return
    await route.continue_()

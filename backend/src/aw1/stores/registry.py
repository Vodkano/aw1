"""Tiendas que sabe recorrer el comparador.

Cada tienda declara como se busca en ella y como reconocer una ficha de
producto. Todo se abre con un navegador real, asi que da igual que el catalogo
se pinte con JavaScript: es exactamente el caso que la version anterior no podia
resolver y por el que Falabella, Ripley, Paris y Lider devolvian cero
resultados.

``wait_selector`` es lo que hay que esperar para saber que el listado ya se
pinto. Si se queda corto, ``_settle`` cae en ``networkidle`` y sigue.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote, quote_plus

QueryStyle = Literal["plus", "path", "slug"]


def slugify(text: str) -> str:
    """Convierte 'iPhone 15 128 GB' en 'iphone-15-128-gb'.

    Mercado Libre usa la consulta como parte de la ruta, con guiones. Enviarla
    codificada con %20 devuelve una pagina vacia.
    """
    normalized = unicodedata.normalize("NFD", str(text or ""))
    ascii_text = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


@dataclass(frozen=True, slots=True)
class Store:
    slug: str
    name: str
    domain: str
    search_template: str
    url_patterns: tuple[str, ...]
    currency: str = "CLP"
    country: str = "CL"
    wait_selector: str = ""
    product_wait_selector: str = ""
    priority: int = 50
    query_style: QueryStyle = "plus"
    notes: str = ""
    aliases: tuple[str, ...] = field(default=())

    def search_url(self, query: str) -> str:
        if self.query_style == "slug":
            encoded = slugify(query)
        elif self.query_style == "path":
            encoded = quote(query, safe="")
        else:
            encoded = quote_plus(query)
        return self.search_template.format(query=encoded)

    def owns(self, host: str) -> bool:
        host = (host or "").lower()
        domains = (self.domain, *self.aliases)
        return any(host == item or host.endswith(f".{item}") for item in domains)


STORES: tuple[Store, ...] = (
    Store(
        slug="mercadolibre",
        name="Mercado Libre",
        domain="mercadolibre.cl",
        search_template="https://listado.mercadolibre.cl/{query}",
        url_patterns=("/MLC-", "/p/MLC", "articulo.mercadolibre.cl"),
        wait_selector="ol.ui-search-layout, .ui-search-results",
        product_wait_selector=".ui-pdp-price, .andes-money-amount",
        priority=10,
        query_style="slug",
        aliases=("articulo.mercadolibre.cl", "mercadolibre.com"),
    ),
    Store(
        slug="falabella",
        name="Falabella",
        domain="falabella.com",
        search_template="https://www.falabella.com/falabella-cl/search?Ntt={query}",
        url_patterns=("/product/",),
        wait_selector="[data-pod], #testId-searchResults-products",
        product_wait_selector="[data-testid='product-detail']",
        priority=20,
        notes="Catalogo renderizado con JavaScript.",
    ),
    Store(
        slug="paris",
        name="Paris",
        domain="paris.cl",
        search_template="https://www.paris.cl/search/?q={query}",
        url_patterns=("/producto/", "-MKP", ".html"),
        wait_selector="[data-testid='product-card'], .product-item",
        priority=30,
        notes="Catalogo renderizado con JavaScript.",
    ),
    Store(
        slug="ripley",
        name="Ripley",
        domain="ripley.cl",
        search_template="https://simple.ripley.cl/search/{query}",
        url_patterns=("/producto/", "-mpm", "/p/"),
        wait_selector=".catalog-product-item, [data-cy='product-item']",
        priority=40,
        query_style="path",
        aliases=("simple.ripley.cl",),
        notes="Catalogo renderizado con JavaScript.",
    ),
    Store(
        slug="pcfactory",
        name="PC Factory",
        domain="pcfactory.cl",
        search_template="https://www.pcfactory.cl/buscar?q={query}",
        url_patterns=("/producto/",),
        wait_selector=".product-card, .grilla-producto",
        priority=50,
    ),
    Store(
        slug="lider",
        name="Lider",
        domain="lider.cl",
        search_template="https://www.lider.cl/search?query={query}",
        url_patterns=("/product/", "/ip/"),
        wait_selector="[data-testid='product-tile'], .product-tile",
        priority=60,
        notes="Catalogo renderizado con JavaScript.",
    ),
    Store(
        slug="solotodo",
        name="SoloTodo",
        domain="solotodo.cl",
        search_template="https://www.solotodo.cl/search?search={query}",
        url_patterns=("/products/",),
        wait_selector="[class*='ProductCard'], a[href*='/products/']",
        priority=70,
        notes="Agregador: util para descubrir tiendas pequenas.",
    ),
    Store(
        slug="spdigital",
        name="SP Digital",
        domain="spdigital.cl",
        search_template="https://www.spdigital.cl/search?q={query}",
        url_patterns=("/products/", "/product/"),
        wait_selector=".product-item, [class*='product']",
        priority=80,
    ),
)

BY_SLUG = {store.slug: store for store in STORES}
BY_DOMAIN = {store.domain: store for store in STORES}


def resolve(slugs: list[str] | None, limit: int) -> list[Store]:
    """Traduce lo pedido a tiendas concretas, ordenadas por prioridad."""
    if slugs:
        wanted = {str(slug).strip().lower() for slug in slugs}
        selected = [
            store
            for store in STORES
            if store.slug in wanted or store.domain in wanted or store.name.lower() in wanted
        ]
        if selected:
            return sorted(selected, key=lambda store: store.priority)[:limit]
    return sorted(STORES, key=lambda store: store.priority)[:limit]


def store_for_host(host: str) -> Store | None:
    for store in STORES:
        if store.owns(host):
            return store
    return None


def catalog() -> list[dict[str, object]]:
    return [
        {
            "slug": store.slug,
            "name": store.name,
            "domain": store.domain,
            "country": store.country,
            "currency": store.currency,
            "notes": store.notes,
        }
        for store in sorted(STORES, key=lambda item: item.priority)
    ]


def demo_store(base_url: str) -> Store:
    """Tienda de demostracion apuntando a un servidor local.

    Sirve para verificar la instalacion de punta a punta -navegador, extraccion,
    decision del modelo y ranking- sin depender de que una tienda real este
    disponible ni de su estructura.
    """
    base = base_url.rstrip("/")
    return Store(
        slug="demo",
        name="Tienda Demo",
        domain=base.split("//", 1)[-1].split("/")[0].split(":")[0],
        search_template=base + "/buscar?q={query}",
        url_patterns=("/producto/",),
        wait_selector="[data-state='ready']",
        product_wait_selector="[data-state='ready']",
        priority=1,
        notes="Servidor local de pruebas.",
    )

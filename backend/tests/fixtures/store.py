"""Tienda simulada para las pruebas de extremo a extremo.

Es deliberadamente hostil, para que las pruebas valgan de algo:

* El listado de resultados **no existe en el HTML**: lo pinta JavaScript despues
  de un retardo, igual que Falabella, Ripley, Paris o Lider. Si el extractor
  funcionara con el HTML crudo, aqui obtendria cero resultados.
* La ficha mezcla el precio real con un precio tachado mas alto, un valor de
  cuotas mucho menor y un producto recomendado con otro precio. Elegir bien no
  es trivial.
* Hay un accesorio ("Funda para Zeta 12") entre los resultados, para comprobar
  que se descarta.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CATALOG = [
    {
        "id": "1",
        "title": "Smartphone Zeta 12 256GB Negro",
        "price": 549990,
        "old_price": 699990,
        "currency": "CLP",
        "stock": True,
    },
    {
        "id": "2",
        "title": "Smartphone Zeta 12 128GB Azul",
        "price": 479990,
        "old_price": 529990,
        "currency": "CLP",
        "stock": True,
    },
    {
        "id": "3",
        "title": "Funda para Zeta 12 silicona",
        "price": 9990,
        "old_price": 12990,
        "currency": "CLP",
        "stock": True,
    },
    {
        "id": "4",
        "title": "Smartphone Zeta 11 256GB Negro",
        "price": 399990,
        "old_price": 449990,
        "currency": "CLP",
        "stock": False,
    },
]
BY_ID = {item["id"]: item for item in CATALOG}

SEARCH_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Buscar - Tienda Demo</title></head>
<body>
  <header><h1>Tienda Demo</h1></header>
  <!-- El listado llega por JavaScript: el HTML inicial esta vacio a proposito. -->
  <main id="results" data-state="loading">Cargando resultados...</main>
  <script>
    const QUERY = %(query)s;
    setTimeout(async () => {
      const response = await fetch('/api/search?q=' + encodeURIComponent(QUERY));
      const items = await response.json();
      const main = document.getElementById('results');
      main.innerHTML = '';
      main.dataset.state = 'ready';
      for (const item of items) {
        const card = document.createElement('article');
        card.className = 'product-card';
        card.innerHTML =
          '<a class="product-link" href="/producto/' + item.id + '">' + item.title + '</a>' +
          '<span class="price">$' + item.price.toLocaleString('es-CL') + '</span>';
        main.appendChild(card);
      }
    }, 250);
  </script>
</body></html>
"""

PRODUCT_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
  <title>%(title)s - Tienda Demo</title>
  <meta property="og:title" content="%(title)s">
  <script type="application/ld+json">%(jsonld)s</script>
</head>
<body>
  <nav class="breadcrumb"><a href="/">Inicio</a><a href="/c">Celulares</a></nav>
  <h1>%(title)s</h1>
  <div class="prices" data-state="loading">Cargando precio...</div>
  <section class="specs"><table><tr><td>Marca: Zeta</td></tr>
    <tr><td>Garantia: 12 meses</td></tr></table></section>
  <aside class="recommended">
    <h2>Tambien te puede interesar</h2>
    <div class="rec-item"><span>Audifonos Zeta Buds</span><span class="price">$39.990</span></div>
  </aside>
  <script>
    // El bloque de precios tambien se pinta con JavaScript.
    setTimeout(() => {
      const box = document.querySelector('.prices');
      box.dataset.state = 'ready';
      box.innerHTML =
        '<div class="price-old"><span>Precio normal</span>' +
        '<s style="text-decoration:line-through">$%(old)s</s></div>' +
        '<div class="price-internet"><span>Precio internet</span>' +
        '<strong style="font-size:34px;font-weight:800">$%(price)s</strong></div>' +
        '<div class="installments">12 cuotas de $%(installment)s</div>' +
        '<div class="shipping">Despacho $3.990</div>' +
        '<div class="availability">%(stock)s</div>';
    }, 200);
  </script>
</body></html>
"""


def _money(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - firma de BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api/search":
            query = (params.get("q", [""])[0] or "").lower()
            terms = [word for word in query.split() if word]
            items = [
                item
                for item in CATALOG
                if not terms or all(term in item["title"].lower() for term in terms)
            ] or CATALOG
            self._send(200, "application/json", json.dumps(items).encode())
            return

        if parsed.path == "/buscar":
            query = params.get("q", [""])[0]
            body = SEARCH_PAGE % {"query": json.dumps(query)}
            self._send(200, "text/html", body.encode())
            return

        if parsed.path.startswith("/producto/"):
            item = BY_ID.get(parsed.path.rsplit("/", 1)[-1])
            if item is None:
                self._send(404, "text/html", b"<h1>No existe</h1>")
                return
            jsonld = json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": item["title"],
                    "brand": {"@type": "Brand", "name": "Zeta"},
                    "offers": {
                        "@type": "Offer",
                        "price": str(item["price"]),
                        "priceCurrency": item["currency"],
                        "availability": "https://schema.org/InStock"
                        if item["stock"]
                        else "https://schema.org/OutOfStock",
                    },
                }
            )
            body = PRODUCT_PAGE % {
                "title": item["title"],
                "jsonld": jsonld,
                "price": _money(item["price"]),
                "old": _money(item["old_price"]),
                "installment": _money(item["price"] // 12),
                "stock": "En stock" if item["stock"] else "Sin stock",
            }
            self._send(200, "text/html", body.encode())
            return

        self._send(404, "text/html", b"<h1>No existe</h1>")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silencio: el servidor de pruebas no debe ensuciar la salida."""


class FakeStore:
    """Arranca la tienda en un hilo y expone su URL base."""

    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeStore:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def search_url(self, query: str) -> str:
        from urllib.parse import quote_plus

        return f"{self.base}/buscar?q={quote_plus(query)}"


if __name__ == "__main__":  # pragma: no cover - util para inspeccionar a mano
    with FakeStore() as store:
        print(f"Tienda demo en {store.base}/buscar?q=Zeta+12")
        input("Enter para detener...\n")

"""Levanta la tienda de demostracion en un puerto fijo.

    python scripts/demo_store.py 9100

Luego, en otra terminal, arranca AW1 con:

    AW1_DEMO_STORE_URL=http://127.0.0.1:9100 AW1_ALLOW_PRIVATE_HOSTS=true python -m aw1

y busca "Zeta 12" en la pestana Precios. Sirve para comprobar que el navegador,
la extraccion y la decision del modelo funcionan de punta a punta sin depender
de ninguna tienda real.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from tests.fixtures.store import Handler  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Tienda demo en http://127.0.0.1:{port}/buscar?q=Zeta+12")
    print("Ctrl+C para detener.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenida.")
    finally:
        server.server_close()

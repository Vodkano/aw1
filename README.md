# AW1 v3

Asistente que corre en tu computador. Dos cosas hace bien:

**Chat con Ollama.** Respuesta token a token, con memoria de conversación en
SQLite. Las preguntas sobre personas se responden con Wikipedia citando la
fuente. GPT es opcional y solo se consulta si tú lo autorizas en cada caso.

**Comparador de precios que navega de verdad.** Abre cada tienda con un Chromium
real, espera a que el catálogo se pinte, lee la ficha del producto y le entrega
a Ollama todo lo que un humano vería —el título, los datos estructurados y cada
importe con el contexto donde aparece— para que **el modelo decida** cuál es el
precio de venta. Devuelve el precio y el enlace directo de cada tienda.

```
Buscando: iPhone 15 128 GB
  ● Mercado Libre   14 resultados · 2 precios      4.1 s
  ● Falabella        9 resultados · 2 precios      6.8 s
  ● Paris           11 resultados · 1 precio       7.2 s
  ○ Ripley           0 resultados                  8.0 s
  ● PC Factory       6 resultados · 1 precio       5.4 s

MEJOR PRECIO   $749.990   en Falabella
```

---

## Arranque rápido

```bash
git clone <tu-repo> aw1 && cd aw1

make install        # backend + frontend + Chromium de Playwright
cp .env.example .env

ollama serve                    # en otra terminal
ollama pull mistral

make run            # http://127.0.0.1:8000
```

`make install` hace tres cosas que conviene conocer por si prefieres a mano:

```bash
cd backend  && pip install -e ".[dev]" && python -m playwright install chromium
cd frontend && npm install && npm run build
```

Ese `playwright install chromium` **no es opcional**: sin él, el comparador no
tiene con qué entrar a las tiendas. Ocupa unos 400 MB.

### Comprobar la instalación sin tocar tiendas reales

```bash
python scripts/demo_store.py 9100        # terminal 1
```

```bash
# terminal 2
AW1_DEMO_STORE_URL=http://127.0.0.1:9100 AW1_ALLOW_PRIVATE_HOSTS=true python -m aw1
```

Busca `Zeta 12` en la pestaña Precios. La tienda de demostración pinta su
catálogo con JavaScript y mezcla el precio real con un precio tachado, un valor
de cuotas y un producto recomendado, justo como una tienda de verdad. Si eso
funciona, tu instalación está completa.

### Desarrollo con recarga en caliente

```bash
cd backend  && python -m aw1      # :8000
cd frontend && npm run dev        # :5173, con proxy al backend
```

---

## Cómo decide la IA

El comparador no le pide al modelo que "busque precios". Le da un problema
acotado en cada paso y verifica lo que responde.

| Paso | Quién | Qué pasa |
| --- | --- | --- |
| 1. Plan | **IA** | Interpreta `"iphon 15 128"` → producto, variantes de búsqueda, términos obligatorios y vocabulario de accesorios a descartar |
| 2. Buscar | Chromium | Abre el buscador de cada tienda y espera a que el catálogo aparezca |
| 3. Candidatos | **IA** | Recibe los títulos y precios de las tarjetas y elige cuáles son de verdad ese producto |
| 4. Leer ficha | Chromium | Abre cada ficha y extrae título, JSON-LD, disponibilidad y **cada importe con su contexto** |
| 5. Precio | **IA** | Decide cuál de esos importes es el precio de venta, y por qué |
| 6. Verificar | Código | Comprueba que el precio elegido exista de verdad en la página |
| 7. Rankear | Código | Convierte a pesos y ordena por valor real |
| 8. Veredicto | **IA** | Redacta la conclusión en dos frases |

Lo que el modelo ve en el paso 5, ya procesado:

```
Titulo: Smartphone Zeta 12 256GB Negro
Datos estructurados: {"name": "...", "brand": "Zeta", "availability": "InStock"}

Importes encontrados en la pagina:
[1] 549990 CLP  (valor 549990.0 CLP, origen datos estructurados,
                 contexto: json-ld | strong :: Precio internet)
[2] $699.990    (valor 699990.0 CLP, origen texto,
                 contexto: [precio tachado] s :: Precio normal)
[3] $45.832     (valor 45832.0 CLP, origen texto,
                 contexto: [posible cuota o descuento] 12 cuotas)
[4] $39.990     (valor 39990.0 CLP, origen texto,
                 contexto: span .price :: Audifonos Zeta Buds)
```

Tres garantías sobre esa decisión:

**El modelo no escribe números, elige entre los que ya existen.** Si dice
`price: 500000` pero el candidato que eligió vale `549990`, manda la página y se
registra la corrección. Puedes verla en «Cómo se decidió».

**El contenido de una tienda es dato, nunca instrucción.** Va dentro de
delimitadores y el prompt del sistema avisa al modelo de que ignore cualquier
orden que aparezca ahí. Una ficha de producto es texto que controla un tercero.

**Si Ollama no está, el comparador sigue funcionando.** Cada juez tiene una
alternativa determinística: cobertura de términos para la relevancia, y
"estructurado antes que destacado antes que barato" para el precio. Las ofertas
resueltas así aparecen marcadas como `sin IA`.

---

## Estructura

```
aw1/
├── backend/
│   ├── src/aw1/
│   │   ├── settings.py           configuración tipada, validada al arrancar
│   │   ├── core/                 errores, logging, SSRF, límite de uso
│   │   ├── db/                   SQLite asíncrono (schema.sql + repository.py)
│   │   ├── llm/
│   │   │   ├── client.py         Ollama por HTTP: JSON forzado y streaming
│   │   │   ├── prompts.py        los cuatro prompts, con sus reglas
│   │   │   ├── schemas.py        lo que el modelo DEBE devolver
│   │   │   └── judges.py         las decisiones y su verificación
│   │   ├── browser/
│   │   │   ├── pool.py           Chromium compartido, contextos aislados
│   │   │   ├── cards.js          extractor de tarjetas de resultado
│   │   │   └── extract.js        extractor del contexto de una ficha
│   │   ├── stores/registry.py    catálogo de tiendas y cómo buscar en cada una
│   │   ├── pricing/              money · matching · rank · pipeline
│   │   ├── chat/                 servicio, Wikipedia y heurísticas de respaldo
│   │   └── api/                  FastAPI: rutas, esquemas y seguridad
│   └── tests/                    124 pruebas, con navegador real y sin internet
├── frontend/
│   └── src/
│       ├── index.css             sistema visual (tokens, claro/oscuro)
│       ├── lib/api.ts            cliente HTTP + lector de SSE
│       ├── components/           Shell, Markdown
│       └── views/                Chat, Precios, Guardado, Ajustes
├── scripts/demo_store.py         tienda simulada para verificar la instalación
├── Dockerfile · docker-compose.yml · Makefile
└── .github/workflows/ci.yml
```

---

## API

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `GET` | `/healthz` | Sonda de vida (pública) |
| `GET` | `/api/status` | Ollama, modelo, navegador, base de datos (pública) |
| `POST` | `/api/chat` | Chat con respuesta en streaming (SSE) |
| `GET` | `/api/chat/conversations` | Conversaciones guardadas |
| `GET` `DELETE` | `/api/chat/{id}` | Leer o borrar una conversación |
| `POST` | `/api/prices/search` | Búsqueda con progreso en vivo (SSE) |
| `POST` | `/api/prices/compare` | La misma búsqueda, respuesta única |
| `GET` | `/api/prices/stores` | Catálogo de tiendas |
| `GET` `POST` `DELETE` | `/api/memory` | Guardados |

Fuera de producción hay documentación interactiva en `/docs`.

Prueba rápida desde la terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/api/prices/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"iPhone 15 128 GB"}'
```

---

## Configuración

Todo lleva prefijo `AW1_` y está documentado en `.env.example`. Lo que más
cambia el comportamiento:

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `AW1_OLLAMA_MODEL` | `mistral` | Modelo del chat y de los jueces |
| `AW1_OLLAMA_FAST_MODEL` | vacío | Modelo pequeño solo para las decisiones del comparador |
| `AW1_BROWSER_MAX_CONTEXTS` | `3` | Páginas simultáneas. Con 8 GB de RAM no subas de 3 |
| `AW1_BROWSER_HEADLESS` | `true` | Ponlo en `false` para ver a Chromium trabajar |
| `AW1_SEARCH_BUDGET_SECONDS` | `90` | Tope duro de una búsqueda completa |
| `AW1_STORES_PER_SEARCH` | `5` | Menos tiendas, resultado más rápido |
| `AW1_BROWSER_PROXY_URL` | vacío | Proxy residencial rotativo (`http://usuario:clave@host:puerto`) para cuando el navegador corre en un datacenter y una tienda bloquea esa IP directo |
| `AW1_FX_RATES_TO_CLP` | tabla | Conversión para comparar monedas distintas |
| `AW1_API_TOKEN` | vacío | Activa autenticación. Opcional incluso en producción: el chat y el comparador de precios son de uso libre por diseño; si se define, protege el resto de la API |

### Rendimiento en un MacBook Air

El comparador hace varias llamadas al modelo por búsqueda (plan, elegir
candidatos, leer cada ficha, veredicto final): con `mistral` de juez cada una
tarda 40-45s y una búsqueda completa termina agotando el tiempo antes de
encontrar nada. Hace falta un modelo más chico para esas decisiones -pero
probado en la práctica: `qwen2.5:1.5b` es tan chico que a veces dice "no hay
precio" con la información justo delante. `llama3.2:3b` (2 GB) resultó mejor
en los dos sentidos: ~15s por decisión y veredictos correctos.

```bash
ollama pull llama3.2:3b              # si no la tienes ya
AW1_OLLAMA_FAST_MODEL=llama3.2:3b    # jueces rapidos y confiables, chat con mistral
AW1_SEARCH_BUDGET_SECONDS=150        # el default (90) queda justo con Ollama local
AW1_STORES_PER_SEARCH=3
```

---

## Antes de publicarlo en internet

`docker-compose.yml` publica el puerto solo en `127.0.0.1` a propósito.

1. `AW1_ENV=production`. `AW1_API_TOKEN` es opcional: el chat y el comparador
   de precios funcionan sin él por diseño (para eso está pensada la app). Si
   lo defines, debe tener al menos 24 caracteres y solo protege `/api/memory`.
2. HTTPS por delante (Caddy, Traefik o el proxy de tu proveedor).
3. `AW1_ALLOWED_ORIGINS` con tu dominio real.
4. Volumen persistente para `/data` y copias del SQLite.
5. Chromium necesita RAM: cuenta ~350 MB por contexto simultáneo.

El limitador de peticiones es en memoria y sirve para un proceso. Si algún día
hay varias réplicas, `core/ratelimit.py` es el único archivo que cambia.

---

## Sobre el scraping

Se navega solo por páginas públicas, con un contexto de navegador limpio, sin
sesiones ni cookies de nadie, y bloqueando imágenes y rastreadores para pedir lo
mínimo. Aun así: las tiendas cambian su HTML sin avisar, y un precio puede
cambiar entre la consulta y la compra. **Verifica siempre en la tienda antes de
pagar.** Si vas a usarlo de forma intensiva, revisa los términos de cada sitio.

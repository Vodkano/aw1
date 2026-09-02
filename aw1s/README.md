# aw1s — prototipo de codigo

Paquete Python aislado, sin dependencia de `backend/src/aw1` (AW1 v3) todavia
— ver el punto pendiente sobre la relacion entre ambos sistemas en
`docs/aw1s/documentacion/arquitectura.md#8`. La spec completa vive en
`docs/aw1s/`; este directorio es la implementacion.

## Instalar y correr tests

```bash
cd aw1s
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

## Que hay implementado

- `src/aw1s/atajo_semantico/` — el fast-path pre-Inteligencia (ver
  `docs/aw1s/documentacion/arquitectura.md#20-atajo-semantico-fast-path`),
  calibracion v1 completa: filtro de longitud, match exacto normalizado,
  similitud coseno (umbrales 0.93/0.85), regla de sesion activa.
  - `normalizar.py` — pasos 0 y 1, deterministas, sin vectorizar.
  - `embeddings.py` — `EmbeddingsProvider` (protocolo) + `OllamaEmbeddings`
    (implementacion real via `/api/embeddings`, modelo `nomic-embed-text`
    por defecto — decision propia no documentada en la spec, ver docstring
    del archivo).
  - `indice.py` — `IndiceFrasesConocidas` (protocolo) + `IndiceEnMemoria`
    (implementacion de referencia) + `indice_semilla()` con el set inicial
    de saludos/despedidas/agradecimientos en espanol.
  - `atajo.py` — `evaluar_atajo()`, la orquestacion de los tres pasos.

Nada de esto esta conectado a un servidor HTTP ni a Postgres todavia — son
funciones puras + un cliente de Ollama, pensadas para poder probarse y
usarse desde cualquier lado (incluida la version futura con Postgres/
pgvector en vez de `IndiceEnMemoria`, sin tocar `atajo.py`).

## Que falta (siguientes pasos, en orden sugerido)

1. Backend real del indice sobre Postgres+pgvector (implementar
   `IndiceFrasesConocidas` con una tabla, en vez de `IndiceEnMemoria`).
2. Modelo de datos base (Usuario, Sesion, Interaccion, Evento, Memoria,
   Embedding, Contexto) — bajar el modelo conceptual a schema real.
3. Inteligencia: integrar el prompt ya escrito en
   `docs/aw1s/prompts/inteligencia.md` con un cliente LLM.
4. Contexto: recuperacion desde el modelo de datos del punto 2.
5. Procesamiento principal + Humanizacion.
6. Recien ahi: decidir la relacion con AW1 v3 (punto pendiente #4 de la
   documentacion) con datos reales de por medio, no en abstracto.

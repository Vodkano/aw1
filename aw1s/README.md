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

Los tests corren sin Postgres ni Ollama reales (todo con Fakes, ver
`tests/fakes.py`). Para probar `almacenamiento/postgres.py` contra una base
real (sin Docker -alcanza con el paquete de Postgres del sistema):

```bash
sudo apt-get install -y postgresql-16-pgvector
sudo service postgresql start
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'aw1s';"
sudo -u postgres createdb aw1s
DATABASE_URL=postgresql://postgres:aw1s@127.0.0.1:5432/aw1s \
    .venv/bin/python -m scripts.verificar_schema
```

**Ya se corrio y quedo verificado** (3 veces seguidas sobre la misma base,
para confirmar que es repetible). Aparecieron y se arreglaron dos bugs
reales que la version anterior (nunca probada) tenia:

1. `RepositorioPostgres.crear()` intentaba registrar el tipo `vector` en
   cada conexion nueva, pero en una base recien creada esa extension
   todavia no existe -se creaba recien al cargar el schema. Se separo en
   dos pasos obligatorios: `asegurar_schema()` primero (DDL puro, no
   necesita el tipo `vector`), `crear()` despues.
2. La limpieza del script de verificacion solo borraba la fila de
   `usuarios`, pero `sesiones.usuario_id` y `eventos.interaccion_id` son
   `ON DELETE SET NULL` a proposito (no perder historial si se borra un
   usuario) -asi que quedaban sesiones/memorias/embeddings huerfanos.
   Corriendo el script dos veces seguidas, dos memorias con el mismo
   vector de prueba quedaban empatadas en similitud y
   `buscar_memorias_similares` podia devolver la vieja en vez de la
   nueva. Arreglado borrando explicitamente evento + sesion + usuario
   (la sesion cascadea el resto).

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
- `src/aw1s/db/schema.sql` — el modelo de datos conceptual
  (`docs/aw1s/documentacion/arquitectura.md#3`) bajado a tablas Postgres +
  pgvector. Independiente del schema de AW1 v3.
- `src/aw1s/almacenamiento/` — la capa de persistencia sobre ese schema.
  - `modelos.py` — un dataclass por entidad.
  - `protocolo.py` — `RepositorioAlmacenamiento`, la interfaz. Cubre tanto
    lo que persiste Inteligencia (Usuario/Sesion/Interaccion/Evento, ver
    `docs/aw1s/planos/0.1.0.3`) como lo que persiste Memoria
    (Memoria/Embedding) — es una sola capa de almacenamiento fisico para
    dos responsabilidades distintas de la arquitectura.
  - `postgres.py` — `RepositorioPostgres`, implementacion real via
    asyncpg + pgvector-python. **No probada contra Postgres real todavia**,
    ver seccion de arriba.
- `tests/fakes.py` — `RepositorioEnMemoria`, el mismo protocolo sin
  Postgres, para probar Inteligencia/Contexto/Memoria mas adelante sin
  depender de una base real.

Nada de esto esta conectado a un servidor HTTP todavia — son funciones
puras + clientes de Ollama/Postgres, pensadas para poder probarse y usarse
desde cualquier lado.

## Que falta (siguientes pasos, en orden sugerido)

1. **Correr `scripts/verificar_schema.py` contra un Postgres+pgvector
   real** para confirmar que el SQL de `almacenamiento/postgres.py` esta
   bien — es lo unico de lo ya escrito que sigue sin verificar.
2. Backend real del indice del Atajo semantico sobre Postgres (implementar
   `IndiceFrasesConocidas` con una tabla, en vez de `IndiceEnMemoria`) —
   ahora que ya existe la infraestructura de Postgres+pgvector, es un
   paso chico.
3. Inteligencia: integrar el prompt ya escrito en
   `docs/aw1s/prompts/inteligencia.md` con un cliente LLM, escribiendo
   sobre `RepositorioAlmacenamiento` (ya deberia alcanzar tal cual esta).
4. Contexto: recuperacion desde `RepositorioAlmacenamiento`.
5. Procesamiento principal + Humanizacion.
6. Recien ahi: decidir la relacion con AW1 v3 (punto pendiente #4 de la
   documentacion) con datos reales de por medio, no en abstracto.

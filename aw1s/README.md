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
    asyncpg + pgvector-python. **Verificada contra Postgres+pgvector real**
    (ver seccion de arriba) -- dos bugs reales encontrados y arreglados.
- `tests/fakes.py` — `RepositorioEnMemoria`, el mismo protocolo sin
  Postgres, y `FakeClienteLLM`, para probar Inteligencia/Contexto/Memoria
  sin depender de una base ni de un modelo real.
- `src/aw1s/inteligencia/` — primer componente generativo con codigo real.
  - `prompt.py` — copia literal del system prompt de
    `docs/aw1s/prompts/inteligencia.md` (los dos archivos hay que
    mantenerlos sincronizados a mano, no hay generador).
  - `cliente_llm.py` — `ClienteLLM` (protocolo) + `OllamaChatClient`
    (`/api/chat` con `format: "json"`, modelo `mistral` por defecto -mismo
    default que ya usa AW1 v3). **No se probo contra un Ollama real**
    (bloqueado el acceso a ollama.com en el entorno donde se escribio, sin
    paquete apt como alternativa) -se valido en cambio el contrato HTTP
    real de Ollama con mocks (`tests/test_cliente_llm.py`), no es lo mismo
    que probarlo en vivo.
  - `modelos.py` — `DecisionInteligencia` y afines, tipados desde el JSON
    del prompt.
  - `inteligencia.py` — `analizar()`: persiste Usuario/Sesion/Interaccion/
    Evento primero (plano 0.1.0.3, efecto de lado deterministico, no lo
    decide el LLM), arma el historial breve, llama al modelo, valida la
    forma de la respuesta. Si el LLM devuelve algo mal formado, la
    interaccion ya persistida no se pierde -se propaga
    `DecisionInvalidaError` para que el llamador decida como seguir.
- `src/aw1s/contexto/` — ejecuta las `Necesidad` que decidio Inteligencia,
  sin decidir nada por su cuenta (ver
  `docs/aw1s/documentacion/arquitectura.md#22-contexto`).
  - `contexto.py` — `construir_contexto()`: por cada necesidad, segun
    `fuente` (`postgres`/`pgvector`/`ambas`) y las banderas
    `usa_historial_sesion`/`usa_memoria_semantica`, trae historial de
    sesion (`repositorio.interacciones_recientes`) y/o memoria semantica
    (vectoriza `terminos_busqueda_semantica` con el mismo
    `EmbeddingsProvider` del Atajo semantico, despues
    `repositorio.buscar_memorias_similares`). Persiste el resultado via
    `repositorio.guardar_contexto`. **Verificado contra Postgres real**
    (incluida la columna JSONB con contenido anidado, no solo el caso
    chico de `verificar_schema.py`) ademas de los tests con Fakes.
  - `modelos.py` — `ContextoArmado` / `ResultadoBusqueda`.

Nada de esto esta conectado a un servidor HTTP todavia — son funciones
puras + clientes de Ollama/Postgres, pensadas para poder probarse y usarse
desde cualquier lado.

## Que falta (siguientes pasos, en orden sugerido)

1. **Probar `inteligencia/cliente_llm.py` contra un Ollama real** en
   cuanto haya un entorno con acceso a internet para instalarlo -es lo
   unico de lo ya escrito que sigue sin verificacion en vivo (la logica
   de parseo/orquestacion si esta probada, contra mocks del contrato HTTP
   y contra `RepositorioEnMemoria`).
2. Backend real del indice del Atajo semantico sobre Postgres (implementar
   `IndiceFrasesConocidas` con una tabla, en vez de `IndiceEnMemoria`) —
   ya existe la infraestructura de Postgres+pgvector, es un paso chico.
3. Procesamiento principal + Humanizacion.
4. El ciclo completo: si `listo_para_procesar` es `false`, volver a llamar
   a Inteligencia con `contexto_recuperado` (el `ContextoArmado` que ya
   arma este modulo) -el limite de iteraciones para evitar un loop
   infinito sigue sin definir (ver nota en
   `docs/aw1s/prompts/inteligencia.md`).
5. Recien ahi: decidir la relacion con AW1 v3 (punto pendiente #4 de la
   documentacion) con datos reales de por medio, no en abstracto.

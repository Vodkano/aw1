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
- `src/aw1s/llm/` — cliente Ollama compartido (`ollama.py`), usado por
  Inteligencia y Procesamiento principal. Vive en un paquete neutral para
  que ninguno de los dos dependa del paquete del otro: cada componente
  declara su propio protocolo angosto (`GeneradorJSON` / `GeneradorTexto`)
  y `OllamaChatClient` satisface los dos por duck typing. Modelo por
  defecto `mistral` (mismo default que ya usa AW1 v3). **No se probo
  contra un Ollama real** (bloqueado el acceso a ollama.com en el entorno
  donde se escribio, sin paquete apt como alternativa) -se valido el
  contrato HTTP real con mocks (`tests/test_llm_ollama.py`), no es lo
  mismo que probarlo en vivo.
- `src/aw1s/inteligencia/` — primer componente generativo con codigo real.
  - `prompt.py` — copia literal del system prompt de
    `docs/aw1s/prompts/inteligencia.md` (los dos archivos hay que
    mantenerlos sincronizados a mano, no hay generador).
  - `cliente_llm.py` — re-exporta `aw1s.llm.ollama` (`ClienteLLM` es un
    alias de `GeneradorJSON`, el protocolo angosto que le corresponde a
    este componente).
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
- `src/aw1s/procesamiento_principal/` — resuelve el problema con SOLO la
  consulta y el `ContextoArmado` (nunca memoria cruda).
  - `prompt.py` — system prompt propio, **no formaba parte de la spec
    original** (a diferencia de Inteligencia/Humanizacion) -se agrego
    durante la implementacion y se documento en
    `docs/aw1s/prompts/procesamiento_principal.md`.
  - `procesamiento.py` — `resolver()`: formatea la consulta + el contexto
    como texto legible (no el JSON crudo), llama al modelo via
    `GeneradorTexto`, devuelve el resultado tal cual -no persiste nada,
    es stateless. Admite `instrucciones` opcionales que se suman al
    prompt base (pensado para personalidad/alcance por agente mas
    adelante, mismo patron que ya usa AW1 v3 por bot de Telegram).
  - `modelos.py` — `ResultadoProcesamiento`.
- `src/aw1s/humanizacion/` — convierte el resultado interno en la
  respuesta final, sin cambiar la decision (nunca resuelve nada de nuevo).
  Mismo patron que Procesamiento principal: stateless, `GeneradorTexto`,
  prompt ya escrito en `docs/aw1s/prompts/humanizacion.md` (este si
  formaba parte de la spec original, copiado literal en
  `humanizacion/prompt.py`).
  - `humanizacion.py` — `humanizar()`: recibe el resultado interno + la
    consulta original + historial breve opcional + canal opcional
    (chat web, Telegram, etc. -por si cambia el formato esperado).
  - `modelos.py` — `ResultadoHumanizacion`.
- `src/aw1s/entidad/` — el orquestador: encadena los 5 componentes de
  arriba en el orden que describe
  `docs/aw1s/documentacion/arquitectura.md#4`.
  - `entidad.py` — `procesar_mensaje()`: Atajo semantico (corto-circuito
    sin LLM si hay match) → Inteligencia → ciclo Contexto/reevaluar → 
    Procesamiento principal → Humanizacion. **No incluye Memoria** -sin
    regla definida todavia de que se conserva como memoria semantica, ver
    "Que falta" abajo. Dos decisiones propias documentadas en el
    docstring del archivo: `sesion_activa` para el Atajo se aproxima
    como "se paso un `sesion_id`", y `limite_iteraciones` (tope duro del
    ciclo, la spec pide uno pero no da numero) por defecto es 3.
  - **Verificado contra Postgres real**: un ciclo de 2 rondas deja
    exactamente 1 interaccion y 1 fila de contexto (no una por ronda) —
    dos bugs reales que aparecieron recien al armar este orquestador y ya
    estan arreglados (`inteligencia.reevaluar()` no persiste una
    interaccion nueva; `contexto.construir_contexto(persistir=False)`
    para las rondas intermedias). Ver historial de commits para el
    detalle de cada uno.
  - `modelos.py` — `ResultadoEntidad`.

Nada de esto esta conectado a un servidor HTTP todavia — son funciones
puras + clientes de Ollama/Postgres, pensadas para poder probarse y usarse
desde cualquier lado.

## Que falta (siguientes pasos, en orden sugerido)

1. **Probar `llm/ollama.py` contra un Ollama real** en cuanto haya un
   entorno con acceso a internet para instalarlo -es lo unico de lo ya
   escrito que sigue sin verificacion en vivo (la logica de
   parseo/orquestacion si esta probada, contra mocks del contrato HTTP
   y contra `RepositorioEnMemoria`).
2. Backend real del indice del Atajo semantico sobre Postgres (implementar
   `IndiceFrasesConocidas` con una tabla, en vez de `IndiceEnMemoria`) —
   ya existe la infraestructura de Postgres+pgvector, es un paso chico.
3. El componente Memoria en si: decidir que interaccion se conserva como
   memoria semantica y generar su embedding -sigue sin regla definida
   (ver punto pendiente en `documentacion/arquitectura.md#8`). Recien ahi
   el orquestador queda completo de punta a punta.
4. Exponerlo como algo llamable de verdad (HTTP, o directo desde un bot
   de Telegram) -hoy `procesar_mensaje()` es una funcion Python que hay
   que invocar a mano, no hay servidor.
5. Recien ahi: decidir la relacion con AW1 v3 (punto pendiente #4 de la
   documentacion) con datos reales de por medio, no en abstracto.

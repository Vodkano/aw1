# Instrucciones para GitHub Copilot en este repo

Este archivo lo lee Copilot Chat automaticamente en cada request dentro de
este workspace en VSCode. No lo pegues a mano — ya esta activo.

## Antes de escribir codigo, siempre

1. **Restablece el problema con tus propias palabras** antes de tocar
   nada: que se pide, que archivos toca, que se rompe si te equivocas.
   Si el pedido es ambiguo, decilo explicitamente en vez de asumir la
   interpretacion mas facil de programar.
2. **Lee antes de escribir**: `CLAUDE.md` (raiz del repo) tiene las
   convenciones y trampas ya conocidas de este proyecto — no repitas
   errores ya resueltos ahi. Para cualquier tarea relacionada con AW1S
   (ver mas abajo), lee `docs/aw1s/documentacion/arquitectura.md` completo
   y el archivo mas reciente en `docs/aw1s/planos/` antes de proponer
   codigo — no soluciones "razonables en general", soluciones consistentes
   con lo que esos documentos ya definieron.
3. **No resuelvas de tu cuenta un punto que la documentacion marca como
   "pendiente" o "punto abierto"**. Devolveme la pregunta en vez de asumir
   un valor (umbral, regla de negocio, decision de privacidad) — esas
   decisiones son del usuario, no tuyas ni mias.
4. **Explica el porque antes del que**: si vas a proponer un diseno,
   primero un parrafo corto de razonamiento (que alternativas evaluaste,
   por que esta y no otra), despues el codigo. No generes codigo de
   entrada sin ese paso — es lo que "pensar mas" significa aca: no
   autocompletar el patron mas obvio, sino verificar que encaja con la
   arquitectura ya definida antes de escribirlo.

## Que es este repo

AW1: asistente personal de un solo usuario/administrador. Chat (Ollama
local, GPT opcional), comparador de precios que navega tiendas reales con
Chromium, y una plataforma de bots de Telegram (cada agente = prompt +
personalidad). Corre en un unico servidor EC2, sin Kubernetes, sin cola de
mensajes, sin CI/CD real — deploy es `git push` + SSM + `docker compose`.

Stack: FastAPI + Python (backend/), React + TS + Vite + Tailwind v4
(frontend/), SQLite en local / Postgres en produccion con dos repositorios
de mismo contrato (`db/repository.py` y `db/postgres_repository.py`).

## Reglas que no se relajan en ningun archivo de este repo

- **Schema**: `db/schema.sql` y `db/schema_postgres.sql` tienen que quedar
  identicos en estructura — cualquier tabla o metodo nuevo va en los dos.
  No existe mecanismo de migracion (`ALTER TABLE`): agregar una columna a
  una tabla que ya existe en produccion necesita migracion escrita a mano,
  nunca alcanza con editar el `CREATE TABLE`. Antes de tocar cualquiera de
  los dos archivos, correr la verificacion de comentarios que describe
  `CLAUDE.md` (un `;` dentro de un `--` comentario ya trunco un CREATE
  TABLE en produccion una vez).
- **Tests**: un "Fake" liviano por dependencia externa (ver
  `tests/fakes.py`), no mocks pesados. `patch("httpx.AsyncClient.post",
  new=AsyncMock(...))` para simular APIs externas — si se parchea con una
  funcion `async def` plana en vez de `AsyncMock`, hay que agregarle
  `self` como primer parametro.
- **Sandbox de herramientas generadas** (`core/sandbox.py`,
  `core/tool_designer.py`): las cinco invariantes de seguridad ahi
  (aprobacion humana obligatoria, `env={}`, sin `httpx`/`socket`/`os`/
  `subprocess` directo, todo trafico de red pasa por `core/netguard.py`)
  no se relajan sin discutirlo explicitamente con el usuario primero.
- **Sin abstracciones prematuras**: no agregues capas, flags de feature ni
  manejo de errores para casos que no pueden pasar. Tres lineas parecidas
  es mejor que una abstraccion prematura.
- **Comentarios**: por defecto ninguno. Solo si explican un porque
  no-obvio (una restriccion oculta, un workaround de un bug puntual) —
  nunca que hace el codigo, para eso estan los nombres.

## AW1S — evolucion "pesada"/MVP

Diseno en `docs/aw1s/`: `documentacion/arquitectura.md` es la spec de
referencia, `planos/` el historial de cada documento/decision en el orden
en que se tomo, `prompts/` los system prompts ya definidos para las capas
generativas.

Codigo en `aw1s/` (raiz del repo, paquete Python propio, **no** dentro de
`backend/`) — leer `aw1s/README.md` antes de tocar nada ahi: que esta
implementado, que sigue, como correr sus tests (`.venv` propio, no el de
`backend/`). Implementado hasta ahora:
- **Atajo semantico** (`aw1s/src/aw1s/atajo_semantico/`) — calibracion v1
  completa, verificada con tests. Backend real del indice sobre Postgres
  (`IndiceFrasesConocidasPostgres`, tabla `frases_conocidas`) ademas de
  `IndiceEnMemoria`. Esa tabla NO lleva indice `ivfflat` -bug real
  encontrado al probarla: con pocas filas (es chica y curada a mano a
  proposito) un indice aproximado puede devolver cero resultados para un
  vector fuera de la distribucion de los datos. No agregarle un indice
  vectorial sin volver a leer el comentario en `db/schema.sql`.
- **Schema + persistencia** (`aw1s/src/aw1s/db/schema.sql` +
  `aw1s/src/aw1s/almacenamiento/`) — Postgres+pgvector real via asyncpg,
  **ya verificado** contra una base real (`aw1s/scripts/verificar_schema.py`,
  ver README para el procedimiento sin Docker). Aparecieron y se
  arreglaron dos bugs reales al probarlo -no asumir que un cambio nuevo
  aca esta bien solo porque los tests con Fakes pasan: correr ese script
  de nuevo despues de tocar `almacenamiento/postgres.py` o `db/schema.sql`.
- **`aw1s/src/aw1s/llm/ollama.py`** — cliente Ollama compartido entre
  Inteligencia y Procesamiento principal (protocolos angostos
  `GeneradorJSON`/`GeneradorTexto`, duck typing, sin que ninguno de los
  dos paquetes dependa del otro). Validado solo contra mocks del contrato
  HTTP, no contra un Ollama real (bloqueado el acceso a ollama.com en el
  entorno donde se escribio) -si hay acceso a internet disponible,
  correrlo contra un Ollama real es el paso pendiente antes de confiar
  del todo en este archivo. Nunca agregar un cliente Ollama nuevo en otro
  lado del paquete: todo lo que hable con Ollama pasa por aca.
- **Inteligencia** (`aw1s/src/aw1s/inteligencia/`) — persistencia +
  llamada al LLM (prompt en `docs/aw1s/prompts/inteligencia.md`, copiado
  literal en `inteligencia/prompt.py` -mantener los dos sincronizados a
  mano).
- **Contexto** (`aw1s/src/aw1s/contexto/`) — ejecuta las `Necesidad` que
  arma Inteligencia (no decide nada por su cuenta, ver
  arquitectura.md#22-contexto), persiste el resultado. **Verificado**
  contra Postgres real (incluida la columna JSONB con contenido anidado).
- **Procesamiento principal** (`aw1s/src/aw1s/procesamiento_principal/`)
  — resuelve con SOLO la consulta + el `ContextoArmado` (nunca memoria
  cruda). Stateless, no persiste nada. Prompt propio en
  `docs/aw1s/prompts/procesamiento_principal.md` (no formaba parte de la
  spec original -se agrego durante la implementacion).
- **Humanizacion** (`aw1s/src/aw1s/humanizacion/`) — convierte el
  resultado interno en la respuesta final, sin cambiar la decision.
  Stateless, mismo patron que Procesamiento principal. Prompt ya escrito
  en `docs/aw1s/prompts/humanizacion.md` (este si formaba parte de la
  spec original).
- **Entidad / orquestador** (`aw1s/src/aw1s/entidad/`) — `procesar_mensaje()`
  encadena los 5 componentes de arriba (Atajo semantico → Inteligencia →
  ciclo Contexto/reevaluar → Procesamiento principal → Humanizacion).
  **No incluye Memoria** -sin regla definida, ver
  `documentacion/arquitectura.md#8`. **Verificado contra Postgres real**
  (un ciclo de N rondas deja 1 interaccion y 1 contexto, no uno por
  ronda). Si se toca esto: `inteligencia.reevaluar()` (no
  `inteligencia.analizar()`) es la funcion correcta para las rondas
  intermedias del ciclo -usar `analizar()` de nuevo ahi duplicaria la
  interaccion persistida (bug real que ya paso una vez). Mismo cuidado
  con `contexto.construir_contexto(persistir=False)` en rondas
  intermedias, `persistir=True` (default) solo en la ronda final.

Puntos que Copilot tiene que respetar si se empieza a implementar algo de
esto:

- Es un sistema separado del AW1 actual todavia — la relacion entre ambos
  (reemplazo, paralelo, AW1 como "Procesamiento principal" de AW1S) es
  explicitamente un punto pendiente. No asumas que se integra con
  `chat/service.py` sin que se haya decidido.
- Separacion estricta de responsabilidades entre componentes (Atajo
  semantico, Inteligencia, Contexto, Procesamiento principal,
  Humanizacion, Memoria) — no fusiones capas para simplificar el codigo.
  Contexto no decide que buscar, solo ejecuta lo que decidio Inteligencia;
  Humanizacion no cambia el razonamiento, solo la forma.
- Memoria: PostgreSQL es la unica fuente de verdad, pgvector vive DENTRO
  de Postgres (nunca una base vectorial separada), no todo se vectoriza.
- El modelo de datos de `documentacion/arquitectura.md#3` es conceptual,
  no un schema SQL — no lo confundas ni lo mezcles con
  `backend/src/aw1/db/schema.sql`, que es el sistema real en produccion.
- El Atajo semantico ya tiene calibracion v1 definida (filtro de
  longitud → match exacto → similitud coseno con umbrales 0.93/0.85) —
  no reinventes esos numeros, estan en
  `docs/aw1s/planos/0.1.0.2-atajo-semantico.md`.

## Cuando no estes seguro

Preguntá en vez de generar codigo especulativo — este proyecto tiene un
historial de tener que deshacer trabajo por asumir de mas (ver
"El usuario" en `CLAUDE.md`: prefiere que se le pregunte con opciones
concretas cuando la decision es cara de revertir, en vez de que se asuma).

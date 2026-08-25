# AW1 v3 -- guia para quien retome este repo

Este archivo es para otro modelo/sesion que trabaje aca despues -no para el
usuario. Objetivo: que no repita errores ya resueltos ni tenga que
re-descubrir decisiones ya tomadas. `README.md` y `docs/ARQUITECTURA.md`
documentan el comparador de precios en detalle; esto cubre lo que falta,
sobre todo la plataforma de bots de Telegram (mas nueva) y como trabajar
con el usuario.

## Que es esto

Un asistente personal de un solo usuario/administrador: chat (Ollama local,
GPT opcional/automatico segun la tarea), comparador de precios que navega
tiendas reales con Chromium, y una plataforma de agentes de IA para bots de
Telegram (cada agente = prompt + personalidad, puede atender varios bots).
Todo corre en **un solo servidor EC2**, sin Kubernetes, sin cola de
mensajes, sin CI/CD -desplegar es `git push` + SSM + `docker compose up
--build`.

## Mapa rapido

- `backend/src/aw1/` -FastAPI. `chat/service.py` es el corazon del chat
  (ruteo Ollama/GPT, tool-calling, streaming). `telegram/orchestrator.py`
  es el equivalente para los bots. `core/telegram_store.py` es la "capa de
  servicio" de todo lo relacionado a agentes de Telegram (cache en memoria
  + validaciones de negocio), no solo el repositorio.
- `backend/src/aw1/db/` -**dos** repositorios con el mismo contrato:
  `repository.py` (SQLite/aiosqlite, desarrollo local) y
  `postgres_repository.py` (Postgres/asyncpg, produccion). `schema.sql` y
  `schema_postgres.sql` tienen que quedar identicos en estructura -cada
  tabla nueva va en los dos, cada metodo nuevo va en los dos repos con la
  misma firma.
- `frontend/src/` -React + TS + Vite + Tailwind v4 (tokens CSS-first en
  `index.css`, tema claro/oscuro con clase `.dark`). Vistas privadas
  (`agents`, `admin`, `autoextension`) piden una password aparte
  (`X-Admin-Password`) ademas del token general -ver `PasswordGate.tsx`.

## Antes de tocar `db/schema.sql` o `schema_postgres.sql`

**Incidente real de produccion**: un `;` dentro de un comentario `-- ...`
trunco un `CREATE TABLE` a mitad, porque el loader parte el archivo por
`;` de forma ingenua. Ya esta arreglado (se filtran las lineas de
comentario antes de partir), pero antes de cualquier deploy que toque
schema, correr esta verificacion:

```bash
python3 -c "
for path in ['backend/src/aw1/db/schema.sql', 'backend/src/aw1/db/schema_postgres.sql']:
    raw = open(path).read()
    without_comments = '\n'.join(l for l in raw.splitlines() if not l.strip().startswith('--'))
    statements = [s.strip() for s in without_comments.split(';') if s.strip()]
    bad = [s[:60] for s in statements if not s.upper().startswith(('CREATE', 'PRAGMA'))]
    print(path, 'count:', len(statements), 'raro (deberia ser []):', bad)
"
```

**Tambien importante**: no existe ningun mecanismo de migracion
(`ALTER TABLE`) en este repo -todo el schema se crea con
`CREATE TABLE IF NOT EXISTS`, que no le agrega columnas a una tabla que ya
existe en produccion. Si hace falta agregarle una columna a una tabla que
ya esta viva (no una tabla nueva), hay que escribir la migracion a mano
(ver `Flags` en el historial de PRs del sistema de agentes
auto-extensibles para un ejemplo de este razonamiento) -nunca asumir que
editar el `CREATE TABLE` alcanza.

## Tests y verificacion

```bash
cd backend && pytest -q -k "not browser and not pipeline"   # rapido, sin Chromium
cd frontend && npx tsc --noEmit && npm run build
```

Patrones a seguir (ya establecidos, no reinventar):
- Un "Fake" liviano por dependencia externa (`FakeOllama`, `FakeTelegramClient`,
  `FakeChatService`) en vez de mocks pesados -ver `tests/fakes.py` y el
  inicio de `tests/test_telegram.py`.
- `patch("httpx.AsyncClient.post", new=AsyncMock(...))` para simular
  respuestas de OpenAI/Telegram. Cuidado: si se parchea con una funcion
  `async def` plana en vez de un `AsyncMock`, hay que agregarle `self`
  como primer parametro (los metodos son descriptores, `self` se bindea
  solo al acceder via instancia) -`AsyncMock` no tiene ese problema.
- `netguard._allow_private` es un flag global de proceso que las fixtures
  compartidas (`settings`/`repo`) dejan en `True` en casi todos los tests
  -una asercion de "esto se rechaza por SSRF" no es confiable en un
  archivo de tests generico; esa cobertura va en un archivo aislado
  (ver `test_agent_apis.py`, `test_sandbox.py`).

## Deploy

```bash
git push origin main
# SSM en la instancia EC2 (i-084f5d23ba86d844f, us-east-2):
aws ssm send-command --instance-ids i-084f5d23ba86d844f --document-name AWS-RunShellScript \
  --parameters '{"commands":["cd /opt/aw1 && git fetch && git reset --hard origin/main"]}' --region us-east-2
aws ssm send-command --instance-ids i-084f5d23ba86d844f --document-name AWS-RunShellScript \
  --parameters '{"commands":["cd /opt/aw1 && docker compose up -d --build aw1"]}' --region us-east-2
```

Verificar salud despues (via SSM, `curl 127.0.0.1:8000/api/status` dentro
de la instancia): el dominio publico no siempre resuelve directo desde un
sandbox de desarrollo, usar `curl --resolve app.aw1s.online:443:<IP> https://...`
si hace falta confirmar desde afuera. La password de admin vive en la
variable de entorno `AW1_ADMIN_PASSWORD` del `.env` de la instancia -no
esta en este repo, pedirsela al usuario o leerla de ahi si hace falta para
verificar.

## El usuario

Persona no-tecnica, escribe en espanol coloquial con errores de tipeo,
espera que el trabajo se haga de punta a punta solo (probar, desplegar,
confirmar) sin que se le pida permiso para cada paso chico. Prefiere
respuestas cortas y directas, sin narrar el proceso interno. Es
consciente del costo de las APIs de pago (eligio expresamente quedarse
solo con el modelo mas barato de GPT en vez de habilitar otros mas caros)
-nunca asumir un modelo/proveedor mas caro sin que lo pida.

Cuando un pedido es ambiguo Y la decision es cara de revertir o afecta
arquitectura (que se guarda donde, que herramienta reusar, que proveedor
externo usar), preguntar con opciones concretas (una por decision) en vez
de asumir. Cuando un pedido es grande y riesgoso -como el sistema descrito
abajo- cuestionarlo primero con el problema concreto explicado en
terminos que no-tecnicos entiendan (no solo jerga de ingenieria), y dejar
que decida con esa informacion.

## Sistema de agentes auto-extensibles (`core/sandbox.py`,
`core/tool_designer.py`, `core/code_agent.py`, tabla `generated_tools`)

Un agente de Telegram puede: (1) notar que le falta una capacidad y
anotarlo (`solicitar_nueva_capacidad`, un tool-call nativo mas, mismo
mecanismo que `generar_imagen`); (2) desde el panel "Auto-extension", un
humano puede convertir ese pedido en una herramienta generada por IA,
probarla en un sandbox aislado, y aprobarla para que quede disponible en
conversaciones reales.

Invariantes de seguridad que **no se deben relajar** sin discutirlo con el
usuario primero -son decisiones deliberadas, no casualidad:

1. Detectar un hueco nunca dispara la generacion de codigo sola -hace
   falta un click humano en el panel para cada paso (generar, probar,
   aprobar).
2. El Code Agent solo genera un archivo nuevo y autocontenido con una
   funcion `def run(input: dict) -> dict` -nunca un parche sobre archivos
   existentes del repositorio.
3. El codigo generado corre en un subproceso con: variables de entorno
   vacias (`env={}`, ninguna credencial real alcanzable, ni en la prueba
   ni ya activa), limites de CPU/memoria (`resource.setrlimit`, con
   fallback silencioso en macOS donde `RLIMIT_AS` puede no aplicarse -en
   Linux/produccion si aplica), y timeout de pared.
4. El codigo generado NUNCA importa `httpx`/`socket`/`os`/`subprocess`
   directo (bloqueado por `check_module_safety`, un chequeo AST que
   tambien bloquea el truco clasico de escape sin imports,
   `().__class__.__bases__[...].__subclasses__()`, via una lista de
   atributos dunder prohibidos). La unica forma de pedir datos de
   internet es la funcion `fetch()` que el runner le inyecta, que pasa
   por `core/netguard.py` -mismo chequeo anti-SSRF que ya protege las
   APIs que configura el admin, para que una herramienta generada no
   pueda golpear los otros contenedores del mismo servidor (Postgres,
   Ollama).
5. Ninguna herramienta llega a `ACTIVE` sin aprobacion humana explicita,
   sin importar que tan bien haya salido la prueba de sandbox -un LLM
   revisando codigo de otro LLM no es un limite de seguridad confiable en
   esta infraestructura (sin sandbox de nivel contenedor/VM real, sin
   socket de Docker montado, sin infraestructura de aislamiento dedicada).
6. Una herramienta ya aprobada sigue corriendo en el MISMO sandbox
   restringido en produccion -nunca gana mas privilegios al activarse.

Lo que se decidio explicitamente NO construir en esta pasada (documentado,
no descuidado): memoria episodica/procedural con scoring, dataset de
entrenamiento por refuerzo, un "Evolver" que propone mejoras del sistema
solo. No hay infraestructura de entrenamiento que los consuma, y los datos
crudos que necesitarian (pedidos de capacidad, uso de herramientas) ya
quedan guardados -nada se pierde si se quieren construir despues.

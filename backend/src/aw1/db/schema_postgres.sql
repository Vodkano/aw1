CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'local',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

-- Razonamiento interno del modelo. Se guarda para poder auditarlo y NUNCA
-- se devuelve por la API.
CREATE TABLE IF NOT EXISTS reasoning (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    input           TEXT NOT NULL,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reasoning_conv ON reasoning(conversation_id, id);

CREATE TABLE IF NOT EXISTS saved_items (
    id          BIGSERIAL PRIMARY KEY,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'local',
    kind        TEXT NOT NULL DEFAULT 'note',
    meta        TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_saved_created ON saved_items(id DESC);

CREATE TABLE IF NOT EXISTS searches (
    id          BIGSERIAL PRIMARY KEY,
    query       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_searches_created ON searches(id DESC);

CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

-- Panel admin: claves de proveedores (openai_api_key, groq_api_key,
-- ollama_host, llm_provider) editables en caliente, sin redeploy.
CREATE TABLE IF NOT EXISTS secrets (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Panel admin: claves de API emitidas para llamar esta API desde afuera
-- (ademas del AW1_API_TOKEN de entorno). Solo se guarda el hash.
CREATE TABLE IF NOT EXISTS api_keys (
    id          BIGSERIAL PRIMARY KEY,
    label       TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    key_preview TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Panel admin: agentes de Telegram. Un agente es el "cerebro" (prompt,
-- personalidad) -no es un bot en si, sino la logica que puede atender uno o
-- varios bots (ver telegram_tokens). Un agente puede tener muchos tokens,
-- y un token es de un solo agente. El id es un uuid generado en la app. DDL
-- identico al de schema.sql: nada aca necesita sintaxis especifica de
-- Postgres.
CREATE TABLE IF NOT EXISTS telegram_agents (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    system_prompt   TEXT NOT NULL DEFAULT '',
    -- Una de TELEGRAM_PERSONALITIES (llm/prompts.py), sorteada al crear el
    -- agente y fija desde entonces: le da variedad de "voz" a los agentes
    -- sin que el admin tenga que elegir una a mano.
    personality     TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Un token de bot de Telegram (BotFather), enganchado a exactamente un
-- agente. El id (no el token en si) es lo que aparece en la URL publica del
-- webhook (/api/telegram/webhook/{token_id}), igual que conversations.id.
CREATE TABLE IF NOT EXISTS telegram_tokens (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES telegram_agents(id) ON DELETE CASCADE,
    bot_token       TEXT NOT NULL,
    bot_token_hash  TEXT NOT NULL UNIQUE,
    bot_username    TEXT NOT NULL DEFAULT '',
    webhook_secret  TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telegram_tokens_agent ON telegram_tokens(agent_id);

-- Corte de conversacion: cuando un agente detecta mala intencion (abuso,
-- spam, intento de manipularlo) deja de gastar tokens en ese chat por un
-- tiempo -los mensajes que lleguen mientras dure el "mute" se responden con
-- un texto fijo, sin llamar al modelo. Por token (bot), no por agente: la
-- memoria/conversacion tambien es separada por bot, aunque compartan
-- personalidad. DDL identico al de schema.sql.
CREATE TABLE IF NOT EXISTS telegram_mutes (
    token_id     TEXT NOT NULL REFERENCES telegram_tokens(id) ON DELETE CASCADE,
    chat_id      TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    muted_until  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (token_id, chat_id)
);

-- Seguimiento de precio: un producto + N URLs (distintas tiendas) que un
-- bot de Telegram revisa periodicamente, avisando solo cuando cambia cual
-- es la oferta mas barata (precio o tienda distintos a la ultima vez). Por
-- token, no por agente -mismo motivo que telegram_mutes. DDL identico al de
-- schema.sql.
CREATE TABLE IF NOT EXISTS price_watches (
    id              TEXT PRIMARY KEY,
    token_id        TEXT NOT NULL REFERENCES telegram_tokens(id) ON DELETE CASCADE,
    chat_id         TEXT NOT NULL,
    product_label   TEXT NOT NULL,
    urls            TEXT NOT NULL,
    last_price_clp  REAL,
    last_best_url   TEXT,
    last_checked_at TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_watches_enabled ON price_watches(enabled);

-- Archivos que un agente conoce de memoria (menu, catalogo, lista de
-- precios). El texto ya viene extraido al subir el archivo (ver
-- core/file_extract.py) -se agrega siempre al prompt del agente, como
-- contexto fijo, no como busqueda dentro del documento. DDL identico al de
-- schema.sql.
CREATE TABLE IF NOT EXISTS telegram_agent_files (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL REFERENCES telegram_agents(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    content     TEXT NOT NULL,
    char_count  INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telegram_agent_files_agent ON telegram_agent_files(agent_id);

-- APIs externas que un agente puede invocar en vivo durante la
-- conversacion (ej. consultar stock real). El modelo decide cuando
-- llamarla via tool calling de OpenAI -las credenciales (headers) las
-- pone el admin al configurarla, nunca el usuario de Telegram. DDL
-- identico al de schema.sql.
CREATE TABLE IF NOT EXISTS telegram_agent_apis (
    id           TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL REFERENCES telegram_agents(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL,
    url          TEXT NOT NULL,
    method       TEXT NOT NULL DEFAULT 'GET',
    headers      TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telegram_agent_apis_agent ON telegram_agent_apis(agent_id);

-- Herramientas escritas por IA a partir de un hueco detectado en una
-- conversacion (ver chat/service.py, tool solicitar_nueva_capacidad).
-- status recorre PROPOSED -> GENERATING -> PENDING_APPROVAL -> ACTIVE o
-- REJECTED; se valida en Python (core/telegram_store.py), no con un CHECK,
-- para que este archivo y schema.sql queden identicos. Solo las ACTIVE se
-- ofrecen al modelo (ver TelegramStore.get_cached_token) y solo llegan
-- ahi con aprobacion humana explicita desde el panel admin -nunca
-- automatico.
CREATE TABLE IF NOT EXISTS generated_tools (
    id                      TEXT PRIMARY KEY,
    agent_id                TEXT NOT NULL REFERENCES telegram_agents(id) ON DELETE CASCADE,
    source_gap_reasoning_id BIGINT REFERENCES reasoning(id) ON DELETE SET NULL,
    name                    TEXT NOT NULL,
    description             TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'PROPOSED',
    spec                    TEXT NOT NULL DEFAULT '{}',
    code                    TEXT NOT NULL DEFAULT '',
    test_code               TEXT NOT NULL DEFAULT '',
    sandbox_result          TEXT NOT NULL DEFAULT '{}',
    reject_reason           TEXT NOT NULL DEFAULT '',
    call_count              INTEGER NOT NULL DEFAULT 0,
    last_called_at          TEXT,
    last_error              TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_generated_tools_agent ON generated_tools(agent_id);
CREATE INDEX IF NOT EXISTS idx_generated_tools_status ON generated_tools(status);

-- Traza de cada ejecucion que involucra IA (chat, agentes de Telegram,
-- comparador de precios). No reemplaza a `reasoning` -esa guarda el
-- contenido del razonamiento; esta guarda metadatos operacionales (que
-- modelo, cuanto tardo, cuanto costo estimado, con que resultado) para
-- poder ver costos y errores sin tener que leer logs. DDL identico al de
-- schema.sql.
CREATE TABLE IF NOT EXISTS execution_traces (
    id            BIGSERIAL PRIMARY KEY,
    trace_id      TEXT NOT NULL,
    source        TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    tools_called  TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'ok',
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    cost_estimate DOUBLE PRECISION NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT '',
    meta          TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_traces_trace ON execution_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_execution_traces_created ON execution_traces(id DESC);
CREATE INDEX IF NOT EXISTS idx_execution_traces_source ON execution_traces(source, id DESC);

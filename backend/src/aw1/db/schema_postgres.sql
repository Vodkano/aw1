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

-- AW1S -- schema base (Postgres + pgvector).
-- Baja a tablas el modelo conceptual de docs/aw1s/documentacion/arquitectura.md#3.
-- Independiente del schema de AW1 v3 (backend/src/aw1/db/) -- ver punto
-- pendiente sobre la relacion entre ambos sistemas.
--
-- Se carga pasando este archivo entero a una sola llamada de asyncpg
-- (protocolo simple, sin parametros): asyncpg soporta multiples sentencias
-- separadas por punto y coma en un solo execute() cuando no hay argumentos,
-- asi que no hace falta -ni conviene- partir este archivo a mano por ";"
-- (ver incidente documentado en CLAUDE.md sobre un loader que lo hacia
-- ingenuamente y trunco un CREATE TABLE por un ";" dentro de un comentario).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS usuarios (
    id                      BIGSERIAL PRIMARY KEY,
    identificador_externo   TEXT UNIQUE,
    creado_en               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sesiones (
    id                      BIGSERIAL PRIMARY KEY,
    usuario_id              BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    iniciada_en             TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_actividad_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS interacciones (
    id                  BIGSERIAL PRIMARY KEY,
    sesion_id           BIGINT NOT NULL REFERENCES sesiones(id) ON DELETE CASCADE,
    mensaje_usuario     TEXT NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip                  TEXT,
    creada_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS contextos (
    id                  BIGSERIAL PRIMARY KEY,
    interaccion_id      BIGINT NOT NULL REFERENCES interacciones(id) ON DELETE CASCADE,
    contenido           JSONB NOT NULL,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memorias (
    id                  BIGSERIAL PRIMARY KEY,
    interaccion_id      BIGINT NOT NULL REFERENCES interacciones(id) ON DELETE CASCADE,
    contenido           TEXT NOT NULL,
    creada_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 768 = dimension de salida de nomic-embed-text (el modelo por defecto de
-- aw1s.atajo_semantico.embeddings.OllamaEmbeddings). Si se cambia el
-- modelo de embeddings por uno de otra dimension, esta columna necesita
-- migrarse a mano -- no hay mecanismo de ALTER automatico, mismo criterio
-- que CLAUDE.md documenta para el schema de AW1 v3.
CREATE TABLE IF NOT EXISTS embeddings (
    id                  BIGSERIAL PRIMARY KEY,
    memoria_id          BIGINT NOT NULL UNIQUE REFERENCES memorias(id) ON DELETE CASCADE,
    vector              VECTOR(768) NOT NULL,
    modelo              TEXT NOT NULL,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eventos (
    id                  BIGSERIAL PRIMARY KEY,
    interaccion_id      BIGINT REFERENCES interacciones(id) ON DELETE SET NULL,
    tipo                TEXT NOT NULL,
    detalle             JSONB NOT NULL DEFAULT '{}'::jsonb,
    ocurrido_en         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sesiones_usuario ON sesiones (usuario_id);
CREATE INDEX IF NOT EXISTS idx_interacciones_sesion ON interacciones (sesion_id);
CREATE INDEX IF NOT EXISTS idx_contextos_interaccion ON contextos (interaccion_id);
CREATE INDEX IF NOT EXISTS idx_memorias_interaccion ON memorias (interaccion_id);
CREATE INDEX IF NOT EXISTS idx_eventos_interaccion ON eventos (interaccion_id);

-- ivfflat funciona con la tabla vacia pero recien queda bien calibrado
-- despues de tener datos y correr ANALYZE. En un volumen chico (prototipo)
-- esto no hace falta todavia -- ojo si esto crece en serio, ahi conviene
-- revisar el parametro "lists" y re-crear el indice.
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON embeddings USING ivfflat (vector vector_cosine_ops);

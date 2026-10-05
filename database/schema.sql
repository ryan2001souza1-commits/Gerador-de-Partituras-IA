-- ============================================================
-- Gerador de Partituras IA — Schema PostgreSQL (Neon) — ETAPA 4
--
-- Como aplicar (sem expor a connection string):
--   psql "$DATABASE_URL" -f database/schema.sql
--
-- Características:
-- * Idempotente e não destrutivo: somente CREATE ... IF NOT EXISTS.
-- * Nenhum DROP DATABASE / DROP TABLE neste arquivo.
-- * UUIDs via gen_random_uuid() (PostgreSQL 13+, suportado pelo Neon).
-- * Dados estruturados da futura IA em JSONB (score_data, result_data).
-- * Timestamps com fuso (TIMESTAMPTZ) e atualização automática de
--   updated_at via trigger.
-- ============================================================

-- ---------- Tabela: users (estrutura pronta; sem cadastro/login ainda) ----------
CREATE TABLE IF NOT EXISTS users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT        NOT NULL,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------- Tabela: scores (uma partitura; user_id opcional por enquanto) ----------
CREATE TABLE IF NOT EXISTS scores (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID         NULL REFERENCES users (id) ON DELETE CASCADE,
    title          VARCHAR(255) NOT NULL DEFAULT 'Sem título',
    description    TEXT         NOT NULL DEFAULT '',
    instrument     VARCHAR(50)  NOT NULL DEFAULT '',
    musical_key    VARCHAR(20)  NOT NULL DEFAULT '',
    tempo          VARCHAR(30)  NOT NULL DEFAULT '',
    time_signature VARCHAR(10)  NOT NULL DEFAULT '',
    difficulty     VARCHAR(30)  NOT NULL DEFAULT '',
    style          VARCHAR(50)  NOT NULL DEFAULT '',
    status         VARCHAR(30)  NOT NULL DEFAULT 'draft',
    score_data     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ---------- Tabela: score_generations (tentativas de geração da futura IA) ----------
CREATE TABLE IF NOT EXISTS score_generations (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    score_id      UUID         NOT NULL REFERENCES scores (id) ON DELETE CASCADE,
    prompt        TEXT         NOT NULL DEFAULT '',
    status        VARCHAR(30)  NOT NULL DEFAULT 'pending',
    provider      VARCHAR(50)  NOT NULL DEFAULT '',
    model         VARCHAR(100) NOT NULL DEFAULT '',
    result_data   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT         NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ  NULL
);

-- ---------- Índices ----------
-- users.email já possui índice via UNIQUE; os demais são explícitos.
CREATE INDEX IF NOT EXISTS idx_scores_user_id ON scores (user_id);
CREATE INDEX IF NOT EXISTS idx_scores_created_at ON scores (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_score_generations_score_id ON score_generations (score_id);
CREATE INDEX IF NOT EXISTS idx_score_generations_created_at ON score_generations (created_at DESC);

-- ---------- Trigger: mantém updated_at automaticamente ----------
CREATE OR REPLACE FUNCTION gpi_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION gpi_set_updated_at();

DROP TRIGGER IF EXISTS trg_scores_updated_at ON scores;
CREATE TRIGGER trg_scores_updated_at
    BEFORE UPDATE ON scores
    FOR EACH ROW EXECUTE FUNCTION gpi_set_updated_at();

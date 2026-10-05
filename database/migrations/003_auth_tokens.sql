-- ============================================================
-- Migração 003 — Tokens persistentes de autenticação (serverless)
--
-- Motivo: sessões PHP em arquivo não sobrevivem entre invocações
-- serverless da Vercel; o token persistente (cookie HttpOnly +
-- hash SHA-256 no banco, expiração absoluta) restaura o usuário.
--
-- Segurança e dados:
-- * SOMENTE aditiva: CREATE TABLE/INDEX IF NOT EXISTS.
-- * Nenhum DROP TABLE / DROP COLUMN / DELETE / ALTER TYPE.
-- * Armazena só o hash (nunca o token em claro); expiração
--   verificada em cada leitura (expires_at > NOW()).
-- * FK com ON DELETE CASCADE: ao excluir o usuário, os tokens vão juntos.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT        PRIMARY KEY,
    user_id    UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens (expires_at);

COMMIT;

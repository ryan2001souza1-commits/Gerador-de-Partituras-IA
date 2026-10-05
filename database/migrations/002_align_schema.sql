-- ============================================================
-- Migração 002 — Alinhar schema à arquitetura do projeto (ETAPA 4)
--
-- PLANO DE MIGRAÇÃO (aprovado para execução):
-- * Operações SOMENTE aditivas: ADD COLUMN IF NOT EXISTS.
-- * Nenhum DROP TABLE / DROP COLUMN / DELETE / ALTER TYPE.
-- * Todas as colunas novas têm NOT NULL + DEFAULT, portanto as
--   212 linhas existentes em scores recebem valores padrão sem
--   nenhuma perda ou reescrita de dados.
-- * Colunas legadas (scores.project_id, prompt_original, params)
--   são PRESERVADAS sem alteração.
-- * score_generations já está alinhada: nenhuma alteração.
-- * FKs, índices e triggers necessários já existem: nada a criar.
-- * Execução em transação única (BEGIN/COMMIT): qualquer erro
--   desfaz tudo automaticamente.
--
-- Divergências identificadas (atual → especificado):
-- * users: faltava "name".
-- * scores: faltavam "description, instrument, musical_key, tempo,
--   time_signature, difficulty, style, score_data".
-- * Tipos existentes mantidos (ex.: scores.title segue TEXT em vez
--   de VARCHAR(255)) para não reescrever dados.
-- ============================================================

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT 'Sem nome';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS instrument VARCHAR(50) NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS musical_key VARCHAR(20) NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS tempo VARCHAR(30) NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS time_signature VARCHAR(10) NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS difficulty VARCHAR(30) NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS style VARCHAR(50) NOT NULL DEFAULT '';

ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS score_data JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMIT;

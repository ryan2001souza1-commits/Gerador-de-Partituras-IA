-- ============================================================
-- Migração 004 — Fundação do pipeline de áudio (FASE 1)
--
-- SOMENTE aditiva e idempotente: CREATE TABLE/INDEX IF NOT EXISTS.
-- Nenhum DROP TABLE / DROP COLUMN / DELETE / ALTER TYPE.
-- Não toca em users, scores, score_generations ou auth_tokens.
-- Execução em transação única (BEGIN/COMMIT).
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS audio_sources (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    source_type      VARCHAR(20)  NOT NULL DEFAULT 'upload',
    original_filename VARCHAR(255) NOT NULL DEFAULT '',
    storage_path     TEXT         NOT NULL,
    mime_type        VARCHAR(100) NOT NULL DEFAULT '',
    file_size        BIGINT       NOT NULL DEFAULT 0,
    duration_seconds NUMERIC      NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'uploaded',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audio_sources_user_id ON audio_sources (user_id);
CREATE INDEX IF NOT EXISTS idx_audio_sources_status ON audio_sources (status);

DROP TRIGGER IF EXISTS trg_audio_sources_updated_at ON audio_sources;
CREATE TRIGGER trg_audio_sources_updated_at
    BEFORE UPDATE ON audio_sources
    FOR EACH ROW EXECUTE FUNCTION gpi_set_updated_at();

CREATE TABLE IF NOT EXISTS transcription_jobs (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    audio_source_id UUID         NOT NULL REFERENCES audio_sources (id) ON DELETE CASCADE,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    progress        INTEGER      NOT NULL DEFAULT 0,
    current_stage   VARCHAR(40)  NULL,
    error_code      VARCHAR(50)  NULL,
    error_message   TEXT         NULL,
    worker_job_id   VARCHAR(100) NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ  NULL,
    completed_at    TIMESTAMPTZ  NULL,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transcription_jobs_user_id ON transcription_jobs (user_id);
CREATE INDEX IF NOT EXISTS idx_transcription_jobs_status ON transcription_jobs (status);
CREATE INDEX IF NOT EXISTS idx_transcription_jobs_source_id ON transcription_jobs (audio_source_id);

DROP TRIGGER IF EXISTS trg_transcription_jobs_updated_at ON transcription_jobs;
CREATE TRIGGER trg_transcription_jobs_updated_at
    BEFORE UPDATE ON transcription_jobs
    FOR EACH ROW EXECUTE FUNCTION gpi_set_updated_at();

CREATE TABLE IF NOT EXISTS audio_analysis (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    audio_source_id  UUID         NOT NULL REFERENCES audio_sources (id) ON DELETE CASCADE,
    tempo_bpm        NUMERIC      NULL,
    key              VARCHAR(20)  NULL,
    time_signature   VARCHAR(10)  NULL,
    duration_seconds NUMERIC      NULL,
    sample_rate      INTEGER      NULL,
    channels         INTEGER      NULL,
    analysis_json    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_analysis_source ON audio_analysis (audio_source_id);

DROP TRIGGER IF EXISTS trg_audio_analysis_updated_at ON audio_analysis;
CREATE TRIGGER trg_audio_analysis_updated_at
    BEFORE UPDATE ON audio_analysis
    FOR EACH ROW EXECUTE FUNCTION gpi_set_updated_at();

COMMIT;

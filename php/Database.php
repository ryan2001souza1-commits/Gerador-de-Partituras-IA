<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Camada de acesso ao PostgreSQL (Neon) — ETAPA 4.
 *
 * - Conexão via variável de ambiente DATABASE_URL. Nenhuma connection
 *   string é fixada no código e nada sensível é impresso ou retornado.
 * - PDO com prepared statements reais (emulação desativada) e erros por
 *   exceção. Mensagens de erro expostas são sempre genéricas.
 * - As funções de escrita/leitura abaixo são a base para etapas futuras
 *   (usuários, partituras, gerações). Nada aqui é ligado a login ou IA.
 */

class Database
{
    /** @var PDO|null Conexão reutilizada durante a requisição. */
    private static $pdo = null;

    /**
     * Lê DATABASE_URL do ambiente (getenv, $_ENV ou $_SERVER).
     * Retorna null quando ausente ou vazia. Nunca imprime o valor.
     */
    public static function databaseUrl(): ?string
    {
        $candidates = [];
        $fromGetenv = getenv('DATABASE_URL');
        if (is_string($fromGetenv)) {
            $candidates[] = $fromGetenv;
        }
        if (isset($_ENV['DATABASE_URL']) && is_string($_ENV['DATABASE_URL'])) {
            $candidates[] = $_ENV['DATABASE_URL'];
        }
        if (isset($_SERVER['DATABASE_URL']) && is_string($_SERVER['DATABASE_URL'])) {
            $candidates[] = $_SERVER['DATABASE_URL'];
        }
        foreach ($candidates as $value) {
            if (trim($value) !== '') {
                return $value;
            }
        }
        return null;
    }

    /**
     * Descarta a conexão em cache (útil em testes e scripts longos).
     */
    public static function reset(): void
    {
        self::$pdo = null;
    }

    /**
     * Devolve a conexão PDO (cria na primeira chamada).
     *
     * @throws RuntimeException com mensagem genérica em qualquer falha.
     */
    public static function pdo(): PDO
    {
        if (self::$pdo instanceof PDO) {
            return self::$pdo;
        }
        if (!in_array('pgsql', PDO::getAvailableDrivers(), true)) {
            error_log('[gpi] driver pgsql indisponível.');
            throw new RuntimeException('Banco de dados indisponível.');
        }
        $url = self::databaseUrl();
        if ($url === null) {
            throw new RuntimeException('Banco de dados indisponível.');
        }
        $parts = parse_url($url);
        if (!is_array($parts)) {
            throw new RuntimeException('Banco de dados indisponível.');
        }
        $scheme = strtolower((string) ($parts['scheme'] ?? ''));
        if ($scheme !== 'postgres' && $scheme !== 'postgresql') {
            throw new RuntimeException('Banco de dados indisponível.');
        }
        $host = (string) ($parts['host'] ?? '');
        $dbname = ltrim((string) ($parts['path'] ?? ''), '/');
        if ($host === '' || $dbname === '') {
            throw new RuntimeException('Banco de dados indisponível.');
        }
        $port = isset($parts['port']) ? (int) $parts['port'] : 5432;
        $user = isset($parts['user']) ? rawurldecode((string) $parts['user']) : '';
        $pass = isset($parts['pass']) ? rawurldecode((string) $parts['pass']) : '';
        $sslmode = 'require'; // padrão seguro para o Neon
        if (isset($parts['query'])) {
            parse_str((string) $parts['query'], $query);
            if (isset($query['sslmode']) && is_string($query['sslmode']) && $query['sslmode'] !== '') {
                $sslmode = $query['sslmode'];
            }
        }
        $dsn = sprintf('pgsql:host=%s;port=%d;dbname=%s;sslmode=%s', $host, $port, $dbname, $sslmode);
        try {
            $pdo = new PDO($dsn, $user, $pass, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]);
        } catch (PDOException $e) {
            error_log('[gpi] falha de conexão PostgreSQL.');
            throw new RuntimeException('Banco de dados indisponível.');
        }
        self::$pdo = $pdo;
        return $pdo;
    }

    /**
     * Verifica a conexão com um SELECT 1. Nunca expõe detalhes.
     */
    public static function isAvailable(): bool
    {
        try {
            self::pdo()->query('SELECT 1');
            return true;
        } catch (Throwable $e) {
            return false;
        }
    }

    /* ---------------- Usuários (base para etapa futura; sem login ainda) ---------------- */

    public static function findUserByEmail(string $email): ?array
    {
        $stmt = self::pdo()->prepare('SELECT id, name, email, password_hash, created_at, updated_at FROM users WHERE email = :email LIMIT 1');
        $stmt->execute([':email' => $email]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function createUser(string $name, string $email, string $password): array
    {
        $hash = password_hash($password, PASSWORD_DEFAULT);
        try {
            $stmt = self::pdo()->prepare(
                'INSERT INTO users (name, email, password_hash) VALUES (:name, :email, :hash) ' .
                'RETURNING id, name, email, created_at, updated_at'
            );
            $stmt->execute([':name' => $name, ':email' => $email, ':hash' => $hash]);
            $row = $stmt->fetch();
        } catch (PDOException $e) {
            if ($e->getCode() === '23505') { // violação de UNIQUE (email)
                throw new RuntimeException('E-mail já cadastrado.');
            }
            error_log('[gpi] falha ao criar usuário.');
            throw new RuntimeException('Banco de dados indisponível.');
        }
        return $row === false ? [] : $row;
    }

    /* ---------------- Partituras (base para etapa futura) ---------------- */

    public static function createScore(?string $userId, array $fields): array
    {
        $stmt = self::pdo()->prepare(
            'INSERT INTO scores (user_id, title, description, instrument, musical_key, tempo, ' .
            'time_signature, difficulty, style, status, score_data) ' .
            'VALUES (:user_id, :title, :description, :instrument, :musical_key, :tempo, ' .
            ':time_signature, :difficulty, :style, :status, CAST(:score_data AS jsonb)) ' .
            'RETURNING id, user_id, title, status, created_at, updated_at'
        );
        $stmt->execute([
            ':user_id' => $userId,
            ':title' => (string) ($fields['title'] ?? 'Sem título'),
            ':description' => (string) ($fields['description'] ?? ''),
            ':instrument' => (string) ($fields['instrument'] ?? ''),
            ':musical_key' => (string) ($fields['musical_key'] ?? ''),
            ':tempo' => (string) ($fields['tempo'] ?? ''),
            ':time_signature' => (string) ($fields['time_signature'] ?? ''),
            ':difficulty' => (string) ($fields['difficulty'] ?? ''),
            ':style' => (string) ($fields['style'] ?? ''),
            ':status' => (string) ($fields['status'] ?? 'draft'),
            ':score_data' => json_encode($fields['score_data'] ?? new stdClass(), JSON_UNESCAPED_UNICODE),
        ]);
        $row = $stmt->fetch();
        return $row === false ? [] : $row;
    }

    public static function findScoreById(string $id): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM scores WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $id]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function listScoresByUser(string $userId, int $limit = 20, int $offset = 0): array
    {
        $limit = max(1, min(100, $limit));
        $offset = max(0, $offset);
        $stmt = self::pdo()->prepare(
            'SELECT * FROM scores WHERE user_id = :user_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset'
        );
        $stmt->bindValue(':user_id', $userId, PDO::PARAM_STR);
        $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
        $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
        $stmt->execute();
        return $stmt->fetchAll();
    }

    /* ---------------- Gerações (base para a futura IA) ---------------- */

    public static function createGeneration(string $scoreId, string $prompt, string $provider = '', string $model = ''): array
    {
        $stmt = self::pdo()->prepare(
            "INSERT INTO score_generations (score_id, prompt, status, provider, model) " .
            "VALUES (:score_id, :prompt, 'pending', :provider, :model) " .
            'RETURNING id, score_id, status, created_at'
        );
        $stmt->execute([':score_id' => $scoreId, ':prompt' => $prompt, ':provider' => $provider, ':model' => $model]);
        $row = $stmt->fetch();
        return $row === false ? [] : $row;
    }

    public static function completeGeneration(string $id, string $status, ?array $resultData = null, string $error = ''): array
    {
        $stmt = self::pdo()->prepare(
            'UPDATE score_generations SET status = :status, result_data = CAST(:result_data AS jsonb), ' .
            'error_message = :error_message, completed_at = NOW() WHERE id = :id ' .
            'RETURNING id, score_id, status, completed_at'
        );
        $stmt->execute([
            ':status' => $status,
            ':result_data' => json_encode($resultData ?? new stdClass(), JSON_UNESCAPED_UNICODE),
            ':error_message' => $error,
            ':id' => $id,
        ]);
        $row = $stmt->fetch();
        return $row === false ? [] : $row;
    }

    /* -------- Partituras do usuário (sempre filtradas por user_id) -------- */

    public static function listScoresForUser(string $userId, int $limit = 50): array
    {
        $limit = max(1, min(100, $limit));
        $stmt = self::pdo()->prepare(
            'SELECT id, title, description, instrument, musical_key, tempo, ' .
            'time_signature, difficulty, style, status, created_at, updated_at ' .
            'FROM scores WHERE user_id = :user_id ORDER BY created_at DESC LIMIT :limit'
        );
        $stmt->bindValue(':user_id', $userId, PDO::PARAM_STR);
        $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
        $stmt->execute();
        return $stmt->fetchAll();
    }

    public static function findScoreForUser(string $id, string $userId): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM scores WHERE id = :id AND user_id = :user_id LIMIT 1');
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function deleteScoreForUser(string $id, string $userId): bool
    {
        $stmt = self::pdo()->prepare('DELETE FROM scores WHERE id = :id AND user_id = :user_id');
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        return $stmt->rowCount() > 0;
    }

    /* -------- Tokens persistentes (sessão serverless; sem dados sensíveis) -------- */

    /** Persiste o hash do token (nunca o token em claro). */
    public static function createAuthToken(string $userId, string $tokenHash, string $expiresAt): void
    {
        $stmt = self::pdo()->prepare(
            'INSERT INTO auth_tokens (token_hash, user_id, expires_at) VALUES (:hash, :user_id, :expires_at)'
        );
        $stmt->execute([':hash' => $tokenHash, ':user_id' => $userId, ':expires_at' => $expiresAt]);
        try {
            self::pdo()->prepare('DELETE FROM auth_tokens WHERE expires_at <= NOW()')->execute();
        } catch (Throwable $e) {
            // Limpeza oportunista: falha aqui não invalida o token criado.
        }
    }

    /** Devolve id/name/email do dono do token válido (não expirado) ou null. */
    public static function findUserByTokenHash(string $tokenHash): ?array
    {
        $stmt = self::pdo()->prepare(
            'SELECT u.id, u.name, u.email FROM auth_tokens t ' .
            'JOIN users u ON u.id = t.user_id ' .
            'WHERE t.token_hash = :hash AND t.expires_at > NOW() LIMIT 1'
        );
        $stmt->execute([':hash' => $tokenHash]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    /** Revoga um token (logout). Inexistente = sem erro. */
    public static function deleteAuthToken(string $tokenHash): void
    {
        $stmt = self::pdo()->prepare('DELETE FROM auth_tokens WHERE token_hash = :hash');
        $stmt->execute([':hash' => $tokenHash]);
    }

    /* -------- Pipeline de áudio (FASE 1; tabelas audio_*) -------- */

    public static function createAudioSource(string $userId, array $fields): array
    {
        $stmt = self::pdo()->prepare(
            'INSERT INTO audio_sources (user_id, source_type, original_filename, storage_path, ' .
            'mime_type, file_size, status) ' .
            'VALUES (:user_id, :source_type, :original_filename, :storage_path, ' .
            ':mime_type, :file_size, :status) ' .
            'RETURNING id, status, created_at'
        );
        $stmt->execute([
            ':user_id' => $userId,
            ':source_type' => (string) ($fields['source_type'] ?? 'upload'),
            ':original_filename' => (string) ($fields['original_filename'] ?? ''),
            ':storage_path' => (string) ($fields['storage_path'] ?? ''),
            ':mime_type' => (string) ($fields['mime_type'] ?? ''),
            ':file_size' => (int) ($fields['file_size'] ?? 0),
            ':status' => (string) ($fields['status'] ?? 'uploaded'),
        ]);
        $row = $stmt->fetch();
        return $row === false ? [] : $row;
    }

    public static function findAudioSource(string $id): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM audio_sources WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $id]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function findAudioSourceForUser(string $id, string $userId): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM audio_sources WHERE id = :id AND user_id = :user_id LIMIT 1');
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function updateAudioSourceStatus(string $id, string $status): void
    {
        $stmt = self::pdo()->prepare('UPDATE audio_sources SET status = :status WHERE id = :id');
        $stmt->execute([':status' => $status, ':id' => $id]);
    }

    /** Uploads do usuário desde 00:00 (limite antiabuso). */
    public static function countUserUploadsToday(string $userId): int
    {
        $stmt = self::pdo()->prepare(
            "SELECT count(*) FROM audio_sources WHERE user_id = :user_id AND created_at >= CURRENT_DATE"
        );
        $stmt->execute([':user_id' => $userId]);
        return (int) $stmt->fetchColumn();
    }

    public static function createTranscriptionJob(string $userId, string $sourceId, string $status = 'queued', int $progress = 0, ?string $stage = null): array
    {
        $stmt = self::pdo()->prepare(
            'INSERT INTO transcription_jobs (user_id, audio_source_id, status, progress, current_stage) ' .
            'VALUES (:user_id, :source_id, :status, :progress, :stage) ' .
            'RETURNING id, status, progress, current_stage, created_at'
        );
        $stmt->execute([
            ':user_id' => $userId,
            ':source_id' => $sourceId,
            ':status' => $status,
            ':progress' => max(0, min(100, $progress)),
            ':stage' => $stage,
        ]);
        $row = $stmt->fetch();
        return $row === false ? [] : $row;
    }

    public static function findJobForUser(string $id, string $userId): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM transcription_jobs WHERE id = :id AND user_id = :user_id LIMIT 1');
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function findJobById(string $id): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM transcription_jobs WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $id]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    /**
     * Atualiza o job com campos já sanitizados (AudioJobs::sanitizeUpdate).
     * Preenche started_at no primeiro processing e completed_at ao fechar.
     */
    public static function updateTranscriptionJob(string $id, array $fields): ?array
    {
        $row = self::findJobById($id);
        if ($row === null) {
            return null;
        }
        $status = array_key_exists('status', $fields) ? $fields['status'] : $row['status'];
        $progress = array_key_exists('progress', $fields) ? max(0, min(100, (int) $fields['progress'])) : (int) $row['progress'];
        $stage = array_key_exists('current_stage', $fields) ? $fields['current_stage'] : $row['current_stage'];
        $errorCode = array_key_exists('error_code', $fields) ? $fields['error_code'] : $row['error_code'];
        $errorMessage = array_key_exists('error_message', $fields) ? $fields['error_message'] : $row['error_message'];
        $workerJobId = array_key_exists('worker_job_id', $fields) ? $fields['worker_job_id'] : $row['worker_job_id'];
        $startedAt = $row['started_at'];
        if ($startedAt === null && in_array($status, ['processing', 'completed', 'partial', 'failed'], true)) {
            $startedAt = date('Y-m-d H:i:s');
        }
        $completedAt = $row['completed_at'];
        if (in_array($status, ['completed', 'partial', 'failed', 'cancelled'], true)) {
            $completedAt = date('Y-m-d H:i:s');
        }
        $stmt = self::pdo()->prepare(
            'UPDATE transcription_jobs SET status = :status, progress = :progress, current_stage = :stage, ' .
            'error_code = :error_code, error_message = :error_message, worker_job_id = :worker_job_id, ' .
            'started_at = :started_at, completed_at = :completed_at WHERE id = :id ' .
            'RETURNING id, status, progress, current_stage, updated_at'
        );
        $stmt->execute([
            ':status' => $status,
            ':progress' => $progress,
            ':stage' => $stage,
            ':error_code' => $errorCode,
            ':error_message' => $errorMessage,
            ':worker_job_id' => $workerJobId,
            ':started_at' => $startedAt,
            ':completed_at' => $completedAt,
            ':id' => $id,
        ]);
        $updated = $stmt->fetch();
        return $updated === false ? null : $updated;
    }

    /**
     * Persiste o resultado musical do worker (FASE 3M) em audio_analysis.
     * Upsert por audio_source_id; $analysisJson deve ser array já
     * validado. Metadados (bpm/tom/compasso/duração) espelhados nas
     * colunas para consulta sem abrir o JSONB.
     */
    public static function upsertAudioAnalysis(string $sourceId, array $analysisJson, array $meta = []): void
    {
        $stmt = self::pdo()->prepare(
            'INSERT INTO audio_analysis (audio_source_id, tempo_bpm, key, time_signature, ' .
            'duration_seconds, sample_rate, channels, analysis_json) ' .
            'VALUES (:source_id, :bpm, :key, :meter, :duration, :rate, :channels, :json) ' .
            'ON CONFLICT (audio_source_id) DO UPDATE SET tempo_bpm = EXCLUDED.tempo_bpm, ' .
            'key = EXCLUDED.key, time_signature = EXCLUDED.time_signature, ' .
            'duration_seconds = EXCLUDED.duration_seconds, sample_rate = EXCLUDED.sample_rate, ' .
            'channels = EXCLUDED.channels, analysis_json = EXCLUDED.analysis_json'
        );
        $stmt->execute([
            ':source_id' => $sourceId,
            ':bpm' => $meta['tempo_bpm'] ?? null,
            ':key' => isset($meta['key']) ? substr((string) $meta['key'], 0, 20) : null,
            ':meter' => isset($meta['time_signature']) ? substr((string) $meta['time_signature'], 0, 10) : null,
            ':duration' => $meta['duration_seconds'] ?? null,
            ':rate' => isset($meta['sample_rate']) ? (int) $meta['sample_rate'] : null,
            ':channels' => isset($meta['channels']) ? (int) $meta['channels'] : null,
            ':json' => json_encode($analysisJson, JSON_UNESCAPED_UNICODE),
        ]);
    }

    public static function findAudioAnalysisBySource(string $sourceId): ?array
    {
        $stmt = self::pdo()->prepare('SELECT * FROM audio_analysis WHERE audio_source_id = :id LIMIT 1');
        $stmt->execute([':id' => $sourceId]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }
}

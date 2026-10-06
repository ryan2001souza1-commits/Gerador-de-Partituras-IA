<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Configuração do pipeline de áudio (FASE 1).
 *
 * Lê variáveis de ambiente com padrões seguros. Nenhum segredo é
 * impresso, registrado ou retornado por estas funções.
 */
class AudioConfig
{
    const DEFAULT_BUCKET = 'audio-inputs';
    const DEFAULT_MAX_SIZE_MB = 25;
    const MAX_UPLOADS_PER_DAY = 20;
    const SIGNED_URL_TTL_S = 120;

    /** Extensão => MIMEs aceitos (detectados via finfo, nunca do cliente). */
    const ALLOWED_AUDIO = [
        'mp3' => ['audio/mpeg', 'audio/mp3'],
        'wav' => ['audio/wav', 'audio/x-wav', 'audio/vnd.wave', 'audio/wave'],
        'flac' => ['audio/flac', 'audio/x-flac'],
        'ogg' => ['audio/ogg', 'application/ogg'],
        'm4a' => ['audio/mp4', 'audio/x-m4a', 'audio/aac', 'audio/mp4a-latm'],
        'aac' => ['audio/aac', 'audio/mp4', 'audio/x-aac'],
    ];

    /** Status válidos de transcription_jobs. */
    const JOB_STATUSES = ['pending', 'queued', 'processing', 'completed', 'partial', 'failed', 'cancelled'];
    /** Status que o webhook pode definir. */
    const WEBHOOK_STATUSES = ['queued', 'processing', 'completed', 'partial', 'failed'];
    /** Stages do pipeline (presentes e futuros). */
    const STAGES = ['queued', 'downloading', 'decoding', 'analyzing', 'separating',
        'detecting_instruments', 'extracting_notes', 'quantizing', 'building_score',
        'refining_ai', 'validating', 'completed', 'failed'];

    public static function supabaseUrl(): ?string
    {
        $v = getenv('SUPABASE_URL');
        if (!is_string($v) || trim($v) === '') {
            return null;
        }
        return rtrim(trim($v), '/');
    }

    /** Chave service_role (somente servidor). Nunca imprimir. */
    public static function serviceKey(): ?string
    {
        $v = getenv('SUPABASE_SERVICE_ROLE_KEY');
        if (!is_string($v) || trim($v) === '') {
            return null;
        }
        return trim($v);
    }

    public static function bucket(): string
    {
        $v = getenv('AUDIO_STORAGE_BUCKET');
        if (!is_string($v) || trim($v) === '') {
            return self::DEFAULT_BUCKET;
        }
        return trim($v);
    }

    public static function maxBytes(): int
    {
        $v = getenv('AUDIO_MAX_SIZE_MB');
        $mb = is_numeric($v) ? (int) $v : self::DEFAULT_MAX_SIZE_MB;
        if ($mb < 1 || $mb > 500) {
            $mb = self::DEFAULT_MAX_SIZE_MB;
        }
        return $mb * 1024 * 1024;
    }

    public static function workerBaseUrl(): string
    {
        $v = getenv('WORKER_BASE_URL');
        return (is_string($v) && trim($v) !== '') ? rtrim(trim($v), '/') : '';
    }

    public static function webhookSecret(): string
    {
        $v = getenv('WORKER_WEBHOOK_SECRET');
        return (is_string($v) && $v !== '') ? $v : '';
    }

    /**
     * Confere o segredo do webhook em tempo constante.
     * Segredo ausente/não configurado => sempre falso.
     */
    public static function checkWebhookSecret(string $provided): bool
    {
        $expected = self::webhookSecret();
        if ($expected === '' || $provided === '') {
            return false;
        }
        return hash_equals($expected, $provided);
    }
}

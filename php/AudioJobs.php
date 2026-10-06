<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Sanitização pura de updates de job (FASE 1).
 *
 * Sem banco e sem rede (testável em CLI). Campos desconhecidos são
 * ignorados; valores inválidos lançam InvalidArgumentException.
 */
/**
 * Erro de validação da seleção com código HTTP associado.
 */
class SelectionError extends InvalidArgumentException
{
    public $httpCode;
    public function __construct(int $httpCode, string $message)
    {
        parent::__construct($message);
        $this->httpCode = $httpCode;
    }
}

class AudioJobs
{    /**
     * Normaliza campos de atualização de transcription_jobs.
     * Retorna somente colunas permitidas já validadas.
     */
    public static function sanitizeUpdate(array $fields): array
    {
        $out = [];
        if (array_key_exists('status', $fields)) {
            $st = $fields['status'];
            if (!is_string($st) || !in_array($st, AudioConfig::JOB_STATUSES, true)) {
                throw new InvalidArgumentException('Status inválido.');
            }
            $out['status'] = $st;
        }
        if (array_key_exists('progress', $fields)) {
            $p = $fields['progress'];
            if (is_numeric($p)) {
                $p = (int) $p;
            }
            if (!is_int($p) || $p < 0 || $p > 100) {
                throw new InvalidArgumentException('Progresso inválido.');
            }
            $out['progress'] = $p;
        }
        if (array_key_exists('current_stage', $fields)) {
            $sg = $fields['current_stage'];
            if ($sg !== null && (!is_string($sg) || !in_array($sg, AudioConfig::STAGES, true))) {
                throw new InvalidArgumentException('Etapa inválida.');
            }
            $out['current_stage'] = $sg;
        }
        if (array_key_exists('error_code', $fields)) {
            $ec = $fields['error_code'];
            if ($ec !== null && (!is_string($ec) || strlen($ec) > 50)) {
                throw new InvalidArgumentException('Código de erro inválido.');
            }
            $out['error_code'] = $ec;
        }
        if (array_key_exists('error_message', $fields)) {
            $em = $fields['error_message'];
            if ($em !== null && !is_string($em)) {
                throw new InvalidArgumentException('Mensagem de erro inválida.');
            }
            $out['error_message'] = is_string($em) ? substr($em, 0, 2000) : null;
        }
        if (array_key_exists('worker_job_id', $fields)) {
            $wj = $fields['worker_job_id'];
            if ($wj !== null && (!is_string($wj) || strlen($wj) > 100)) {
                throw new InvalidArgumentException('Identificador do worker inválido.');
            }
            $out['worker_job_id'] = $wj;
        }
        if (array_key_exists('result', $fields)) {
            // Aceito para compatibilidade futura; ainda não persistido.
            if ($fields['result'] !== null && !is_array($fields['result'])) {
                throw new InvalidArgumentException('Resultado inválido.');
            }
        }
        return $out;
    }

    /**
     * Monta a URL de callback do webhook a partir da requisição atual.
     * Host validado estritamente; inválido => exceção.
     */
    public static function callbackUrl($https, $forwardedProto, $host): string
    {
        $secure = (!empty($https) && $https !== 'off') || $forwardedProto === 'https';
        if (!is_string($host) || preg_match('/^[A-Za-z0-9.-]+(:\d+)?$/', $host) !== 1) {
            throw new InvalidArgumentException('Host inválido.');
        }
        return ($secure ? 'https://' : 'http://') . $host . '/api/transcription/webhook';
    }

    /**
     * Monta o payload INTERNO do worker (nunca vai ao navegador).
     * Contém a signed URL; o segredo do webhook NUNCA entra aqui —
     * ele viaja apenas como header na chamada real futura.
     */
    public static function buildWorkerPayload(array $job, array $source, string $audioUrl, string $callbackUrl, int $expiresIn): array
    {
        return [
            'job_id' => (string) $job['id'],
            'audio_source_id' => (string) $source['id'],
            'audio_url' => $audioUrl,
            'callback_url' => $callbackUrl,
            'callback_token_hint' => 'header X-Webhook-Secret',
            'expires_in' => $expiresIn,
        ];
    }

    /** Campos que o webhook pode enviar. */
    public static function sanitizeWebhook(array $body): array
    {
        if (!isset($body['job_id']) || !is_string($body['job_id']) || !AudioUpload::isUuid($body['job_id'])) {
            throw new InvalidArgumentException('Job inválido.');
        }
        if (!isset($body['status']) || !is_string($body['status'])
            || !in_array($body['status'], AudioConfig::WEBHOOK_STATUSES, true)) {
            throw new InvalidArgumentException('Status inválido.');
        }
        $fields = ['status' => $body['status']];
        foreach (['progress', 'current_stage', 'error_code', 'error_message', 'worker_job_id'] as $k) {
            if (array_key_exists($k, $body)) {
                $fields[$k] = $body[$k];
            }
        }
        if (isset($fields['current_stage']) && $fields['current_stage'] !== null
            && !in_array($fields['current_stage'], AudioConfig::STAGES, true)) {
            throw new InvalidArgumentException('Etapa inválida.');
        }
        $sanitized = self::sanitizeUpdate($fields);
        $sanitized['job_id'] = strtolower($body['job_id']);
        return $sanitized;
    }

    /**
     * Extrai o resultado musical do corpo do webhook (FASE 3M).
     * Retorna null quando ausente; lança quando presente mas inválido.
     * completed/partial exigem resultado (nunca result null com terminal).
     */
    public static function extractWebhookResult(array $body): ?array
    {
        $candidate = null;
        if (isset($body['result']['transcription']) && is_array($body['result']['transcription'])) {
            $candidate = $body['result']['transcription'];
        } elseif (isset($body['result']) && is_array($body['result'])
            && isset($body['result']['tracks']) && is_array($body['result']['tracks'])) {
            $candidate = $body['result'];
        }
        $terminal = isset($body['status']) && in_array($body['status'], ['completed', 'partial'], true);
        if ($candidate === null) {
            if ($terminal) {
                throw new InvalidArgumentException('Resultado ausente.');
            }
            return null;
        }
        if (count($candidate) > 50000) {
            throw new InvalidArgumentException('Resultado inválido.');
        }
        $encoded = json_encode($candidate);
        if (!is_string($encoded) || strlen($encoded) > 1048576) {
            throw new InvalidArgumentException('Resultado inválido.');
        }
        return $candidate;
    }

    /** Mensagem segura p/ exibição: sem paths, URLs, tokens ou HTML. */
    public static function sanitizeDisplayMessage($message): string
    {
        $text = is_string($message) ? $message : '';
        $text = strip_tags($text);
        $text = (string) preg_replace('#/(tmp|home|root|etc|var|mnt|data)/\S*#i', '[caminho]', $text);
        $text = (string) preg_replace('#[A-Za-z]+://\S+#', '[url]', $text ?? '');
        $text = (string) preg_replace('/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/', '[email]', $text ?? '');
        $text = trim(preg_replace('/\s+/', ' ', $text ?? ''));
        if (function_exists('mb_substr')) {
            return mb_substr($text, 0, 300);
        }
        return substr($text, 0, 300);
    }

    /** Normaliza número finito ou null (nunca NaN/Infinity no JSON). */
    private static function finiteOrNull($value)
    {
        if (is_int($value) || is_float($value)) {
            return is_finite($value) ? $value : null;
        }
        if (is_numeric($value)) {
            $f = (float) $value;
            return is_finite($f) ? $f : null;
        }
        return null;
    }

    /**
     * Contrato JSON final p/ o frontend (FASE 3M): job + result.
     * Puro e sem banco/rede. Nunca inventa valores: ausente vira
     * null (ou []) conforme o campo. Preserva todos os campos
     * públicos já retornados pelo status handler.
     */
    public static function buildStatusResult(array $job, $analysis): array
    {
        $status = isset($job['status']) && is_string($job['status']) ? $job['status'] : 'queued';
        $storedProgress = isset($job['progress']) && is_numeric($job['progress']) ? (int) $job['progress'] : 0;
        $storedProgress = max(0, min(100, $storedProgress));
        if ($status === 'completed' || $status === 'partial') {
            $progress = 100;
        } elseif ($status === 'queued') {
            $progress = min($storedProgress, 10);
        } elseif ($status === 'processing') {
            $progress = max(10, min(99, $storedProgress <= 0 ? 10 : $storedProgress));
        } else {
            $progress = $storedProgress;
        }
        $out = [
            'success' => true,
            'job' => [
                'job_id' => isset($job['id']) ? (string) $job['id'] : null,
                'status' => $status,
                'progress' => $progress,
                'current_stage' => $job['current_stage'] ?? null,
                'created_at' => $job['created_at'] ?? null,
                'started_at' => $job['started_at'] ?? null,
                'completed_at' => $job['completed_at'] ?? null,
                'error_message' => isset($job['error_message']) && $job['error_message'] !== null
                    ? self::sanitizeDisplayMessage($job['error_message']) : null,
            ],
            'result' => null,
        ];
        if (!in_array($status, ['completed', 'partial'], true) || !is_array($analysis)) {
            return $out;
        }
        $tracks = isset($analysis['tracks']) && is_array($analysis['tracks']) ? $analysis['tracks'] : [];
        $music = isset($analysis['music']) && is_array($analysis['music']) ? $analysis['music'] : [];
        $stats = isset($analysis['statistics']) && is_array($analysis['statistics']) ? $analysis['statistics'] : [];
        $tempo = isset($music['tempo']) && is_array($music['tempo']) ? $music['tempo'] : [];
        $key = isset($music['key']) && is_array($music['key']) ? $music['key'] : [];
        $meter = isset($music['meter']) && is_array($music['meter']) ? $music['meter'] : [];
        $duration = self::finiteOrNull($stats['duration_seconds'] ?? ($analysis['source']['duration_seconds'] ?? null));
        $bpm = self::finiteOrNull($tempo['bpm'] ?? null);
        $meterStr = null;
        if (isset($meter['numerator'], $meter['denominator']) && is_numeric($meter['numerator']) && is_numeric($meter['denominator'])) {
            $meterStr = ((int) $meter['numerator']) . '/' . ((int) $meter['denominator']);
        }
        $outTracks = [];
        $flatNotes = [];
        $byInstrument = [];
        foreach ($tracks as $track) {
            if (!is_array($track)) {
                continue;
            }
            $inst = isset($track['instrument']) && is_array($track['instrument']) ? $track['instrument'] : [];
            $instId = isset($inst['name']) && is_string($inst['name']) && $inst['name'] !== '' ? $inst['name'] : null;
            $trackStatus = $track['status'] ?? null;
            $tstats = isset($track['statistics']) && is_array($track['statistics']) ? $track['statistics'] : [];
            $tnotes = isset($track['notes']) && is_array($track['notes']) ? $track['notes'] : [];
            $active = self::finiteOrNull($tstats['active_seconds'] ?? null);
            $silence = self::finiteOrNull($tstats['silence_seconds'] ?? null);
            $trackDuration = ($active !== null || $silence !== null) ? (float) ($active ?? 0) + (float) ($silence ?? 0) : null;
            $shaped = [
                'track_id' => isset($track['track_id']) ? (string) $track['track_id'] : null,
                'name' => isset($inst['display_name']) && is_string($inst['display_name']) && $inst['display_name'] !== ''
                    ? $inst['display_name'] : (isset($track['source_stem']) ? (string) $track['source_stem'] : null),
                'instrument_id' => $instId,
                'family' => isset($inst['family']) && is_string($inst['family']) ? $inst['family'] : 'unknown',
                'confidence' => self::finiteOrNull($inst['confidence'] ?? null),
                'selected' => !empty($track['selected']),
                'ambiguous' => $trackStatus === 'ambiguous',
                'note_count' => is_numeric($tstats['note_count'] ?? null) ? (int) $tstats['note_count'] : count($tnotes),
                'duration_seconds' => $trackDuration,
                'evidence' => [
                    'classifier' => isset($track['evidence']['classifier']) ? (string) $track['evidence']['classifier'] : null,
                    'direct_detection' => !empty($track['evidence']['direct_detection']),
                ],
            ];
            $outTracks[] = $shaped;
            foreach ($tnotes as $note) {
                if (!is_array($note)) {
                    continue;
                }
                $pitch = isset($note['pitch']) && is_numeric($note['pitch']) ? (int) $note['pitch'] : null;
                if ($pitch === null || $pitch < 0 || $pitch > 127) {
                    continue;
                }
                $flatNotes[] = [
                    'pitch' => $pitch,
                    'start' => self::finiteOrNull($note['start'] ?? null),
                    'end' => self::finiteOrNull($note['end'] ?? null),
                    'duration' => self::finiteOrNull($note['duration'] ?? null),
                    'velocity' => isset($note['velocity']) && is_numeric($note['velocity'])
                        ? max(0, min(127, (int) $note['velocity'])) : null,
                    'confidence' => self::finiteOrNull($note['confidence'] ?? null),
                    'track_id' => $shaped['track_id'],
                ];
            }
            if ($instId !== null) {
                if (!isset($byInstrument[$instId])) {
                    $byInstrument[$instId] = [
                        'id' => $instId,
                        'name' => isset($inst['display_name']) && is_string($inst['display_name']) ? $inst['display_name'] : $instId,
                        'family' => $shaped['family'],
                        'confidence' => $shaped['confidence'],
                        'evidence' => [
                            'classifier' => $shaped['evidence']['classifier'],
                            'direct_detection' => $shaped['evidence']['direct_detection'],
                            'source_track_ids' => [],
                        ],
                        'selected' => false,
                        'ambiguous' => false,
                    ];
                }
                $byInstrument[$instId]['evidence']['source_track_ids'][] = $shaped['track_id'];
                if ($shaped['confidence'] !== null
                    && ($byInstrument[$instId]['confidence'] === null || $shaped['confidence'] > $byInstrument[$instId]['confidence'])) {
                    $byInstrument[$instId]['confidence'] = $shaped['confidence'];
                }
                if ($shaped['selected']) {
                    $byInstrument[$instId]['selected'] = true;
                }
            }
        }
        $warnings = [];
        $rawWarnings = isset($analysis['warnings']) && is_array($analysis['warnings']) ? $analysis['warnings'] : [];
        foreach ($rawWarnings as $warning) {
            if (is_string($warning)) {
                $warnings[] = self::sanitizeDisplayMessage($warning);
            } elseif (is_array($warning)) {
                $warnings[] = [
                    'code' => isset($warning['code']) ? (string) $warning['code'] : 'UNKNOWN',
                    'message' => self::sanitizeDisplayMessage($warning['message'] ?? ''),
                ];
            }
        }
        $savedTitle = isset($analysis['selection']['title']) && is_string($analysis['selection']['title'])
            && trim($analysis['selection']['title']) !== ''
            ? trim($analysis['selection']['title']) : null;
        $out['result'] = [
            'title' => $savedTitle,
            'duration_seconds' => $duration ?? 0,
            'bpm' => $bpm,
            'bpm_confidence' => self::finiteOrNull($tempo['confidence'] ?? null),
            'key' => (isset($key['tonic'], $key['mode']) && is_string($key['tonic']) && is_string($key['mode']))
                ? ['tonic' => $key['tonic'], 'mode' => $key['mode'], 'confidence' => self::finiteOrNull($key['confidence'] ?? null)]
                : null,
            'key_confidence' => self::finiteOrNull($key['confidence'] ?? null),
            'time_signature' => $meterStr,
            'meter_confidence' => self::finiteOrNull($meter['confidence'] ?? null),
            'measure_count' => is_numeric($stats['measure_count'] ?? null) ? (int) $stats['measure_count'] : null,
            'confidence' => self::finiteOrNull($analysis['confidence'] ?? null) ?? 0,
            'warnings' => $warnings,
            'instruments' => array_values($byInstrument),
            'tracks' => $outTracks,
            'notes' => $flatNotes,
            'statistics' => [
                'total_notes' => is_numeric($stats['total_notes'] ?? null) ? (int) $stats['total_notes'] : count($flatNotes),
                'total_chords' => is_numeric($stats['total_chords'] ?? null) ? (int) $stats['total_chords'] : 0,
                'pitch_min' => is_numeric($stats['pitch_min'] ?? null) ? (int) $stats['pitch_min'] : null,
                'pitch_max' => is_numeric($stats['pitch_max'] ?? null) ? (int) $stats['pitch_max'] : null,
                'mean_velocity' => self::finiteOrNull($stats['mean_velocity'] ?? null),
                'mean_duration' => self::finiteOrNull($stats['mean_duration'] ?? null),
            ],
        ];
        return $out;
    }

    /** Metadados espelhados nas colunas de audio_analysis. */
    public static function analysisMeta($analysis): array
    {
        $analysis = is_array($analysis) ? $analysis : [];
        $music = isset($analysis['music']) && is_array($analysis['music']) ? $analysis['music'] : [];
        $tempo = isset($music['tempo']) && is_array($music['tempo']) ? $music['tempo'] : [];
        $meter = isset($music['meter']) && is_array($music['meter']) ? $music['meter'] : [];
        $key = isset($music['key']) && is_array($music['key']) ? $music['key'] : [];
        $source = isset($analysis['source']) && is_array($analysis['source']) ? $analysis['source'] : [];
        $meterStr = null;
        if (isset($meter['numerator'], $meter['denominator'])) {
            $meterStr = ((int) $meter['numerator']) . '/' . ((int) $meter['denominator']);
        }
        $keyStr = null;
        if (isset($key['tonic'], $key['mode'])) {
            $keyStr = $key['tonic'] . ' ' . $key['mode'];
        }
        return [
            'tempo_bpm' => $tempo['bpm'] ?? null,
            'key' => $keyStr,
            'time_signature' => $meterStr,
            'duration_seconds' => $source['duration_seconds'] ?? null,
            'sample_rate' => $source['sample_rate'] ?? null,
            'channels' => $source['channels'] ?? null,
        ];
    }

    /**
     * Valida a seleção do usuário contra o resultado real (FASE 3O).
     * Retorna ['title', 'selected_instruments'] sanitizados ou lança
     * SelectionError com o HTTP adequado. Nunca confia em ids/título
     * do cliente sem revalidar contra a análise do job.
     */
    public static function sanitizeSelection($job, $analysis, $body): array
    {
        $status = is_array($job) && isset($job['status']) ? $job['status'] : null;
        if (!in_array($status, ['completed', 'partial'], true)) {
            throw new SelectionError(409, 'A análise ainda não está pronta.');
        }
        if (!is_array($body) || !isset($body['selected_instruments'])
            || !is_array($body['selected_instruments']) || count($body['selected_instruments']) === 0) {
            throw new SelectionError(400, 'Seleção inválida.');
        }
        if (count($body['selected_instruments']) > 32) {
            throw new SelectionError(400, 'Seleção inválida.');
        }
        $title = isset($body['title']) ? $body['title'] : '';
        if (!is_string($title)) {
            throw new SelectionError(400, 'Título inválido.');
        }
        $title = trim((string) preg_replace('/\s+/', ' ', $title));
        $tooLong = function_exists('mb_strlen') ? mb_strlen($title) > 120 : strlen($title) > 120;
        if ($title === '' || $tooLong) {
            throw new SelectionError(400, $title === '' ? 'Título inválido.' : 'Título deve ter no máximo 120 caracteres.');
        }
        $tracks = isset($analysis['tracks']) && is_array($analysis['tracks']) ? $analysis['tracks'] : [];
        $byTrack = [];
        $validInstruments = [];
        foreach ($tracks as $track) {
            if (!is_array($track) || !isset($track['track_id']) || !is_string($track['track_id'])) {
                continue;
            }
            // Tracks 3J/3K: id canônico em instrument.name (nunca plano).
            $inst = isset($track['instrument']) && is_array($track['instrument']) ? $track['instrument'] : [];
            $instId = isset($inst['name']) && is_string($inst['name']) && $inst['name'] !== ''
                ? $inst['name'] : null;
            $byTrack[$track['track_id']] = $instId;
            if ($instId !== null) {
                $validInstruments[$instId] = true;
            }
        }
        $selected = [];
        $seenInst = [];
        foreach ($body['selected_instruments'] as $item) {
            if (!is_array($item) || !isset($item['instrument_id']) || !is_string($item['instrument_id'])
                || !isset($validInstruments[$item['instrument_id']])) {
                throw new SelectionError(422, 'Instrumento inválido para este job.');
            }
            if (!isset($item['track_ids']) || !is_array($item['track_ids']) || count($item['track_ids']) === 0) {
                throw new SelectionError(422, 'Faixa inválida para este job.');
            }
            if (isset($seenInst[$item['instrument_id']])) {
                throw new SelectionError(422, 'Instrumento duplicado.');
            }
            $seenInst[$item['instrument_id']] = true;
            $trackIds = [];
            foreach ($item['track_ids'] as $trackId) {
                if (!is_string($trackId) || !array_key_exists($trackId, $byTrack)) {
                    throw new SelectionError(422, 'Faixa inválida para este job.');
                }
                if ($byTrack[$trackId] !== $item['instrument_id']) {
                    throw new SelectionError(422, 'Faixa inválida para este instrumento.');
                }
                $trackIds[] = $trackId;
            }
            $selected[] = ['instrument_id' => $item['instrument_id'], 'track_ids' => array_values(array_unique($trackIds))];
        }
        return ['title' => $title, 'selected_instruments' => $selected];
    }
}

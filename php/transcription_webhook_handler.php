<?php
declare(strict_types=1);

/**
 * Handler do webhook de transcrição (lógica movida de
 * api/transcription/webhook.php).
 *
 * Servido via api/transcription-router.php (rewrites preservam a URL
 * pública POST /api/transcription/webhook, incluindo o header
 * X-Webhook-Secret). Arquivo de biblioteca: não executa sozinho.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioConfig.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/AudioJobs.php';

function gpi_hook_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

function transcription_webhook_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        gpi_hook_error(405, 'Método não permitido. Utilize POST.');
    }

    $provided = $_SERVER['HTTP_X_WEBHOOK_SECRET'] ?? null;
    if (!is_string($provided) || !AudioConfig::checkWebhookSecret($provided)) {
        gpi_hook_error(401, 'Não autorizado.');
    }

    $raw = file_get_contents('php://input');
    $body = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($body)) {
        gpi_hook_error(400, 'JSON inválido.');
    }

    try {
        $sanitized = AudioJobs::sanitizeWebhook($body);
    } catch (InvalidArgumentException $e) {
        gpi_hook_error(400, 'Requisição inválida.');
    }

    try {
        $terminalResult = null;
        if (in_array($sanitized['status'], ['completed', 'partial'], true)) {
            try {
                $terminalResult = AudioJobs::extractWebhookResult($body);
            } catch (InvalidArgumentException $e) {
                gpi_hook_error(400, 'Resultado ausente ou inválido.');
            }
        }
        $job = Database::findJobById($sanitized['job_id']);
        if ($job === null) {
            gpi_hook_error(404, 'Job não encontrado.');
        }
        $updated = Database::updateTranscriptionJob($sanitized['job_id'], $sanitized);
        if ($updated === null) {
            gpi_hook_error(404, 'Job não encontrado.');
        }
        if ($terminalResult !== null) {
            $music = isset($terminalResult['music']) && is_array($terminalResult['music']) ? $terminalResult['music'] : [];
            $tempo = isset($music['tempo']) && is_array($music['tempo']) ? $music['tempo'] : [];
            $meter = isset($music['meter']) && is_array($music['meter']) ? $music['meter'] : [];
            $key = isset($music['key']) && is_array($music['key']) ? $music['key'] : [];
            $source = isset($terminalResult['source']) && is_array($terminalResult['source']) ? $terminalResult['source'] : [];
            Database::upsertAudioAnalysis((string) $job['audio_source_id'], $terminalResult, [
                'tempo_bpm' => $tempo['bpm'] ?? null,
                'key' => isset($key['tonic'], $key['mode']) ? $key['tonic'] . ' ' . $key['mode'] : null,
                'time_signature' => isset($meter['numerator'], $meter['denominator'])
                    ? ((int) $meter['numerator']) . '/' . ((int) $meter['denominator']) : null,
                'duration_seconds' => $source['duration_seconds'] ?? null,
                'sample_rate' => $source['sample_rate'] ?? null,
                'channels' => $source['channels'] ?? null,
            ]);
        }
        if (in_array($sanitized['status'], ['processing', 'completed', 'partial', 'failed'], true)) {
            Database::updateAudioSourceStatus((string) $job['audio_source_id'], $sanitized['status']);
        }
    } catch (RuntimeException $e) {
        error_log('[gpi] falha no webhook de transcrição.');
        gpi_hook_error(500, 'Erro interno. Tente novamente.');
    }

    http_response_code(200);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'success' => true,
        'job_id' => $sanitized['job_id'],
        'status' => $updated['status'],
    ], JSON_UNESCAPED_UNICODE);
}

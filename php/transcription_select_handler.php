<?php
declare(strict_types=1);

/**
 * Handler da seleção de instrumentos (FASE 3O).
 *
 * POST /api/transcription/select — valida a escolha do usuário contra
 * o resultado real do job e guarda o pedido em
 * audio_analysis.analysis_json->selection (sem migration: reutiliza a
 * tabela existente). Nunca confia em instrument_id/track_id/title do
 * cliente sem revalidar contra a análise persistida.
 *
 * Arquivo de biblioteca: transcription_select_process() é pura e
 * testável em CLI; transcription_select_handle() faz HTTP + banco.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioConfig.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/AudioJobs.php';

/**
 * Núcleo puro: [$httpCode, $response, $selection|null].
 * $userId null => 401; $job null => 404 (inexistente ou de outro
 * usuário, sem distinguir); $analysis null => 422.
 */
function transcription_select_process($userId, $job, $analysis, $body): array
{
    if (!is_string($userId) || $userId === '') {
        return [401, ['success' => false, 'error' => 'Não autenticado.'], null];
    }
    if (!is_array($job)) {
        return [404, ['success' => false, 'error' => 'Job não encontrado.'], null];
    }
    if (!is_array($analysis)) {
        return [422, ['success' => false, 'error' => 'Resultado indisponível para este job.'], null];
    }
    try {
        $selection = AudioJobs::sanitizeSelection($job, $analysis, $body);
    } catch (SelectionError $e) {
        return [$e->httpCode, ['success' => false, 'error' => $e->getMessage()], null];
    } catch (InvalidArgumentException $e) {
        return [400, ['success' => false, 'error' => 'Seleção inválida.'], null];
    }
    return [200, [
        'success' => true,
        'job_id' => (string) $job['id'],
        'title' => $selection['title'],
        'selected_instruments' => $selection['selected_instruments'],
    ], $selection];
}

function gpi_select_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

function transcription_select_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        gpi_select_error(405, 'Método não permitido. Utilize POST.');
    }

    $user = gpi_current_user();
    $raw = file_get_contents('php://input');
    $body = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($body)) {
        gpi_select_error(400, 'JSON inválido.');
    }
    $jobId = $body['job_id'] ?? null;
    if (!is_string($jobId) || !AudioUpload::isUuid($jobId)) {
        gpi_select_error(400, 'Job inválido.');
    }

    try {
        $job = ($user === null) ? null : Database::findJobForUser(strtolower($jobId), $user['id']);
        $analysis = null;
        if (is_array($job) && isset($job['audio_source_id'])) {
            $row = Database::findAudioAnalysisBySource((string) $job['audio_source_id']);
            if ($row !== null && isset($row['analysis_json'])) {
                $decoded = is_string($row['analysis_json']) ? json_decode($row['analysis_json'], true) : $row['analysis_json'];
                $analysis = is_array($decoded) ? $decoded : null;
            }
        }
        [$code, $response, $selection] = transcription_select_process(
            $user === null ? null : (string) $user['id'], $job, $analysis, $body
        );
        if ($code === 200 && $selection !== null && is_array($job)) {
            $merged = $analysis;
            $merged['selection'] = [
                'title' => $selection['title'],
                'selected_instruments' => $selection['selected_instruments'],
                'updated_at' => date('Y-m-d H:i:s'),
            ];
            Database::upsertAudioAnalysis(
                (string) $job['audio_source_id'], $merged, AudioJobs::analysisMeta($merged)
            );
        }
    } catch (RuntimeException $e) {
        error_log('[gpi] falha na seleção de instrumentos.');
        gpi_select_error(500, 'Erro interno. Tente novamente.');
    }

    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

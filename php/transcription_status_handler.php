<?php
declare(strict_types=1);

/**
 * Handler do status do job (lógica movida de
 * api/transcription/status.php).
 *
 * Servido via api/transcription-router.php (rewrites preservam a URL
 * pública GET /api/transcription/status). Arquivo de biblioteca: não
 * executa sozinho.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/AudioJobs.php';

function gpi_job_status_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

function transcription_status_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
        header('Allow: GET');
        gpi_job_status_error(405, 'Método não permitido. Utilize GET.');
    }

    $id = $_GET['job_id'] ?? null;
    if (!is_string($id) || !AudioUpload::isUuid($id)) {
        gpi_job_status_error(400, 'Job inválido.');
    }

    $user = gpi_current_user();
    if ($user === null) {
        gpi_job_status_error(401, 'Não autenticado.');
    }

    try {
        $job = Database::findJobForUser(strtolower($id), $user['id']);
    } catch (RuntimeException $e) {
        error_log('[gpi] falha ao consultar job.');
        gpi_job_status_error(500, 'Erro interno. Tente novamente.');
    }
    if ($job === null) {
        gpi_job_status_error(404, 'Job não encontrado.');
    }

    $analysis = null;
    try {
        if (isset($job['status']) && in_array($job['status'], ['completed', 'partial'], true)
            && isset($job['audio_source_id']) && is_string($job['audio_source_id'])) {
            $row = Database::findAudioAnalysisBySource($job['audio_source_id']);
            if ($row !== null && isset($row['analysis_json'])) {
                $decoded = is_string($row['analysis_json'])
                    ? json_decode($row['analysis_json'], true) : $row['analysis_json'];
                $analysis = is_array($decoded) ? $decoded : null;
            }
        }
    } catch (RuntimeException $e) {
        error_log('[gpi] falha ao consultar análise.');
        gpi_job_status_error(500, 'Erro interno. Tente novamente.');
    }

    $contract = AudioJobs::buildStatusResult($job, $analysis);
    http_response_code(200);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'success' => true,
        'job_id' => $job['id'],
        'status' => $job['status'],
        'progress' => $contract['job']['progress'],
        'current_stage' => $job['current_stage'],
        'error_message' => $contract['job']['error_message'],
        'created_at' => $job['created_at'],
        'started_at' => $job['started_at'],
        'completed_at' => $job['completed_at'],
        'job' => $contract['job'],
        'result' => $contract['result'],
    ], JSON_UNESCAPED_UNICODE);
}

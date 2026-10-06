<?php
declare(strict_types=1);

/**
 * Handler da geração a partir da seleção (FASE 3P).
 *
 * POST /api/transcription/generate?format=json|midi|pdf
 * Corpo: {"job_id": "..."}. Usa a seleção PERSISTIDA (select 3O);
 * nada do frontend é fonte de verdade além do job_id.
 * Geração síncrona e determinística (sem modelos, sem IA nova).
 *
 * Arquivo de biblioteca: transcription_generate_process() é pura e
 * testável em CLI; transcription_generate_handle() faz HTTP + banco.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioConfig.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/AudioJobs.php';
require_once __DIR__ . '/ScoreTranscription.php';
require_once __DIR__ . '/ScorePdf.php';
require_once __DIR__ . '/PdfWriter.php';

/**
 * Núcleo puro: [httpCode, response|bytes, isBinary].
 * $job null => 404; $analysis null => 422.
 * $body opcional: se trouxer title/selected_instruments, a seleção é
 * revalidada (sanitizeSelection) e usada nesta geração; senão usa a
 * seleção persistida. Nada do cliente vira fonte de verdade sem
 * revalidação contra a análise.
 */
function transcription_generate_process($userId, $job, $analysis, string $format, $body = null): array
{
    if (!is_string($userId) || $userId === '') {
        return [401, ['success' => false, 'error' => 'Não autenticado.'], false];
    }
    if (!is_array($job)) {
        return [404, ['success' => false, 'error' => 'Job não encontrado.'], false];
    }
    if (!in_array($format, ['json', 'midi', 'pdf'], true)) {
        return [400, ['success' => false, 'error' => 'Formato inválido.'], false];
    }
    if (!is_array($analysis)) {
        return [422, ['success' => false, 'error' => 'Resultado indisponível para este job.'], false];
    }
    $status = $job['status'] ?? null;
    if (!in_array($status, ['completed', 'partial'], true)) {
        return [409, ['success' => false, 'error' => 'A análise ainda não está pronta.'], false];
    }
    $selection = isset($analysis['selection']) && is_array($analysis['selection']) ? $analysis['selection'] : null;
    if (is_array($body) && (array_key_exists('title', $body) || array_key_exists('selected_instruments', $body))) {
        try {
            $selection = AudioJobs::sanitizeSelection($job, $analysis, $body);
        } catch (SelectionError $e) {
            return [$e->httpCode, ['success' => false, 'error' => $e->getMessage()], false];
        } catch (InvalidArgumentException $e) {
            return [400, ['success' => false, 'error' => 'Seleção inválida.'], false];
        }
    }
    if ($selection === null || !isset($selection['selected_instruments'])
        || !is_array($selection['selected_instruments']) || $selection['selected_instruments'] === []) {
        return [409, ['success' => false, 'error' => 'Selecione os instrumentos antes de gerar.'], false];
    }
    try {
        $filtered = ScoreTranscription::filterSelectedTracks($analysis, $selection);
    } catch (SelectionError $e) {
        return [$e->httpCode, ['success' => false, 'error' => $e->getMessage()], false];
    } catch (InvalidArgumentException $e) {
        return [400, ['success' => false, 'error' => 'Seleção inválida.'], false];
    }
    $usable = 0;
    foreach ($filtered['tracks'] as $track) {
        $usable += isset($track['notes']) && is_array($track['notes']) ? count($track['notes']) : 0;
    }
    if ($usable === 0) {
        return [422, ['success' => false, 'error' => 'Nenhuma nota utilizável nas faixas selecionadas.'], false];
    }
    $music = isset($analysis['music']) && is_array($analysis['music']) ? $analysis['music'] : [];
    $tempo = isset($music['tempo']) && is_array($music['tempo']) ? $music['tempo'] : [];
    $bpm = isset($tempo['bpm']) && is_numeric($tempo['bpm']) ? (int) $tempo['bpm'] : null;
    if ($bpm === null || $bpm < 20 || $bpm > 300) {
        return [422, ['success' => false, 'error' => 'Andamento indisponível para gerar.'], false];
    }
    $meter = ScoreTranscription::meterLabel($music);
    $title = ScoreTranscription::cleanTitle($selection['title'] ?? null);
    $parts = ScoreTranscription::buildParts($filtered['tracks'], $music, $title, $bpm, $meter);
    $partWarnings = [];
    foreach ($parts as $part) {
        foreach ($part['warnings'] as $warning) {
            $partWarnings[] = $warning;
        }
    }
    $warnings = array_merge($filtered['warnings'], $partWarnings);
    $outStatus = (isset($analysis['status']) && $analysis['status'] === 'partial') ? 'partial' : 'completed';
    if ($format === 'midi') {
        try {
            $bytes = ScoreTranscription::renderMidi($parts, $bpm, $meter, $title);
        } catch (InvalidArgumentException $e) {
            return [422, ['success' => false, 'error' => $e->getMessage()], false];
        }
        return [200, $bytes, true];
    }
    if ($format === 'pdf') {
        // Todas as partes com score válido (ordem da seleção); título
        // uma única vez. Sem nenhuma parte renderizável → 422 honesto.
        $scores = [];
        $subtitles = [];
        foreach ($parts as $part) {
            if ($part['score'] === null) {
                continue;
            }
            $scores[] = $part['score'];
            $subtitles[] = $part['name'] . ' — ' . $part['family'];
        }
        if ($scores === []) {
            return [422, ['success' => false, 'error' => 'PDF indisponível: tonalidade ou compasso indeterminados.'], false];
        }
        try {
            $bytes = ScorePdf::renderParts($scores, $subtitles);
        } catch (InvalidArgumentException $e) {
            return [422, ['success' => false, 'error' => $e->getMessage()], false];
        }
        return [200, $bytes, true];
    }
    $summaryParts = [];
    foreach ($parts as $part) {
        $summaryParts[] = [
            'instrument_id' => $part['instrument_id'],
            'track_id' => $part['track_id'],
            'name' => $part['name'],
            'family' => $part['family'],
            'note_count' => count($part['notes']),
            'bpm' => $bpm,
            'time_signature' => $meter,
        ];
    }
    return [200, [
        'success' => true,
        'job_id' => (string) $job['id'],
        'title' => $title,
        'status' => $outStatus,
        'parts' => $summaryParts,
        'warnings' => array_merge($warnings, []),
        'confidence' => null,
        'statistics' => ['total_notes' => $usable, 'part_count' => count($parts)],
    ], false];
}

function gpi_generate_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

function transcription_generate_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        gpi_generate_error(405, 'Método não permitido. Utilize POST.');
    }

    $user = gpi_current_user();
    $raw = file_get_contents('php://input');
    $body = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($body)) {
        gpi_generate_error(400, 'JSON inválido.');
    }
    $jobId = $body['job_id'] ?? null;
    if (!is_string($jobId) || !AudioUpload::isUuid($jobId)) {
        gpi_generate_error(400, 'Job inválido.');
    }
    $format = 'json';
    if (isset($_GET['format']) && is_string($_GET['format'])) {
        $format = strtolower(trim($_GET['format']));
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
        [$code, $response, $isBinary] = transcription_generate_process(
            $user === null ? null : (string) $user['id'], $job, $analysis, $format
        );
    } catch (RuntimeException $e) {
        error_log('[gpi] falha na geração a partir da seleção.');
        gpi_generate_error(500, 'Erro interno. Tente novamente.');
    }

    if ($isBinary) {
        $isPdf = $format === 'pdf';
        http_response_code($code);
        header('Content-Type: ' . ($isPdf ? 'application/pdf' : 'audio/midi'));
        header('Content-Disposition: attachment; filename="partitura.' . ($isPdf ? 'pdf' : 'mid') . '"');
        header('Content-Length: ' . strlen($response));
        header('Cache-Control: private, max-age=0, must-revalidate');
        echo $response;
        exit;
    }
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

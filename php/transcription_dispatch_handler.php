<?php
declare(strict_types=1);

/**
 * Handler do dispatch (lógica movida de api/transcription/dispatch.php).
 *
 * Servido via api/transcription-router.php (rewrites preservam a URL
 * pública POST /api/transcription/dispatch). Arquivo de biblioteca: não
 * executa sozinho.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioConfig.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/AudioJobs.php';
require_once __DIR__ . '/Supabase.php';

function gpi_dispatch_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

/**
 * Envio real ao Worker via cURL (timeouts rígidos, sem segredos).
 * Retorna [httpStatus, body|null]. Transport errors => [0, null].
 */
function gpi_worker_post(string $url, array $payload): array
{
    $ch = curl_init($url);
    if ($ch === false) {
        return [0, null];
    }
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json'],
        CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_TIMEOUT => 20,
        CURLOPT_FOLLOWLOCATION => false,
    ]);
    $raw = curl_exec($ch);
    if ($raw === false) {
        curl_close($ch);
        return [0, null];
    }
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    $decoded = is_string($raw) ? json_decode($raw, true) : null;
    return [$status, is_array($decoded) ? $decoded : null];
}

/**
 * Núcleo puro do dispatch para o Worker (testável em CLI).
 * $httpPost($url, $payload): [status, body|null].
 * Retorna [http, response]. Nunca vaza detalhes do Worker nem segredos.
 */
function transcription_dispatch_deliver(string $jobStatus, string $workerBase, array $payload, callable $httpPost): array
{
    if ($jobStatus !== 'queued') {
        return [409, ['success' => false, 'error' => 'Job não está aguardando.']];
    }
    if ($workerBase === '') {
        return [200, ['success' => true, 'dry_run' => true, 'worker_accepted' => false]];
    }
    try {
        [$status, $body] = $httpPost(rtrim($workerBase, '/') . '/jobs/transcribe', $payload);
    } catch (\Throwable $e) {
        error_log('[gpi] dispatch: worker inacessível.');
        return [502, ['success' => false, 'error' => 'Worker indisponível. Tente novamente.']];
    }
    if ($status === 0) {
        error_log('[gpi] dispatch: timeout ou falha de rede no worker.');
        return [502, ['success' => false, 'error' => 'Worker indisponível. Tente novamente.']];
    }
    if ($status >= 200 && $status < 300 && is_array($body)
        && ($body['accepted'] ?? false) === true) {
        return [200, ['success' => true, 'dry_run' => false, 'worker_accepted' => true]];
    }
    if ($status === 400 || $status === 401 || $status === 403) {
        error_log('[gpi] dispatch: worker rejeitou o job.');
        return [502, ['success' => false, 'error' => 'Worker rejeitou o job.']];
    }
    error_log('[gpi] dispatch: worker indisponível.');
    return [502, ['success' => false, 'error' => 'Worker indisponível. Tente novamente.']];
}

function transcription_dispatch_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        gpi_dispatch_error(405, 'Método não permitido. Utilize POST.');
    }

    $user = gpi_current_user();
    if ($user === null) {
        gpi_dispatch_error(401, 'Não autenticado.');
    }

    $raw = file_get_contents('php://input');
    $body = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($body)) {
        gpi_dispatch_error(400, 'JSON inválido.');
    }
    $jobId = $body['job_id'] ?? null;
    if (!is_string($jobId) || !AudioUpload::isUuid($jobId)) {
        gpi_dispatch_error(400, 'Job inválido.');
    }

    try {
        $job = Database::findJobForUser(strtolower($jobId), $user['id']);
        if ($job === null) {
            gpi_dispatch_error(404, 'Job não encontrado.');
        }
        if ($job['status'] !== 'queued') {
            gpi_dispatch_error(409, 'Job não está aguardando.');
        }
        $source = Database::findAudioSourceForUser((string) $job['audio_source_id'], $user['id']);
        if ($source === null) {
            gpi_dispatch_error(404, 'Áudio não encontrado.');
        }
        $storage = Supabase::fromEnv();
        $audioUrl = $storage->createSignedUrl(
            AudioConfig::bucket(),
            (string) $source['storage_path'],
            AudioConfig::SIGNED_URL_TTL_S
        );
        $callback = AudioJobs::callbackUrl(
            $_SERVER['HTTPS'] ?? null,
            $_SERVER['HTTP_X_FORWARDED_PROTO'] ?? null,
            $_SERVER['HTTP_HOST'] ?? ''
        );
        // Prova interna de montagem (nunca serializada com segredo/URL).
        $internal = AudioJobs::buildWorkerPayload($job, $source, $audioUrl, $callback, AudioConfig::SIGNED_URL_TTL_S);
        unset($internal);
    } catch (RuntimeException $e) {
        error_log('[gpi] falha no dispatch de transcrição.');
        gpi_dispatch_error(500, 'Erro interno. Tente novamente.');
    } catch (InvalidArgumentException $e) {
        gpi_dispatch_error(400, 'Requisição inválida.');
    }

    // Envio real ao Worker (fora do try de banco/Supabase: falhas aqui
    // são do transporte e têm resposta própria, sem vazar detalhes).
    // Sem WORKER_BASE_URL configurada, preserva o dry_run anterior.
    $workerPayload = [
        'job_id' => $job['id'],
        'audio_source_id' => $source['id'],
        'audio_url' => $audioUrl,
        'callback_url' => $callback,
    ];
    [$dispatchHttp, $dispatchBody] = transcription_dispatch_deliver(
        (string) $job['status'], AudioConfig::workerBaseUrl(), $workerPayload, 'gpi_worker_post'
    );
    if ($dispatchHttp !== 200) {
        http_response_code($dispatchHttp);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($dispatchBody, JSON_UNESCAPED_UNICODE);
        exit;
    }

    http_response_code(200);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'success' => true,
        'job_id' => $job['id'],
        'status' => $job['status'],
        'dry_run' => (bool) ($dispatchBody['dry_run'] ?? false),
        'worker_accepted' => (bool) ($dispatchBody['worker_accepted'] ?? false),
        'audio_url_ready' => true,
        'worker_payload' => [
            'job_id' => $job['id'],
            'audio_source_id' => $source['id'],
            'callback_url' => $callback,
            'expires_in' => AudioConfig::SIGNED_URL_TTL_S,
        ],
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

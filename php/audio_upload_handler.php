<?php
declare(strict_types=1);

/**
 * Handler do upload de áudio (lógica movida de api/audio/upload.php).
 *
 * Servido via api/audio-router.php (rewrites preservam a URL pública
 * POST /api/audio/upload). Arquivo de biblioteca: não executa sozinho.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioConfig.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/Supabase.php';

function gpi_audio_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

function audio_upload_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        gpi_audio_error(405, 'Método não permitido. Utilize POST.');
    }

    $user = gpi_current_user();
    if ($user === null) {
        gpi_audio_error(401, 'Não autenticado.');
    }

    if (!isset($_FILES['audio']) || !is_array($_FILES['audio'])) {
        gpi_audio_error(400, 'Nenhum arquivo enviado.');
    }

    try {
        if (Database::countUserUploadsToday($user['id']) >= AudioConfig::MAX_UPLOADS_PER_DAY) {
            gpi_audio_error(429, 'Limite diário de uploads atingido.');
        }
    } catch (RuntimeException $e) {
        error_log('[gpi] falha ao verificar cota de upload.');
        gpi_audio_error(500, 'Erro interno. Tente novamente.');
    }

    [$ok, $error, $mime, $ext, $size] = AudioUpload::validateFile($_FILES['audio'], AudioConfig::maxBytes());
    if (!$ok) {
        gpi_audio_error($error === 'Arquivo muito grande.' ? 413 : 400, $error);
    }

    $tmp = $_FILES['audio']['tmp_name'];
    $uuid = AudioUpload::newUuid();
    try {
        $path = AudioUpload::storagePath($user['id'], $uuid, $ext);
        $original = AudioUpload::sanitizeFilename((string) ($_FILES['audio']['name'] ?? ''));
    } catch (InvalidArgumentException $e) {
        gpi_audio_error(400, 'Arquivo inválido.');
    }

    try {
        $storage = Supabase::fromEnv();
        $bucket = AudioConfig::bucket();
        $storage->ensureBucket($bucket);
        $storage->uploadObject($bucket, $path, $tmp, $mime);
    } catch (SupabaseException $e) {
        error_log('[gpi] falha no upload para o Storage.');
        gpi_audio_error(500, 'Erro interno. Tente novamente.');
    }

    try {
        $source = Database::createAudioSource($user['id'], [
            'source_type' => 'upload',
            'original_filename' => $original,
            'storage_path' => $path,
            'mime_type' => $mime,
            'file_size' => $size,
            'status' => 'uploaded',
        ]);
        if (!isset($source['id'])) {
            throw new RuntimeException('Falha ao registrar áudio.');
        }
        $job = Database::createTranscriptionJob($user['id'], (string) $source['id'], 'queued', 0, 'queued');
        if (!isset($job['id'])) {
            throw new RuntimeException('Falha ao criar job.');
        }
    } catch (RuntimeException $e) {
        error_log('[gpi] falha ao registrar upload de áudio.');
        gpi_audio_error(500, 'Erro interno. Tente novamente.');
    }

    http_response_code(201);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'success' => true,
        'audio_source_id' => $source['id'],
        'job_id' => $job['id'],
        'status' => 'queued',
    ], JSON_UNESCAPED_UNICODE);
}

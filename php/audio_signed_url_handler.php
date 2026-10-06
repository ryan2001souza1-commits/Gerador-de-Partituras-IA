<?php
declare(strict_types=1);

/**
 * Handler da signed URL (lógica movida de api/audio/signed-url.php).
 *
 * Servido via api/audio-router.php (rewrites preservam a URL pública
 * GET /api/audio/signed-url). Arquivo de biblioteca: não executa sozinho.
 */

require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/AudioConfig.php';
require_once __DIR__ . '/AudioUpload.php';
require_once __DIR__ . '/Supabase.php';

function gpi_signed_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

function audio_signed_url_handle(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
        header('Allow: GET');
        gpi_signed_error(405, 'Método não permitido. Utilize GET.');
    }

    $id = $_GET['source_id'] ?? null;
    if (!is_string($id) || !AudioUpload::isUuid($id)) {
        gpi_signed_error(400, 'Áudio não encontrado.');
    }

    $provided = $_SERVER['HTTP_X_WEBHOOK_SECRET'] ?? null;
    $viaWebhook = is_string($provided) && AudioConfig::checkWebhookSecret($provided);

    try {
        if ($viaWebhook) {
            $source = Database::findAudioSource(strtolower($id));
        } else {
            $user = gpi_current_user();
            if ($user === null) {
                gpi_signed_error(401, 'Não autenticado.');
            }
            $source = Database::findAudioSourceForUser(strtolower($id), $user['id']);
        }
    } catch (RuntimeException $e) {
        error_log('[gpi] falha ao buscar áudio.');
        gpi_signed_error(500, 'Erro interno. Tente novamente.');
    }
    if ($source === null) {
        gpi_signed_error(404, 'Áudio não encontrado.');
    }

    try {
        $storage = Supabase::fromEnv();
        $url = $storage->createSignedUrl(AudioConfig::bucket(), (string) $source['storage_path'], AudioConfig::SIGNED_URL_TTL_S);
    } catch (SupabaseException $e) {
        error_log('[gpi] falha ao assinar URL.');
        gpi_signed_error(500, 'Erro interno. Tente novamente.');
    }

    http_response_code(200);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'success' => true,
        'url' => $url,
        'expires_in' => AudioConfig::SIGNED_URL_TTL_S,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

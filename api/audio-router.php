<?php
declare(strict_types=1);

/**
 * Roteador do domínio áudio (consolidação p/ limite Hobby: 11 funções).
 *
 * URLs públicas preservadas via rewrites em vercel.json:
 *   POST /api/audio/upload[.php]     → op=upload
 *   GET  /api/audio/signed-url[.php]  → op=signed
 * Método, query string, multipart, headers e cookies passam intactos;
 * cada ramo executa exatamente a lógica original do handler.
 */

$op = $_GET['op'] ?? null;
if (!is_string($op) || ($op !== 'upload' && $op !== 'signed')) {
    $path = (string) (parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/');
    if (preg_match('#/signed-url(\.php)?$#', $path) === 1) {
        $op = 'signed';
    } elseif (preg_match('#/upload(\.php)?$#', $path) === 1) {
        $op = 'upload';
    }
}

if ($op === 'upload') {
    require_once __DIR__ . '/../php/audio_upload_handler.php';
    audio_upload_handle();
    exit;
} elseif ($op === 'signed') {
    require_once __DIR__ . '/../php/audio_signed_url_handler.php';
    audio_signed_url_handle();
    exit;
}

http_response_code(404);
header('Content-Type: application/json; charset=utf-8');
echo json_encode(['success' => false, 'error' => 'Não encontrado.'], JSON_UNESCAPED_UNICODE);

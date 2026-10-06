<?php
declare(strict_types=1);

/**
 * Roteador do domínio transcrição (consolidação p/ limite Hobby).
 *
 * URLs públicas preservadas via rewrites em vercel.json:
 *   POST /api/transcription/webhook[.php] → op=webhook
 *   GET  /api/transcription/status[.php]  → op=status
 *   POST /api/transcription/dispatch[.php] → op=dispatch
 *   POST /api/transcription/select[.php]  → op=select
 *   POST /api/transcription/generate[.php] → op=generate
 * Método, query, headers (incl. X-Webhook-Secret), body e cookies
 * passam intactos; cada ramo executa exatamente a lógica original.
 */

$op = $_GET['op'] ?? null;
if (!is_string($op) || ($op !== 'webhook' && $op !== 'status' && $op !== 'dispatch' && $op !== 'select' && $op !== 'generate')) {
    $path = (string) (parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/');
    if (preg_match('#/webhook(\.php)?$#', $path) === 1) {
        $op = 'webhook';
    } elseif (preg_match('#/status(\.php)?$#', $path) === 1) {
        $op = 'status';
    } elseif (preg_match('#/dispatch(\.php)?$#', $path) === 1) {
        $op = 'dispatch';
    } elseif (preg_match('#/select(\.php)?$#', $path) === 1) {
        $op = 'select';
    } elseif (preg_match('#/generate(\.php)?$#', $path) === 1) {
        $op = 'generate';
    }
}

if ($op === 'webhook') {
    require_once __DIR__ . '/../php/transcription_webhook_handler.php';
    transcription_webhook_handle();
    exit;
} elseif ($op === 'status') {
    require_once __DIR__ . '/../php/transcription_status_handler.php';
    transcription_status_handle();
    exit;
} elseif ($op === 'dispatch') {
    require_once __DIR__ . '/../php/transcription_dispatch_handler.php';
    transcription_dispatch_handle();
    exit;
} elseif ($op === 'select') {
    require_once __DIR__ . '/../php/transcription_select_handler.php';
    transcription_select_handle();
    exit;
} elseif ($op === 'generate') {
    require_once __DIR__ . '/../php/transcription_generate_handler.php';
    transcription_generate_handle();
    exit;
}

http_response_code(404);
header('Content-Type: application/json; charset=utf-8');
echo json_encode(['success' => false, 'error' => 'Não encontrado.'], JSON_UNESCAPED_UNICODE);

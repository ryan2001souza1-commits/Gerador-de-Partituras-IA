<?php
declare(strict_types=1);

/**
 * /api/score-pdf.php — Exporta partitura em PDF (gerado em memória).
 *
 * - GET  /api/score-pdf.php?id=UUID → PDF da partitura SALVA. Exige
 *   sessão válida E propriedade (user_id da sessão). Sem sessão → 401;
 *   de outro usuário/inexistente → 404.
 * - POST /api/score-pdf.php {score:{...}} → renderiza os dados enviados
 *   (partitura atual ainda não salva). Não acessa o banco nem exige
 *   login: só desenha o que o cliente enviou (limitado a 300 notas).
 *
 * Tudo em memória (compatível com serverless). Erros genéricos, sem
 * credenciais ou detalhes internos.
 */

require_once __DIR__ . '/../php/Auth.php';
require_once __DIR__ . '/../php/Database.php';
require_once __DIR__ . '/../php/PdfWriter.php';
require_once __DIR__ . '/../php/ScorePdf.php';

const GPI_PDF_MAX_BODY = 65536;

/** Envia o PDF como download. */
function gpi_send_pdf(string $bytes, string $filename): void
{
    $safe = preg_match('/^[A-Za-z0-9_-]+\.pdf$/', $filename) === 1 ? $filename : 'partitura.pdf';
    header('Content-Type: application/pdf');
    header('Content-Disposition: attachment; filename="' . $safe . '"');
    header('Content-Length: ' . strlen($bytes));
    header('Cache-Control: private, max-age=0, must-revalidate');
    echo $bytes;
    exit;
}

function gpi_pdf_error(int $status, string $message): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['success' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    exit;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

try {
    if ($method === 'GET') {
        $id = $_GET['id'] ?? null;
        if (!is_string($id) || preg_match('/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/', $id) !== 1) {
            gpi_pdf_error(400, 'Partitura não encontrada.');
        }
        $user = gpi_current_user();
        if ($user === null) {
            gpi_pdf_error(401, 'Não autenticado.');
        }
        $score = Database::findScoreForUser(strtolower($id), $user['id']);
        if ($score === null) {
            gpi_pdf_error(404, 'Partitura não encontrada.');
        }
        $data = $score['score_data'] ?? null;
        if (is_string($data)) {
            $decoded = json_decode($data, true);
            $data = (json_last_error() === JSON_ERROR_NONE) ? $decoded : null;
        }
        if (!is_array($data) || !isset($data['notes']) || !is_array($data['notes'])) {
            gpi_pdf_error(400, 'Partitura sem dados para exportar.');
        }
        // Título/atributos da linha têm precedência sobre o JSON antigo.
        if (isset($score['title']) && is_string($score['title']) && trim($score['title']) !== '') {
            $data['title'] = $score['title'];
        }
        try {
            $pdf = ScorePdf::render($data);
        } catch (InvalidArgumentException $e) {
            gpi_pdf_error(400, $e->getMessage());
        }
        gpi_send_pdf($pdf, 'partitura-' . substr(strtolower($id), 0, 8) . '.pdf');
    }

    if ($method === 'POST') {
        $raw = file_get_contents('php://input');
        if ($raw === false || $raw === '' || strlen($raw) > GPI_PDF_MAX_BODY) {
            gpi_pdf_error(400, 'JSON inválido.');
        }
        $body = json_decode($raw, true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($body) || !isset($body['score']) || !is_array($body['score'])) {
            gpi_pdf_error(400, 'JSON inválido.');
        }
        try {
            $pdf = ScorePdf::render($body['score']);
        } catch (InvalidArgumentException $e) {
            gpi_pdf_error(400, $e->getMessage());
        }
        gpi_send_pdf($pdf, 'partitura.pdf');
    }

    header('Allow: GET, POST');
    gpi_pdf_error(405, 'Método não permitido.');
} catch (RuntimeException $e) {
    error_log('[gpi] falha em score-pdf.php.');
    gpi_pdf_error(500, 'Erro interno. Tente novamente.');
}

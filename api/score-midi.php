<?php
declare(strict_types=1);

/**
 * /api/score-midi.php — Exporta partitura em MIDI (gerado em memória).
 *
 * - GET  /api/score-midi.php?id=UUID → MIDI da partitura SALVA. Exige
 *   sessão válida E propriedade (user_id da sessão). Sem sessão → 401;
 *   de outro usuário/inexistente → 404; sem dados → 400.
 * - POST /api/score-midi.php {score:{...}} → converte os dados enviados
 *   (partitura atual ainda não salva). Não acessa o banco nem exige
 *   login: só converte o que o cliente enviou (limitado a 300 notas).
 *
 * Tudo em memória (compatível com serverless). Erros genéricos, sem
 * credenciais ou detalhes internos.
 */

require_once __DIR__ . '/../php/Auth.php';
require_once __DIR__ . '/../php/Database.php';
require_once __DIR__ . '/../php/MidiWriter.php';
require_once __DIR__ . '/../php/ScoreMidi.php';

const GPI_MIDI_MAX_BODY = 65536;

/** Envia o .mid como download. */
function gpi_send_midi(string $bytes, string $filename): void
{
    $safe = preg_match('/^[A-Za-z0-9_-]+\.mid$/', $filename) === 1 ? $filename : 'partitura.mid';
    header('Content-Type: audio/midi');
    header('Content-Disposition: attachment; filename="' . $safe . '"');
    header('Content-Length: ' . strlen($bytes));
    header('Cache-Control: private, max-age=0, must-revalidate');
    echo $bytes;
    exit;
}

function gpi_midi_error(int $status, string $message): void
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
            gpi_midi_error(400, 'Partitura não encontrada.');
        }
        $user = gpi_current_user();
        if ($user === null) {
            gpi_midi_error(401, 'Não autenticado.');
        }
        $score = Database::findScoreForUser(strtolower($id), $user['id']);
        if ($score === null) {
            gpi_midi_error(404, 'Partitura não encontrada.');
        }
        $data = $score['score_data'] ?? null;
        if (is_string($data)) {
            $decoded = json_decode($data, true);
            $data = (json_last_error() === JSON_ERROR_NONE) ? $decoded : null;
        }
        if (!is_array($data) || !isset($data['notes']) || !is_array($data['notes'])) {
            gpi_midi_error(400, 'Partitura sem dados para exportar.');
        }
        if (isset($score['title']) && is_string($score['title']) && trim($score['title']) !== '') {
            $data['title'] = $score['title'];
        }
        try {
            $midi = ScoreMidi::render($data);
        } catch (InvalidArgumentException $e) {
            gpi_midi_error(400, $e->getMessage());
        }
        gpi_send_midi($midi, 'partitura-' . substr(strtolower($id), 0, 8) . '.mid');
    }

    if ($method === 'POST') {
        $raw = file_get_contents('php://input');
        if ($raw === false || $raw === '' || strlen($raw) > GPI_MIDI_MAX_BODY) {
            gpi_midi_error(400, 'JSON inválido.');
        }
        $body = json_decode($raw, true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($body) || !isset($body['score']) || !is_array($body['score'])) {
            gpi_midi_error(400, 'JSON inválido.');
        }
        try {
            $midi = ScoreMidi::render($body['score']);
        } catch (InvalidArgumentException $e) {
            gpi_midi_error(400, $e->getMessage());
        }
        gpi_send_midi($midi, 'partitura.mid');
    }

    header('Allow: GET, POST');
    gpi_midi_error(405, 'Método não permitido.');
} catch (RuntimeException $e) {
    error_log('[gpi] falha em score-midi.php.');
    gpi_midi_error(500, 'Erro interno. Tente novamente.');
}

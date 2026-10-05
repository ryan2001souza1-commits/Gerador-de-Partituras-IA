<?php
declare(strict_types=1);

/**
 * /api/scores.php — Partituras do usuário autenticado.
 *
 * - GET  /api/scores.php        → lista somente as partituras do usuário.
 * - GET  /api/scores.php?id=UUID → detalhe (com score_data) se pertencer ao usuário.
 * - DELETE /api/scores.php?id=UUID → exclui se pertencer ao usuário.
 *
 * O usuário é identificado EXCLUSIVAMENTE pela sessão PHP; nenhum
 * user_id do frontend é aceito. Não autenticado → 401. Partitura de
 * outro usuário ou inexistente → 404 (sem enumeração). Nenhum dado
 * sensível (password_hash etc.) é retornado.
 */

header('Content-Type: application/json; charset=utf-8');

require_once __DIR__ . '/../php/Auth.php';
require_once __DIR__ . '/../php/Database.php';

$user = gpi_current_user();
if ($user === null) {
    gpi_auth_respond(401, ['success' => false, 'error' => 'Não autenticado.']);
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

/** Lê e valida o parâmetro id (UUID). Retorna null quando ausente/inválido. */
function gpi_score_id_param(): ?string
{
    $id = $_GET['id'] ?? null;
    if (!is_string($id)) {
        return null;
    }
    if (!preg_match('/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/', $id)) {
        return null;
    }
    return strtolower($id);
}

try {
    if ($method === 'GET') {
        $id = gpi_score_id_param();
        if ($id === null && !isset($_GET['id'])) {
            $scores = Database::listScoresForUser($user['id']);
            gpi_auth_respond(200, ['success' => true, 'scores' => $scores]);
        }
        if ($id === null) {
            gpi_auth_respond(404, ['success' => false, 'error' => 'Partitura não encontrada.']);
        }
        $score = Database::findScoreForUser($id, $user['id']);
        if ($score === null) {
            gpi_auth_respond(404, ['success' => false, 'error' => 'Partitura não encontrada.']);
        }
        // PDO devolve JSONB como string; decodifica para entregar JSON real.
        foreach (['score_data', 'params'] as $col) {
            if (isset($score[$col]) && is_string($score[$col])) {
                $decoded = json_decode($score[$col], true);
                if (json_last_error() === JSON_ERROR_NONE) {
                    $score[$col] = $decoded;
                }
            }
        }
        gpi_auth_respond(200, ['success' => true, 'score' => $score]);
    }

    if ($method === 'DELETE') {
        $id = gpi_score_id_param();
        if ($id === null || !Database::deleteScoreForUser($id, $user['id'])) {
            gpi_auth_respond(404, ['success' => false, 'error' => 'Partitura não encontrada.']);
        }
        gpi_auth_respond(200, ['success' => true]);
    }

    header('Allow: GET, DELETE');
    gpi_auth_respond(405, ['success' => false, 'error' => 'Método não permitido.']);
} catch (RuntimeException $e) {
    error_log('[gpi] falha em scores.php.');
    gpi_auth_respond(500, ['success' => false, 'error' => 'Erro interno. Tente novamente.']);
}

<?php
declare(strict_types=1);

/**
 * POST /api/logout.php — Encerra a sessão atual. Sempre 200 quando o
 * método está correto, esteja ou não alguém autenticado.
 */

header('Content-Type: application/json; charset=utf-8');

require_once __DIR__ . '/../php/Auth.php';

gpi_require_post();
gpi_logout();
gpi_auth_respond(200, ['success' => true]);

<?php
declare(strict_types=1);

/**
 * GET /api/session.php — Estado da sessão atual.
 * {authenticated:true, user:{id,name,email}} ou {authenticated:false}.
 * Nunca expõe hash de senha ou qualquer segredo.
 */

header('Content-Type: application/json; charset=utf-8');

require_once __DIR__ . '/../php/Auth.php';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    header('Allow: GET');
    gpi_auth_respond(405, ['success' => false, 'error' => 'Método não permitido. Utilize GET.']);
}

$user = gpi_current_user();
if ($user === null) {
    gpi_auth_respond(200, ['success' => true, 'authenticated' => false]);
}
gpi_auth_respond(200, ['success' => true, 'authenticated' => true, 'user' => $user]);

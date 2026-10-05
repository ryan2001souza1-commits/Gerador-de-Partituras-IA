<?php
declare(strict_types=1);

/**
 * POST /api/login.php — Login (JSON: email, password).
 * Mensagem de erro genérica tanto para e-mail inexistente quanto para
 * senha incorreta (não permite enumeração de contas).
 */

header('Content-Type: application/json; charset=utf-8');

require_once __DIR__ . '/../php/Auth.php';
require_once __DIR__ . '/../php/Database.php';

gpi_require_post();

$input = gpi_read_json();
if ($input === null) {
    gpi_auth_respond(400, ['success' => false, 'error' => 'JSON inválido.']);
}

$validation = gpi_validate_credentials($input, false);
if (!$validation['valid']) {
    // Formato inválido também recebe a mensagem genérica de credenciais.
    gpi_auth_respond(401, ['success' => false, 'error' => 'E-mail ou senha inválidos.']);
}

try {
    $row = Database::findUserByEmail($validation['email']);
} catch (RuntimeException $e) {
    error_log('[gpi] falha no login.');
    gpi_auth_respond(500, ['success' => false, 'error' => 'Erro interno. Tente novamente.']);
}

$hash = ($row !== null && isset($row['password_hash']) && is_string($row['password_hash'])) ? $row['password_hash'] : '';
if ($row === null || $hash === '' || !password_verify($validation['password'], $hash)) {
    gpi_auth_respond(401, ['success' => false, 'error' => 'E-mail ou senha inválidos.']);
}

gpi_login_user((string) $row['id'], (string) $row['name'], (string) $row['email']);
gpi_auth_respond(200, [
    'success' => true,
    'user' => ['id' => $row['id'], 'name' => $row['name'], 'email' => $row['email']],
]);

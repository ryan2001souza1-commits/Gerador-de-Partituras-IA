<?php
declare(strict_types=1);

/**
 * POST /api/register.php — Cadastro (JSON: name, email, password).
 * Cria o usuário com password_hash(), inicia a sessão e devolve o
 * perfil público. E-mail duplicado → 409. Sem login automático fora
 * desta resposta: a sessão é criada aqui mesmo.
 */

header('Content-Type: application/json; charset=utf-8');

require_once __DIR__ . '/../php/Auth.php';
require_once __DIR__ . '/../php/Database.php';

gpi_require_post();

$input = gpi_read_json();
if ($input === null) {
    gpi_auth_respond(400, ['success' => false, 'error' => 'JSON inválido.']);
}

$validation = gpi_validate_credentials($input, true);
if (!$validation['valid']) {
    gpi_auth_respond(400, ['success' => false, 'error' => $validation['error']]);
}

try {
    if (Database::findUserByEmail($validation['email']) !== null) {
        gpi_auth_respond(409, ['success' => false, 'error' => 'Este e-mail já está cadastrado.']);
    }
    $user = Database::createUser($validation['name'], $validation['email'], $validation['password']);
} catch (RuntimeException $e) {
    if ($e->getMessage() === 'E-mail já cadastrado.') {
        gpi_auth_respond(409, ['success' => false, 'error' => 'Este e-mail já está cadastrado.']);
    }
    error_log('[gpi] falha no cadastro.');
    gpi_auth_respond(500, ['success' => false, 'error' => 'Erro interno. Tente novamente.']);
}

gpi_login_user((string) $user['id'], (string) $user['name'], (string) $user['email']);
gpi_auth_respond(201, [
    'success' => true,
    'user' => ['id' => $user['id'], 'name' => $user['name'], 'email' => $user['email']],
]);

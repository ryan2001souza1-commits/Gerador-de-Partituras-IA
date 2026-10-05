<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Sessão e autenticação (base).
 *
 * Sessões PHP seguras: cookie HttpOnly + SameSite=Lax (+ Secure em HTTPS),
 * nome de sessão próprio, regenerate no login (anti-fixação) e expiração
 * por inatividade. Nenhuma credencial é exposta por estas funções.
 */

const GPI_SESSION_IDLE_TIMEOUT = 3600; // 60 minutos
const GPI_SESSION_NAME = 'gpi_session';
const GPI_TOKEN_NAME = 'gpi_token';
const GPI_TOKEN_TTL = 2592000; // 30 dias (token persistente p/ serverless)

require_once __DIR__ . '/Database.php';

/**
 * Inicia a sessão com parâmetros seguros de cookie. Idempotente.
 */
function gpi_session_start(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $isHttps = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
    session_name(GPI_SESSION_NAME);
    session_set_cookie_params([
        'lifetime' => 0, // cookie de sessão (expira ao fechar o navegador)
        'path' => '/',
        'domain' => '',
        'secure' => $isHttps,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
}

/**
 * Garante método POST; responde 405 JSON caso contrário.
 */
function gpi_require_post(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
        header('Allow: POST');
        http_response_code(405);
        echo json_encode(['success' => false, 'error' => 'Método não permitido. Utilize POST.']);
        exit;
    }
}

/**
 * Lê o corpo JSON da requisição. Retorna null quando inválido.
 *
 * @return array<string, mixed>|null
 */
function gpi_read_json(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    if (strlen($raw) > 16384) {
        return null;
    }
    $data = json_decode($raw, true);
    if (json_last_error() !== JSON_ERROR_NONE || !is_array($data)) {
        return null;
    }
    return $data;
}

/**
 * Resposta JSON e encerramento.
 */
function gpi_auth_respond(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/**
 * Valida nome/e-mail/senha do cadastro e login. Retorna [ok, erro, dados].
 *
 * @param array<string, mixed> $input
 * @return array{valid: bool, error: string, name: string, email: string, password: string}
 */
function gpi_validate_credentials(array $input, bool $requireName): array
{
    $blank = ['valid' => false, 'error' => '', 'name' => '', 'email' => '', 'password' => ''];

    $name = isset($input['name']) && is_string($input['name']) ? trim($input['name']) : '';
    if ($requireName) {
        $len = function_exists('mb_strlen') ? mb_strlen($name, 'UTF-8') : strlen($name);
        if ($name === '' || $len > 100) {
            $blank['error'] = 'Informe seu nome (até 100 caracteres).';
            return $blank;
        }
    }

    $email = isset($input['email']) && is_string($input['email']) ? trim($input['email']) : '';
    if ($email === '' || strlen($email) > 255 || filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
        $blank['error'] = 'Informe um e-mail válido.';
        return $blank;
    }

    $password = isset($input['password']) && is_string($input['password']) ? $input['password'] : '';
    if (strlen($password) < 8 || strlen($password) > 72) {
        $blank['error'] = 'A senha deve ter entre 8 e 72 caracteres.';
        return $blank;
    }

    return ['valid' => true, 'error' => '', 'name' => $name, 'email' => $email, 'password' => $password];
}

/**
 * Autentica a sessão para o usuário informado (sem hash, sem segredos).
 * Emite também um token persistente (cookie HttpOnly) para que a
 * autenticação sobreviva entre invocações serverless sem sessão em arquivo.
 */
function gpi_login_user(string $id, string $name, string $email): void
{
    gpi_session_start();
    session_regenerate_id(true);
    $_SESSION['user'] = ['id' => $id, 'name' => $name, 'email' => $email];
    $_SESSION['last_activity'] = time();
    gpi_issue_token($id);
}

/**
 * Parâmetros do cookie do token persistente (mesmo padrão do de sessão).
 */
function gpi_token_cookie_params(int $expires): array
{
    $isHttps = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
    return [
        'expires' => $expires,
        'path' => '/',
        'domain' => '',
        'secure' => $isHttps,
        'httponly' => true,
        'samesite' => 'Lax',
    ];
}

/**
 * Cria token aleatório, persiste só o hash e envia o cookie.
 * Best-effort: falha aqui não derruba o login (sessão nativa continua).
 */
function gpi_issue_token(string $userId): void
{
    if ($userId === '' || headers_sent()) {
        return;
    }
    try {
        $token = bin2hex(random_bytes(32));
        $expiresAt = gmdate('Y-m-d H:i:s', time() + GPI_TOKEN_TTL);
        Database::createAuthToken($userId, hash('sha256', $token), $expiresAt);
        setcookie(GPI_TOKEN_NAME, $token, gpi_token_cookie_params(time() + GPI_TOKEN_TTL));
    } catch (Throwable $e) {
        error_log('[gpi] falha ao emitir token persistente.');
    }
}

/**
 * Restaura o usuário via token persistente (quando a sessão em arquivo
 * não existe nesta invocação). Repopula $_SESSION para o restante do fluxo.
 */
function gpi_user_from_token(): ?array
{
    $token = $_COOKIE[GPI_TOKEN_NAME] ?? null;
    if (!is_string($token) || strlen($token) !== 64 || !ctype_xdigit($token)) {
        return null;
    }
    try {
        $row = Database::findUserByTokenHash(hash('sha256', $token));
    } catch (Throwable $e) {
        return null;
    }
    if ($row === null || !isset($row['id'], $row['name'], $row['email'])) {
        return null;
    }
    $_SESSION['user'] = ['id' => (string) $row['id'], 'name' => (string) $row['name'], 'email' => (string) $row['email']];
    $_SESSION['last_activity'] = time();
    return ['id' => (string) $row['id'], 'name' => (string) $row['name'], 'email' => (string) $row['email']];
}

/**
 * Revoga o token atual (logout): apaga do banco e limpa o cookie.
 */
function gpi_clear_token(): void
{
    $token = $_COOKIE[GPI_TOKEN_NAME] ?? null;
    if (is_string($token) && strlen($token) === 64 && ctype_xdigit($token)) {
        try {
            Database::deleteAuthToken(hash('sha256', $token));
        } catch (Throwable $e) {
            error_log('[gpi] falha ao revogar token persistente.');
        }
    }
    if (!headers_sent()) {
        setcookie(GPI_TOKEN_NAME, '', gpi_token_cookie_params(time() - 42000));
    }
}

/**
 * Devolve o usuário da sessão ou null (inclui expiração por inatividade).
 *
 * @return array{id: string, name: string, email: string}|null
 */
function gpi_current_user(): ?array
{
    gpi_session_start();
    if (!isset($_SESSION['user']) || !is_array($_SESSION['user'])) {
        // Sessão em arquivo ausente (serverless): tenta o token persistente.
        return gpi_user_from_token();
    }
    $last = isset($_SESSION['last_activity']) ? (int) $_SESSION['last_activity'] : 0;
    if ($last <= 0 || (time() - $last) > GPI_SESSION_IDLE_TIMEOUT) {
        gpi_logout();
        return null;
    }
    $_SESSION['last_activity'] = time();
    $user = $_SESSION['user'];
    if (!isset($user['id'], $user['name'], $user['email'])) {
        gpi_logout();
        return null;
    }
    return ['id' => (string) $user['id'], 'name' => (string) $user['name'], 'email' => (string) $user['email']];
}

/**
 * Encerra a sessão por completo (dados + cookie).
 */
function gpi_logout(): void
{
    gpi_session_start();
    gpi_clear_token();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', [
            'expires' => time() - 42000,
            'path' => $params['path'] ?? '/',
            'domain' => $params['domain'] ?? '',
            'secure' => (bool) ($params['secure'] ?? false),
            'httponly' => true,
            'samesite' => $params['samesite'] ?? 'Lax',
        ]);
    }
    session_destroy();
}

<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Endpoint de geração (PHP puro, sem Python).
 *
 * Fluxo: Frontend (POST JSON) → valida → IA via HTTPS (quando configurada)
 * ou regras locais em PHP → valida/normaliza → Neon → JSON ao Frontend.
 *
 * Regras:
 * - Aceita somente POST (outros métodos → 405).
 * - Exige Content-Type: application/json.
 * - Valida todos os campos antes de gerar.
 * - NUNCA usa proc_open/exec/shell (inexistentes na Vercel).
 * - Erros internos retornam 500 genérico; detalhes vão apenas para error_log.
 * - Warnings nunca vazam para a saída (display_errors desligado).
 */

ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');

const GPI_MAX_BODY_BYTES = 65536;

/**
 * Envia a resposta JSON e encerra a execução.
 */
function gpi_respond(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/* ---------- 1. Método HTTP ---------- */
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method !== 'POST') {
    header('Allow: POST');
    gpi_respond(405, ['success' => false, 'error' => 'Método não permitido. Utilize POST.']);
}

/* ---------- 2. Content-Type ---------- */
$contentType = $_SERVER['CONTENT_TYPE'] ?? ($_SERVER['HTTP_CONTENT_TYPE'] ?? '');
if (stripos((string) $contentType, 'application/json') === false) {
    gpi_respond(400, ['success' => false, 'error' => 'Content-Type deve ser application/json.']);
}

/* ---------- 3. Leitura e decodificação do corpo ---------- */
$raw = file_get_contents('php://input');
if ($raw === false || $raw === '') {
    gpi_respond(400, ['success' => false, 'error' => 'JSON inválido.']);
}
if (strlen($raw) > GPI_MAX_BODY_BYTES) {
    gpi_respond(400, ['success' => false, 'error' => 'Corpo da requisição muito grande.']);
}
$data = json_decode($raw, true);
if (json_last_error() !== JSON_ERROR_NONE || !is_array($data)) {
    gpi_respond(400, ['success' => false, 'error' => 'JSON inválido.']);
}

/* ---------- 4. Validação dos campos ---------- */
require_once __DIR__ . '/../php/score_validator.php';
require_once __DIR__ . '/../php/Auth.php';
require_once __DIR__ . '/../php/Database.php';
require_once __DIR__ . '/../php/AiClient.php';
require_once __DIR__ . '/../php/ScoreFactory.php';

/* ---------- Instrumentação temporária (debug de travamento) ----------
 * Somente error_log com rótulos fixos + tempo decorrido. Nenhum dado,
 * segredo, prompt ou resposta é registrado. Remover após o diagnóstico. */
$GLOBALS['gpi_dbg_t0'] = microtime(true);
function gpi_dbg_step(int $step, string $label): void
{
    $t0 = $GLOBALS['gpi_dbg_t0'] ?? microtime(true);
    error_log('[gpi-debug] STEP ' . $step . ' ' . $label
        . ' +' . (int) round((microtime(true) - $t0) * 1000) . 'ms');
}
$validation = gpi_validate_score_input($data);
if (!$validation['valid']) {
    gpi_respond(400, ['success' => false, 'error' => $validation['error']]);
}
$payload = $validation['data'];

/* ---------- 5. Geração (IA via HTTPS ou regras locais em PHP) ---------- */
// Sem proc_open/exec: na Vercel não há Python no ambiente da função PHP.
// Com AI_API_KEY => OpenRouter/Responses; sem chave => gerador local.
// Falha da IA => erro controlado exato, SEM fallback silencioso.
gpi_dbg_step(1, 'generate-start');
$aiConfig = AiClient::config();
if ($aiConfig === null) {
    $score = ScoreFactory::buildLocal($payload);
    $meta = ['generator' => 'local', 'provider' => 'rule-based', 'model' => 'score-model-v1'];
    $message = 'Partitura gerada localmente (IA não configurada).';
    $result = ['success' => true, 'message' => $message, 'score' => $score, 'meta' => $meta];
} else {
    try {
        gpi_dbg_step(2, 'ai-start');
        $aiResp = AiClient::generate(ScoreFactory::buildPrompt($payload), $aiConfig);
        gpi_dbg_step(3, 'ai-end');
        $rawScore = AiClient::extractJson($aiResp['text']);
        $score = ScoreFactory::normalizeAiScore($rawScore, $payload, $aiResp);
        $result = [
            'success' => true,
            'message' => 'Partitura gerada com IA.',
            'score' => $score,
            'meta' => ['generator' => 'ai', 'provider' => $aiResp['provider'], 'model' => $aiResp['model']],
        ];
    } catch (AiException $e) {
        gpi_respond(500, ['success' => false, 'error' => 'Não foi possível gerar a partitura com IA. Tente novamente.']);
    } catch (ScoreValidationException $e) {
        error_log('[gpi] IA devolveu partitura inválida.');
        gpi_respond(500, ['success' => false, 'error' => 'Não foi possível gerar a partitura com IA. Tente novamente.']);
    } catch (Throwable $e) {
        error_log('[gpi] falha na geração por IA.');
        gpi_respond(500, ['success' => false, 'error' => 'Erro interno ao processar a solicitação.']);
    }
}

// Contrato da estrutura musical: notas como lista de objetos validada.
$notes = $result['score']['notes'] ?? null;
if (!is_array($notes) || $notes === []) {
    error_log('[gpi] partitura sem notas.');
    gpi_respond(500, ['success' => false, 'error' => 'Erro interno ao processar a solicitação.']);
}

/* ---------- 6. Persistência opcional para autenticados ---------- */
// Somente quando há cookie de sessão: o user_id vem EXCLUSIVAMENTE da
// sessão PHP (nunca do frontend). Falha aqui não cancela a geração.
$scoreId = null;
gpi_dbg_step(4, 'persistence-start');
if (isset($_COOKIE[GPI_SESSION_NAME])) {
    try {
        $sessionUser = gpi_current_user();
        if ($sessionUser !== null) {
            $pyTitle = isset($result['score']['title']) && is_string($result['score']['title']) ? trim($result['score']['title']) : '';
            $title = $pyTitle !== '' ? $pyTitle : (
                function_exists('mb_substr')
                    ? mb_substr($payload['descricao'], 0, 80, 'UTF-8')
                    : substr($payload['descricao'], 0, 80)
            );
            gpi_dbg_step(6, 'db-operation-start');
            $saved = Database::createScore($sessionUser['id'], [
                'title' => $title !== '' ? $title : 'Sem título',
                'description' => $payload['descricao'],
                'instrument' => $payload['instrumento'],
                'musical_key' => $payload['tom'],
                'tempo' => $payload['andamento'],
                'time_signature' => $payload['compasso'],
                'difficulty' => $payload['dificuldade'],
                'style' => $payload['estilo'],
                'status' => 'ready',
                'score_data' => $result['score'],
            ]);
            if (isset($saved['id'])) {
                $scoreId = $saved['id'];
                // Procedência registrada: meta do Python (ai|local), com
                // fallback para o gerador local histórico.
                $meta = (isset($result['meta']) && is_array($result['meta'])) ? $result['meta'] : [];
                $provider = (isset($meta['provider']) && is_string($meta['provider']) && $meta['provider'] !== '')
                    ? substr($meta['provider'], 0, 50) : 'rule-based';
                $model = (isset($meta['model']) && is_string($meta['model']) && $meta['model'] !== '')
                    ? substr($meta['model'], 0, 100) : 'score-model-v1';
                $gen = Database::createGeneration((string) $scoreId, $payload['descricao'], $provider, $model);
                if (isset($gen['id'])) {
                    Database::completeGeneration((string) $gen['id'], 'completed', $result['score']);
                }
                gpi_dbg_step(7, 'db-operation-end');
            }
        }
    } catch (Throwable $e) {
        error_log('[gpi] persistência da partitura falhou (best-effort).');
    }
}
gpi_dbg_step(8, 'persistence-end');

/* ---------- 7. Resposta de sucesso ---------- */
gpi_dbg_step(9, 'generate-end');
gpi_respond(200, [
    'success' => true,
    'message' => isset($result['message']) && is_string($result['message']) ? $result['message'] : 'Solicitação processada.',
    'score' => $result['score'],
    'score_id' => $scoreId,
]);

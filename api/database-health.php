<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Health check do banco (etapa 4).
 *
 * Verifica se DATABASE_URL existe e se o PostgreSQL responde a um
 * SELECT 1. Nunca retorna credenciais, hosts, stack traces ou
 * detalhes internos — apenas o formato público abaixo.
 */

header('Content-Type: application/json; charset=utf-8');

require_once __DIR__ . '/../php/Database.php';

function gpi_health_respond(int $status, bool $connected): void
{
    http_response_code($status);
    echo json_encode(
        ['success' => $connected, 'database' => $connected ? 'connected' : 'unavailable'],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
    );
    exit;
}

try {
    Database::pdo()->query('SELECT 1');
    gpi_health_respond(200, true);
} catch (Throwable $e) {
    gpi_health_respond(503, false);
}

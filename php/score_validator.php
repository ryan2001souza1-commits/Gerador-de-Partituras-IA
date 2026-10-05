<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Validação da solicitação de geração.
 *
 * Funções puras, sem efeitos colaterais: recebem os dados decodificados
 * do JSON e devolvem um resultado de validação. Usado por api/generate.php.
 * Nenhuma informação sensível é manipulada aqui.
 */

/**
 * Valores aceitos para cada campo (espelham os controles do formulário
 * em index.html). Comparação exata (case-sensitive).
 *
 * @return array<string, array<int, string>>
 */
function gpi_allowed_values(): array
{
    return [
        'instrumento' => ['Piano', 'Violão', 'Violino', 'Flauta', 'Baixo', 'Bateria', 'Outro'],
        'tom' => [
            'C Maior', 'D Maior', 'E Maior', 'F Maior', 'G Maior', 'A Maior', 'B Maior',
            'C Menor', 'D Menor', 'E Menor', 'F Menor', 'G Menor', 'A Menor', 'B Menor',
        ],
        'andamento' => ['Muito lento', 'Lento', 'Moderado', 'Rápido', 'Muito rápido'],
        'compasso' => ['2/4', '3/4', '4/4', '6/8', '12/8'],
        'dificuldade' => ['Iniciante', 'Intermediário', 'Avançado'],
        'estilo' => [
            'Clássico', 'Romântico', 'Jazz', 'Blues', 'Pop', 'Rock',
            'Gospel', 'Cinematográfico', 'Épico', 'Personalizado',
        ],
    ];
}

/**
 * Comprimento em caracteres (UTF-8) com fallback quando mbstring
 * não está disponível.
 */
function gpi_strlen(string $value): int
{
    if (function_exists('mb_strlen')) {
        return mb_strlen($value, 'UTF-8');
    }
    return strlen($value);
}

/**
 * Valida os dados da solicitação de geração.
 *
 * @param mixed $input Dados decodificados do corpo JSON.
 * @return array{valid: bool, error: string, data: array<string, string>}
 */
function gpi_validate_score_input($input): array
{
    if (!is_array($input)) {
        return ['valid' => false, 'error' => 'Dados inválidos.', 'data' => []];
    }

    $descricao = isset($input['descricao']) && is_string($input['descricao'])
        ? trim($input['descricao'])
        : '';

    if ($descricao === '') {
        return ['valid' => false, 'error' => 'Descrição é obrigatória.', 'data' => []];
    }

    if (gpi_strlen($descricao) > 2000) {
        return ['valid' => false, 'error' => 'Descrição deve ter no máximo 2000 caracteres.', 'data' => []];
    }

    $normalized = ['descricao' => $descricao];

    foreach (gpi_allowed_values() as $field => $allowed) {
        $value = isset($input[$field]) && is_string($input[$field]) ? $input[$field] : '';
        if (!in_array($value, $allowed, true)) {
            return ['valid' => false, 'error' => 'Valor inválido para o campo "' . $field . '".', 'data' => []];
        }
        $normalized[$field] = $value;
    }

    return ['valid' => true, 'error' => '', 'data' => $normalized];
}

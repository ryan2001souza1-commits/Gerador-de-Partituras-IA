<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Cliente HTTPS do provedor de IA.
 *
 * Somente stdlib (streams): POST {base}/responses com model,
 * instructions, input e max_output_tokens. Tolera envelope Responses
 * (output/output_text) e, por compatibilidade, o formato Chat
 * Completions (choices/message/content) — útil para gateways como o
 * OpenRouter. Timeout e teto de resposta sempre aplicados. A chave
 * nunca aparece em logs, erros ou respostas.
 */
class AiException extends RuntimeException
{
}

class AiClient
{
    const DEFAULT_BASE_URL = 'https://api.openai.com/v1';
    const DEFAULT_MODEL = 'gpt-4.1-mini';
    const DEFAULT_TIMEOUT_S = 25;
    const MAX_TIMEOUT_S = 120;
    const MAX_RESPONSE_BYTES = 131072;

    const UNAVAILABLE = 'Não foi possível gerar a partitura com IA. Tente novamente.';

    /**
     * Lê a configuração do ambiente. Retorna null quando sem chave
     * (geração local). Nunca expõe valores.
     *
     * @return array{base_url: string, model: string, timeout: int}|null
     */
    public static function config(): ?array
    {
        $key = getenv('AI_API_KEY');
        if (!is_string($key) || trim($key) === '') {
            return null;
        }
        $base = getenv('AI_BASE_URL');
        $base = (is_string($base) && trim($base) !== '') ? rtrim(trim($base), '/') : self::DEFAULT_BASE_URL;
        $model = getenv('AI_MODEL');
        $model = (is_string($model) && trim($model) !== '') ? trim($model) : self::DEFAULT_MODEL;
        $timeout = getenv('AI_TIMEOUT_S');
        $timeout = is_numeric($timeout) ? (int) $timeout : self::DEFAULT_TIMEOUT_S;
        if ($timeout <= 0 || $timeout > self::MAX_TIMEOUT_S) {
            $timeout = self::DEFAULT_TIMEOUT_S;
        }
        return ['key' => $key, 'base_url' => $base, 'model' => $model, 'timeout' => $timeout];
    }

    /**
     * Chama a IA e devolve ['text', 'provider', 'model'].
     * Erros viram AiException com mensagem segura.
     *
     * Transporte cURL com deadline total (CURLOPT_TIMEOUT) e teto de
     * conexão (CURLOPT_CONNECTTIMEOUT): sem espera indefinida. Mesma
     * URL, headers, payload, validação e exceções de antes.
     */
    public static function generate(string $prompt, array $config): array
    {
        $payload = json_encode([
            'model' => $config['model'],
            'instructions' => 'Você é um compositor que responde SOMENTE com JSON válido, sem texto antes ou depois, sem markdown.',
            'input' => $prompt,
            'temperature' => 0.7,
            'max_output_tokens' => 4000,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($payload === false) {
            throw new AiException(self::UNAVAILABLE);
        }
        $ch = curl_init($config['base_url'] . '/responses');
        if ($ch === false) {
            throw new AiException(self::UNAVAILABLE);
        }
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 25,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_POST => true,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'Accept: application/json',
                'Authorization: Bearer ' . $config['key'],
            ],
            CURLOPT_POSTFIELDS => $payload,
        ]);
        $raw = curl_exec($ch);
        if ($raw === false) {
            curl_close($ch);
            throw new AiException(self::UNAVAILABLE);
        }
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if (!is_string($raw) || $raw === '') {
            throw new AiException(self::UNAVAILABLE);
        }
        if (strlen($raw) > self::MAX_RESPONSE_BYTES) {
            throw new AiException(self::UNAVAILABLE);
        }
        if ($status !== 200) {
            throw new AiException(self::UNAVAILABLE);
        }
        $envelope = json_decode($raw, true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($envelope)) {
            throw new AiException(self::UNAVAILABLE);
        }
        $text = self::extractText($envelope);
        return ['text' => $text, 'provider' => 'openai-responses', 'model' => $config['model']];
    }

    /**
     * Extrai o texto do envelope Responses (output/output_text) ou do
     * formato Chat (choices/message/content). Recusa, status incompleto
     * ou ausência de texto => AiException.
     */
    public static function extractText(array $envelope): string
    {
        // Formato Chat Completions (fallback para gateways compatíveis).
        if (isset($envelope['choices']) && is_array($envelope['choices']) && isset($envelope['choices'][0])) {
            $content = $envelope['choices'][0]['message']['content'] ?? null;
            if (is_string($content) && trim($content) !== '') {
                return $content;
            }
            throw new AiException(self::UNAVAILABLE);
        }
        if (array_key_exists('status', $envelope) && $envelope['status'] !== null && $envelope['status'] !== 'completed') {
            throw new AiException(self::UNAVAILABLE);
        }
        $output = $envelope['output'] ?? null;
        if (!is_array($output) || $output === []) {
            throw new AiException(self::UNAVAILABLE);
        }
        $texts = [];
        foreach ($output as $item) {
            if (!is_array($item)) {
                continue;
            }
            if (($item['type'] ?? null) === 'refusal') {
                throw new AiException(self::UNAVAILABLE);
            }
            $content = $item['content'] ?? null;
            if (is_string($content)) {
                $texts[] = $content;
            } elseif (is_array($content)) {
                foreach ($content as $part) {
                    if (!is_array($part)) {
                        continue;
                    }
                    if (($part['type'] ?? null) === 'refusal') {
                        throw new AiException(self::UNAVAILABLE);
                    }
                    if (($part['type'] ?? null) === 'output_text' && isset($part['text']) && is_string($part['text'])) {
                        $texts[] = $part['text'];
                    }
                }
            }
        }
        $joined = trim(implode("\n", array_filter(array_map('trim', $texts), function ($t) {
            return $t !== '';
        })));
        if ($joined === '') {
            throw new AiException(self::UNAVAILABLE);
        }
        return $joined;
    }

    /**
     * Extrai o JSON (tolera cercas markdown e texto ao redor).
     * Nunca avalia código: apenas json_decode.
     *
     * @return array<string, mixed>
     */
    public static function extractJson(string $text): array
    {
        $cleaned = trim($text);
        if (strpos($cleaned, '```') === 0) {
            $lines = explode("\n", $cleaned);
            if (isset($lines[0]) && strpos($lines[0], '```') === 0) {
                array_shift($lines);
            }
            $last = count($lines) - 1;
            if ($last >= 0 && strpos(trim($lines[$last]), '```') === 0) {
                array_pop($lines);
            }
            $cleaned = trim(implode("\n", $lines));
        }
        $start = strpos($cleaned, '{');
        $end = strrpos($cleaned, '}');
        if ($start === false || $end === false || $end <= $start) {
            throw new AiException(self::UNAVAILABLE);
        }
        $obj = json_decode(substr($cleaned, $start, $end - $start + 1), true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($obj)) {
            throw new AiException(self::UNAVAILABLE);
        }
        return $obj;
    }
}

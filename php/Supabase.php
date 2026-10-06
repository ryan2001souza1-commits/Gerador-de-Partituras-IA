<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Cliente REST do Supabase Storage (FASE 1).
 *
 * Somente servidor: usa SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY do
 * ambiente. Nenhum segredo é impresso, registrado ou retornado.
 */
class SupabaseException extends RuntimeException
{
}

class Supabase
{
    private $base;
    private $key;

    public static function fromEnv(): self
    {
        $base = AudioConfig::supabaseUrl();
        $key = AudioConfig::serviceKey();
        if ($base === null || $key === null) {
            throw new SupabaseException('Armazenamento indisponível.');
        }
        return new self($base, $key);
    }

    private function __construct(string $base, string $key)
    {
        $this->base = $base;
        $this->key = $key;
    }

    /**
     * @return array{int, string} [http_status, corpo]
     * @throws SupabaseException em falha de transporte/timeout.
     */
    private function request(string $method, string $path, $body = null, string $contentType = 'application/json', int $timeout = 20, string $op = 'request'): array
    {
        $t0 = microtime(true);
        $ms = function () use ($t0) {
            return (int) round((microtime(true) - $t0) * 1000);
        };
        $ch = curl_init($this->base . $path);
        if ($ch === false) {
            error_log('[gpi-storage] op=' . $op . ' init-fail');
            throw new SupabaseException('Armazenamento indisponível.');
        }
        $headers = ['apikey: ' . $this->key, 'Authorization: Bearer ' . $this->key];
        $opts = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_HTTPHEADER => $headers,
        ];
        if ($body !== null) {
            $opts[CURLOPT_HTTPHEADER][] = 'Content-Type: ' . $contentType;
            $opts[CURLOPT_POSTFIELDS] = $body;
        }
        curl_setopt_array($ch, $opts);
        $raw = curl_exec($ch);
        if ($raw === false) {
            error_log('[gpi-storage] op=' . $op . ' transport-fail ms=' . $ms());
            throw new SupabaseException('Armazenamento indisponível.');
        }
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        error_log('[gpi-storage] op=' . $op . ' status=' . $status . ' ms=' . $ms());
        return [$status, is_string($raw) ? $raw : ''];
    }

    /** Garante bucket privado existente (idempotente). */
    public function ensureBucket(string $bucket): void
    {
        [$status] = $this->request('GET', '/storage/v1/bucket/' . rawurlencode($bucket), null, 'application/json', 20, 'ensure-get');
        if ($status === 200) {
            return;
        }
        [$created] = $this->request(
            'POST',
            '/storage/v1/bucket',
            json_encode(['name' => $bucket, 'public' => false]),
            'application/json',
            20,
            'ensure-create'
        );
        if ($created !== 200 && $created !== 201) {
            // Pode já existir (condição de corrida): reconfere.
            [$retry] = $this->request('GET', '/storage/v1/bucket/' . rawurlencode($bucket), null, 'application/json', 20, 'ensure-retry');
            if ($retry !== 200) {
                throw new SupabaseException('Armazenamento indisponível.');
            }
        }
    }

    /** Envia bytes para {bucket}/{path} (path com segmentos encodados). */
    public function uploadObject(string $bucket, string $path, string $localFile, string $mime, int $timeout = 100): void
    {
        $segments = array_map('rawurlencode', explode('/', $path));
        $data = file_get_contents($localFile);
        if ($data === false) {
            throw new SupabaseException('Armazenamento indisponível.');
        }
        [$status] = $this->request(
            'PUT',
            '/storage/v1/object/' . rawurlencode($bucket) . '/' . implode('/', $segments),
            $data,
            $mime,
            $timeout,
            'upload-put'
        );
        if ($status !== 200 && $status !== 201) {
            throw new SupabaseException('Armazenamento indisponível.');
        }
    }

    /** URL assinada temporária (segundos). Retorna a URL completa. */
    public function createSignedUrl(string $bucket, string $path, int $expiresIn): string
    {
        $segments = array_map('rawurlencode', explode('/', $path));
        [$status, $body] = $this->request(
            'POST',
            '/storage/v1/object/sign/' . rawurlencode($bucket) . '/' . implode('/', $segments),
            json_encode(['expiresIn' => $expiresIn]),
            'application/json',
            20,
            'sign-post'
        );
        if ($status !== 200) {
            throw new SupabaseException('Armazenamento indisponível.');
        }
        $decoded = json_decode($body, true);
        $signed = (is_array($decoded) && isset($decoded['signedURL']) && is_string($decoded['signedURL']))
            ? $decoded['signedURL'] : '';
        if ($signed === '') {
            throw new SupabaseException('Armazenamento indisponível.');
        }
        if (strpos($signed, 'http') === 0) {
            return $signed;
        }
        return $this->base . '/storage/v1' . ($signed[0] === '/' ? '' : '/') . $signed;
    }
}

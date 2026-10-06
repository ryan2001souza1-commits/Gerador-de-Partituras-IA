<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Validadores puros do upload de áudio (FASE 1).
 *
 * Funções sem banco e sem rede (testáveis em CLI). MIME sempre via
 * finfo sobre o conteúdo; nunca confia no tipo informado pelo cliente.
 */
class AudioUpload
{
    /**
     * Valida um item de $_FILES.
     * Retorna [ok, erro, mime, ext, size]. Mensagens seguras p/ usuário.
     */
    public static function validateFile(array $file, int $maxBytes): array
    {
        $fail = function ($error) {
            return [false, $error, '', '', 0];
        };
        $code = $file['error'] ?? UPLOAD_ERR_NO_FILE;
        if ($code === UPLOAD_ERR_INI_SIZE || $code === UPLOAD_ERR_FORM_SIZE) {
            return $fail('Arquivo muito grande.');
        }
        if ($code !== UPLOAD_ERR_OK) {
            return $fail('Nenhum arquivo enviado.');
        }
        $tmp = isset($file['tmp_name']) && is_string($file['tmp_name']) ? $file['tmp_name'] : '';
        if ($tmp === '' || !is_file($tmp)) {
            return $fail('Nenhum arquivo enviado.');
        }
        $size = isset($file['size']) ? (int) $file['size'] : 0;
        if ($size <= 0) {
            return $fail('Arquivo vazio.');
        }
        if ($size > $maxBytes) {
            return $fail('Arquivo muito grande.');
        }
        $orig = isset($file['name']) && is_string($file['name']) ? $file['name'] : '';
        $ext = strtolower(pathinfo($orig, PATHINFO_EXTENSION));
        if ($ext === '' || !isset(AudioConfig::ALLOWED_AUDIO[$ext])) {
            return $fail('Formato de áudio não suportado.');
        }
        $finfo = new finfo(FILEINFO_MIME_TYPE);
        $mime = $finfo->file($tmp);
        if (!is_string($mime) || $mime === '') {
            return $fail('Não foi possível verificar o arquivo.');
        }
        $mime = strtolower(trim(explode(';', $mime)[0]));
        if (!in_array($mime, AudioConfig::ALLOWED_AUDIO[$ext], true)) {
            return $fail('Formato de áudio não suportado.');
        }
        return [true, '', $mime, $ext, $size];
    }

    /** Nome original sanitizado para exibição (nunca vira identificador). */
    public static function sanitizeFilename(string $name): string
    {
        $base = basename(str_replace('\\', '/', $name));
        $base = preg_replace('/[\x00-\x1F\x7F]/', '', $base);
        $base = trim((string) $base);
        if ($base === '' || $base === '.' || $base === '..') {
            return 'audio';
        }
        if (function_exists('mb_substr')) {
            $base = mb_substr($base, 0, 255, 'UTF-8');
        } else {
            $base = substr($base, 0, 255);
        }
        return $base === '' ? 'audio' : $base;
    }

    /** UUID v4 para nomes e identificadores. */
    public static function newUuid(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0F) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3F) | 0x80);
        $h = bin2hex($b);
        return substr($h, 0, 8) . '-' . substr($h, 8, 4) . '-' . substr($h, 12, 4) . '-'
            . substr($h, 16, 4) . '-' . substr($h, 20, 12);
    }

    public static function isUuid(string $s): bool
    {
        return preg_match('/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/', $s) === 1;
    }

    /**
     * Caminho isolado por usuário: {user_id}/{uuid}/original.{ext}.
     * Aceita somente caracteres seguros (sem ../).
     */
    public static function storagePath(string $userId, string $uuid, string $ext): string
    {
        if (!self::isUuid($userId) || !self::isUuid($uuid)) {
            throw new InvalidArgumentException('Identificador inválido.');
        }
        if (!isset(AudioConfig::ALLOWED_AUDIO[$ext])) {
            throw new InvalidArgumentException('Extensão inválida.');
        }
        return strtolower($userId) . '/' . strtolower($uuid) . '/original.' . $ext;
    }

    /**
     * Extrai o videoId de URLs do YouTube (validação/parsing apenas;
     * nenhuma extração de áudio). Retorna null quando inválida.
     */
    public static function parseYouTubeUrl(string $url): ?string
    {
        $url = trim($url);
        if ($url === '' || strlen($url) > 2048) {
            return null;
        }
        $parts = parse_url($url);
        if (!is_array($parts) || !isset($parts['host'])) {
            return null;
        }
        $host = strtolower((string) $parts['host']);
        $path = (string) ($parts['path'] ?? '');
        $query = [];
        if (isset($parts['query'])) {
            parse_str((string) $parts['query'], $query);
        }
        $validId = function ($v) {
            return is_string($v) && preg_match('/^[A-Za-z0-9_-]{11}$/', $v) === 1 ? $v : null;
        };
        if ($host === 'youtu.be') {
            return $validId(ltrim($path, '/'));
        }
        if ($host === 'youtube.com' || $host === 'www.youtube.com' || $host === 'm.youtube.com') {
            if ($path === '/watch') {
                return $validId($query['v'] ?? null);
            }
            foreach (['/shorts/', '/embed/', '/live/', '/v/'] as $prefix) {
                if (strpos($path, $prefix) === 0) {
                    return $validId(substr($path, strlen($prefix)));
                }
            }
        }
        return null;
    }
}

<?php
declare(strict_types=1);

/**
 * Testes do pipeline de áudio FASE 1 (puros, sem banco/rede).
 * Uso: php php/tests_audio_pipeline.php  (saída 0 = tudo OK)
 */

error_reporting(E_ALL);
require __DIR__ . '/AudioConfig.php';
require __DIR__ . '/AudioUpload.php';
require __DIR__ . '/AudioJobs.php';

$fail = 0;
function t_check($label, $cond)
{
    global $fail;
    echo ($cond ? 'PASS' : 'FAIL') . " $label\n";
    if (!$cond) {
        $fail++;
    }
}

function tmp_wav(): string
{
    // WAV mínimo válido (44 bytes de header + silêncio).
    $data = 'RIFF' . pack('V', 36 + 8000) . 'WAVEfmt ' . pack('V', 16)
        . pack('v', 1) . pack('v', 1) . pack('V', 8000) . pack('V', 8000)
        . pack('v', 1) . pack('v', 8) . 'data' . pack('V', 8000)
        . str_repeat("\x80", 8000);
    $f = tempnam(sys_get_temp_dir(), 'gpi');
    file_put_contents($f, $data);
    return $f;
}

function fake_file(string $name, string $tmp, int $size, int $err = UPLOAD_ERR_OK): array
{
    return ['name' => $name, 'type' => 'x', 'tmp_name' => $tmp, 'error' => $err, 'size' => $size];
}

// 1. WAV válido passa (MIME real detectado).
$wav = tmp_wav();
[$ok, $err, $mime, $ext, $size] = AudioUpload::validateFile(fake_file('musica.wav', $wav, filesize($wav)), 25 * 1024 * 1024);
t_check('wav valido', $ok && $ext === 'wav' && $size > 0);

// 2. TXT renomeado p/ .mp3 é rejeitado (MIME real).
$txt = tempnam(sys_get_temp_dir(), 'gpi');
file_put_contents($txt, "texto puro, nao eh audio");
[$ok] = AudioUpload::validateFile(fake_file('musica.mp3', $txt, filesize($txt)), 25 * 1024 * 1024);
t_check('mp3 falso rejeitado', !$ok);

// 3. Extensão fora da lista.
[$ok] = AudioUpload::validateFile(fake_file('virus.exe', $wav, 100), 25 * 1024 * 1024);
t_check('extensao exe rejeitada', !$ok);

// 4. Arquivo grande.
[$ok, $err] = AudioUpload::validateFile(fake_file('g.mp3', $wav, 99 * 1024 * 1024), 25 * 1024 * 1024);
t_check('grande rejeitado', !$ok && $err === 'Arquivo muito grande.');

// 5. Ausente/vazio.
[$ok] = AudioUpload::validateFile(['error' => UPLOAD_ERR_NO_FILE], 100);
t_check('ausente rejeitado', !$ok);
[$ok] = AudioUpload::validateFile(fake_file('x.wav', '/nao/existe', 0), 100);
t_check('vazio rejeitado', !$ok);

// 6. Sanitização de nomes.
t_check('basename traversal', AudioUpload::sanitizeFilename('../../etc/passwd') === 'passwd');
t_check('vazio vira audio', AudioUpload::sanitizeFilename('   ') === 'audio');
t_check('normal preservado', AudioUpload::sanitizeFilename('Minha Música.mp3') === 'Minha Música.mp3');

// 7. UUID e path isolado.
$u1 = AudioUpload::newUuid();
$u2 = AudioUpload::newUuid();
t_check('uuid valido e unico', AudioUpload::isUuid($u1) && $u1 !== $u2);
t_check('uuid invalido', !AudioUpload::isUuid('x') && !AudioUpload::isUuid('../a'));
$p = AudioUpload::storagePath($u1, $u2, 'mp3');
t_check('path isolado', $p === strtolower($u1) . '/' . strtolower($u2) . '/original.mp3');
try {
    AudioUpload::storagePath('../x', $u2, 'mp3');
    t_check('path rejeita traversal', false);
} catch (InvalidArgumentException $e) {
    t_check('path rejeita traversal', true);
}

// 8. YouTube parsing.
t_check('watch', AudioUpload::parseYouTubeUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ') === 'dQw4w9WgXcQ');
t_check('youtu.be', AudioUpload::parseYouTubeUrl('https://youtu.be/dQw4w9WgXcQ') === 'dQw4w9WgXcQ');
t_check('shorts', AudioUpload::parseYouTubeUrl('https://www.youtube.com/shorts/dQw4w9WgXcQ') === 'dQw4w9WgXcQ');
t_check('embed', AudioUpload::parseYouTubeUrl('https://www.youtube.com/embed/dQw4w9WgXcQ') === 'dQw4w9WgXcQ');
t_check('invalida', AudioUpload::parseYouTubeUrl('https://vimeo.com/123') === null);
t_check('id curto', AudioUpload::parseYouTubeUrl('https://youtu.be/abc') === null);
t_check('nao-url', AudioUpload::parseYouTubeUrl('ola mundo') === null);

// 9. Sanitização de update de job.
$s = AudioJobs::sanitizeUpdate(['status' => 'processing', 'progress' => 50, 'current_stage' => 'analyzing', 'x' => 1]);
t_check('sanitize normaliza', $s === ['status' => 'processing', 'progress' => 50, 'current_stage' => 'analyzing']);
foreach ([-5, 150] as $badProgress) {
    try {
        AudioJobs::sanitizeUpdate(['status' => 'processing', 'progress' => $badProgress]);
        t_check("progress $badProgress rejeitado", false);
    } catch (InvalidArgumentException $e) {
        t_check("progress $badProgress rejeitado", true);
    }
}
$s = AudioJobs::sanitizeUpdate(['status' => 'completed', 'result' => ['bpm' => 120]]);
t_check('result array aceito (ignorado)', !array_key_exists('result', $s));
try {
    AudioJobs::sanitizeUpdate(['status' => 'completed', 'result' => 'x']);
    t_check('result nao-array rejeitado', false);
} catch (InvalidArgumentException $e) {
    t_check('result nao-array rejeitado', true);
}

// 12. Callback URL e payload interno (sem segredo).
t_check('callback https', AudioJobs::callbackUrl('on', null, 'example.com') === 'https://example.com/api/transcription/webhook');
t_check('callback http', AudioJobs::callbackUrl('', null, 'h.test:8080') === 'http://h.test:8080/api/transcription/webhook');
try {
    AudioJobs::callbackUrl(null, null, 'evil/../x');
    t_check('callback host invalido', false);
} catch (InvalidArgumentException $e) {
    t_check('callback host invalido', true);
}
$secret = 'segredo-simulado-123';
$p = AudioJobs::buildWorkerPayload(
    ['id' => 'j1'],
    ['id' => 's1'],
    'https://x/object?token=abc',
    'https://h/api/transcription/webhook',
    120
);
t_check('payload tem ids/callback', $p['job_id'] === 'j1' && $p['audio_source_id'] === 's1'
    && $p['callback_url'] === 'https://h/api/transcription/webhook' && $p['expires_in'] === 120);
t_check('payload sem segredo', strpos(json_encode($p), $secret) === false);
try {
    AudioJobs::sanitizeUpdate(['status' => 'magica']);
    t_check('status invalido', false);
} catch (InvalidArgumentException $e) {
    t_check('status invalido', true);
}
try {
    AudioJobs::sanitizeUpdate(['current_stage' => 'voando']);
    t_check('stage invalido', false);
} catch (InvalidArgumentException $e) {
    t_check('stage invalido', true);
}

// 10. Webhook: auth e corpo.
putenv('WORKER_WEBHOOK_SECRET=segredo-teste');
t_check('webhook secret ok', AudioConfig::checkWebhookSecret('segredo-teste'));
t_check('webhook secret errado', !AudioConfig::checkWebhookSecret('outro'));
putenv('WORKER_WEBHOOK_SECRET');
t_check('webhook sem segredo configurado', !AudioConfig::checkWebhookSecret('segredo-teste'));
$jid = AudioUpload::newUuid();
$w = AudioJobs::sanitizeWebhook(['job_id' => $jid, 'status' => 'processing', 'progress' => 10, 'current_stage' => 'analyzing']);
t_check('webhook valido', $w['job_id'] === strtolower($jid) && $w['status'] === 'processing');
try {
    AudioJobs::sanitizeWebhook(['job_id' => 'x', 'status' => 'processing']);
    t_check('webhook job invalido', false);
} catch (InvalidArgumentException $e) {
    t_check('webhook job invalido', true);
}
try {
    AudioJobs::sanitizeWebhook(['job_id' => $jid, 'status' => 'magica']);
    t_check('webhook status invalido', false);
} catch (InvalidArgumentException $e) {
    t_check('webhook status invalido', true);
}

// 11. Config defaults (sem expor valores).
putenv('AUDIO_MAX_SIZE_MB');
t_check('maxBytes default', AudioConfig::maxBytes() === 25 * 1024 * 1024);
t_check('bucket default', AudioConfig::bucket() === 'audio-inputs');

@unlink($wav);
@unlink($txt);
echo $fail === 0 ? "TUDO OK\n" : "FALHAS: $fail\n";
exit($fail === 0 ? 0 : 1);

<?php
declare(strict_types=1);

/**
 * Testes do dispatch real para o Worker (FASE WORKER REAL).
 * Puros: HTTP injetável, sem banco/rede.
 * Uso: php php/tests_dispatch_worker.php  (saída 0 = tudo OK)
 */

error_reporting(E_ALL);
require __DIR__ . '/AudioConfig.php';
require __DIR__ . '/AudioUpload.php';
require __DIR__ . '/AudioJobs.php';
require __DIR__ . '/transcription_dispatch_handler.php';

$fail = 0;
function t_check($label, $cond)
{
    global $fail;
    echo ($cond ? 'PASS' : 'FAIL') . " $label\n";
    if (!$cond) {
        $fail++;
    }
}

$payload = ['job_id' => 'j', 'audio_source_id' => 's',
    'audio_url' => 'https://cdn.test/f.wav', 'callback_url' => 'https://api.test/hook'];
$okPost = function ($url, $body) {
    return [200, ['accepted' => true, 'job_id' => 'j', 'status' => 'queued']];
};

// F) 200 accepted=true, job continua queued (só o webhook finaliza)
[$code, $resp] = transcription_dispatch_deliver('queued', 'http://worker:8001', $payload, $okPost);
t_check('worker accepted', $code === 200 && ($resp['worker_accepted'] ?? false) === true && ($resp['dry_run'] ?? true) === false);
// G/H) duplicado: só queued despacha
foreach (['processing', 'completed', 'partial', 'failed'] as $st) {
    $calls = 0;
    $counting = function ($url, $body) use (&$calls) {
        $calls++;
        return [200, ['accepted' => true]];
    };
    [$code] = transcription_dispatch_deliver($st, 'http://worker:8001', $payload, $counting);
    t_check('sem redispatch ' . $st, $code === 409 && $calls === 0);
}
// A) worker indisponível (transport throw)
$throwing = function ($url, $body) {
    throw new RuntimeException('conn refused');
};
[$code, $resp] = transcription_dispatch_deliver('queued', 'http://worker:8001', $payload, $throwing);
t_check('worker indisponivel', $code === 502 && $resp['error'] === 'Worker indisponível. Tente novamente.');
// E) timeout ([0, null])
[$code] = transcription_dispatch_deliver('queued', 'http://worker:8001', $payload, function ($u, $b) {
    return [0, null];
});
t_check('worker timeout', $code === 502);
// B) worker 400
[$code, $resp] = transcription_dispatch_deliver('queued', 'http://worker:8001', $payload, function ($u, $b) {
    return [400, ['accepted' => false]];
});
t_check('worker 400 sanitizado', $code === 502 && $resp['error'] === 'Worker rejeitou o job.');
// C) worker 401/403
foreach ([401, 403] as $denied) {
    [$code, $resp] = transcription_dispatch_deliver('queued', 'http://worker:8001', $payload, function ($u, $b) use ($denied) {
        return [$denied, null];
    });
    t_check('worker ' . $denied . ' sanitizado', $code === 502 && strpos(json_encode($resp), (string) $denied) === false);
}
// D) worker 500
[$code, $resp] = transcription_dispatch_deliver('queued', 'http://worker:8001', $payload, function ($u, $b) {
    return [500, null];
});
t_check('worker 500', $code === 502);
// I) segredo nunca aparece no log (só mensagens literais no handler)
$src = file_get_contents(__DIR__ . '/transcription_dispatch_handler.php');
$logLinesOk = true;
foreach (explode("\n", $src) as $line) {
    if (strpos($line, 'error_log') !== false && strpos($line, "'[gpi]") === false) {
        $logLinesOk = false;
    }
}
t_check('log sem segredos', $logLinesOk && strpos($src, 'WORKER_WEBHOOK_SECRET') === false
    && strpos($src, 'service_role') === false && strpos($src, 'callback_token') === false);
// J) payload sem secrets (usa buildWorkerPayload real)
$built = AudioJobs::buildWorkerPayload(
    ['id' => 'jid'], ['id' => 'sid'], 'https://cdn.test/f.wav?token=abc', 'https://api.test/hook', 120
);
$keys = array_keys($built);
sort($keys);
t_check('payload sem secrets', $keys === ['audio_source_id', 'audio_url', 'callback_token_hint', 'callback_url', 'expires_in', 'job_id']
    && $built['callback_token_hint'] === 'header X-Webhook-Secret'
    && strpos(json_encode($built), 'token=abc') !== false); // URL vai ao worker (necessária), segredo não
// Sem WORKER_BASE_URL: dry_run preservado
[$code, $resp] = transcription_dispatch_deliver('queued', '', $payload, function ($u, $b) {
    throw new RuntimeException('nao deve chamar');
});
t_check('sem worker dry_run', $code === 200 && ($resp['dry_run'] ?? false) === true);

echo $fail === 0 ? "TUDO OK\n" : "FALHAS: $fail\n";
exit($fail === 0 ? 0 : 1);

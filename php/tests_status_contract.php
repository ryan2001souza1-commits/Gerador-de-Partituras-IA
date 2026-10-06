<?php
declare(strict_types=1);

/**
 * Testes do contrato final p/ o frontend FASE 3M (puros, sem banco/rede).
 * Uso: php php/tests_status_contract.php  (saída 0 = tudo OK)
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

function job_row($status, $progress = 0)
{
    return [
        'id' => '123e4567-e89b-42d3-a456-426614174000',
        'status' => $status, 'progress' => $progress,
        'current_stage' => 'analyzing', 'error_message' => null,
        'created_at' => '2026-01-01 00:00:00', 'started_at' => null,
        'completed_at' => null,
    ];
}

function worker_analysis()
{
    return [
        'schema_version' => '1.0', 'status' => 'ready',
        'source' => ['duration_seconds' => 4.0, 'sample_rate' => 44100, 'channels' => 2, 'format' => 'wav'],
        'music' => [
            'tempo' => ['bpm' => 120.0, 'confidence' => 0.8],
            'key' => ['tonic' => 'C', 'mode' => 'major', 'confidence' => 0.75],
            'scale' => ['name' => 'C major', 'notes' => ['C', 'D', 'E', 'F', 'G', 'A', 'B'], 'confidence' => 0.75],
            'meter' => ['numerator' => 4, 'denominator' => 4, 'confidence' => 0.7],
            'grid' => ['division' => '1/8', 'beats' => 0.5, 'quantization_error' => 0.02, 'changed_notes' => 1],
            'chords' => [['start' => 0.0, 'end' => 1.0, 'duration' => 1.0, 'pitches' => [60, 64, 67], 'name' => 'C major', 'confidence' => 0.7]],
            'sections' => [],
        ],
        'tracks' => [[
            'track_id' => 'track_01', 'source_stem' => 'other',
            'instrument' => ['name' => 'piano', 'display_name' => 'Piano', 'family' => 'keyboards', 'confidence' => 0.87, 'source_label' => 'piano', 'top_candidates' => []],
            'evidence' => ['classifier' => 'panns-cnn14', 'direct_detection' => true, 'stem_type' => 'other', 'warnings' => []],
            'notes' => [['pitch' => 60, 'start' => 0.1, 'end' => 0.6, 'duration' => 0.5, 'velocity' => 80, 'confidence' => 0.7]],
            'statistics' => ['note_count' => 1, 'pitch_min' => 60, 'pitch_max' => 60, 'mean_velocity' => 80, 'mean_duration' => 0.5, 'density' => 2.0, 'active_seconds' => 0.6, 'silence_seconds' => 3.4],
            'musical_analysis' => ['bpm' => 120.0], 'selected' => true, 'editable' => true, 'status' => 'ready',
        ], [
            'track_id' => 'track_02', 'source_stem' => 'vocals',
            'instrument' => ['name' => null, 'display_name' => null, 'family' => 'unknown', 'confidence' => null, 'source_label' => null, 'top_candidates' => []],
            'evidence' => ['classifier' => 'unavailable', 'direct_detection' => false, 'stem_type' => 'vocals', 'warnings' => []],
            'notes' => [], 'statistics' => ['note_count' => 0, 'pitch_min' => null, 'pitch_max' => null, 'mean_velocity' => null, 'mean_duration' => null, 'density' => 0.0, 'active_seconds' => 0.0, 'silence_seconds' => 4.0],
            'musical_analysis' => null, 'selected' => false, 'editable' => false, 'status' => 'ambiguous',
        ]],
        'selection' => [], 'statistics' => ['total_notes' => 1, 'total_chords' => 1, 'pitch_min' => 60, 'pitch_max' => 60, 'mean_velocity' => 80, 'mean_duration' => 0.5],
        'warnings' => [['code' => 'AMBIGUOUS_INSTRUMENT', 'track_id' => 'track_02', 'message' => 'Instrumento não identificado.']],
        'confidence' => 0.7,
    ];
}

// 1. queued
$r = AudioJobs::buildStatusResult(job_row('queued', 5), null);
t_check('queued sem result', $r['success'] && $r['job']['status'] === 'queued' && $r['job']['progress'] === 5 && $r['result'] === null);
// 2. processing
$r = AudioJobs::buildStatusResult(job_row('processing', 55), null);
t_check('processing sem result', $r['job']['status'] === 'processing' && $r['job']['progress'] === 55 && $r['result'] === null);
// 3. completed
$r = AudioJobs::buildStatusResult(job_row('completed', 100), worker_analysis());
t_check('completed com result', $r['job']['progress'] === 100 && is_array($r['result']) && $r['result']['bpm'] === 120.0);
// 4. partial
$r = AudioJobs::buildStatusResult(job_row('partial', 100), worker_analysis());
t_check('partial com result', $r['job']['progress'] === 100 && is_array($r['result']));
// 5. failed
$r = AudioJobs::buildStatusResult(array_merge(job_row('failed', 45), ['error_message' => 'Falha X', 'current_stage' => 'separating']), null);
t_check('failed sem result e com erro', $r['result'] === null && $r['job']['error_message'] === 'Falha X' && $r['job']['progress'] === 45);

// 6-9. guardas do handler preservadas (auth, uuid, escopo, 404).
$handler = file_get_contents(__DIR__ . '/transcription_status_handler.php');
t_check('401 sem autenticacao', strpos($handler, "gpi_job_status_error(401, 'Não autenticado.')") !== false);
t_check('404 job ausente', strpos($handler, "gpi_job_status_error(404, 'Job não encontrado.')") !== false);
t_check('job_id invalido 400', strpos($handler, "gpi_job_status_error(400, 'Job inválido.')") !== false);
t_check('outro usuario isolado', strpos($handler, 'findJobForUser(strtolower($id), $user[') !== false);

// 10. instrumento conhecido
$r = AudioJobs::buildStatusResult(job_row('completed', 100), worker_analysis());
$inst = $r['result']['instruments'][0];
t_check('instrumento conhecido', $inst['id'] === 'piano' && $inst['name'] === 'Piano' && $inst['family'] === 'keyboards' && $inst['confidence'] === 0.87 && $inst['evidence']['source_track_ids'] === ['track_01']);
// 11. instrumento unknown não vira específico
$amb = array_values(array_filter($r['result']['tracks'], function ($t) {
    return $t['ambiguous'];
}));
t_check('track ambigua sem instrumento', count($amb) === 1 && $amb[0]['instrument_id'] === null && $amb[0]['family'] === 'unknown');
$ids = array_column($r['result']['instruments'], 'id');
t_check('unknown fora da lista', !in_array('unknown', $ids, true) && !in_array(null, $ids, true));
// 12. track ambígua marcada
t_check('track ambigua flag', $amb[0]['selected'] === false);
// 13. notas reais preservadas com track_id
t_check('notas reais', count($r['result']['notes']) === 1 && $r['result']['notes'][0]['pitch'] === 60 && $r['result']['notes'][0]['track_id'] === 'track_01');
// 14. BPM
t_check('bpm', $r['result']['bpm'] === 120.0);
// 15. tonalidade
t_check('tonalidade', $r['result']['key']['tonic'] === 'C' && $r['result']['key']['mode'] === 'major');
// 16. compasso
t_check('compasso', $r['result']['time_signature'] === '4/4');
// 17. warnings preservados e seguros
t_check('warnings', count($r['result']['warnings']) === 1 && $r['result']['warnings'][0]['code'] === 'AMBIGUOUS_INSTRUMENT');
t_check('warning sem path', strpos(json_encode($r['result']['warnings']), '/tmp') === false);
// 18. ausência de segredo
$json = json_encode($r);
$t_checkSemSegredo = true;
foreach (['service_role', 'token', 'secret', 'api_key', 'signed', 'cookie'] as $bad) {
    if (stripos($json, $bad) !== false) {
        $t_checkSemSegredo = false;
    }
}
t_check('ausencia de segredo', $t_checkSemSegredo);
// 19. ausência de signed URL
t_check('ausencia de signed url', strpos($json, 'http') === false && strpos($json, '/tmp') === false);
// 20. JSON sempre válido
t_check('json valido', is_string($json) && json_decode($json, true) !== null);

// Extras: partial aceito no webhook/sanitize; resultado exigido no terminal.
$jid = '123e4567-e89b-42d3-a456-426614174000';
$w = AudioJobs::sanitizeWebhook(['job_id' => $jid, 'status' => 'partial', 'progress' => 100, 'current_stage' => 'completed']);
t_check('webhook partial aceito', $w['status'] === 'partial');
try {
    AudioJobs::extractWebhookResult(['job_id' => $jid, 'status' => 'completed']);
    t_check('completed sem result rejeitado', false);
} catch (InvalidArgumentException $e) {
    t_check('completed sem result rejeitado', true);
}
$res = AudioJobs::extractWebhookResult(['job_id' => $jid, 'status' => 'completed', 'result' => ['transcription' => ['tracks' => []]]]);
t_check('result transcription extraido', isset($res['tracks']));
t_check('mensagem sanitizada', AudioJobs::sanitizeDisplayMessage('ver /tmp/x.wav em https://h.test/f') === 'ver [caminho] em [url]');

echo $fail === 0 ? "TUDO OK\n" : "FALHAS: $fail\n";
exit($fail === 0 ? 0 : 1);

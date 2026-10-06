<?php
declare(strict_types=1);

/**
 * Testes do endpoint de seleção FASE 3O (puros, sem banco/rede).
 * Uso: php php/tests_selection.php  (saída 0 = tudo OK)
 */

error_reporting(E_ALL);
require __DIR__ . '/AudioConfig.php';
require __DIR__ . '/AudioUpload.php';
require __DIR__ . '/AudioJobs.php';
require __DIR__ . '/transcription_select_handler.php';

$fail = 0;
function t_check($label, $cond)
{
    global $fail;
    echo ($cond ? 'PASS' : 'FAIL') . " $label\n";
    if (!$cond) {
        $fail++;
    }
}

function sel_job($status)
{
    return ['id' => '123e4567-e89b-42d3-a456-426614174000', 'status' => $status, 'audio_source_id' => 's1'];
}

function sel_analysis()
{
    // Forma real 3J/3K: instrumento aninhado em instrument.name.
    return ['tracks' => [
        ['track_id' => 'track_01', 'instrument' => ['name' => 'piano']],
        ['track_id' => 'track_02', 'instrument' => ['name' => 'piano']],
        ['track_id' => 'track_03', 'instrument' => ['name' => null]],
    ]];
}

function sel_body()
{
    return ['job_id' => '123e4567-e89b-42d3-a456-426614174000', 'title' => 'Minha música',
        'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01', 'track_02']]]];
}

// 1. 401 sem usuário
[$code] = transcription_select_process(null, sel_job('completed'), sel_analysis(), sel_body());
t_check('401 sem autenticacao', $code === 401);
// 2. job inexistente
[$code] = transcription_select_process('u1', null, sel_analysis(), sel_body());
t_check('404 job inexistente', $code === 404);
// 3. outro usuário (handler usa findJobForUser: mesma resposta 404, sem distinguir)
$handler = file_get_contents(__DIR__ . '/transcription_select_handler.php');
t_check('outro usuario isolado', strpos($handler, 'findJobForUser(strtolower($jobId), $user[') !== false);
// 4-5. queued/processing → 409
foreach (['queued', 'processing'] as $st) {
    [$code] = transcription_select_process('u1', sel_job($st), sel_analysis(), sel_body());
    t_check('409 job ' . $st, $code === 409);
}
// 6-7. completed/partial → 200
foreach (['completed', 'partial'] as $st) {
    [$code, $resp] = transcription_select_process('u1', sel_job($st), sel_analysis(), sel_body());
    t_check('200 job ' . $st, $code === 200 && $resp['success'] === true && $resp['title'] === 'Minha música');
}
// 8. vazio → 400
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(),
    ['job_id' => 'x', 'title' => 'T', 'selected_instruments' => []]);
t_check('400 selecao vazia', $code === 400);
// 9. instrumento inexistente → 422
$bad = sel_body();
$bad['selected_instruments'] = [['instrument_id' => 'theremin', 'track_ids' => ['track_01']]];
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), $bad);
t_check('422 instrumento inexistente', $code === 422);
// 10. track inexistente → 422
$bad = sel_body();
$bad['selected_instruments'] = [['instrument_id' => 'piano', 'track_ids' => ['track_99']]];
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), $bad);
t_check('422 track inexistente', $code === 422);
// 11. track de outro instrumento/job → 422
$bad = sel_body();
$bad['selected_instruments'] = [['instrument_id' => 'piano', 'track_ids' => ['track_03']]];
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), $bad);
t_check('422 track de outro instrumento', $code === 422);
// 12. título válido preservado
[$code, $resp] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), sel_body());
t_check('titulo valido', $code === 200 && $resp['selected_instruments'][0]['track_ids'] === ['track_01', 'track_02']);
// 13. título muito grande → 400
$bad = sel_body();
$bad['title'] = str_repeat('x', 121);
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), $bad);
t_check('400 titulo grande', $code === 400);
// 14. payload malformado → 400
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), ['job_id' => 'x']);
t_check('400 malformado', $code === 400);
[$code] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), 'nao-array');
t_check('400 nao-array', $code === 400);
// 15. JSON válido
[$code, $resp] = transcription_select_process('u1', sel_job('completed'), sel_analysis(), sel_body());
t_check('json valido', is_string(json_encode($resp)) && json_decode(json_encode($resp), true)['success'] === true);
// 16. nenhum secret retornado
$dump = json_encode($resp);
$clean = true;
foreach (['service_role', 'token', 'secret', 'api_key', 'signed', 'cookie', 'http'] as $bad) {
    if (stripos($dump, $bad) !== false) {
        $clean = false;
    }
}
t_check('sem secret retornado', $clean);
t_check('sem secret no payload aceito', strpos($handler, 'service_role') === false && strpos($handler, 'signed_url') === false);

echo $fail === 0 ? "TUDO OK\n" : "FALHAS: $fail\n";
exit($fail === 0 ? 0 : 1);

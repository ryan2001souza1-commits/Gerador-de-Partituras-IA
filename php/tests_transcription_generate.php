<?php
declare(strict_types=1);

/**
 * Testes da geração a partir da seleção FASE 3P (puros, sem banco/rede).
 * Uso: php php/tests_transcription_generate.php  (saída 0 = tudo OK)
 */

error_reporting(E_ALL);
require __DIR__ . '/AudioConfig.php';
require __DIR__ . '/AudioUpload.php';
require __DIR__ . '/AudioJobs.php';
require __DIR__ . '/MidiWriter.php';
require __DIR__ . '/ScoreTranscription.php';
require __DIR__ . '/ScorePdf.php';
require __DIR__ . '/PdfWriter.php';
require __DIR__ . '/transcription_generate_handler.php';

$fail = 0;
function t_check($label, $cond)
{
    global $fail;
    echo ($cond ? 'PASS' : 'FAIL') . " $label\n";
    if (!$cond) {
        $fail++;
    }
}

function g_note($pitch, $start, $dur, $vel = 80)
{
    return ['pitch' => $pitch, 'start' => $start, 'end' => $start + $dur,
        'duration' => $dur, 'velocity' => $vel, 'confidence' => 0.7];
}

function g_track($id, $inst, $notes, $status = 'ready')
{
    return ['track_id' => $id, 'source_stem' => 'other',
        'instrument' => ['name' => $inst, 'display_name' => $inst, 'family' => 'keyboards',
            'confidence' => 0.8, 'source_label' => $inst, 'top_candidates' => []],
        'evidence' => [], 'notes' => $notes, 'statistics' => ['note_count' => count($notes)],
        'musical_analysis' => null, 'selected' => true, 'editable' => true, 'status' => $status];
}

function g_analysis($tracks, $status = 'ready')
{
    return ['status' => $status,
        'music' => ['tempo' => ['bpm' => 120, 'confidence' => 0.8],
            'key' => ['tonic' => 'C', 'mode' => 'major', 'confidence' => 0.7],
            'meter' => ['numerator' => 4, 'denominator' => 4, 'confidence' => 0.7],
            'grid' => [], 'chords' => [], 'sections' => []],
        'tracks' => $tracks,
        'selection' => ['title' => 'Teste', 'selected_instruments' => [], 'updated_at' => '2026-01-01'],
        'warnings' => [], 'confidence' => 0.7];
}

function g_job($status = 'completed')
{
    return ['id' => '123e4567-e89b-42d3-a456-426614174000', 'status' => $status];
}

$piano = [g_note(60, 0.0, 0.5), g_note(64, 0.5, 0.5), g_note(67, 1.0, 1.0)];
$bass = [g_note(36, 0.0, 1.0), g_note(43, 1.0, 1.0)];
$violin = [g_note(76, 0.0, 2.0)];

// 1-3. uma/duas/três tracks distintas
$a = g_analysis([g_track('track_01', 'piano', $piano)]);
$f = ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]);
t_check('uma track', count($f['tracks']) === 1 && $f['tracks'][0]['track_id'] === 'track_01');
$a = g_analysis([g_track('track_01', 'piano', $piano), g_track('track_02', 'electric_bass', $bass)]);
$f = ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => [
    ['instrument_id' => 'piano', 'track_ids' => ['track_01']],
    ['instrument_id' => 'electric_bass', 'track_ids' => ['track_02']]]]);
t_check('duas tracks distintas', count($f['tracks']) === 2 && $f['tracks'][0]['track_id'] !== $f['tracks'][1]['track_id']);
$a = g_analysis([g_track('track_01', 'piano', $piano), g_track('track_02', 'electric_bass', $bass), g_track('track_03', 'violin', $violin)]);
$f = ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => [
    ['instrument_id' => 'piano', 'track_ids' => ['track_01']],
    ['instrument_id' => 'electric_bass', 'track_ids' => ['track_02']],
    ['instrument_id' => 'violin', 'track_ids' => ['track_03']]]]);
t_check('tres tracks distintas', count($f['tracks']) === 3);
// 4. vazia
try {
    ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => []]);
    t_check('vazia 400', false);
} catch (SelectionError $e) {
    t_check('vazia 400', $e->httpCode === 400 && $e->getMessage() === 'Selecione pelo menos um instrumento.');
}
// 5. instrumento inexistente
try {
    ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => [['instrument_id' => 'theremin', 'track_ids' => ['track_01']]]]);
    t_check('instrumento inexistente 422', false);
} catch (SelectionError $e) {
    t_check('instrumento inexistente 422', $e->httpCode === 422);
}
// 6. track inexistente
try {
    ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_99']]]]);
    t_check('track inexistente 422', false);
} catch (SelectionError $e) {
    t_check('track inexistente 422', $e->httpCode === 422);
}
// 7. track de outro instrumento
try {
    ScoreTranscription::filterSelectedTracks($a, ['selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_02']]]]);
    t_check('track de outro instrumento 422', false);
} catch (SelectionError $e) {
    t_check('track de outro instrumento 422', $e->httpCode === 422);
}
// 8-9. outro usuário / job inexistente (process puro)
[$code] = transcription_generate_process(null, g_job(), $a, 'json');
t_check('401 sem usuario', $code === 401);
[$code] = transcription_generate_process('u1', null, $a, 'json');
t_check('404 job inexistente', $code === 404);
// 10. partial com warning
$aPartial = g_analysis([g_track('track_01', 'piano', $piano)], 'partial');
$aPartial['selection'] = ['title' => 'T', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]];
[$code, $resp] = transcription_generate_process('u1', g_job('partial'), $aPartial, 'json');
$hasPartialWarn = false;
foreach (($resp['warnings'] ?? []) as $w) {
    if (($w['code'] ?? '') === 'PARTIAL_ANALYSIS') {
        $hasPartialWarn = true;
    }
}
t_check('partial continua', $code === 200 && $resp['status'] === 'partial' && $hasPartialWarn);
// 11-12. ambiguous selecionada/não selecionada
$aAmb = g_analysis([g_track('track_01', 'piano', $piano, 'ambiguous')]);
[$code, $resp] = transcription_generate_process('u1', g_job(), array_merge($aAmb, ['selection' => ['title' => 'T', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'json');
$kept = false;
foreach (($resp['warnings'] ?? []) as $w) {
    if (($w['code'] ?? '') === 'AMBIGUOUS_TRACK_KEPT') {
        $kept = true;
    }
}
t_check('ambiguous selecionada preservada', $code === 200 && $kept);
[$code, $resp] = transcription_generate_process('u1', g_job(), array_merge($aAmb, ['selection' => ['title' => 'T', 'selected_instruments' => []]]), 'json');
t_check('ambiguous nao selecionada ignorada', $code === 409);
// 13. nenhuma nota utilizável
$aEmpty = g_analysis([g_track('track_01', 'piano', [])]);
[$code, $resp] = transcription_generate_process('u1', g_job(), array_merge($aEmpty, ['selection' => ['title' => 'T', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'json');
t_check('sem notas 422', $code === 422);
// 14. notas preservadas exatamente
$aFull = g_analysis([g_track('track_01', 'piano', $piano)]);
[$code, $resp] = transcription_generate_process('u1', g_job(), array_merge($aFull, ['selection' => ['title' => 'T', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'midi');
t_check('midi bytes MThd', $code === 200 && substr($resp, 0, 4) === 'MThd' && strlen($resp) > 0);
$orig = $piano;
$f2 = ScoreTranscription::filterSelectedTracks($aFull, ['selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]);
t_check('notas preservadas', $f2['tracks'][0]['notes'] === $orig);
// 15. ordem determinística
$r1 = transcription_generate_process('u1', g_job(), array_merge($aFull, ['selection' => ['title' => 'T', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'json');
$r2 = transcription_generate_process('u1', g_job(), array_merge($aFull, ['selection' => ['title' => 'T', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'json');
t_check('ordem deterministica', json_encode($r1) === json_encode($r2));
// 16. título sanitizado
[$code, $resp] = transcription_generate_process('u1', g_job(), array_merge($aFull, ['selection' => ['title' => '<b>Oi</b>', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'json');
t_check('titulo sanitizado', $code === 200 && $resp['title'] === 'Oi');
// 17. MIDI válido (tracks, pitches, duração, sem NaN/Inf)
$multi = g_analysis([g_track('track_01', 'piano', $piano), g_track('track_02', 'electric_bass', $bass)]);
[$code, $mid] = transcription_generate_process('u1', g_job(), array_merge($multi, ['selection' => ['title' => 'T', 'selected_instruments' => [
    ['instrument_id' => 'piano', 'track_ids' => ['track_01']],
    ['instrument_id' => 'electric_bass', 'track_ids' => ['track_02']]]]]), 'midi');
$ntracks = $code === 200 ? unpack('n', substr($mid, 10, 2))[1] : 0;
t_check('midi multitrack', $code === 200 && $ntracks === 3 && strpos($mid, 'NaN') === false);
// 18. PDF válido (uma parte, gap documentado)
[$code, $pdf] = transcription_generate_process('u1', g_job(), array_merge($multi, ['selection' => ['title' => 'T', 'selected_instruments' => [
    ['instrument_id' => 'piano', 'track_ids' => ['track_01']]]]]), 'pdf');
t_check('pdf uma parte', $code === 200 && substr($pdf, 0, 5) === '%PDF-');

echo $fail === 0 ? "TUDO OK\n" : "FALHAS: $fail\n";
exit($fail === 0 ? 0 : 1);

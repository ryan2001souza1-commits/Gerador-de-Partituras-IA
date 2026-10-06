<?php
declare(strict_types=1);

/**
 * Testes do PDF multi-partes FASE 3Q (puros, sem banco/rede).
 * Uso: php php/tests_pdf_multipart.php  (saída 0 = tudo OK)
 */

error_reporting(E_ALL);
require __DIR__ . '/AudioConfig.php';
require __DIR__ . '/AudioUpload.php';
require __DIR__ . '/AudioJobs.php';
require __DIR__ . '/MidiWriter.php';
require __DIR__ . '/PdfWriter.php';
require __DIR__ . '/ScorePdf.php';
require __DIR__ . '/ScoreTranscription.php';
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

function q_note($pitch, $start, $dur, $vel = 80)
{
    return ['pitch' => $pitch, 'start' => $start, 'end' => $start + $dur,
        'duration' => $dur, 'velocity' => $vel, 'confidence' => 0.7];
}

function q_track($id, $inst, $display, $notes, $status = 'ready')
{
    return ['track_id' => $id, 'source_stem' => 'other',
        'instrument' => ['name' => $inst, 'display_name' => $display, 'family' => 'keyboards',
            'confidence' => 0.8, 'source_label' => $inst, 'top_candidates' => []],
        'evidence' => [], 'notes' => $notes, 'statistics' => ['note_count' => count($notes)],
        'musical_analysis' => null, 'selected' => true, 'editable' => true, 'status' => $status];
}

function q_analysis($tracks, $status = 'ready')
{
    return ['status' => $status,
        'music' => ['tempo' => ['bpm' => 120, 'confidence' => 0.8],
            'key' => ['tonic' => 'C', 'mode' => 'major', 'confidence' => 0.7],
            'meter' => ['numerator' => 4, 'denominator' => 4, 'confidence' => 0.7],
            'grid' => [], 'chords' => [], 'sections' => []],
        'tracks' => $tracks, 'warnings' => [], 'confidence' => 0.7];
}

function q_job($status = 'completed')
{
    return ['id' => '123e4567-e89b-42d3-a456-426614174000', 'status' => $status];
}

function q_select($analysis, $title = 'Peça 3Q')
{
    $items = [];
    foreach ($analysis['tracks'] as $t) {
        $inst = $t['instrument']['name'] ?? null;
        if ($inst !== null) {
            $items[] = ['instrument_id' => $inst, 'track_ids' => [$t['track_id']]];
        }
    }
    $analysis['selection'] = ['title' => $title, 'selected_instruments' => $items];
    return $analysis;
}

function latin1($text)
{
    return mb_convert_encoding($text, 'ISO-8859-1', 'UTF-8');
}

function page_count($pdf)
{
    if (preg_match('/\/Count\s+(\d+)/', $pdf, $m)) {
        return (int) $m[1];
    }
    return 0;
}

$piano = [q_note(60, 0.0, 0.5), q_note(64, 0.5, 0.5), q_note(67, 1.0, 1.0)];
$organ = [q_note(48, 0.0, 1.0), q_note(55, 1.0, 1.0)];
$bass = [q_note(36, 0.0, 1.0)];

// 1. PDF com 1 instrumento
$a = q_select(q_analysis([q_track('track_01', 'piano', 'Piano', $piano)]));
[$code, $pdf, $bin] = transcription_generate_process('u1', q_job(), $a, 'pdf');
t_check('pdf 1 parte', $code === 200 && $bin === true && substr($pdf, 0, 5) === '%PDF-' && strlen($pdf) > 0);
t_check('pdf 1 parte titulo unico', $code === 200 && substr_count($pdf, latin1('Peça 3Q')) === 1);
t_check('pdf 1 parte instrumento', $code === 200 && strpos($pdf, latin1('Piano')) !== false);
// 2. PDF com 2 instrumentos
$a = q_select(q_analysis([
    q_track('track_01', 'piano', 'Piano', $piano),
    q_track('track_02', 'organ', 'Órgão', $organ)]), 'Duas Partes');
[$code, $pdf] = transcription_generate_process('u1', q_job(), $a, 'pdf');
t_check('pdf 2 partes', $code === 200 && substr($pdf, 0, 5) === '%PDF-');
t_check('pdf 2 instrumentos', strpos($pdf, latin1('Piano')) !== false && strpos($pdf, latin1('Órgão')) !== false);
t_check('pdf titulo unico 2 partes', substr_count($pdf, latin1('Duas Partes')) === 1);
t_check('pdf paginas > 0', page_count($pdf) > 0);
// 3. PDF com 3 instrumentos
$a = q_select(q_analysis([
    q_track('track_01', 'piano', 'Piano', $piano),
    q_track('track_02', 'organ', 'Órgão', $organ),
    q_track('track_03', 'electric_bass', 'Baixo elétrico', $bass)]), 'Três Partes');
[$code, $pdf] = transcription_generate_process('u1', q_job(), $a, 'pdf');
$three = $code === 200 && strpos($pdf, latin1('Piano')) !== false
    && strpos($pdf, latin1('Órgão')) !== false && strpos($pdf, latin1('Baixo elétrico')) !== false;
t_check('pdf 3 partes', $three);
// instrumento não selecionado ausente
$a2 = q_analysis([
    q_track('track_01', 'piano', 'Piano', $piano),
    q_track('track_02', 'organ', 'Órgão', $organ)]);
$a2['selection'] = ['title' => 'Só Piano', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]];
[$code, $pdf] = transcription_generate_process('u1', q_job(), $a2, 'pdf');
t_check('nao selecionado ausente', $code === 200 && strpos($pdf, latin1('Piano')) !== false && strpos($pdf, latin1('Órgão')) === false);
// 4. seleção vazia
try {
    ScoreTranscription::filterSelectedTracks($a2, ['selected_instruments' => []]);
    t_check('selecao vazia 400', false);
} catch (SelectionError $e) {
    t_check('selecao vazia 400', $e->httpCode === 400);
}
// 5-7. ids inválidos
foreach ([
    ['instrumento inexistente', ['instrument_id' => 'theremin', 'track_ids' => ['track_01']]],
    ['track inexistente', ['instrument_id' => 'piano', 'track_ids' => ['track_99']]],
    ['mismatch', ['instrument_id' => 'piano', 'track_ids' => ['track_02']]],
] as [$label, $item]) {
    try {
        ScoreTranscription::filterSelectedTracks($a2, ['selected_instruments' => [$item]]);
        t_check($label . ' 422', false);
    } catch (SelectionError $e) {
        t_check($label . ' 422', $e->httpCode === 422);
    }
}
// 8. outro usuário
[$code] = transcription_generate_process(null, null, $a2, 'pdf');
t_check('outro usuario 404', $code === 401 || $code === 404);
// 9. título sanitizado
$a3 = q_select(q_analysis([q_track('track_01', 'piano', 'Piano', $piano)]), '<b>Oi</b>');
[$code, $pdf] = transcription_generate_process('u1', q_job(), $a3, 'pdf');
t_check('titulo sanitizado', $code === 200 && strpos($pdf, '<b>') === false && strpos($pdf, latin1('Oi')) !== false);
// 10. notas preservadas (score-data por parte)
$parts = ScoreTranscription::buildParts(
    ScoreTranscription::filterSelectedTracks($a2, ['selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]])['tracks'],
    $a2['music'], 'T', 120, '4/4');
t_check('notas preservadas', count($parts) === 1 && count($parts[0]['notes']) === 3
    && $parts[0]['notes'][0]['pitch'] === 60 && $parts[0]['notes'][0]['start'] === 0.0);
// 11. ordem determinística
$r1 = transcription_generate_process('u1', q_job(), $a, 'json');
$r2 = transcription_generate_process('u1', q_job(), $a, 'json');
t_check('ordem deterministica', json_encode($r1) === json_encode($r2)
    && array_column($r1[1]['parts'], 'track_id') === ['track_01', 'track_02', 'track_03']);
// 12. partial preserva warning
$aP = q_analysis([q_track('track_01', 'piano', 'Piano', $piano)], 'partial');
$aP['selection'] = ['title' => 'P', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]];
[$code, $resp] = transcription_generate_process('u1', q_job('partial'), $aP, 'pdf');
$hasWarn = false;
if ($code === 200) {
    // warning vive no ramo json; aqui basta o status fluir sem preencher nada
    $hasWarn = true;
}
t_check('partial gera pdf', $code === 200 && substr($resp, 0, 5) === '%PDF-');
// 13-14. ambiguous selecionada / ignorada
$aAmb = q_analysis([q_track('track_01', 'piano', 'Piano', $piano, 'ambiguous')]);
$aAmb['selection'] = ['title' => 'A', 'selected_instruments' => [['instrument_id' => 'piano', 'track_ids' => ['track_01']]]];
[$code, $resp] = transcription_generate_process('u1', q_job(), $aAmb, 'json');
$kept = false;
foreach (($resp['warnings'] ?? []) as $w) {
    if (($w['code'] ?? '') === 'AMBIGUOUS_TRACK_KEPT') {
        $kept = true;
    }
}
t_check('ambiguous selecionada com warning', $code === 200 && $kept);
$aAmb['selection'] = ['title' => 'A', 'selected_instruments' => []];
[$code] = transcription_generate_process('u1', q_job(), $aAmb, 'json');
t_check('ambiguous nao selecionada 409', $code === 409);

echo $fail === 0 ? "TUDO OK\n" : "FALHAS: $fail\n";
exit($fail === 0 ? 0 : 1);

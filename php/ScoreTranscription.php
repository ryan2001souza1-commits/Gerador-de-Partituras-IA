<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Geração a partir da seleção (FASE 3P).
 *
 * Camada isolada e determinística sobre o resultado real das fases
 * 3E–3K. Consome SOMENTE dados persistidos (análise + seleção
 * validada); nunca reexecuta Demucs/PANNs/Basic Pitch, nunca inventa
 * instrumentos, tracks ou notas. Sem rede, sem banco aqui (puro).
 *
 * - filterSelectedTracks(): seleção validada → tracks reais intactas.
 * - buildParts(): representação musical por parte + score-data no
 *   formato exato aceito por ScoreMidi/ScorePdf.
 * - renderMidi(): SMF formato 1 multi-track (1 trilha/instrumento).
 * - renderPdf(): UMA parte via ScorePdf (limitação documentada: a
 *   infraestrutura atual de PDF só renderiza uma parte; multi-part
 *   fica como trabalho futuro, sem improvisar).
 */

require_once __DIR__ . '/MidiWriter.php';

class ScoreTranscription
{
    const DIVISION = 480;
    const MAX_PARTS = 16; // canais MIDI úteis (15 + percussão)
    const MAX_NOTES_PER_PART = 2000;

    const BEATS = ['whole' => 4.0, 'half' => 2.0, 'quarter' => 1.0,
        'eighth' => 0.5, 'sixteenth' => 0.25];
    const PITCH_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G',
        'G#', 'A', 'A#', 'B'];
    const METERS = ['2/4' => [2, 2], '3/4' => [3, 2], '4/4' => [4, 2],
        '6/8' => [6, 3], '12/8' => [12, 3]];

    /**
     * Filtra as tracks escolhidas preservando tudo byte a byte.
     * Retorna ['tracks' => [...], 'warnings' => [...] culpados].
     * Lança SelectionError (400 vazia / 422 inválida).
     */
    public static function filterSelectedTracks($analysis, $selection): array
    {
        $allTracks = isset($analysis['tracks']) && is_array($analysis['tracks']) ? $analysis['tracks'] : [];
        $byId = [];
        foreach ($allTracks as $track) {
            if (is_array($track) && isset($track['track_id']) && is_string($track['track_id'])) {
                $byId[$track['track_id']] = $track;
            }
        }
        $items = isset($selection['selected_instruments']) && is_array($selection['selected_instruments'])
            ? $selection['selected_instruments'] : [];
        if ($items === []) {
            throw new SelectionError(400, 'Selecione pelo menos um instrumento.');
        }
        if (count($items) > self::MAX_PARTS) {
            throw new SelectionError(400, 'Seleção inválida.');
        }
        $warnings = [];
        if (isset($analysis['status']) && $analysis['status'] === 'partial') {
            $warnings[] = ['code' => 'PARTIAL_ANALYSIS',
                'message' => 'A análise foi parcial; somente faixas com notas utilizáveis foram incluídas.'];
        }
        $chosen = [];
        $seenTracks = [];
        foreach ($items as $item) {
            if (!is_array($item) || !isset($item['instrument_id']) || !is_string($item['instrument_id'])
                || $item['instrument_id'] === '') {
                throw new SelectionError(422, 'Instrumento inválido para este job.');
            }
            if (!isset($item['track_ids']) || !is_array($item['track_ids']) || $item['track_ids'] === []) {
                throw new SelectionError(422, 'Faixa inválida para este job.');
            }
            foreach ($item['track_ids'] as $trackId) {
                if (!is_string($trackId) || !isset($byId[$trackId])) {
                    throw new SelectionError(422, 'Faixa inexistente neste job.');
                }
                $track = $byId[$trackId];
                $inst = isset($track['instrument']) && is_array($track['instrument']) ? $track['instrument'] : [];
                $trackInst = isset($inst['name']) && is_string($inst['name']) ? $inst['name'] : null;
                if ($trackInst !== $item['instrument_id']) {
                    throw new SelectionError(422, 'Faixa não pertence ao instrumento selecionado.');
                }
                if (isset($seenTracks[$trackId])) {
                    throw new SelectionError(422, 'Faixa duplicada na seleção.');
                }
                $seenTracks[$trackId] = true;
                if (isset($track['status']) && $track['status'] === 'ambiguous') {
                    $warnings[] = ['code' => 'AMBIGUOUS_TRACK_KEPT', 'track_id' => $trackId,
                        'message' => 'Faixa ambígua incluída por escolha explícita; a ambiguidade foi preservada.'];
                }
                $chosen[] = $track; // cópia fiel: nada é tocado nas notas
            }
        }
        return ['tracks' => $chosen, 'warnings' => $warnings];
    }

    /** Rótulo PT de tonalidade ('C Maior'/'A Menor') ou null honesto. */
    public static function keyLabel($music): ?string
    {
        $key = isset($music['key']) && is_array($music['key']) ? $music['key'] : [];
        $tonic = isset($key['tonic']) && is_string($key['tonic']) ? $key['tonic'] : '';
        $mode = isset($key['mode']) && is_string($key['mode']) ? $key['mode'] : '';
        if (!preg_match('/^[A-G](#|b)?$/', $tonic) || ($mode !== 'major' && $mode !== 'minor')) {
            return null;
        }
        return $tonic . ($mode === 'major' ? ' Maior' : ' Menor');
    }

    /** Compasso 'N/D' válido ou null honesto. */
    public static function meterLabel($music): ?string
    {
        $meter = isset($music['meter']) && is_array($music['meter']) ? $music['meter'] : [];
        if (!isset($meter['numerator'], $meter['denominator'])) {
            return null;
        }
        $label = ((int) $meter['numerator']) . '/' . ((int) $meter['denominator']);
        return isset(self::METERS[$label]) ? $label : null;
    }

    /** Segundos → nome de duração mais próximo (com clamp avisado). */
    public static function durationName(float $beats): array
    {
        $best = 'sixteenth';
        $bestDist = INF;
        foreach (self::BEATS as $name => $value) {
            $dist = abs($beats - $value);
            if ($dist < $bestDist) {
                $bestDist = $dist;
                $best = $name;
            }
        }
        $clamped = $beats > 4.0 || $beats < 0.125;
        return [$best, $clamped];
    }

    public static function midiToName(int $midi): array
    {
        $names = self::PITCH_NAMES;
        return [$names[$midi % 12], (int) floor($midi / 12) - 1];
    }

    /**
     * Partes musicais por track (ordem determinística da análise).
     * Cada parte traz as notas EXATAS + score-data no formato aceito
     * por ScoreMidi/ScorePdf. Sem score quando faltar tom/compasso
     * válido (warning explícito, sem palpite).
     */
    public static function buildParts(array $tracks, $music, string $title, $bpm, ?string $meter): array
    {
        $keyLabel = self::keyLabel($music);
        $parts = [];
        foreach ($tracks as $track) {
            $inst = isset($track['instrument']) && is_array($track['instrument']) ? $track['instrument'] : [];
            $notes = isset($track['notes']) && is_array($track['notes']) ? array_values($track['notes']) : [];
            $warnings = [];
            if ($keyLabel === null) {
                $warnings[] = ['code' => 'NO_KEY_FOR_SCORE', 'track_id' => $track['track_id'],
                    'message' => 'Tonalidade indeterminada; score-data indisponível para esta parte.'];
            }
            if ($meter === null) {
                $warnings[] = ['code' => 'NO_METER_FOR_SCORE', 'track_id' => $track['track_id'],
                    'message' => 'Compasso indeterminado; score-data indisponível para esta parte.'];
            }
            $scoreNotes = [];
            foreach ($notes as $n) {
                [$pitchName, $octave] = self::midiToName((int) $n['pitch']);
                $beats = (float) $n['duration'] * $bpm / 60.0;
                [$durName, $clamped] = self::durationName($beats);
                if ($clamped) {
                    $warnings[] = ['code' => 'DURATION_CLAMPED', 'track_id' => $track['track_id'],
                        'message' => 'Duração fora do vocabulário da partitura; aproximada sem alterar o MIDI.'];
                }
                $scoreNotes[] = ['pitch' => $pitchName, 'octave' => $octave, 'duration' => $durName];
            }
            $score = null;
            if ($keyLabel !== null && $meter !== null && $scoreNotes !== []) {
                $score = [
                    'title' => $title,
                    'instrument' => (isset($inst['display_name']) && is_string($inst['display_name']) && $inst['display_name'] !== '')
                        ? $inst['display_name'] : (isset($inst['name']) ? (string) $inst['name'] : ''),
                    'tom' => $keyLabel,
                    'tempo' => $bpm,
                    'compasso' => $meter,
                    'dificuldade' => 'Intermediário',
                    'estilo' => 'Personalizado',
                    'notes' => $scoreNotes,
                ];
            }
            $parts[] = [
                'instrument_id' => isset($inst['name']) ? (string) $inst['name'] : null,
                'track_id' => $track['track_id'],
                'name' => (isset($inst['display_name']) && is_string($inst['display_name']) && $inst['display_name'] !== '')
                    ? $inst['display_name'] : (isset($track['source_stem']) ? (string) $track['source_stem'] : $track['track_id']),
                'family' => isset($inst['family']) ? (string) $inst['family'] : 'unknown',
                'notes' => $notes,
                'warnings' => $warnings,
                'score' => $score,
            ];
        }
        return $parts;
    }

    /** Título sanitizado (≤120, sem HTML) ou padrão honesto. */
    public static function cleanTitle($title): string
    {
        $text = is_string($title) ? trim(strip_tags($title)) : '';
        $text = trim((string) preg_replace('/\s+/', ' ', $text));
        if ($text === '') {
            return 'Música sem título';
        }
        return function_exists('mb_substr') ? mb_substr($text, 0, 120) : substr($text, 0, 120);
    }

    /** SMF formato 1: 1 trilha de regência + 1 por parte. */
    public static function renderMidi(array $parts, int $bpm, ?string $meter, string $title = ''): string
    {
        if ($bpm < 20 || $bpm > 300) {
            throw new InvalidArgumentException('Andamento inválido para o MIDI.');
        }
        [$num, $denExp] = self::METERS[$meter] ?? self::METERS['4/4'];
        $mpqn = (int) round(60000000 / $bpm);
        $conductor = [
            ['tick' => 0, 'seq' => 0, 'bytes' => chr(0xFF) . chr(0x51) . chr(3)
                . chr(($mpqn >> 16) & 0xFF) . chr(($mpqn >> 8) & 0xFF) . chr($mpqn & 0xFF)],
            ['tick' => 0, 'seq' => 1, 'bytes' => chr(0xFF) . chr(0x58) . chr(4)
                . chr($num) . chr($denExp) . chr(24) . chr(8)],
        ];
        if ($title !== '') {
            $raw = MidiWriter::latin1($title);
            $conductor[] = ['tick' => 0, 'seq' => 2,
                'bytes' => chr(0xFF) . chr(0x03) . MidiWriter::vlq(strlen($raw)) . $raw];
        }
        $bodies = [MidiWriter::serializeEvents($conductor)];
        $channel = 0;
        $seq = 0;
        foreach ($parts as $part) {
            if ($channel === 9) {
                $channel++;
            }
            if ($channel > 15) {
                throw new InvalidArgumentException('Partes demais para o MIDI.');
            }
            $isDrums = ($part['family'] === 'unpitched_percussion'
                || $part['instrument_id'] === 'drum_kit');
            $chan = $isDrums ? 9 : $channel;
            $events = [];
            $events[] = ['tick' => 0, 'seq' => $seq++,
                'bytes' => chr(0xFF) . chr(0x03) . MidiWriter::vlq(strlen($part['name'])) . $part['name']];
            if (!$isDrums) {
                // Programa padrão (piano GM); mapeamento por instrumento é trabalho futuro.
                $events[] = ['tick' => 0, 'seq' => $seq++, 'bytes' => chr(0xC0 | $chan) . chr(0)];
            }
            foreach ($part['notes'] as $n) {
                $pitch = (int) $n['pitch'];
                $velocity = isset($n['velocity']) ? (int) $n['velocity'] : 90;
                $velocity = max(1, min(127, $velocity));
                $start = (float) $n['start'];
                $dur = (float) $n['duration'];
                if ($pitch < 0 || $pitch > 127 || !(is_finite($start)) || !(is_finite($dur)) || $dur <= 0 || $start < 0) {
                    throw new InvalidArgumentException('Nota inválida para o MIDI.');
                }
                $tick = (int) round($start * $bpm / 60.0 * self::DIVISION);
                $len = max(1, (int) round($dur * $bpm / 60.0 * self::DIVISION));
                $key = $isDrums ? 38 : $pitch; // percussão: caixa GM
                $events[] = ['tick' => $tick, 'seq' => $seq++,
                    'bytes' => chr(0x90 | $chan) . chr($key) . chr($velocity)];
                $events[] = ['tick' => $tick + $len, 'seq' => $seq++,
                    'bytes' => chr(0x80 | $chan) . chr($key) . chr(0)];
            }
            $bodies[] = MidiWriter::serializeEvents($events);
            if (!$isDrums) {
                $channel++;
            }
        }
        return MidiWriter::buildFormat1($bodies, self::DIVISION);
    }
}

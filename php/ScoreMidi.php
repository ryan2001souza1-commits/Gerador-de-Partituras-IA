<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Mapeamento score_data → MIDI.
 *
 * Converte DIRETAMENTE as notas exibidas (pitch, octave, duration, rest,
 * order) em eventos MIDI, no mesmo BPM da partitura. Pausas só avançam o
 * tempo. Instrumento vira Program Change (General MIDI); Bateria usa o
 * canal de percussão com mapa próprio; demais sem correspondência usam
 * Piano (programa 0). Sem dependências externas.
 */
class ScoreMidi
{
    const MAX_NOTES = 300;
    const DIVISION = 480;
    const VELOCITY = 90;

    const SEMITONES = ['C' => 0, 'C#' => 1, 'D' => 2, 'D#' => 3, 'E' => 4, 'F' => 5,
        'F#' => 6, 'G' => 7, 'G#' => 8, 'A' => 9, 'A#' => 10, 'B' => 11];
    const BEATS = ['whole' => 4.0, 'half' => 2.0, 'quarter' => 1.0, 'eighth' => 0.5, 'sixteenth' => 0.25];
    const MEASURE = ['2/4' => [2, 2], '3/4' => [3, 2], '4/4' => [4, 2], '6/8' => [6, 3], '12/8' => [12, 3]];

    // General MIDI: instrumento PT → programa (0-127). Bateria = canal 9.
    const PROGRAMS = [
        'Piano' => 0, 'Violão' => 25, 'Violino' => 40, 'Flauta' => 73,
        'Baixo' => 33, 'Outro' => 0,
    ];
    // Canal de percussão (10): classe de altura → nota GM.
    const DRUMS = ['C' => 36, 'D' => 38, 'E' => 42, 'F' => 46, 'G' => 49, 'A' => 51, 'B' => 47];

    const TOM_TO_KEY = [
        'C Maior' => 'C', 'D Maior' => 'D', 'E Maior' => 'E', 'F Maior' => 'F',
        'G Maior' => 'G', 'A Maior' => 'A', 'B Maior' => 'B',
        'C Menor' => 'Cm', 'D Menor' => 'Dm', 'E Menor' => 'Em', 'F Menor' => 'Fm',
        'G Menor' => 'Gm', 'A Menor' => 'Am', 'B Menor' => 'Bm',
    ];
    const ANDAMENTO_TO_BPM = ['Muito lento' => 50, 'Lento' => 70, 'Moderado' => 96, 'Rápido' => 128, 'Muito rápido' => 160];

    /** Normaliza/valida. Lança InvalidArgumentException (mensagem segura). */
    public static function normalize(array $score): array
    {
        $str = function ($v, int $max, string $def) {
            $v = is_string($v) ? trim($v) : '';
            if ($v === '') {
                return $def;
            }
            return function_exists('mb_substr') ? mb_substr($v, 0, $max, 'UTF-8') : substr($v, 0, $max);
        };
        $title = $str($score['title'] ?? null, 200, 'Partitura sem título');
        $instrument = $str($score['instrument'] ?? null, 50, '');
        if ($instrument === '' || (!isset(self::PROGRAMS[$instrument]) && $instrument !== 'Bateria')) {
            throw new InvalidArgumentException('Instrumento inválido para o MIDI.');
        }

        $bpm = null;
        if (isset($score['tempo']) && is_numeric($score['tempo'])) {
            $bpm = (int) $score['tempo'];
        } elseif (isset($score['andamento'], self::ANDAMENTO_TO_BPM[$score['andamento']])) {
            $bpm = self::ANDAMENTO_TO_BPM[$score['andamento']];
        }
        if ($bpm === null || $bpm < 20 || $bpm > 300) {
            throw new InvalidArgumentException('Andamento inválido para o MIDI.');
        }

        $compasso = '';
        if (is_string($score['time_signature'] ?? null) && $score['time_signature'] !== '') {
            $compasso = $score['time_signature'];
        } elseif (is_string($score['compasso'] ?? null)) {
            $compasso = $score['compasso']; // rótulo vindo do frontend
        }
        if (!isset(self::MEASURE[$compasso])) {
            throw new InvalidArgumentException('Fórmula de compasso inválida para o MIDI.');
        }

        $notes = $score['notes'] ?? null;
        if (!is_array($notes) || $notes === [] || count($notes) > self::MAX_NOTES) {
            throw new InvalidArgumentException('A partitura precisa de 1 a ' . self::MAX_NOTES . ' notas.');
        }
        $clean = [];
        foreach (array_values($notes) as $i => $n) {
            if (!is_array($n)) {
                throw new InvalidArgumentException('Nota inválida para o MIDI.');
            }
            $rest = !empty($n['rest']);
            $midi = null;
            if (!$rest) {
                $raw = is_string($n['pitch'] ?? null) ? trim((string) $n['pitch']) : '';
                $octave = isset($n['octave']) ? (int) $n['octave'] : null;
                if (preg_match('/^([A-G][#]?)(\d)$/', $raw, $m)) {
                    $raw = $m[1];
                    $octave = (int) $m[2];
                }
                if (!isset(self::SEMITONES[$raw]) || $octave === null || $octave < 0 || $octave > 8) {
                    throw new InvalidArgumentException('Nota inválida para o MIDI.');
                }
                $midi = ($octave + 1) * 12 + self::SEMITONES[$raw];
                if ($midi < 0 || $midi > 127) {
                    throw new InvalidArgumentException('Nota fora do alcance MIDI.');
                }
            }
            $dur = is_string($n['duration'] ?? null) ? $n['duration'] : '';
            if (!isset(self::BEATS[$dur])) {
                throw new InvalidArgumentException('Duração inválida para o MIDI.');
            }
            $clean[] = ['midi' => $midi, 'pitch_class' => $rest ? null : $raw,
                'beats' => self::BEATS[$dur], 'rest' => $rest, 'order' => $i];
        }

        return ['title' => $title, 'instrument' => $instrument, 'bpm' => $bpm,
            'compasso' => $compasso, 'notes' => $clean];
    }

    /** Gera os bytes do .mid. */
    public static function render(array $score): string
    {
        $s = self::normalize($score);
        $w = new MidiWriter(self::DIVISION);
        [$num, $denExp] = self::MEASURE[$s['compasso']];

        // Andamento: microssegundos por semínima.
        $mpqn = (int) round(60000000 / $s['bpm']);
        $w->addMeta(0, 0x51, chr(($mpqn >> 16) & 0xFF) . chr(($mpqn >> 8) & 0xFF) . chr($mpqn & 0xFF));
        // Fórmula de compasso: nn, dd (potência de 2), 24 clocks, 8 fusas.
        $w->addMeta(0, 0x58, chr($num) . chr($denExp) . chr(24) . chr(8));
        $w->addMeta(0, 0x03, MidiWriter::latin1($s['title']));

        $drums = ($s['instrument'] === 'Bateria');
        $channel = $drums ? 9 : 0;
        if ($drums) {
            $w->addMeta(0, 0x04, 'Bateria (GM)');
        } else {
            $program = self::PROGRAMS[$s['instrument']];
            $w->addEvent(0, chr(0xC0 | $channel) . chr($program));
            $w->addMeta(0, 0x04, MidiWriter::latin1($s['instrument']));
        }

        $tick = 0;
        foreach ($s['notes'] as $n) {
            $len = (int) round($n['beats'] * self::DIVISION);
            if (!$n['rest']) {
                $key = $drums ? (self::DRUMS[$n['pitch_class']] ?? 38) : $n['midi'];
                $w->addEvent($tick, chr(0x90 | $channel) . chr($key) . chr(self::VELOCITY));
                $w->addEvent($tick + $len, chr(0x80 | $channel) . chr($key) . chr(0));
            }
            $tick += $len; // pausas só avançam o tempo
        }
        return $w->build();
    }
}

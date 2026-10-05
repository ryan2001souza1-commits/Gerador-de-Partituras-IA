<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Fábrica musical em PHP (espelho de
 * python/score_model.py para o ambiente serverless, onde não há Python).
 *
 * Contém: validação rigorosa (validateScore), normalização da resposta
 * da IA (normalizeAiScore, parâmetros do pedido como autoridade),
 * construção do prompt (buildPrompt) e gerador local determinístico
 * (buildLocal). Sem eval/exec. Erros via ScoreValidationException com
 * mensagens seguras.
 */
class ScoreValidationException extends RuntimeException
{
}

class ScoreFactory
{
    const MAX_NOTES = 300;
    const AI_MAX_NOTES = 120;
    const AI_NOTES_REQUESTED = 20;

    const INSTRUMENTS = ['Piano', 'Violão', 'Violino', 'Flauta', 'Baixo', 'Bateria', 'Outro'];
    const TOM_TO_KEY = [
        'C Maior' => 'C', 'D Maior' => 'D', 'E Maior' => 'E', 'F Maior' => 'F',
        'G Maior' => 'G', 'A Maior' => 'A', 'B Maior' => 'B',
        'C Menor' => 'Cm', 'D Menor' => 'Dm', 'E Menor' => 'Em', 'F Menor' => 'Fm',
        'G Menor' => 'Gm', 'A Menor' => 'Am', 'B Menor' => 'Bm',
    ];
    const ANDAMENTO_TO_BPM = [
        'Muito lento' => 50, 'Lento' => 70, 'Moderado' => 96,
        'Rápido' => 128, 'Muito rápido' => 160,
    ];
    const TIME_SIGNATURES = ['2/4', '3/4', '4/4', '6/8', '12/8'];
    const DIFICULDADE_TO_LEVEL = ['Iniciante' => 'beginner', 'Intermediário' => 'intermediate', 'Avançado' => 'advanced'];
    const ESTILO_TO_STYLE = [
        'Clássico' => 'classical', 'Romântico' => 'romantic', 'Jazz' => 'jazz',
        'Blues' => 'blues', 'Pop' => 'pop', 'Rock' => 'rock',
        'Gospel' => 'gospel', 'Cinematográfico' => 'cinematic', 'Épico' => 'epic',
        'Personalizado' => 'custom',
    ];
    const PITCHES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    const DURATIONS = ['whole', 'half', 'quarter', 'eighth', 'sixteenth'];
    /** Durações em tempos de semínima. */
    const DURATION_BEATS = ['whole' => 4.0, 'half' => 2.0, 'quarter' => 1.0, 'eighth' => 0.5, 'sixteenth' => 0.25];
    /** Tempos por compasso (unidade = semínima). */
    const MEASURE_BEATS = ['2/4' => 2.0, '3/4' => 3.0, '4/4' => 4.0, '6/8' => 3.0, '12/8' => 6.0];
    const INSTRUMENT_OCTAVES = [
        'Piano' => [3, 5], 'Violão' => [3, 4], 'Violino' => [4, 6], 'Flauta' => [5, 6],
        'Baixo' => [2, 3], 'Bateria' => [3, 4], 'Outro' => [4, 5],
    ];
    const DURATION_ALIASES = [
        'semibreve' => 'whole',
        'minima' => 'half', 'minim' => 'half',
        'seminima' => 'quarter', 'crotchet' => 'quarter',
        'colcheia' => 'eighth', 'quaver' => 'eighth',
        'semicolcheia' => 'sixteenth', 'semiquaver' => 'sixteenth',
    ];

    /** Validação rigorosa da partitura canônica. */
    public static function validateScore(array $score): bool
    {
        foreach (['title', 'instrument', 'musical_key', 'time_signature', 'difficulty', 'style', 'status'] as $field) {
            if (!isset($score[$field]) || !is_string($score[$field]) || $score[$field] === '') {
                throw new ScoreValidationException('Partitura inválida.');
            }
        }
        if (!in_array($score['instrument'], self::INSTRUMENTS, true)) {
            throw new ScoreValidationException('Instrumento inválido na partitura.');
        }
        if (!in_array($score['musical_key'], array_values(self::TOM_TO_KEY), true)) {
            throw new ScoreValidationException('Tonalidade inválida na partitura.');
        }
        if (!isset($score['tempo']) || !is_int($score['tempo']) || $score['tempo'] < 20 || $score['tempo'] > 300) {
            throw new ScoreValidationException('BPM fora do intervalo permitido.');
        }
        if (!in_array($score['time_signature'], self::TIME_SIGNATURES, true)) {
            throw new ScoreValidationException('Fórmula de compasso inválida na partitura.');
        }
        if (!in_array($score['difficulty'], array_values(self::DIFICULDADE_TO_LEVEL), true)) {
            throw new ScoreValidationException('Dificuldade inválida na partitura.');
        }
        if (!in_array($score['style'], array_values(self::ESTILO_TO_STYLE), true)) {
            throw new ScoreValidationException('Estilo inválido na partitura.');
        }
        $notes = $score['notes'] ?? null;
        if (!is_array($notes) || $notes === [] || count($notes) > self::MAX_NOTES) {
            throw new ScoreValidationException('A partitura precisa de 1 a ' . self::MAX_NOTES . ' notas.');
        }
        foreach (array_values($notes) as $i => $note) {
            self::validateNote($note, $i);
        }
        return true;
    }

    private static function validateNote($note, int $order): bool
    {
        if (!is_array($note)) {
            throw new ScoreValidationException('Nota inválida na posição ' . $order . '.');
        }
        $rest = !empty($note['rest']);
        if ($rest) {
            if (array_key_exists('pitch', $note) && $note['pitch'] !== null) {
                throw new ScoreValidationException('Pausa não deve ter altura definida.');
            }
        } elseif (!isset($note['pitch']) || !in_array($note['pitch'], self::PITCHES, true)) {
            throw new ScoreValidationException('Altura inválida na posição ' . $order . '.');
        }
        if (!isset($note['octave']) || !is_int($note['octave']) || $note['octave'] < 0 || $note['octave'] > 8) {
            throw new ScoreValidationException('Oitava inválida na posição ' . $order . '.');
        }
        if (!isset($note['duration']) || !in_array($note['duration'], self::DURATIONS, true)) {
            throw new ScoreValidationException('Duração inválida na posição ' . $order . '.');
        }
        if (!array_key_exists('order', $note) || $note['order'] !== $order) {
            throw new ScoreValidationException('Ordem inválida na posição ' . $order . '.');
        }
        return true;
    }

    /** Prompt interno para a IA (resposta SOMENTE JSON). */
    public static function buildPrompt(array $data): string
    {
        $oct = self::INSTRUMENT_OCTAVES[$data['instrumento']] ?? [4, 5];
        $bpm = self::ANDAMENTO_TO_BPM[$data['andamento']];
        $key = self::TOM_TO_KEY[$data['tom']];
        $scale = implode(' ', self::scalePitches($key));
        $beats = self::beatsPerMeasure($data['compasso']);
        $beatsLabel = (fmod($beats, 1.0) === 0.0) ? (string) (int) $beats : (string) $beats;
        $tonic = self::tonicOf($key);
        return 'Componha uma melodia com ' . self::AI_NOTES_REQUESTED . ' notas para '
            . $data['instrumento'] . ' em ' . $data['tom'] . ', ' . $bpm . ' BPM, compasso '
            . $data['compasso'] . ', nível ' . $data['dificuldade'] . ', estilo ' . $data['estilo']
            . ', sobre: "' . mb_substr(trim($data['descricao']), 0, 2000, 'UTF-8') . '".' . "\n"
            . 'Responda SOMENTE com JSON válido, sem texto antes ou depois, neste formato exato:' . "\n"
            . '{"title": "...", "notes": [{"pitch": "C4", "duration": "quarter", "rest": false}, ...]}' . "\n"
            . 'Regras: pitch é nota A-G com # opcional + oitava (ex. C4, F#5); oitavas entre '
            . $oct[0] . ' e ' . $oct[1] . '; duration é um de whole|half|quarter|eighth|sixteenth; '
            . 'pausas usam {"pitch": null, "duration": "...", "rest": true}; exatamente '
            . self::AI_NOTES_REQUESTED . ' notas.' . "\n"
            . 'Regras musicais (obrigatórias): use APENAS estas alturas da escala de '
            . $data['tom'] . ': ' . $scale . '; cada compasso de ' . $data['compasso']
            . ' soma exatamente ' . $beatsLabel . ' tempos — complete todos os compassos; '
            . 'prefira graus conjuntos com salto máximo de 7 semitons e nunca salte de '
            . 'oitava sem retorno por graus conjuntos; repita um motivo de 1 compasso '
            . 'com variação e termine na tônica (' . $tonic . ') com nota longa.';
    }

    private static function normalizeAiNote($raw, int $order): array
    {
        if (!is_array($raw)) {
            throw new ScoreValidationException('Nota inválida na resposta da IA.');
        }
        $rest = !empty($raw['rest']);
        $pitch = null;
        $octave = 4;
        if (!$rest) {
            $token = $raw['pitch'] ?? null;
            if (is_array($token)) {
                $octave = $token['octave'] ?? 4;
                $token = $token['pitch'] ?? null;
            }
            if (!is_string($token)) {
                throw new ScoreValidationException('Nota inválida na resposta da IA.');
            }
            $token = trim($token);
            if (strlen($token) >= 2 && ctype_digit($token[strlen($token) - 1])) {
                $pitch = substr($token, 0, -1);
                $octave = (int) substr($token, -1);
            } else {
                $pitch = $token;
                if (isset($raw['octave']) && is_int($raw['octave'])) {
                    $octave = $raw['octave'];
                }
            }
            if (!in_array($pitch, self::PITCHES, true)) {
                throw new ScoreValidationException('Nota inválida na resposta da IA.');
            }
            if ($octave < 0 || $octave > 8) {
                throw new ScoreValidationException('Nota inválida na resposta da IA.');
            }
        }
        $dur = isset($raw['duration']) && is_string($raw['duration']) ? strtolower(trim($raw['duration'])) : '';
        $dur = self::DURATION_ALIASES[$dur] ?? $dur;
        if (!in_array($dur, self::DURATIONS, true)) {
            throw new ScoreValidationException('Nota inválida na resposta da IA.');
        }
        return ['pitch' => $pitch, 'octave' => $octave, 'duration' => $dur, 'order' => $order, 'rest' => $rest];
    }

    /**
     * Monta a partitura canônica da resposta da IA. Parâmetros musicais
     * do PEDIDO são autoritativos; a IA compõe título e notas.
     */
    public static function normalizeAiScore(array $raw, array $data, array $providerInfo): array
    {
        $notesRaw = $raw['notes'] ?? null;
        if (!is_array($notesRaw) || $notesRaw === [] || count($notesRaw) > self::AI_MAX_NOTES) {
            throw new ScoreValidationException('Resposta inválida da IA.');
        }
        $notes = [];
        foreach (array_values($notesRaw) as $i => $n) {
            $notes[] = self::normalizeAiNote($n, $i);
        }
        $title = (isset($raw['title']) && is_string($raw['title']) && trim($raw['title']) !== '')
            ? mb_substr(trim($raw['title']), 0, 200, 'UTF-8')
            : ($data['estilo'] . ' para ' . $data['instrumento'] . ' em ' . $data['tom']);
        $score = [
            'title' => $title,
            'instrument' => $data['instrumento'],
            'musical_key' => self::TOM_TO_KEY[$data['tom']],
            'tempo' => self::ANDAMENTO_TO_BPM[$data['andamento']],
            'time_signature' => $data['compasso'],
            'difficulty' => self::DIFICULDADE_TO_LEVEL[$data['dificuldade']],
            'style' => self::ESTILO_TO_STYLE[$data['estilo']],
            'notes' => $notes,
            'labels' => [
                'instrumento' => $data['instrumento'],
                'tom' => $data['tom'],
                'andamento' => $data['andamento'],
                'compasso' => $data['compasso'],
                'dificuldade' => $data['dificuldade'],
                'estilo' => $data['estilo'],
            ],
            'generator' => ['type' => 'ai', 'provider' => $providerInfo['provider'], 'model' => $providerInfo['model']],
            'status' => 'generated-ai',
        ];
        self::validateScore($score);
        return $score;
    }

    /** Gerador local determinístico (mesma entrada → mesma saída).
     *
     * Melodia com estrutura (motivo + variação + cadência na tônica),
     * compassos preenchidos exatamente, graus conjuntos com saltos
     * limitados e sem teletransporte de oitava. Oitavas mudam só pelo
     * movimento dos graus da escala, dentro da tessitura do instrumento.
     */
    public static function buildLocal(array $data): array
    {
        $key = self::TOM_TO_KEY[$data['tom']];
        $bpm = self::ANDAMENTO_TO_BPM[$data['andamento']];
        $level = self::DIFICULDADE_TO_LEVEL[$data['dificuldade']];
        $style = self::ESTILO_TO_STYLE[$data['estilo']];

        $seedSrc = implode('|', [trim($data['descricao']), $data['instrumento'], $key, (string) $bpm, $data['compasso'], $level, $style]);
        $seed = hexdec(substr(hash('sha256', $seedSrc), 0, 8));
        mt_srand($seed);

        $minor = substr($key, -1) === 'm';
        $root = $minor ? substr($key, 0, -1) : $key;
        $rootIdx = array_search($root, self::PITCHES, true);
        $scale = self::scaleDegrees($root, $minor); // semitons relativos (7 graus)
        [$loOct, $hiOct] = self::INSTRUMENT_OCTAVES[$data['instrumento']] ?? [4, 5];
        $measureBeats = self::MEASURE_BEATS[$data['compasso']];
        // Vocabulário rítmico por nível (sempre preenche o compasso exato).
        $vocab = [
            'beginner' => [['half', 2.0, 1], ['quarter', 1.0, 6]],
            'intermediate' => [['half', 2.0, 1], ['quarter', 1.0, 5], ['eighth', 0.5, 3]],
            'advanced' => [['half', 2.0, 1], ['quarter', 1.0, 4], ['eighth', 0.5, 4], ['sixteenth', 0.25, 2]],
        ][ $level ];
        $minUnit = ['beginner' => 1.0, 'intermediate' => 0.5, 'advanced' => 0.25][ $level ];
        // Salto máximo (semitons) e direção por nível.
        $maxLeap = ['beginner' => 4, 'intermediate' => 5, 'advanced' => 7][ $level ];

        $loMidi = ($loOct + 1) * 12;
        $hiMidi = ($hiOct + 1) * 12 + 11;
        // Começo na tônica, região média da tessitura.
        $midi = self::nearestScaleMidi(self::tonicMidi($rootIdx, (int) round(($loOct + $hiOct) / 2)), $scale, $rootIdx);
        $midi = max($loMidi, min($hiMidi, $midi));
        $direction = mt_rand(0, 1) === 0 ? -1 : 1;
        $resolveStep = 0; // após salto, resolve por graus conjuntos

        $measures = 4 + mt_rand(0, 2); // 4–6 compassos
        $tonicMid = self::nearestScaleMidi(self::tonicMidi($rootIdx, (int) round(($loOct + $hiOct) / 2)), $scale, $rootIdx, $loMidi, $hiMidi);
        $notes = [];
        $order = 0;
        $prevMidi = null;
        $motifRhythm = null;
        $motifFirstMidi = null;
        for ($m = 0; $m < $measures; $m++) {
            $isLast = ($m === $measures - 1);
            // Tônica final decidida no início do último compasso: a mais
            // próxima (evita salto cadencial) e atração total até ela.
            // A caminhada fica na faixa [F-8, F+8] → salto final ≤ 8.
            $finalTonic = null;
            $bandLo = $loMidi;
            $bandHi = $hiMidi;
            if ($isLast) {
                $finalTonic = self::nearestTonic($midi, $rootIdx, $loMidi, $hiMidi);
                $bandLo = max($loMidi, $finalTonic - 8);
                $bandHi = min($hiMidi, $finalTonic + 8);
                $resolveStep = 0;
            }
            // Motivo rítmico do 1º compasso, reutilizado com variação.
            if ($m === 0 || mt_rand(1, 100) > 55) {
                $durs = self::fillMeasure($measureBeats, $vocab, $minUnit);
                if ($m === 0) {
                    $motifRhythm = $durs;
                }
            } else {
                $durs = $motifRhythm;
            }
            foreach ($durs as $di => $dur) {
                $isFirst = ($order === 0);
                $isFinal = $isLast && ($di === count($durs) - 1);
                if (!$isFirst && !$isFinal && mt_rand(1, 100) <= 8) {
                    $notes[] = ['pitch' => null, 'octave' => $loOct, 'duration' => $dur, 'order' => $order++, 'rest' => true];
                    continue;
                }
                if ($isFinal) {
                    // Cadência: tônica decidida no início do compasso.
                    $midi = $finalTonic;
                } elseif ($isFirst) {
                    // Primeira nota: tônica (começo claro).
                    $midi = $tonicMid;
                    $motifFirstMidi = $midi;
                } else {
                    // Variação do motivo: recomeço transposto para perto (sem salto).
                    if ($di === 0 && !$isLast && $motifFirstMidi !== null && mt_rand(1, 100) <= 30) {
                        $midi = self::nearestScaleMidi(
                            self::clampMidi(self::nearOctave($motifFirstMidi, $midi) + (mt_rand(0, 2) - 1), $loMidi, $hiMidi),
                            $scale, $rootIdx, $loMidi, $hiMidi);
                    } else {
                        [$midi, $direction, $resolveStep] = self::nextStep($midi, $direction, $resolveStep, $maxLeap, $scale, $rootIdx, $isLast ? $bandLo : $loMidi, $isLast ? $bandHi : $hiMidi, $isLast ? $finalTonic : null, $isLast ? 100 : 70);
                    }
                }
                $pc = self::PITCHES[$midi % 12];
                if (!$isFinal && $prevMidi !== null && abs($midi - $prevMidi) > 8) {
                    // Rede de segurança: nenhum salto excede uma 6ª menor.
                    $midi = self::nearestScaleMidi(
                        self::clampMidi($prevMidi + ($midi > $prevMidi ? 7 : -7), $loMidi, $hiMidi),
                        $scale, $rootIdx, $loMidi, $hiMidi);
                    $pc = self::PITCHES[$midi % 12];
                }
                $notes[] = ['pitch' => $pc, 'octave' => (int) floor($midi / 12) - 1, 'duration' => $dur, 'order' => $order++, 'rest' => false];
                $prevMidi = $midi;
            }
        }
        mt_srand(); // devolve aleatoriedade ao gerador global

        $score = [
            'title' => $data['estilo'] . ' para ' . $data['instrumento'] . ' em ' . $data['tom'],
            'instrument' => $data['instrumento'],
            'musical_key' => $key,
            'tempo' => $bpm,
            'time_signature' => $data['compasso'],
            'difficulty' => $level,
            'style' => $style,
            'notes' => $notes,
            'labels' => [
                'instrumento' => $data['instrumento'],
                'tom' => $data['tom'],
                'andamento' => $data['andamento'],
                'compasso' => $data['compasso'],
                'dificuldade' => $data['dificuldade'],
                'estilo' => $data['estilo'],
            ],
            'generator' => ['type' => 'local', 'provider' => 'rule-based', 'model' => 'score-model-v1'],
            'status' => 'generated-rule-based',
        ];
        self::validateScore($score);
        return $score;
    }

    private static function scaleDegrees(string $root, bool $minor): array
    {
        $idx = ['C' => 0, 'C#' => 1, 'D' => 2, 'D#' => 3, 'E' => 4, 'F' => 5, 'F#' => 6, 'G' => 7, 'G#' => 8, 'A' => 9, 'A#' => 10, 'B' => 11];
        $intervals = $minor ? [0, 2, 3, 5, 7, 8, 10] : [0, 2, 4, 5, 7, 9, 11];
        $out = [];
        foreach ($intervals as $s) {
            $out[] = ($idx[$root] + $s) % 12;
        }
        return $out;
    }

    /** Alturas da escala (classes) em ordem, ex. C Maior → [C D E F G A B]. */
    public static function scalePitches(string $key): array
    {
        $minor = substr($key, -1) === 'm';
        $root = $minor ? substr($key, 0, -1) : $key;
        $out = [];
        foreach (self::scaleDegrees($root, $minor) as $semi) {
            $out[] = self::PITCHES[$semi];
        }
        return $out;
    }

    /** Tônica (classe) da tonalidade canônica, ex. Cm → C. */
    public static function tonicOf(string $key): string
    {
        return substr($key, -1) === 'm' ? substr($key, 0, -1) : $key;
    }

    /** Tempos de semínima por compasso. */
    public static function beatsPerMeasure(string $sig): float
    {
        return self::MEASURE_BEATS[$sig] ?? 4.0;
    }

    /** MIDI da tônica na oitava indicada (fórmula do ScoreMidi). */
    private static function tonicMidi(int $rootIdx, int $octave): int
    {
        return ($octave + 1) * 12 + $rootIdx;
    }

    /**
     * Aproxima um MIDI para o tom diatônico mais próximo da escala.
     * Com $lo/$hi, nunca sai da tessitura.
     */
    private static function nearestScaleMidi(int $midi, array $scaleSemis, int $rootIdx, ?int $lo = null, ?int $hi = null): int
    {
        $best = $midi;
        $bestDist = 99;
        for ($cand = $midi - 6; $cand <= $midi + 6; $cand++) {
            if (!in_array($cand % 12, $scaleSemis, true)) {
                continue;
            }
            if (($lo !== null && $cand < $lo) || ($hi !== null && $cand > $hi)) {
                continue;
            }
            $d = abs($cand - $midi);
            if ($d < $bestDist) {
                $bestDist = $d;
                $best = $cand;
            }
        }
        return $best;
    }

    /** Tônica (MIDI) mais próxima da posição, dentro da tessitura. */
    private static function nearestTonic(int $midi, int $rootIdx, int $lo, int $hi): int
    {
        $best = max($lo, min($hi, $midi));
        $bestDist = 999;
        $k0 = (int) ceil(($lo - $rootIdx) / 12);
        $k1 = (int) floor(($hi - $rootIdx) / 12);
        for ($k = $k0; $k <= $k1; $k++) {
            $cand = 12 * $k + $rootIdx;
            $d = abs($cand - $midi);
            if ($d < $bestDist) {
                $bestDist = $d;
                $best = $cand;
            }
        }
        return $best;
    }

    /** Transpõe por oitavas para o mais próximo da referência. */
    private static function nearOctave(int $midi, int $ref): int
    {
        while ($midi - $ref > 6) {
            $midi -= 12;
        }
        while ($ref - $midi > 6) {
            $midi += 12;
        }
        return $midi;
    }

    private static function clampMidi(int $midi, int $lo, int $hi): int
    {
        return max($lo, min($hi, $midi));
    }

    /** Passo melódico: graus conjuntos com direção, salto raro e resolução. */
    private static function nextStep(int $midi, int $direction, int $resolveStep, int $maxLeap, array $scale, int $rootIdx, int $lo, int $hi, ?int $attractTo = null, int $attractProb = 70): array
    {
        if ($resolveStep > 0) {
            $delta = -$direction * mt_rand(1, 2);
            $resolveStep--;
        } elseif ($attractTo !== null && mt_rand(1, 100) <= $attractProb) {
            // Atração cadencial: caminha por graus conjuntos até o alvo.
            $toward = ($attractTo >= $midi) ? 1 : -1;
            $delta = $toward * mt_rand(1, 2);
            $direction = $toward;
        } elseif (mt_rand(1, 100) <= 65) {
            // Graus conjuntos; repetição eventual como recurso motívico.
            $delta = (mt_rand(1, 100) <= 18) ? 0 : ($direction * mt_rand(1, 2));
            if ($delta !== 0) {
                $direction = ($delta > 0) ? 1 : -1;
            }
        } else {
            $direction = -$direction;
            $delta = $direction * mt_rand(1, 2);
            if (mt_rand(1, 100) <= 12) {
                $delta = $direction * mt_rand(3, $maxLeap);
            }
        }
        $target = $midi + $delta;
        if (abs($target - $midi) > $maxLeap) {
            $target = $midi + ($target > $midi ? $maxLeap : -$maxLeap);
        }
        // Encaixa na escala e na tessitura (nesta ordem, sem teletransporte).
        $target = self::nearestScaleMidi($target, $scale, $rootIdx);
        $target = self::clampMidi($target, $lo, $hi);
        $target = self::nearestScaleMidi($target, $scale, $rootIdx, $lo, $hi);
        $leap = abs($target - $midi);
        if ($leap >= 5) {
            $resolveStep = 2; // resolve o salto por graus conjuntos
            $direction = ($target > $midi) ? 1 : -1;
        } elseif ($leap > 0) {
            $direction = ($target > $midi) ? 1 : -1;
        }
        return [$target, $direction, $resolveStep];
    }

    /** Preenche um compasso exatamente (soma = $beats). */
    private static function fillMeasure(float $beats, array $vocab, float $minUnit): array
    {
        $durs = [];
        $remaining = $beats;
        $guard = 0;
        while ($remaining > 0.0001 && $guard++ < 64) {
            $choices = [];
            foreach ($vocab as [$dur, $b, $w]) {
                if ($b > $remaining + 0.0001) {
                    continue;
                }
                $r = fmod($remaining - $b, $minUnit);
                if ($r < 0) {
                    $r += $minUnit;
                }
                // Resto múltiplo da unidade mínima → preenchimento exato possível.
                if ($r < 0.0002 || $r > $minUnit - 0.0002) {
                    $choices[] = [$dur, $w];
                }
            }
            if ($choices === []) {
                // Segurança (inalcançável com vocábulos exatos): menor que caiba.
                foreach (array_reverse($vocab) as [$dur, $b, $w]) {
                    if ($b <= $remaining + 0.0001) {
                        $choices[] = [$dur, 1];
                        break;
                    }
                }
                if ($choices === []) {
                    break;
                }
            }
            $total = 0;
            foreach ($choices as $c) {
                $total += $c[1];
            }
            $roll = mt_rand(1, max(1, $total));
            $pick = $choices[0][0];
            foreach ($choices as $c) {
                $roll -= $c[1];
                if ($roll <= 0) {
                    $pick = $c[0];
                    break;
                }
            }
            $durs[] = $pick;
            $remaining = round($remaining - self::DURATION_BEATS[$pick], 4);
        }
        return $durs;
    }

    /**
     * Métricas musicais da partitura (nunca lança; para testes e auditoria).
     * Retorna compassos, fora-da-escala, maior salto, tônica final e pausas.
     */
    public static function auditMelody(array $score): array
    {
        $out = ['measures' => [], 'measures_ok' => false, 'out_of_scale' => 0,
            'max_leap' => 0, 'final_tonic' => false, 'rests' => 0, 'total_beats' => 0.0];
        $notes = $score['notes'] ?? null;
        if (!is_array($notes) || $notes === []) {
            return $out;
        }
        $key = (isset($score['musical_key']) && is_string($score['musical_key'])) ? $score['musical_key'] : 'C';
        $sig = (isset($score['time_signature']) && is_string($score['time_signature'])) ? $score['time_signature'] : '4/4';
        $beats = self::MEASURE_BEATS[$sig] ?? 4.0;
        $scale = self::scalePitches(in_array($key, array_values(self::TOM_TO_KEY), true) ? $key : 'C');
        $tonic = self::tonicOf(in_array($key, array_values(self::TOM_TO_KEY), true) ? $key : 'C');
        $idx = ['C' => 0, 'C#' => 1, 'D' => 2, 'D#' => 3, 'E' => 4, 'F' => 5, 'F#' => 6, 'G' => 7, 'G#' => 8, 'A' => 9, 'A#' => 10, 'B' => 11];
        $acc = 0.0;
        $prev = null;
        $lastPitch = null;
        foreach ($notes as $n) {
            if (!is_array($n)) {
                continue;
            }
            $d = self::DURATION_BEATS[$n['duration'] ?? ''] ?? 0.0;
            $acc = round($acc + $d, 4);
            $out['total_beats'] = round($out['total_beats'] + $d, 4);
            if ($acc >= $beats - 0.0001) {
                $out['measures'][] = $acc;
                $acc = 0.0;
            }
            if (!empty($n['rest'])) {
                $out['rests']++;
                continue;
            }
            $pitch = $n['pitch'] ?? null;
            if (!is_string($pitch) || !isset($idx[$pitch])) {
                continue;
            }
            if (!in_array($pitch, $scale, true)) {
                $out['out_of_scale']++;
            }
            $oct = (isset($n['octave']) && is_int($n['octave'])) ? $n['octave'] : 4;
            $midi = ($oct + 1) * 12 + $idx[$pitch];
            if ($prev !== null) {
                $out['max_leap'] = max($out['max_leap'], abs($midi - $prev));
            }
            $prev = $midi;
            $lastPitch = $pitch;
        }
        $out['measures_ok'] = $out['measures'] !== [] && $acc < 0.0001;
        foreach ($out['measures'] as $m) {
            if (abs($m - $beats) > 0.0001) {
                $out['measures_ok'] = false;
            }
        }
        $out['final_tonic'] = ($lastPitch === $tonic);
        return $out;
    }
}

<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Renderizador de partitura em PDF.
 *
 * Recebe a estrutura musical canônica (a mesma de score_data) e desenha:
 * cabeçalho (título, instrumento, tonalidade, BPM, compasso, dificuldade,
 * estilo), pauta com clave de sol estilizada, notas posicionadas por
 * altura diatônica, hastes/bandeiras por duração, pausas, barras de
 * compasso e fórmula de compasso. Sem dependências externas.
 */
class PdfCanvas
{
    /** @var string */
    public $s = '';

    public static function num(float $v): string
    {
        $t = rtrim(rtrim(sprintf('%.2F', $v), '0'), '.');
        return $t === '-0' ? '0' : ($t === '' ? '0' : $t);
    }

    public function line(float $x1, float $y1, float $x2, float $y2, float $w = 1.0): void
    {
        $n = [self::class, 'num'];
        $this->s .= $n($w) . " w\n" . $n($x1) . ' ' . $n($y1) . " m\n" . $n($x2) . ' ' . $n($y2) . " l\nS\n";
    }

    public function polyline(array $pts, float $w = 1.0): void
    {
        if (count($pts) < 2) {
            return;
        }
        $n = [self::class, 'num'];
        $this->s .= $n($w) . " w\n";
        $this->s .= $n($pts[0][0]) . ' ' . $n($pts[0][1]) . " m\n";
        for ($i = 1; $i < count($pts); $i++) {
            $this->s .= $n($pts[$i][0]) . ' ' . $n($pts[$i][1]) . " l\n";
        }
        $this->s .= "S\n";
    }

    public function rect(float $x, float $y, float $w, float $h, bool $fill = true): void
    {
        $n = [self::class, 'num'];
        $this->s .= $n($x) . ' ' . $n($y) . ' ' . $n($w) . ' ' . $n($h) . ' re' . ($fill ? "\nf\n" : "\nS\n");
    }

    public function ellipse(float $cx, float $cy, float $rx, float $ry, bool $fill = true): void
    {
        $n = [self::class, 'num'];
        $k = 0.5523;
        $wx = $rx * $k;
        $wy = $ry * $k;
        $this->s .= $n($cx + $rx) . ' ' . $n($cy) . " m\n";
        $this->s .= $n($cx + $rx) . ' ' . $n($cy + $wy) . ' ' . $n($cx + $wx) . ' ' . $n($cy + $ry) . ' ' . $n($cx) . ' ' . $n($cy + $ry) . " c\n";
        $this->s .= $n($cx - $wx) . ' ' . $n($cy + $ry) . ' ' . $n($cx - $rx) . ' ' . $n($cy + $wy) . ' ' . $n($cx - $rx) . ' ' . $n($cy) . " c\n";
        $this->s .= $n($cx - $rx) . ' ' . $n($cy - $wy) . ' ' . $n($cx - $wx) . ' ' . $n($cy - $ry) . ' ' . $n($cx) . ' ' . $n($cy - $ry) . " c\n";
        $this->s .= $n($cx + $wx) . ' ' . $n($cy - $ry) . ' ' . $n($cx + $rx) . ' ' . $n($cy - $wy) . ' ' . $n($cx + $rx) . ' ' . $n($cy) . " c\n";
        $this->s .= $fill ? "f\n" : "S\n";
    }

    public function curve(float $x1, float $y1, float $x2, float $y2, float $x3, float $y3, float $x4, float $y4, float $w = 1.2): void
    {
        $n = [self::class, 'num'];
        $this->s .= $n($w) . " w\n" . $n($x1) . ' ' . $n($y1) . " m\n";
        $this->s .= $n($x2) . ' ' . $n($y2) . ' ' . $n($x3) . ' ' . $n($y3) . ' ' . $n($x4) . ' ' . $n($y4) . " c\nS\n";
    }

    /** Texto WinAnsi (acentos PT suportados; sem símbolos musicais). */
    public function text(float $x, float $y, string $text, float $size, string $font = 'F1'): void
    {
        $n = [self::class, 'num'];
        $safe = str_replace(['\\', '(', ')'], ['\\\\', '\\(', '\\)'], self::toLatin1($text));
        $this->s .= "BT\n/" . $font . ' ' . $n($size) . " Tf\n1 0 0 1 " . $n($x) . ' ' . $n($y) . " Tm\n(" . $safe . ") Tj\nET\n";
    }

    /** UTF-8 → Latin1 sem utf8_decode() (deprecated PHP 8.2+). Sem @, sem saída. */
    private static function toLatin1(string $text): string
    {
        if (function_exists('mb_convert_encoding')) {
            return mb_convert_encoding($text, 'ISO-8859-1', 'UTF-8');
        }
        $out = '';
        $len = strlen($text);
        for ($i = 0; $i < $len;) {
            $c = ord($text[$i]);
            if ($c < 0x80) {
                $out .= $text[$i];
                $i++;
                continue;
            }
            // Cauda truncada: mesma saída do mb_convert_encoding ('?' único).
            if (((($c & 0xE0) === 0xC0) && ($i + 1 >= $len))
                || ((($c & 0xF0) === 0xE0) && ($i + 2 >= $len))
                || ((($c & 0xF8) === 0xF0) && ($i + 3 >= $len))) {
                $out .= '?';
                break;
            }
            if ((($c & 0xE0) === 0xC0) && ($i + 1 < $len)) {
                $c2 = ord($text[$i + 1]);
                if ((($c2 & 0xC0) === 0x80)) {
                    $cp = ((($c & 0x1F) << 6) | ($c2 & 0x3F));
                    $out .= $cp <= 0xFF ? chr($cp) : '?';
                    $i += 2;
                    continue;
                }
            } elseif ((($c & 0xF0) === 0xE0) && ($i + 2 < $len)) {
                $c2 = ord($text[$i + 1]);
                $c3 = ord($text[$i + 2]);
                if ((($c2 & 0xC0) === 0x80) && (($c3 & 0xC0) === 0x80)) {
                    $cp = ((($c & 0x0F) << 12) | ((($c2 & 0x3F) << 6)) | ($c3 & 0x3F));
                    $out .= $cp <= 0xFF ? chr($cp) : '?';
                    $i += 3;
                    continue;
                }
            } elseif ((($c & 0xF8) === 0xF0) && ($i + 3 < $len)) {
                $c2 = ord($text[$i + 1]);
                $c3 = ord($text[$i + 2]);
                $c4 = ord($text[$i + 3]);
                if ((($c2 & 0xC0) === 0x80) && (($c3 & 0xC0) === 0x80) && (($c4 & 0xC0) === 0x80)) {
                    $out .= '?';
                    $i += 4;
                    continue;
                }
            }
            $out .= '?';
            $i++;
        }
        return $out;
    }
}

class ScorePdf
{
    const MAX_NOTES = 300;
    const PAGE_W = 595;
    const PAGE_H = 842;
    const MARGIN = 48;
    const GAP = 9;          // distância entre linhas da pauta
    const STEP = 4.5;       // meio espaço (por grau diatônico)
    const NOTE_DX = 18;     // avanço horizontal por nota
    const SYSTEM_H = 108;   // altura reservada por sistema

    const DIATONIC = ['C' => 0, 'D' => 1, 'E' => 2, 'F' => 3, 'G' => 4, 'A' => 5, 'B' => 6];
    const BEATS = ['whole' => 4.0, 'half' => 2.0, 'quarter' => 1.0, 'eighth' => 0.5, 'sixteenth' => 0.25];
    const MEASURE_BEATS = ['2/4' => 2.0, '3/4' => 3.0, '4/4' => 4.0, '6/8' => 3.0, '12/8' => 6.0];
    const TOM_TO_KEY = [
        'C Maior' => 'C', 'D Maior' => 'D', 'E Maior' => 'E', 'F Maior' => 'F',
        'G Maior' => 'G', 'A Maior' => 'A', 'B Maior' => 'B',
        'C Menor' => 'Cm', 'D Menor' => 'Dm', 'E Menor' => 'Em', 'F Menor' => 'Fm',
        'G Menor' => 'Gm', 'A Menor' => 'Am', 'B Menor' => 'Bm',
    ];
    const ANDAMENTO_TO_BPM = ['Muito lento' => 50, 'Lento' => 70, 'Moderado' => 96, 'Rápido' => 128, 'Muito rápido' => 160];
    const DIFICULDADE_OK = ['beginner' => 1, 'intermediate' => 1, 'advanced' => 1,
        'Iniciante' => 1, 'Intermediário' => 1, 'Avançado' => 1];
    const ESTILO_OK = ['classical' => 1, 'romantic' => 1, 'jazz' => 1, 'blues' => 1, 'pop' => 1,
        'rock' => 1, 'gospel' => 1, 'cinematic' => 1, 'epic' => 1, 'custom' => 1,
        'Clássico' => 1, 'Romântico' => 1, 'Jazz' => 1, 'Blues' => 1, 'Pop' => 1,
        'Rock' => 1, 'Gospel' => 1, 'Cinematográfico' => 1, 'Épico' => 1, 'Personalizado' => 1];

    /** Normaliza/valida a entrada. Lança InvalidArgumentException (mensagem segura). */
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
        if ($instrument === '') {
            throw new InvalidArgumentException('Instrumento inválido para o PDF.');
        }

        // Tonalidade: aceita canônico ou rótulo PT (frontend envia "tom").
        $tomRaw = '';
        if (is_string($score['musical_key'] ?? null) && trim((string) $score['musical_key']) !== '') {
            $tomRaw = trim((string) $score['musical_key']);
        } elseif (is_string($score['tom'] ?? null)) {
            $tomRaw = trim((string) $score['tom']);
        }
        if (isset(self::TOM_TO_KEY[$tomRaw])) {
            $tomLabel = $tomRaw;
        } elseif (in_array($tomRaw, self::TOM_TO_KEY, true)) {
            $found = array_search($tomRaw, self::TOM_TO_KEY, true);
            $tomLabel = is_string($found) ? $found : $tomRaw;
        } else {
            throw new InvalidArgumentException('Tonalidade inválida para o PDF.');
        }

        // BPM: número direto ou rótulo PT de andamento.
        $bpm = null;
        if (isset($score['tempo']) && is_numeric($score['tempo'])) {
            $bpm = (int) $score['tempo'];
        } elseif (isset($score['andamento'], self::ANDAMENTO_TO_BPM[$score['andamento']])) {
            $bpm = self::ANDAMENTO_TO_BPM[$score['andamento']];
        }
        if ($bpm === null || $bpm < 20 || $bpm > 300) {
            throw new InvalidArgumentException('Andamento inválido para o PDF.');
        }

        $compasso = '';
        if (is_string($score['time_signature'] ?? null) && $score['time_signature'] !== '') {
            $compasso = $score['time_signature'];
        } elseif (is_string($score['compasso'] ?? null)) {
            $compasso = $score['compasso']; // rótulo vindo do frontend
        }
        if (!isset(self::MEASURE_BEATS[$compasso])) {
            throw new InvalidArgumentException('Fórmula de compasso inválida para o PDF.');
        }
        $dificuldade = '';
        if (is_string($score['difficulty'] ?? null) && $score['difficulty'] !== '') {
            $dificuldade = $score['difficulty'];
        } elseif (is_string($score['dificuldade'] ?? null)) {
            $dificuldade = $score['dificuldade']; // rótulo vindo do frontend
        }
        if (!isset(self::DIFICULDADE_OK[$dificuldade])) {
            throw new InvalidArgumentException('Dificuldade inválida para o PDF.');
        }
        $estilo = '';
        if (is_string($score['style'] ?? null) && $score['style'] !== '') {
            $estilo = $score['style'];
        } elseif (is_string($score['estilo'] ?? null)) {
            $estilo = $score['estilo']; // rótulo vindo do frontend
        }
        if (!isset(self::ESTILO_OK[$estilo])) {
            throw new InvalidArgumentException('Estilo inválido para o PDF.');
        }

        $notes = $score['notes'] ?? null;
        if (!is_array($notes) || $notes === [] || count($notes) > self::MAX_NOTES) {
            throw new InvalidArgumentException('A partitura precisa de 1 a ' . self::MAX_NOTES . ' notas.');
        }
        $clean = [];
        foreach (array_values($notes) as $i => $n) {
            if (!is_array($n)) {
                throw new InvalidArgumentException('Nota inválida para o PDF.');
            }
            $rest = !empty($n['rest']);
            $pitch = null;
            $octave = isset($n['octave']) ? (int) $n['octave'] : 4;
            if (!$rest) {
                $raw = is_string($n['pitch'] ?? null) ? trim((string) $n['pitch']) : '';
                // Aceita "C" (+ octave) ou "C4".
                if (preg_match('/^([A-G])([#b]?)$/', $raw, $m)) {
                    $pitch = $m[1] . ($m[2] === 'b' ? 'b' : ($m[2] === '#' ? '#' : ''));
                    if (strpos($pitch, 'b') !== false) {
                        throw new InvalidArgumentException('Nota com bemol não suportada no PDF.');
                    }
                } elseif (preg_match('/^([A-G][#]?)(\d)$/', $raw, $m)) {
                    $pitch = $m[1];
                    $octave = (int) $m[2];
                } else {
                    throw new InvalidArgumentException('Nota inválida para o PDF.');
                }
                if (!isset(self::DIATONIC[$pitch[0]]) || ($pitch !== $pitch[0] && $pitch[1] !== '#')) {
                    throw new InvalidArgumentException('Nota inválida para o PDF.');
                }
                if ($octave < 0 || $octave > 8) {
                    throw new InvalidArgumentException('Oitava inválida para o PDF.');
                }
            }
            $dur = is_string($n['duration'] ?? null) ? $n['duration'] : '';
            if (!isset(self::BEATS[$dur])) {
                throw new InvalidArgumentException('Duração inválida para o PDF.');
            }
            $clean[] = ['pitch' => $pitch, 'octave' => $octave, 'duration' => $dur, 'rest' => $rest, 'order' => $i];
        }

        return [
            'title' => $title, 'instrument' => $instrument, 'tom' => $tomLabel,
            'bpm' => $bpm, 'compasso' => $compasso, 'dificuldade' => $dificuldade,
            'estilo' => $estilo, 'notes' => $clean,
        ];
    }

    /** Graus diatônicos a partir do Mi da clave (linha inferior). */
    private static function step(array $note): int
    {
        $di = self::DIATONIC[$note['pitch'][0]];
        return ($note['octave'] - 4) * 7 + ($di - 2);
    }

    private static function drawClef(PdfCanvas $c, float $x, float $yG): void
    {
        // Haste vertical + espiral na linha do Sol: clave de sol estilizada.
        $c->line($x + 3, $yG - 32, $x + 3, $yG + 24, 1.8);
        $c->ellipse($x + 3, $yG, 8.5, 7.0, false);
        $c->curve($x + 3, $yG + 24, $x - 8, $yG + 30, $x - 8, $yG + 40, $x + 1, $yG + 38, 1.4);
        $c->curve($x + 3, $yG - 32, $x - 6, $yG - 36, $x - 7, $yG - 30, $x - 2, $yG - 29, 1.4);
    }

    private static function drawSharp(PdfCanvas $c, float $x, float $y): void
    {
        $c->line($x - 1.6, $y - 6, $x - 1.6, $y + 6, 1.1);
        $c->line($x + 1.6, $y - 6, $x + 1.6, $y + 6, 1.1);
        $c->line($x - 5, $y + 1.6, $x + 5, $y + 3.0, 1.1);
        $c->line($x - 5, $y - 3.0, $x + 5, $y - 1.6, 1.1);
    }

    private static function drawRest(PdfCanvas $c, float $x, float $yTop, string $dur): void
    {
        // yTop = linha superior; linhas a cada GAP.
        if ($dur === 'whole') {
            $c->rect($x - 5, $yTop - self::GAP - 3.5, 10, 3.5, true);
        } elseif ($dur === 'half') {
            $c->rect($x - 5, $yTop - 2 * self::GAP, 10, 3.5, true);
        } elseif ($dur === 'quarter') {
            $ym = $yTop - 2 * self::GAP;
            $c->polyline([[$x + 2, $ym + 9], [$x - 2, $ym + 4], [$x + 3, $ym + 1], [$x - 3, $ym - 4], [$x + 1, $ym - 6], [$x - 1, $ym - 9]], 1.4);
        } elseif ($dur === 'eighth') {
            $ym = $yTop - 2 * self::GAP;
            $c->ellipse($x - 1, $ym + 3, 1.7, 1.7, true);
            $c->line($x - 4, $ym + 7, $x + 3, $ym - 7, 1.3);
        } else { // sixteenth
            $ym = $yTop - 2 * self::GAP;
            $c->ellipse($x - 2, $ym + 4, 1.6, 1.6, true);
            $c->ellipse($x + 1, $ym - 1, 1.6, 1.6, true);
            $c->line($x - 4, $ym + 8, $x + 3, $ym - 6, 1.3);
            $c->line($x - 4, $ym + 4, $x + 3, $ym - 10, 1.1);
        }
    }

    private static function noteHead(PdfCanvas $c, float $x, float $y, bool $filled): void
    {
        if ($filled) {
            $c->ellipse($x, $y, 5.0, 3.6, true);
        } else {
            $c->ellipse($x, $y, 5.0, 3.6, false);
        }
    }

    private static function stem(PdfCanvas $c, float $x, float $y, bool $up, string $dur): void
    {
        $len = 30.0;
        if ($up) {
            $c->line($x + 4.4, $y, $x + 4.4, $y + $len, 1.3);
            if ($dur === 'eighth' || $dur === 'sixteenth') {
                $c->line($x + 4.4, $y + $len, $x + 12, $y + $len - 8, 1.3);
            }
            if ($dur === 'sixteenth') {
                $c->line($x + 4.4, $y + $len - 6, $x + 12, $y + $len - 14, 1.1);
            }
        } else {
            $c->line($x - 4.4, $y, $x - 4.4, $y - $len, 1.3);
            if ($dur === 'eighth' || $dur === 'sixteenth') {
                $c->line($x - 4.4, $y - $len, $x - 12, $y - $len + 8, 1.3);
            }
            if ($dur === 'sixteenth') {
                $c->line($x - 4.4, $y - $len + 6, $x - 12, $y - $len + 14, 1.1);
            }
        }
    }

    /** Gera o PDF e devolve os bytes. */
    public static function render(array $score): string
    {
        $s = self::normalize($score);
        $st = ['canvas' => new PdfCanvas(), 'yTop' => self::PAGE_H - 150, 'pages' => [], 'pageNum' => 1];
        self::headerFirstPage($st['canvas'], $s);
        $x = self::openSystem($st['canvas'], $st['yTop'], $s, true);
        $beatUsed = 0.0;
        self::flowNotes($st, $s, $x, $beatUsed);
        self::finalBar($st['canvas'], $x, $st['yTop']);
        $st['pages'][] = $st['canvas']->s;
        return self::finishDoc($st['pages']);
    }

    /**
     * Gera PDF multi-partes (FASE 3Q): título uma única vez + uma
     * seção rotulada por parte, na ordem recebida (determinística).
     * Reutiliza os mesmos primitivos e layout de render().
     */
    public static function renderParts(array $scores, array $subtitles = []): string
    {
        if ($scores === [] || count($scores) > 16) {
            throw new InvalidArgumentException('Partitura precisa de 1 a 16 partes.');
        }
        $parts = [];
        foreach (array_values($scores) as $score) {
            if (!is_array($score)) {
                throw new InvalidArgumentException('Parte inválida para o PDF.');
            }
            $parts[] = self::normalize($score);
        }
        $first = $parts[0];
        $st = ['canvas' => new PdfCanvas(), 'yTop' => self::PAGE_H - 150, 'pages' => [], 'pageNum' => 1];
        self::headerFirstPage($st['canvas'], $first);
        foreach ($parts as $i => $s) {
            $label = isset($subtitles[$i]) && is_string($subtitles[$i]) && $subtitles[$i] !== ''
                ? $subtitles[$i] : ('Parte ' . ($i + 1) . ' — ' . $s['instrument']);
            // Garante espaço para rótulo + ao menos um sistema.
            if ($st['yTop'] - 2 * self::SYSTEM_H < 70) {
                $st['pages'][] = $st['canvas']->s;
                $st['canvas'] = new PdfCanvas();
                $st['pageNum']++;
                $st['yTop'] = self::PAGE_H - 90;
            }
            $st['canvas']->text(self::MARGIN, $st['yTop'] + 6, $label, 12, 'F2');
            $st['yTop'] -= 30;
            $x = self::openSystem($st['canvas'], $st['yTop'], $s, ($i === 0));
            $beatUsed = 0.0;
            self::flowNotes($st, $s, $x, $beatUsed);
            self::finalBar($st['canvas'], $x, $st['yTop']);
            $st['yTop'] -= self::SYSTEM_H;
        }
        $st['pages'][] = $st['canvas']->s;
        return self::finishDoc($st['pages']);
    }

    /** Cabeçalho global (título + linha do instrumento): só 1ª página. */
    private static function headerFirstPage(PdfCanvas $c, array $s): void
    {
        $c->text(self::MARGIN, self::PAGE_H - 62, $s['title'], 17, 'F2');
        $c->text(self::MARGIN, self::PAGE_H - 82,
            $s['instrument'] . '  ·  Tom: ' . $s['tom'] . '  ·  ' . $s['bpm'] . ' BPM  ·  Compasso: ' . $s['compasso'], 11, 'F1');
        $c->text(self::MARGIN, self::PAGE_H - 98,
            'Estilo: ' . $s['estilo'] . '  ·  Dificuldade: ' . $s['dificuldade'], 10, 'F1');
    }

    /** Abre um sistema (pauta + clave + fórmula no primeiro). */
    private static function openSystem(PdfCanvas $c, float $y, array $s, bool $firstSystem): float
    {
        for ($k = 0; $k < 5; $k++) {
            $ly = $y - $k * ScorePdf::GAP;
            $c->line(ScorePdf::MARGIN, $ly, ScorePdf::PAGE_W - ScorePdf::MARGIN, $ly, 1.0);
        }
        $yG = $y - 3 * ScorePdf::GAP;
        ScorePdf::drawClef($c, ScorePdf::MARGIN + 8, $yG);
        $x = ScorePdf::MARGIN + 46;
        if ($firstSystem) {
            [$num, $den] = explode('/', $s['compasso']);
            $c->text($x, $y - 2 * ScorePdf::GAP + 3, $num, 13, 'F2');
            $c->text($x, $y - 4 * ScorePdf::GAP + 3, $den, 13, 'F2');
            $x += 24;
        }
        return $x;
    }

    /** Fluxo de notas com quebra de sistema/página e barras. */
    private static function flowNotes(array &$st, array $s, float &$x, float &$beatUsed): void
    {
        $staffW = self::PAGE_W - 2 * self::MARGIN;
        $measureBeats = self::MEASURE_BEATS[$s['compasso']];
        /** @var PdfCanvas $canvas */
        $canvas = $st['canvas'];
        foreach ($s['notes'] as $note) {
            $beats = self::BEATS[$note['duration']];
            // Quebra de sistema / página antes de estourar a largura.
            if ($x + self::NOTE_DX > self::MARGIN + $staffW) {
                $canvas->line($x, $st['yTop'] - 4 * self::GAP, $x, $st['yTop'], 1.2); // barra final do sistema
                $st['yTop'] -= self::SYSTEM_H;
                if ($st['yTop'] - 4 * self::GAP < 70) {
                    $st['pages'][] = $canvas->s;
                    $canvas = new PdfCanvas();
                    $st['canvas'] = $canvas;
                    $st['pageNum']++;
                    $st['yTop'] = self::PAGE_H - 90;
                }
                $x = self::openSystem($canvas, $st['yTop'], $s, false);
                $beatUsed = 0.0;
            }
            // Barra de compasso quando o compasso encheu.
            if ($beatUsed >= $measureBeats - 1e-9) {
                $canvas->line($x - 7, $st['yTop'] - 4 * self::GAP, $x - 7, $st['yTop'], 1.2);
                $beatUsed = 0.0;
            }
            $x += 7;
            if ($note['rest']) {
                self::drawRest($canvas, $x, $st['yTop'], $note['duration']);
            } else {
                $step = self::step($note);
                $y = $st['yTop'] - 4 * self::GAP + $step * self::STEP;
                // Linhas suplementares.
                for ($ls = -2; $ls >= $step; $ls -= 2) {
                    $canvas->line($x - 9, $st['yTop'] - 4 * self::GAP + $ls * self::STEP, $x + 9, $st['yTop'] - 4 * self::GAP + $ls * self::STEP, 1.0);
                }
                for ($ls = 10; $ls <= $step; $ls += 2) {
                    $canvas->line($x - 9, $st['yTop'] - 4 * self::GAP + $ls * self::STEP, $x + 9, $st['yTop'] - 4 * self::GAP + $ls * self::STEP, 1.0);
                }
                if (strpos($note['pitch'], '#') !== false) {
                    self::drawSharp($canvas, $x - 11, $y);
                }
                $filled = ($note['duration'] === 'quarter' || $note['duration'] === 'eighth' || $note['duration'] === 'sixteenth');
                $up = $step < 4;
                self::noteHead($canvas, $x, $y, $filled);
                if ($note['duration'] !== 'whole') {
                    self::stem($canvas, $x, $y, $up, $note['duration']);
                }
            }
            $x += self::NOTE_DX;
            $beatUsed += $beats;
        }
    }

    /** Barra final dupla. */
    private static function finalBar(PdfCanvas $c, float $x, float $yTop): void
    {
        $c->line($x - 7, $yTop - 4 * self::GAP, $x - 7, $yTop, 1.4);
        $c->line($x - 4, $yTop - 4 * self::GAP, $x - 4, $yTop, 2.6);
    }

    /** Monta o documento a partir das páginas. */
    private static function finishDoc(array $pages): string
    {
        // Monta o documento.
        $w = new PdfWriter();
        $w->addRaw('<< /Type /Catalog /Pages 2 0 R >>'); // 1
        $kids = [];
        $n = count($pages);
        for ($i = 0; $i < $n; $i++) {
            $kids[] = (3 + 2 + $i * 2) . ' 0 R';
        }
        $w->addRaw('<< /Type /Pages /Kids [' . implode(' ', $kids) . '] /Count ' . $n . ' >>'); // 2
        $w->addRaw('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'); // 3
        $w->addRaw('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'); // 4
        $idx = 0;
        foreach ($pages as $i => $content) {
            $contentId = 6 + $i * 2;
            $foot = new PdfCanvas();
            $foot->text(self::MARGIN, 34, 'Gerador de Partituras IA  ·  pág. ' . ($i + 1), 9, 'F1');
            $w->addRaw('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ' . self::PAGE_W . ' ' . self::PAGE_H . '] '
                . '/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ' . $contentId . ' 0 R >>');
            $w->addStream($content . $foot->s);
        }
        return $w->build(1);
    }
}

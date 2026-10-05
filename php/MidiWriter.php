<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Construtor mínimo de SMF (Standard MIDI File).
 *
 * Formato 0, uma trilha, tudo em memória (compatível com serverless).
 * Sem dependências: monta MThd + MTrk com VLQ, meta-eventos e eventos
 * de canal. Compatível com players MIDI comuns.
 */
class MidiWriter
{
    /** @var int ticks por semínima */
    private $division;
    /** @var array<int, array{tick: int, seq: int, bytes: string}> */
    private $events = [];
    /** @var int */
    private $seq = 0;

    public function __construct(int $division = 480)
    {
        $this->division = $division > 0 ? $division : 480;
    }

    /** Codifica inteiro como quantidade de comprimento variável (VLQ). */
    public static function vlq(int $value): string
    {
        if ($value < 0) {
            $value = 0;
        }
        $bytes = [($value & 0x7F)];
        $value >>= 7;
        while ($value > 0) {
            array_unshift($bytes, ($value & 0x7F) | 0x80);
            $value >>= 7;
        }
        $out = '';
        foreach ($bytes as $b) {
            $out .= chr($b);
        }
        return $out;
    }

    /** Adiciona evento genérico no tick absoluto informado. */
    public function addEvent(int $tick, string $bytes): void
    {
        $this->events[] = ['tick' => max(0, $tick), 'seq' => $this->seq++, 'bytes' => $bytes];
    }

    /** Adiciona meta-evento (0xFF tipo dados). */
    public function addMeta(int $tick, int $type, string $data): void
    {
        $this->addEvent($tick, chr(0xFF) . chr($type & 0xFF) . self::vlq(strlen($data)) . $data);
    }

    /** Texto latin1 (títulos com acentos PT passam; demais viram '?'). */
    public static function latin1(string $text): string
    {
        // Substitui utf8_decode() (deprecated desde PHP 8.2; emite warning
        // que contaminava o binário em produção PHP 8.5). Sem @, sem saída.
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

    /** Monta o arquivo .mid final. */
    public function build(): string
    {
        usort($this->events, function ($a, $b) {
            if ($a['tick'] === $b['tick']) {
                return $a['seq'] <=> $b['seq'];
            }
            return $a['tick'] <=> $b['tick'];
        });
        $track = '';
        $last = 0;
        foreach ($this->events as $ev) {
            $track .= self::vlq($ev['tick'] - $last) . $ev['bytes'];
            $last = $ev['tick'];
        }
        $track .= "\x00\xFF\x2F\x00"; // fim de trilha
        $header = 'MThd' . pack('N', 6) . pack('n', 0) . pack('n', 1) . pack('n', $this->division);
        return $header . 'MTrk' . pack('N', strlen($track)) . $track;
    }
}

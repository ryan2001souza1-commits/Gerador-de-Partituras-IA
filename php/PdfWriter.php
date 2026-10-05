<?php
declare(strict_types=1);

/**
 * Gerador de Partituras IA — Escritor mínimo de PDF 1.4.
 *
 * Sem dependências: monta o documento em memória (compatível com o
 * ambiente serverless, sem filesystem) a partir de objetos, streams de
 * conteúdo e uma tabela xref calculada. Apenas texto WinAnsi (fontes
 * padrão Helvetica) e gráficos vetoriais.
 */
class PdfWriter
{
    /** @var array<int, string> */
    private $objects = [];

    /** Adiciona um objeto e devolve seu ID (iniciando em 1). */
    public function addRaw(string $content): int
    {
        $this->objects[] = $content;
        return count($this->objects);
    }

    /** Adiciona um stream de conteúdo e devolve seu ID. */
    public function addStream(string $data): int
    {
        return $this->addRaw("<< /Length " . strlen($data) . " >>\nstream\n" . $data . "\nendstream");
    }

    /** Monta o arquivo final. $rootId é o ID do objeto /Catalog. */
    public function build(int $rootId): string
    {
        $pdf = "%PDF-1.4\n%\xE2\xE3\xCF\xD3\n";
        $offsets = [];
        foreach ($this->objects as $i => $content) {
            $offsets[$i + 1] = strlen($pdf);
            $pdf .= ($i + 1) . " 0 obj\n" . $content . "\nendobj\n";
        }
        $xrefPos = strlen($pdf);
        $count = count($this->objects) + 1;
        $pdf .= "xref\n0 " . $count . "\n0000000000 65535 f \n";
        foreach ($offsets as $offset) {
            $pdf .= sprintf("%010d 00000 n \n", $offset);
        }
        $pdf .= "trailer\n<< /Size " . $count . " /Root " . $rootId . " 0 R >>\n";
        $pdf .= "startxref\n" . $xrefPos . "\n%%EOF";
        return $pdf;
    }
}

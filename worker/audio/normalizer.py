"""Worker de áudio — normalização para WAV padrão (FASE 3C).

Saída: WAV PCM s16le, 44100 Hz, estéreo. Apenas conversão de
formato/sample rate/canais — sem loudness, ganho ou dinâmica.
Segurança: lista de argumentos (nunca shell), timeout, sem injeção,
erros sanitizados. Nunca instala nada sozinho.
"""

import shutil
import subprocess
from pathlib import Path

FFMPEG_MISSING = (
    "ffmpeg ausente: instale o FFmpeg e verifique com "
    "'ffmpeg -version' e 'ffprobe -version'."
)

EXPECTED = {"format": "wav", "codec": "pcm_s16le",
            "sample_rate": 44100, "channels": 2}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def normalize_audio(source: Path, destination: Path,
                    timeout_s: float = 120.0) -> dict:
    """Converte para o WAV padrão e valida a saída. Sempre dict."""
    if not isinstance(source, Path) or not source.is_file():
        return {"ok": False, "error": "Arquivo inexistente."}
    if not isinstance(destination, Path):
        return {"ok": False, "error": "Destino inválido."}
    if not ffmpeg_available():
        return {"ok": False, "error": FFMPEG_MISSING}
    if not destination.parent.exists():
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False, "error": "Destino inválido."}
    if destination.exists() and destination.samefile(source):
        return {"ok": False, "error": "Destino inválido."}
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(source),
             "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
             str(destination)],
            capture_output=True, timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "error": "Falha na conversão de áudio."}
    if proc.returncode != 0:
        return {"ok": False, "error": "Arquivo de áudio inválido."}
    return _verify_output(destination)


def _verify_output(path: Path) -> dict:
    """Confere o WAV gerado com ffprobe + metadados."""
    from audio.validator import validate_audio
    probed = validate_audio(path)
    if not probed.get("ok"):
        return {"ok": False, "error": "Saída inválida."}
    checks = (
        probed.get("format") == EXPECTED["format"]
        and probed.get("codec") == EXPECTED["codec"]
        and probed.get("sample_rate") == EXPECTED["sample_rate"]
        and probed.get("channels") == EXPECTED["channels"]
    )
    if not checks:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": "Saída fora do padrão."}
    return {
        "ok": True,
        "path": str(path),
        "bytes": probed.get("bytes", 0),
        "duration": probed.get("duration"),
        "sample_rate": probed.get("sample_rate"),
        "channels": probed.get("channels"),
        "codec": probed.get("codec"),
        "format": probed.get("format"),
    }

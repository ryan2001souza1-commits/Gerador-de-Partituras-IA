"""Worker de áudio — validação via ffprobe (FASE 3B).

Nunca instala nada automaticamente: sem ffprobe, retorna erro claro
indicando a dependência. Sem eval/exec de conteúdo externo.
"""

import json
import shutil
import subprocess
from pathlib import Path

FFPROBE_MISSING = (
    "ffprobe ausente: instale o FFmpeg e verifique com "
    "'ffprobe -version' e 'ffmpeg -version'."
)


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def validate_audio(path: Path) -> dict:
    """Inspeciona o áudio com ffprobe. Sempre retorna dict com 'ok'."""
    if not isinstance(path, Path) or not path.is_file():
        return {"ok": False, "error": "Arquivo inexistente."}
    if not ffprobe_available():
        return {"ok": False, "error": FFPROBE_MISSING}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "error": "Falha ao inspecionar áudio."}
    if proc.returncode != 0:
        return {"ok": False, "error": "Arquivo de áudio inválido."}
    try:
        info = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        return {"ok": False, "error": "Arquivo de áudio inválido."}
    fmt = info.get("format", {}) if isinstance(info, dict) else {}
    streams = info.get("streams", []) if isinstance(info, dict) else []
    audio = next((s for s in streams
                  if isinstance(s, dict) and s.get("codec_type") == "audio"),
                 streams[0] if streams and isinstance(streams[0], dict) else {})

    def _num(value, cast):
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    size = _num(fmt.get("size"), int)
    if size is None:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
    return {
        "ok": True,
        "path": str(path),
        "bytes": size,
        "content_type": None,
        "duration": _num(fmt.get("duration"), float),
        "sample_rate": _num(audio.get("sample_rate"), int),
        "channels": _num(audio.get("channels"), int),
        "codec": audio.get("codec_name"),
        "format": fmt.get("format_name"),
    }

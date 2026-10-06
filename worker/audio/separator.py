"""Worker de áudio — separação de fontes com Demucs (FASE 3D).

Executa `python -m demucs` por subprocess (lista de argumentos, nunca
shell). CUDA quando disponível, CPU caso contrário. Nunca sobrescreve
a entrada. Sem eval/exec de conteúdo externo.
"""

import subprocess
import sys
from pathlib import Path

DEMUCS_MISSING = (
    "Demucs indisponível: instale com 'pip install demucs' "
    "(requer PyTorch)."
)

DEFAULT_STEMS = ("vocals", "drums", "bass", "other")


def default_device() -> str:
    """'cuda' se houver GPU utilizável, senão 'cpu'."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except (ImportError, OSError):
        pass
    return "cpu"


def _resolve_device(device: str) -> str:
    device = (device or "auto").strip().lower()
    if device not in ("auto", "cpu", "cuda"):
        raise ValueError("device deve ser auto, cpu ou cuda.")
    if device == "auto":
        return default_device()
    if device == "cuda" and default_device() != "cuda":
        raise ValueError("CUDA indisponível neste ambiente.")
    return device


def separate_sources(input_audio: Path, output_dir: Path,
                     device: str = "auto", model: str = "htdemucs",
                     timeout_s: float = 600.0) -> dict:
    """Separa em stems via Demucs. Sempre retorna dict com 'ok'."""
    if not isinstance(input_audio, Path) or not input_audio.is_file():
        return {"ok": False, "error": "Arquivo inexistente."}
    if not isinstance(output_dir, Path):
        return {"ok": False, "error": "Diretório de saída inválido."}
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"ok": False, "error": "Diretório de saída inválido."}
    try:
        resolved = _resolve_device(device)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not model or not isinstance(model, str):
        return {"ok": False, "error": "Modelo inválido."}
    cmd = [sys.executable, "-m", "demucs", "--out", str(output_dir),
           "-d", resolved, "-n", model, str(input_audio)]
    try:
        proc = subprocess.run(cmd, capture_output=True,
                              timeout=timeout_s, check=False)
    except FileNotFoundError:
        return {"ok": False, "error": DEMUCS_MISSING}
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "error": "Falha na separação de áudio."}
    if proc.returncode != 0:
        return {"ok": False, "error": "Falha na separação de áudio."}
    track_dir = output_dir / model / input_audio.stem
    stems = {}
    for name in DEFAULT_STEMS:
        f = track_dir / (name + ".wav")
        if not f.is_file():
            return {"ok": False, "error": "Stem ausente: " + name + "."}
        try:
            size = f.stat().st_size
        except OSError:
            return {"ok": False, "error": "Stem ilegível: " + name + "."}
        stems[name] = {"path": str(f), "bytes": size}
    return {"ok": True, "device": resolved, "model": model,
            "stems": stems, "track_dir": str(track_dir),
            "note": "'other' é stem residual, não instrumento identificado."}

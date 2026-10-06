"""Guarda de caminhos do worker (diretório controlado)."""

import tempfile
from pathlib import Path

from config import settings


def allowed_dir() -> Path:
    configured = (settings.AUDIO_TMP_DIR or "").strip()
    base = Path(configured) if configured else Path(tempfile.gettempdir())
    return base.resolve()


def inside_allowed(path: Path) -> bool:
    """True se o caminho (resolvendo symlinks) está no diretório."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    base = allowed_dir()
    return resolved == base or base in resolved.parents

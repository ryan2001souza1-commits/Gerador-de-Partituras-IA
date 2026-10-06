"""Worker de áudio — configuração (FASE 3A: fundação).

Lê variáveis de ambiente com padrões inofensivos. Nenhum segredo é
obrigatório nesta fase (sem Supabase, sem webhook, sem processamento).
Nunca imprimir valores de secrets.
"""

import os


def _get(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value if isinstance(value, str) else default


class Settings:
    """Configuração do worker (estendida nas próximas fases)."""

    # Rede/serviço (RunPod injeta PORT; WORKER_PORT é o override
    # legado; padrão 8001 quando nenhum está definido).
    HOST: str = _get("WORKER_HOST", "127.0.0.1")
    PORT: int = int(_get("PORT", "") or _get("WORKER_PORT", "8001")
                    or 8001)

    # Futuro: Supabase (Storage + Postgres) — opcionais por enquanto.
    SUPABASE_URL: str = _get("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY: str = _get("SUPABASE_SERVICE_ROLE_KEY")

    # Futuro: callback p/ o webhook da API (FASE 3B+).
    CALLBACK_URL: str = _get("CALLBACK_URL")
    CALLBACK_TOKEN: str = _get("CALLBACK_TOKEN")

    # Limites da ingestão (FASE 3B): 25 MB e 30s por padrão.
    AUDIO_MAX_BYTES: int = int(_get("AUDIO_MAX_BYTES", "26214400") or 26214400)
    AUDIO_DOWNLOAD_TIMEOUT_S: float = float(
        _get("AUDIO_DOWNLOAD_TIMEOUT_S", "30") or 30)
    AUDIO_NORMALIZE_TIMEOUT_S: float = float(
        _get("AUDIO_NORMALIZE_TIMEOUT_S", "120") or 120)
    # Demucs (FASE 3D): auto seleciona CUDA quando há GPU utilizável.
    DEMUCS_MODEL: str = _get("DEMUCS_MODEL", "htdemucs") or "htdemucs"
    DEMUCS_TIMEOUT_S: float = float(
        _get("DEMUCS_TIMEOUT_S", "600") or 600)
    DEMUCS_DEVICE: str = (_get("DEMUCS_DEVICE", "auto") or "auto").strip().lower()
    AUDIO_TMP_DIR: str = _get("AUDIO_TMP_DIR", "")

settings = Settings()

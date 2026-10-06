"""Worker de áudio — API FastAPI (fundação, ingestão, análise).

Saúde, teste interno, ingestão, normalização, análise de stems e
transcrição musical. Nenhum acesso a Supabase, nenhum webhook, nenhum
DSP pesado aqui (modelos carregam por lazy-load nos adapters).
"""

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from audio import paths as audio_paths
from audio.analysis import KNOWN_STEMS, analyze_stems
from audio.downloader import DownloadError, download_audio, validate_source_url
from audio.models import (AudioJobRequest, AudioMetadata, NormalizedAudioMetadata,
                          NormalizeRequest)
from audio.normalizer import normalize_audio
from audio.validator import validate_audio
from config import settings  # noqa: F401 (base p/ próximas fases)
from models import HealthResponse, TestJobRequest, TestJobResponse

app = FastAPI(title="audio-worker")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        from audio.separator import default_device
        device = default_device()
    except Exception:
        device = "cpu"  # health nunca quebra por causa do device
    return HealthResponse(ok=True, service="audio-worker",
                          device=device)


@app.post("/jobs/test", response_model=TestJobResponse)
def jobs_test(payload: TestJobRequest) -> TestJobResponse:
    return TestJobResponse(accepted=True, job_id=payload.job_id,
                           status="queued")


@app.post("/jobs/ingest")
def jobs_ingest(payload: AudioJobRequest):
    """Baixa e valida áudio em diretório temporário (sem persistir)."""
    try:
        validate_source_url(payload.source_url)
    except DownloadError as exc:
        return {"accepted": False, "error": str(exc)}
    tmpdir = tempfile.mkdtemp(prefix="gpi-audio-",
                              dir=settings.AUDIO_TMP_DIR or None)
    try:
        dest = Path(tmpdir) / "original.bin"
        try:
            dl = download_audio(
                payload.source_url, dest,
                max_bytes=settings.AUDIO_MAX_BYTES,
                timeout_s=settings.AUDIO_DOWNLOAD_TIMEOUT_S)
        except DownloadError as exc:
            return {"accepted": False, "error": str(exc)}
        probed = validate_audio(dest)
        if not probed.get("ok"):
            status_code = 503 if "ffprobe" in str(probed.get("error", "")) else 502
            return {"accepted": False, "error": probed.get("error"),
                    "status_code": status_code}
        meta = AudioMetadata(
            bytes=int(dl.get("bytes", 0)),
            content_type=dl.get("content_type"),
            duration=probed.get("duration"),
            sample_rate=probed.get("sample_rate"),
            channels=probed.get("channels"),
            codec=probed.get("codec"),
            format=probed.get("format"),
        )
        return {"accepted": True, "job_id": payload.job_id,
                "status": "validated",
                "audio": meta.model_dump(exclude={"path"})}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _allowed_dir() -> Path:
    return audio_paths.allowed_dir()


def _inside_allowed(path: Path) -> bool:
    return audio_paths.inside_allowed(path)


@app.post("/audio/normalize")
def audio_normalize(payload: NormalizeRequest):
    """Normalização local de teste: só dentro do diretório controlado."""
    source = Path(payload.source_path)
    if not _inside_allowed(source):
        return {"success": False,
                "error": "Caminho fora do diretório permitido."}
    tmpdir = tempfile.mkdtemp(prefix="gpi-norm-",
                              dir=settings.AUDIO_TMP_DIR or None)
    # Sucesso em endpoint de teste: mantém o WAV (limpeza manual).
    # Falha ou exceção: limpa o temporário.
    dest = Path(tmpdir) / "normalized.wav"
    result = normalize_audio(
        source, dest, timeout_s=settings.AUDIO_NORMALIZE_TIMEOUT_S)
    if not result.get("ok"):
        shutil.rmtree(tmpdir, ignore_errors=True)
        return {"success": False, "error": result.get("error")}
    meta = NormalizedAudioMetadata(
        path=str(dest),
        bytes=int(result.get("bytes", 0)),
        duration=result.get("duration"),
        sample_rate=result.get("sample_rate"),
        channels=result.get("channels"),
        codec=result.get("codec"),
        format=result.get("format"),
    )
    return {"success": True, "audio": meta.model_dump()}


class AnalyzeStemsRequest(BaseModel):
    stems: dict
    metadata: dict = {}


@app.post("/audio/analyze-stems")
def audio_analyze_stems(payload: AnalyzeStemsRequest):
    """Análise local de stems (sem rede, sem Supabase, sem webhook)."""
    stems = payload.stems if isinstance(payload.stems, dict) else {}
    for name, raw_path in list(stems.items()):
        if name not in KNOWN_STEMS:
            return {"success": False,
                    "error": "Stem desconhecido: %s." % str(name)[:40]}
        if not isinstance(raw_path, str):
            return {"success": False, "error": "Caminho inválido."}
        lowered = raw_path.strip().lower()
        if lowered.startswith(("http://", "https://", "file://")):
            return {"success": False, "error": "URL não aceita aqui."}
        candidate = Path(raw_path)
        if not audio_paths.inside_allowed(candidate):
            return {"success": False,
                    "error": "Caminho fora do diretório permitido."}
        try:
            if candidate.stat().st_size > settings.AUDIO_MAX_BYTES:
                return {"success": False, "error": "Arquivo muito grande."}
        except OSError:
            return {"success": False, "error": "Arquivo inacessível."}
    try:
        result = analyze_stems(
            {k: str(v) for k, v in stems.items()},
            payload.metadata if isinstance(payload.metadata, dict) else {})
    except ValueError as exc:
        return {"success": False, "error": str(exc)[:120]}
    return {"success": True, "analysis": result}


class TranscribeRequest(BaseModel):
    audio_path: str
    stem: str = ""
    instrument_id: str = ""


@app.post("/audio/transcribe")
def audio_transcribe(payload: TranscribeRequest):
    """Transcrição musical local (sem rede, sem Supabase, sem webhook)."""
    from audio.transcriber import KNOWN_STEMS, TranscriptionUnavailable
    raw = payload.audio_path if isinstance(payload.audio_path, str) else ""
    if not raw:
        return {"success": False, "error": "Caminho inválido."}
    lowered = raw.strip().lower()
    if lowered.startswith(("http://", "https://", "file://")):
        return {"success": False, "error": "URL não aceita aqui."}
    candidate = Path(raw)
    if not audio_paths.inside_allowed(candidate):
        return {"success": False,
                "error": "Caminho fora do diretório permitido."}
    try:
        if candidate.stat().st_size > settings.AUDIO_MAX_BYTES:
            return {"success": False, "error": "Arquivo muito grande."}
    except OSError:
        return {"success": False, "error": "Arquivo inacessível."}
    stem = (payload.stem or "").strip() or None
    if stem is not None and stem not in KNOWN_STEMS:
        return {"success": False,
                "error": "Stem desconhecido: %s." % str(stem)[:40]}
    instrument = (payload.instrument_id or "").strip() or None
    try:
        from audio.transcriber import MusicTranscriber
        tr = MusicTranscriber()
        if stem is not None:
            result = tr.transcribe_stem(
                str(candidate), stem=stem, instrument=instrument)
        else:
            result = tr.transcribe(str(candidate), instrument=instrument)
    except TranscriptionUnavailable as exc:
        return {"success": False, "error": str(exc)[:120]}
    return {"success": True, "transcription": result}


class TranscribeJobRequest(BaseModel):
    job_id: str = ""
    audio_source_id: str = ""
    source_id: str = ""
    audio_url: str = ""
    callback_url: str = ""


# Jobs aceitos (idempotência de aceite; sem re-agendar duplicado).
_accepted_jobs: set = set()


def _run_transcription_job(job_id: str, source_id: str, audio_url: str,
                           callback_url: str) -> None:
    """Executa o pipeline em background; erros contidos, sem segredos."""
    import logging
    import os as _os

    from job_processor import process_job
    try:
        process_job(
            job_id, audio_url, callback_url,
            _os.environ.get("WORKER_WEBHOOK_SECRET", ""),
            source_id=source_id or None)
    except Exception:
        logging.getLogger("job_processor").warning(
            "job %s: falha em background", job_id)


@app.post("/jobs/transcribe")
def jobs_transcribe(payload: TranscribeJobRequest,
                    background_tasks: BackgroundTasks):
    """Aceita job do dispatch PHP e processa em background.

    Responde IMEDIATAMENTE (sem executar Demucs aqui). Validação de
    forma apenas (http/https); SSRF continua valendo no download e
    no webhook. Segredo do webhook vem do env do worker, nunca do JSON.
    """
    job_id = (payload.job_id or "").strip()
    audio_url = (payload.audio_url or "").strip()
    callback_url = (payload.callback_url or "").strip()
    source_id = (payload.audio_source_id or payload.source_id or "").strip()
    if not job_id or len(job_id) > 100:
        return {"accepted": False, "error": "job_id inválido."}
    for url in (audio_url, callback_url):
        lowered = url.lower()
        if not (lowered.startswith("http://")
                or lowered.startswith("https://")) or len(url) > 2048:
            return {"accepted": False, "error": "URL inválida."}
    if job_id not in _accepted_jobs:
        _accepted_jobs.add(job_id)
        background_tasks.add_task(
            _run_transcription_job, job_id, source_id,
            audio_url, callback_url)
    return {"accepted": True, "job_id": job_id, "status": "queued"}

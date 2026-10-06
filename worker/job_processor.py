"""Integração Worker ↔ job de transcrição (FASE 3L).

Orquestra o pipeline REAL (download → validate → normalize →
separate → classify → transcribe → analyze → tracks → result) e
entrega o resultado ao webhook PHP existente. Sem mocks em produção,
sem frontend, sem banco, sem deploy.

Mapeamento de estágios p/ o vocabulário fechado do contrato
(docs/worker-contract.md + AudioConfig::STAGES — qualquer outro valor
retorna 400 no webhook):
  queued(0) → downloading(5) → decoding(15 download concluído,
  20 validado, 25 normalizado) → separating(40) →
  detecting_instruments(55) → extracting_notes(70) →
  analyzing(82) → building_score(92) → completed/failed(100).

Status parcial interno (3K) vai ao webhook como `completed` (o
contrato só aceita queued|processing|completed|failed); a fidelidade
total permanece no valor de retorno e no campo futuro `result`.
"""

import logging
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from audio import evidence as audio_evidence
from audio.analysis import MIN_ACTIVITY, analyze_stems
from audio.downloader import (DownloadError, download_audio,
                              validate_source_url)
from audio.music import process_music_notes
from audio.musical_analysis import analyze_music
from audio.normalizer import normalize_audio
from audio.separator import separate_sources
from audio.tracks import build_tracks
from audio.transcriber import MusicTranscriber
from audio.transcription_result import (
    build_transcription_result, validate_transcription_result)
from audio.validator import validate_audio
from config import settings

log = logging.getLogger("job_processor")

# Progresso por estágio (contrato: 0–100).
STAGES = (
    ("queued", 0),
    ("downloading", 5),
    ("decoding", 15),
    ("decoding", 20),
    ("decoding", 25),
    ("separating", 40),
    ("detecting_instruments", 55),
    ("extracting_notes", 70),
    ("analyzing", 82),
    ("building_score", 92),
    ("completed", 100),
)
TERMINAL_STATUSES = ("completed", "partial", "failed")
WEBHOOK_MAX_ATTEMPTS = 3
WEBHOOK_BACKOFF_S = (1.0, 2.0)
DOWNLOAD_MAX_ATTEMPTS = 2
# Erros de download transitórios (com retry); demais são finais.
TRANSIENT_DOWNLOAD_MARKERS = (
    "TimeoutException", "ConnectError", "NetworkError",
    "Origem indisponível",
)
SILENT_ACTIVITY_THRESHOLD = MIN_ACTIVITY


class JobError(Exception):
    """Erro estruturado do pipeline (código seguro + estágio)."""

    def __init__(self, code, message, stage="failed", progress=0):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.progress = progress


class WebhookAuthError(JobError):
    """401/403: falha permanente de autenticação (sem retry)."""


class WebhookConflict(Exception):
    """409: já registrado (idempotência) — terminal sem retry."""


def redact_url(url):
    """Mostra só esquema+host (nunca query/token/caminho)."""
    try:
        parts = urlparse(url if isinstance(url, str) else "")
        host = parts.hostname or "?"
        return "%s://%s/…(redacted)" % (parts.scheme or "?",
                                        host)
    except ValueError:
        return "?(redacted)"


def _valid_job_id(job_id):
    return (isinstance(job_id, str) and 1 <= len(job_id) <= 100)


def _wants_retry_download(message):
    return any(marker in str(message)
               for marker in TRANSIENT_DOWNLOAD_MARKERS)


def _default_sender(url, headers, payload, timeout_s=30.0):
    """Envio real (valida SSRF antes; segredo só no header)."""
    validate_source_url(url)
    with httpx.Client(timeout=timeout_s,
                      follow_redirects=False) as client:
        response = client.post(url, json=payload, headers=headers)
        return response.status_code, response.text[:500]


def post_webhook(callback_url, secret, payload, sender=None,
                 max_attempts=WEBHOOK_MAX_ATTEMPTS):
    """POST no webhook com retry limitado (5xx/rede) e sem loop.

    2xx → ok. 401/403 → WebhookAuthError (permanente). 409 →
    WebhookConflict (terminal). 5xx/rede → retry; demais 4xx →
    falha permanente. Segredo nunca entra no payload.
    """
    if not callback_url or not secret:
        raise JobError("webhook_failed",
                       "Callback não configurado.",
                       stage="failed", progress=100)
    safe_payload = dict(payload)
    headers = {"X-Webhook-Secret": secret,
               "Content-Type": "application/json"}
    send = sender or _default_sender
    last_status = None
    for attempt in range(1, max_attempts + 1):
        try:
            status, _body = send(callback_url, headers,
                                 safe_payload)
        except DownloadError as exc:
            raise JobError("webhook_failed", str(exc),
                           stage="failed", progress=100)
        except (httpx.TimeoutException, httpx.ConnectError,
                httpx.NetworkError) as exc:
            last_status = "network:%s" % type(exc).__name__
            if attempt < max_attempts:
                time.sleep(WEBHOOK_BACKOFF_S[min(
                    attempt - 1, len(WEBHOOK_BACKOFF_S) - 1)])
                continue
            raise JobError("webhook_failed",
                           "Webhook indisponível.",
                           stage="failed", progress=100)
        last_status = status
        if 200 <= status < 300:
            return {"ok": True, "status_code": status,
                    "attempts": attempt}
        if status in (401, 403):
            raise WebhookAuthError(
                "webhook_failed", "Webhook não autorizado.",
                stage="failed", progress=100)
        if status == 409:
            raise WebhookConflict("job já registrado")
        if 500 <= status < 600:
            if attempt < max_attempts:
                time.sleep(WEBHOOK_BACKOFF_S[min(
                    attempt - 1, len(WEBHOOK_BACKOFF_S) - 1)])
                continue
            raise JobError("webhook_failed",
                           "Webhook indisponível.",
                           stage="failed", progress=100)
        raise JobError("webhook_failed",
                       "Webhook rejeitou o resultado.",
                       stage="failed", progress=100)
    raise JobError("webhook_failed", "Webhook indisponível "
                   "(%s)." % last_status,
                   stage="failed", progress=100)


def _emit(sender, callback_url, secret, job_id, status, progress,
          stage, error_code=None, error_message=None,
          worker_job_id=None, result=None, strict=False):
    """Atualização de progresso (best-effort) ou final (strict)."""
    payload = {"job_id": job_id, "status": status,
               "progress": progress, "current_stage": stage,
               "error_code": error_code, "error_message": error_message,
               "worker_job_id": worker_job_id}
    if result is not None:
        payload["result"] = result  # compat futura (PHP ignora hoje)
    try:
        post_webhook(callback_url, secret, payload, sender=sender)
    except WebhookConflict:
        log.info("job %s: webhook 409 (idempotente)", job_id)
    except (JobError, WebhookAuthError) as exc:
        log.warning("job %s: progresso não entregue (%s)", job_id,
                    exc.code if isinstance(exc, JobError) else "auth")
        if strict:
            raise
    return payload


def process_job(job_id, audio_url, callback_url, callback_secret,
                source_id=None, force=False, known_status=None,
                sender=None, download_client=None, tmp_base=None,
                local_source_path=None):
    """Executa o job completo e entrega ao webhook. Sempre dict.

    Idempotência: known_status completed/partial → não reprocessa;
    failed → só com force=True. `local_source_path` permite ingestão
    local em testes (nunca exposto em endpoint).
    """
    if not _valid_job_id(job_id):
        raise ValueError("job_id inválido.")
    if known_status in ("completed", "partial") and not force:
        log.info("job %s: já %s, sem reprocessar", job_id,
                 known_status)
        return {"job_id": job_id, "status": known_status,
                "progress": 100, "reprocessed": False}
    if known_status == "failed" and not force:
        log.info("job %s: failed anterior, sem reprocessar", job_id)
        return {"job_id": job_id, "status": "failed",
                "progress": 0, "reprocessed": False}

    tmpdir = Path(tempfile.mkdtemp(
        prefix="gpi-job-", dir=tmp_base or
        (settings.AUDIO_TMP_DIR or None)))
    worker_job_id = "worker-%s" % job_id[:8]

    def progress(status, prog, stage):
        _emit(sender, callback_url, callback_secret, job_id,
              status, prog, stage, worker_job_id=worker_job_id)

    try:
        progress("processing", 0, "queued")
        progress("processing", 5, "downloading")
        if local_source_path is not None:
            original = Path(local_source_path)
            if not original.is_file():
                raise JobError("download_failed",
                               "Áudio de teste inacessível.",
                               stage="failed", progress=5)
            staged = tmpdir / "original.bin"
            staged.write_bytes(original.read_bytes())
            downloaded_bytes = staged.stat().st_size
        else:
            staged = tmpdir / "original.bin"
            downloaded_bytes = None
            for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
                try:
                    info = download_audio(
                        audio_url, staged,
                        max_bytes=settings.AUDIO_MAX_BYTES,
                        timeout_s=settings.AUDIO_DOWNLOAD_TIMEOUT_S,
                        client=download_client)
                    downloaded_bytes = info.get("bytes", 0)
                    break
                except DownloadError as exc:
                    if attempt < DOWNLOAD_MAX_ATTEMPTS \
                            and _wants_retry_download(exc):
                        log.info("job %s: retry de download", job_id)
                        continue
                    raise JobError("download_failed", str(exc),
                                   stage="failed", progress=5)
        progress("processing", 15, "decoding")
        probed = validate_audio(staged)
        if not probed.get("ok"):
            raise JobError("validation_failed",
                           str(probed.get("error", "Áudio inválido.")),
                           stage="failed", progress=15)
        progress("processing", 20, "decoding")
        normalized = tmpdir / "normalized.wav"
        norm = normalize_audio(
            staged, normalized,
            timeout_s=settings.AUDIO_NORMALIZE_TIMEOUT_S)
        if not norm.get("ok"):
            raise JobError("normalization_failed",
                           str(norm.get("error", "Falha ao normalizar.")),
                           stage="failed", progress=20)
        progress("processing", 25, "decoding")
        progress("processing", 40, "separating")
        separated = separate_sources(
            normalized, tmpdir / "stems",
            device=settings.DEMUCS_DEVICE, model=settings.DEMUCS_MODEL,
            timeout_s=settings.DEMUCS_TIMEOUT_S)
        if not separated.get("ok"):
            raise JobError("separation_failed",
                           str(separated.get("error",
                                             "Falha na separação.")),
                           stage="failed", progress=40)
        stem_paths = {name: meta["path"]
                      for name, meta in separated["stems"].items()}
        progress("processing", 55, "detecting_instruments")
        try:
            classification = analyze_stems(dict(stem_paths), {},
                                           classifier="panns")
        except (ValueError, RuntimeError) as exc:
            raise JobError("classification_failed", str(exc)[:120],
                           stage="failed", progress=55)
        progress("processing", 70, "extracting_notes")
        transcriber = MusicTranscriber()
        try:
            transcriber.load()
        except Exception as exc:
            raise JobError("transcription_failed",
                           "Modelo de transcrição indisponível: %s"
                           % type(exc).__name__,
                           stage="failed", progress=70)
        track_payload, all_notes = {}, []
        try:
            for stem in ("vocals", "drums", "bass", "other"):
                path = stem_paths[stem]
                if stem == "drums":
                    stem_notes = []
                else:
                    transcribed = transcriber.transcribe_stem(
                        path, stem=stem)
                    stem_notes = transcribed.get("notes", [])
                all_notes.extend(stem_notes)
                processed = process_music_notes(stem_notes,
                                                bpm=None)
                track_payload[stem] = {
                    "detections": [
                        d for d in
                        classification.get("detections", [])
                        if d.get("stem") == stem],
                    "ambiguous": [
                        a for a in
                        classification.get("ambiguous", [])
                        if a.get("stem") == stem],
                    "notes": stem_notes,
                    "analysis": analyze_music(processed),
                    "silent": _is_silent(path, stem_notes, stem),
                    "duration_seconds": (
                        classification.get("duration_seconds")
                        or 0.0),
                    "warnings": [],
                }
        except JobError:
            raise
        except Exception as exc:
            raise JobError("transcription_failed",
                           "Falha na transcrição: %s"
                           % type(exc).__name__,
                           stage="failed", progress=70)
        progress("processing", 82, "analyzing")
        try:
            global_processed = process_music_notes(all_notes,
                                                   bpm=None)
            global_music = analyze_music(global_processed)
            tracks_result = build_tracks(track_payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise JobError("analysis_failed", str(exc)[:120],
                           stage="failed", progress=82)
        progress("processing", 92, "building_score")
        source_meta = {
            "duration_seconds": classification.get(
                "duration_seconds") or norm.get("duration"),
            "sample_rate": norm.get("sample_rate"),
            "channels": norm.get("channels"),
            "format": norm.get("format") or norm.get("codec"),
        }
        try:
            final = build_transcription_result(
                source_meta, global_music, tracks_result)
        except (ValueError, KeyError, TypeError) as exc:
            raise JobError("result_failed", str(exc)[:120],
                           stage="failed", progress=92)
        problems = validate_transcription_result(final)
        if problems:
            raise JobError("result_failed", problems[0][:120],
                           stage="failed", progress=92)
        internal = final["status"]
        webhook_status = ("completed" if internal in
                          ("ready", "partial") else "failed")
        result_body = {
            "job_id": job_id,
            "status": internal,
            "progress": 100,
            "current_stage": ("completed" if internal in
                              ("ready", "partial") else "failed"),
            "tracks": final["tracks"],
            "instruments": final["statistics"]["instruments"],
            "notes": {"total": final["statistics"]["total_notes"],
                      "by_track": {
                          t["track_id"]: t["statistics"]["note_count"]
                          for t in final["tracks"]}},
            "bpm": (final["music"].get("tempo") or {}).get("bpm"),
            "key": final["music"].get("key"),
            "time_signature": {
                "numerator": (final["music"].get("meter") or {}).get(
                    "numerator"),
                "denominator": (
                    final["music"].get("meter") or {}).get(
                    "denominator")},
            "confidence": final["confidence"],
            "warnings": [w["code"] for w in final["warnings"]],
            "statistics": final["statistics"],
            "downloaded_bytes": downloaded_bytes,
            "transcription": final,
        }
        _emit(sender, callback_url, callback_secret, job_id,
              webhook_status, 100, result_body["current_stage"],
              worker_job_id=worker_job_id, result=result_body,
              strict=True)
        log.info("job %s: %s (%s) via %s", job_id, internal,
                 redact_url(audio_url), redact_url(callback_url))
        return dict(result_body, reprocessed=True,
                    error_code=None, error_message=None)
    except WebhookAuthError:
        raise
    except WebhookConflict:
        return {"job_id": job_id, "status": "completed",
                "progress": 100, "reprocessed": False,
                "error_code": None,
                "error_message": "Conflito: já registrado."}
    except JobError as exc:
        if exc.code != "webhook_failed":
            try:
                _emit(sender, callback_url, callback_secret, job_id,
                      "failed", exc.progress, "failed",
                      error_code=exc.code,
                      error_message=str(exc)[:300],
                      worker_job_id=worker_job_id)
            except (JobError, WebhookAuthError, WebhookConflict):
                pass
        log.warning("job %s: %s", job_id, exc.code)
        return {"job_id": job_id, "status": "failed",
                "progress": exc.progress,
                "current_stage": "failed",
                "error_code": exc.code,
                "error_message": str(exc)[:300],
                "reprocessed": True}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _is_silent(path, notes, stem):
    """Stem silencioso: sem notas (exceto drums) + atividade baixa."""
    if stem == "drums":
        note_count = 0
    else:
        note_count = len(notes)
    if note_count > 0:
        return False
    try:
        measured = audio_evidence.measure(Path(path))
    except (OSError, ValueError):
        return True
    if not measured.get("ok"):
        return True
    return measured.get("activity", 0.0) < SILENT_ACTIVITY_THRESHOLD

"""Testes da integração Worker ↔ job (FASE 3L, mocks unitários)."""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import job_processor as JP
from audio.downloader import DownloadError

JOB = "123e4567-e89b-42d3-a456-426614174000"
URL = "https://cdn.test/audio.wav"
HOOK = "https://api.test/api/transcription/webhook"
SECRET = "segredo-de-teste-123"


def ok_sender(calls=None, code=200):
    def send(url, headers, payload):
        (calls if calls is not None else []).append(
            (url, dict(headers), dict(payload)))
        return code, "ok"
    return send


def full_mocks(tmpdir):
    """Pipeline produtivo simulado (só nos testes)."""
    stems = {}
    for name in ("vocals", "drums", "bass", "other"):
        f = Path(tmpdir) / (name + ".wav")
        f.write_bytes(b"RIFF" + bytes(100))
        stems[name] = str(f)
    classification = {
        "duration_seconds": 4.0,
        "detections": [{
            "instrument_id": "piano", "confidence": 0.87,
            "stem": "other", "detection_method": "panns-cnn14",
            "direct_detection": True, "evidence": []}],
        "ambiguous": [],
    }
    notes = [{"pitch": 60, "start": 0.1, "end": 0.6,
              "duration": 0.5, "velocity": 80, "confidence": 0.7}]
    processed = {"bpm": 120.0, "notes": [], "total_measures": 1,
                 "grid": {"division": "1/4", "beats": 1.0},
                 "chords": []}
    music = {"tempo": {"bpm": 120.0, "confidence": 0.8},
             "key": {"tonic": "C", "mode": "major",
                     "confidence": 0.7},
             "scale": {"name": "C major", "notes": ["C"],
                       "confidence": 0.7},
             "meter": {"numerator": 4, "denominator": 4,
                       "confidence": 0.7},
             "grid": {"division": "1/4"}, "chords": [],
             "sections": [], "statistics": {}, "confidence": 0.7}
    tracks = {"tracks": [{
        "track_id": "track_01", "source_stem": "other",
        "instrument": {"name": "piano", "display_name": "Piano",
                       "family": "keyboards", "confidence": 0.87,
                       "source_label": "piano", "top_candidates": []},
        "evidence": {"classifier": "panns-cnn14",
                     "direct_detection": True, "stem_type": "other",
                     "warnings": []},
        "notes": notes,
        "statistics": {"note_count": 1, "pitch_min": 60,
                       "pitch_max": 60, "mean_velocity": 80,
                       "mean_duration": 0.5, "density": 2.0,
                       "active_seconds": 0.6, "silence_seconds": 3.4},
        "musical_analysis": {"bpm": 120.0}, "selected": True,
        "editable": True, "status": "ready"}],
        "track_count": 1, "selected_count": 1,
        "instrument_count": 1, "families": ["keyboards"],
        "confidence": 0.87, "warnings": []}
    final = {"schema_version": "1.0", "status": "ready",
             "source": {"duration_seconds": 4.0}, "music": music,
             "tracks": tracks["tracks"],
             "selection": {"selected_track_ids": ["track_01"],
                           "selected_count": 1, "available_count": 1,
                           "ambiguous_count": 0, "silent_count": 0},
             "statistics": {"total_notes": 1,
                            "instruments": ["piano"]},
             "warnings": [], "confidence": 0.8}
    return stems, classification, notes, processed, music, tracks, \
        final


def patch_pipeline(test, tmpdir):
    stems, cls, notes, proc, music, tracks, final = full_mocks(
        tmpdir)
    test.patchers = [
        mock.patch.object(JP, "download_audio",
                          return_value={"bytes": 10}),
        mock.patch.object(JP, "validate_audio",
                          return_value={"ok": True}),
        mock.patch.object(JP, "normalize_audio",
                          return_value={"ok": True, "duration": 4.0,
                                        "sample_rate": 44100,
                                        "channels": 2,
                                        "format": "wav"}),
        mock.patch.object(JP, "separate_sources",
                          return_value={"ok": True, "stems": {
                              n: {"path": p, "bytes": 10}
                              for n, p in stems.items()}}),
        mock.patch.object(JP, "analyze_stems",
                          return_value=cls),
        mock.patch.object(JP.MusicTranscriber, "load",
                          return_value=object()),
        mock.patch.object(JP.MusicTranscriber, "transcribe_stem",
                          return_value={"notes": notes}),
        mock.patch.object(JP, "process_music_notes",
                          return_value=proc),
        mock.patch.object(JP, "analyze_music", return_value=music),
        mock.patch.object(JP, "build_tracks", return_value=tracks),
        mock.patch.object(JP, "build_transcription_result",
                          return_value=final),
        mock.patch.object(JP, "validate_transcription_result",
                          return_value=[]),
        mock.patch.object(JP.audio_evidence, "measure",
                          return_value={"ok": True,
                                        "activity": 0.9}),
    ]
    for patcher in test.patchers:
        patcher.start()
    test.addCleanup(lambda: [p.stop() for p in test.patchers])
    return final


class TestJobProcessor(unittest.TestCase):
    def test_job_valido_completo(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            out = JP.process_job(JOB, URL, HOOK, SECRET,
                                 sender=ok_sender(calls))
        self.assertEqual(out["status"], "ready")
        self.assertEqual(out["progress"], 100)
        self.assertEqual(out["tracks"][0]["instrument"]["name"],
                         "piano")
        self.assertEqual(out["bpm"], 120.0)
        self.assertTrue(out["reprocessed"])
        final_calls = [c for c in calls
                       if c[2]["progress"] == 100]
        self.assertEqual(len(final_calls), 1)
        body = final_calls[0][2]
        self.assertEqual(body["status"], "completed")
        self.assertNotIn(SECRET, str(body))
        self.assertNotIn("service_role", str(body).lower())

    def test_download_falha(self):
        with mock.patch.object(
                JP, "download_audio",
                side_effect=DownloadError("Áudio não encontrado.")):
            out = JP.process_job(JOB, URL, HOOK, SECRET,
                                 sender=ok_sender())
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error_code"], "download_failed")

    def test_audio_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "validate_audio",
                    return_value={"ok": False,
                                  "error": "Arquivo inválido."}):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"], "validation_failed")

    def test_erro_normalizacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "normalize_audio",
                    return_value={"ok": False,
                                  "error": "Falha."}):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"], "normalization_failed")

    def test_erro_demucs(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "separate_sources",
                    return_value={"ok": False, "error": "Falha."}):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"], "separation_failed")

    def test_erro_panns(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "analyze_stems",
                    side_effect=ValueError("Stem desconhecido")):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"],
                         "classification_failed")

    def test_erro_basic_pitch(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP.MusicTranscriber, "load",
                    side_effect=RuntimeError("sem modelo")):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"], "transcription_failed")

    def test_erro_analise(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "build_tracks",
                    side_effect=ValueError("Stems inválidos")):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"], "analysis_failed")

    def test_resultado_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            final = patch_pipeline(self, tmp)
            final["status"] = "partial"
            out = JP.process_job(JOB, URL, HOOK, SECRET,
                                 sender=ok_sender())
        self.assertEqual(out["status"], "partial")

    def test_resultado_failed_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "validate_transcription_result",
                    return_value=["pitch inválido"]):
                out = JP.process_job(JOB, URL, HOOK, SECRET,
                                     sender=ok_sender())
        self.assertEqual(out["error_code"], "result_failed")

    def test_webhook_200(self):
        self.assertEqual(
            JP.post_webhook(HOOK, SECRET, {"job_id": JOB},
                            sender=ok_sender(code=200))["ok"], True)

    def test_webhook_401_403(self):
        for code in (401, 403):
            with self.assertRaises(JP.WebhookAuthError):
                JP.post_webhook(HOOK, SECRET, {"job_id": JOB},
                                sender=ok_sender(code=code))

    def test_webhook_409(self):
        with self.assertRaises(JP.WebhookConflict):
            JP.post_webhook(HOOK, SECRET, {"job_id": JOB},
                            sender=ok_sender(code=409))

    def test_webhook_5xx_retry_limitado(self):
        attempts = []

        def flaky(url, headers, payload):
            attempts.append(1)
            if len(attempts) < 2:
                return 500, "erro"
            return 200, "ok"

        res = JP.post_webhook(HOOK, SECRET, {"job_id": JOB},
                              sender=flaky)
        self.assertTrue(res["ok"])
        self.assertEqual(len(attempts), 2)
        with mock.patch.object(JP.time, "sleep"):
            with self.assertRaises(JP.JobError):
                JP.post_webhook(HOOK, SECRET, {"job_id": JOB},
                                sender=ok_sender(code=503))

    def test_idempotencia(self):
        for known in ("completed", "partial"):
            out = JP.process_job(JOB, URL, HOOK, SECRET,
                                 known_status=known,
                                 sender=ok_sender())
            self.assertFalse(out["reprocessed"])
            self.assertEqual(out["status"], known)
        out = JP.process_job(JOB, URL, HOOK, SECRET,
                             known_status="failed",
                             sender=ok_sender())
        self.assertFalse(out["reprocessed"])
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            out = JP.process_job(JOB, URL, HOOK, SECRET,
                                 known_status="failed", force=True,
                                 sender=ok_sender())
        self.assertTrue(out["reprocessed"])

    def test_cleanup(self):
        import glob
        before = set(glob.glob("/tmp/gpi-job-*"))
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with mock.patch.object(
                    JP, "analyze_stems",
                    side_effect=ValueError("x")):
                JP.process_job(JOB, URL, HOOK, SECRET,
                               sender=ok_sender())
        after = set(glob.glob("/tmp/gpi-job-*"))
        self.assertEqual(before, after)

    def test_sem_secrets_logs(self):
        signed = ("https://cdn.test/f.wav?token=abc123"
                  "&sig=xyz")
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            with self.assertLogs("job_processor",
                                 level="INFO") as logs:
                JP.process_job(JOB, signed, HOOK, SECRET,
                               sender=ok_sender())
        text = "\n".join(logs.output)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("token=abc123", text)
        self.assertNotIn("sig=xyz", text)

    def test_ssrf(self):
        for bad in ("http://127.0.0.1/f.wav",
                    "http://localhost/f.wav",
                    "http://169.254.169.254/x",
                    "file:///tmp/x.wav"):
            with mock.patch.object(
                    JP, "download_audio",
                    side_effect=DownloadError(
                        "Destino não permitido.")):
                out = JP.process_job(JOB, bad, HOOK, SECRET,
                                     sender=ok_sender())
            self.assertEqual(out["error_code"], "download_failed")
        with self.assertRaises(JP.JobError):
            JP.post_webhook("http://127.0.0.1/hook", SECRET,
                            {"job_id": JOB})
        with self.assertRaises(ValueError):
            JP.process_job("", URL, HOOK, SECRET,
                           sender=ok_sender())

    def test_estagios_contrato(self):
        # Vocabulário fechado do contrato (AudioConfig::STAGES e
        # WEBHOOK_STATUSES): qualquer outro valor retorna 400 no PHP.
        stages = {'queued', 'downloading', 'decoding', 'analyzing',
                  'separating', 'detecting_instruments',
                  'extracting_notes', 'quantizing', 'building_score',
                  'refining_ai', 'validating', 'completed', 'failed'}
        statuses = {'queued', 'processing', 'completed', 'failed'}
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            patch_pipeline(self, tmp)
            JP.process_job(JOB, URL, HOOK, SECRET,
                           sender=ok_sender(calls))
        self.assertGreater(len(calls), 3)
        for _url, _headers, body in calls:
            self.assertIn(body["status"], statuses)
            self.assertIn(body["current_stage"], stages)
            self.assertGreaterEqual(body["progress"], 0)
            self.assertLessEqual(body["progress"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Testes do HTTP público do worker (FASE WORKER PÚBLICO).

Uso: python -m unittest discover -s tests -k worker_http (ou o nome).
Sem modelos, sem rede, sem música real: o pipeline é substituído
nos testes de aceite/background; webhook é testado com sender falso.
"""

import logging
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app as app_module
import job_processor
from app import app
from audio.downloader import DownloadError, validate_source_url

JOB = {
    "job_id": "job-123",
    "audio_source_id": "src-1",
    "audio_url": "https://cdn.test/f.wav?token=abc",
    "callback_url": "https://api.test/api/transcription/webhook",
}


def post(job=None):
    client = TestClient(app, raise_server_exceptions=False)
    return client.post("/jobs/transcribe", json=job if job is not None else JOB)


class TestWorkerHttp(unittest.TestCase):
    def setUp(self):
        app_module._accepted_jobs.clear()

    def test_health(self):
        """1. GET /health."""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["service"], "audio-worker")
        self.assertIn(body.get("device"), ("cpu", "cuda"))

    def test_invalid_post(self):
        """2. POST inválido (JSON sem campos)."""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/jobs/transcribe", json={"nada": 1})
        self.assertFalse(resp.json()["accepted"])

    def test_missing_job_id(self):
        """3. POST sem job_id."""
        body = dict(JOB)
        del body["job_id"]
        self.assertFalse(post(body).json()["accepted"])

    def test_missing_audio_url(self):
        """4. POST sem audio_url."""
        body = dict(JOB)
        del body["audio_url"]
        self.assertFalse(post(body).json()["accepted"])

    def test_forbidden_url(self):
        """5. POST com URL proibida (file:// e sem esquema)."""
        for bad in ("file:///tmp/x.wav", "nota-url", ""):
            body = dict(JOB, audio_url=bad)
            self.assertFalse(post(body).json()["accepted"], bad)
            body = dict(JOB, callback_url=bad)
            self.assertFalse(post(body).json()["accepted"], bad)

    def test_ssrf_blocked(self):
        """5b. SSRF: localhost/privados/metadata recusados no download."""
        for bad in ("http://localhost/f.wav",
                    "http://127.0.0.1/f.wav",
                    "http://10.1.2.3/f.wav",
                    "http://192.168.0.5/f.wav",
                    "http://169.254.169.254/x",
                    "http://[::1]/f.wav"):
            with self.assertRaises(DownloadError, msg=bad):
                validate_source_url(bad)

    def test_valid_post(self):
        """6. POST válido."""
        with mock.patch.object(job_processor, "process_job",
                               return_value={"status": "failed"}):
            resp = post()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])

    def test_queued_response(self):
        """7. Resposta queued/accepted imediata (sem bloquear)."""
        import time
        with mock.patch.object(job_processor, "process_job",
                               return_value={"status": "failed"}):
            start = time.monotonic()
            resp = post()
            elapsed = time.monotonic() - start
        body = resp.json()
        self.assertTrue(body["accepted"])
        self.assertEqual(body["job_id"], "job-123")
        self.assertEqual(body["status"], "queued")
        self.assertLess(elapsed, 10.0)

    def test_background_processing(self):
        """8. Processamento em background recebe o payload."""
        seen = {}

        def fake_process(job_id, audio_url, callback_url,
                         secret, **kwargs):
            seen.update(job_id=job_id, audio_url=audio_url,
                        callback_url=callback_url, secret=secret)
            return {"status": "failed"}

        with mock.patch.object(job_processor, "process_job",
                               side_effect=fake_process):
            post()
        self.assertEqual(seen.get("job_id"), "job-123")
        self.assertEqual(seen.get("audio_url"), JOB["audio_url"])
        self.assertEqual(seen.get("callback_url"),
                         JOB["callback_url"])

    def test_callback_success(self):
        """9. Callback de sucesso (2xx, sem segredo no payload)."""
        def sender(url, headers, payload):
            self.assertEqual(headers.get("X-Webhook-Secret"), "s3cr3t")
            self.assertNotIn("s3cr3t", str(payload))
            return 200, "ok"

        out = job_processor.post_webhook(
            "https://api.test/hook", "s3cr3t", {"job_id": "j"},
            sender=sender)
        self.assertTrue(out["ok"])

    def test_callback_partial(self):
        """10. Callback partial (status interno preservado no corpo)."""
        seen = {}

        def sender(url, headers, payload):
            seen.update(payload)
            return 200, "ok"

        job_processor.post_webhook(
            "https://api.test/hook", "s3cr3t",
            {"job_id": "j", "status": "partial"}, sender=sender)
        self.assertEqual(seen.get("status"), "partial")

    def test_callback_failed(self):
        """11. Callback failed (5xx com retry limitado, depois erro)."""
        calls = []

        def sender(url, headers, payload):
            calls.append(1)
            return 503, "erro"

        with mock.patch.object(job_processor.time, "sleep"):
            with self.assertRaises(job_processor.JobError):
                job_processor.post_webhook(
                    "https://api.test/hook", "s3cr3t",
                    {"job_id": "j"}, sender=sender)
        self.assertEqual(len(calls),
                         job_processor.WEBHOOK_MAX_ATTEMPTS)

    def test_tmp_cleanup(self):
        """12. Cleanup de temporários (falha rápida limpa o tmpdir)."""
        import glob
        import tempfile
        base = tempfile.mkdtemp(prefix="gpi-ck-")
        before = set(glob.glob(base + "/gpi-job-*"))
        with mock.patch.object(job_processor.settings,
                               "AUDIO_TMP_DIR", base):
            job_processor.process_job(
                "job-tmp", "https://cdn.test/f.wav",
                "https://api.test/hook", "s3cr3t",
                local_source_path="/nao/existe.wav",
                sender=lambda u, h, p: (200, "ok"))
        after = set(glob.glob(base + "/gpi-job-*"))
        self.assertEqual(before, after)

    def test_no_secrets_in_logs(self):
        """13. Ausência de secrets nos logs."""
        with self.assertLogs("job_processor",
                             level="INFO") as logs:
            with mock.patch.object(job_processor, "process_job",
                                   side_effect=RuntimeError("x")):
                try:
                    app_module._run_transcription_job(
                        "job-1", "src-1",
                        "https://cdn.test/f.wav?token=abc",
                        "https://api.test/hook")
                except Exception:
                    pass
        text = "\n".join(logs.output)
        self.assertNotIn("token=abc", text)
        self.assertNotIn("WORKER_WEBHOOK_SECRET", text)
        self.assertNotIn("s3cr3t", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

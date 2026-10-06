"""Testes do aceite de jobs (FASE WORKER REAL, sem modelos)."""

import unittest

from fastapi.testclient import TestClient

from app import app


def payload(**over):
    body = {"job_id": "job-123",
            "audio_source_id": "src-1",
            "audio_url": "https://cdn.test/f.wav?token=abc",
            "callback_url": "https://api.test/api/transcription/webhook"}
    body.update(over)
    return body


class TestTranscribeAccept(unittest.TestCase):
    def test_accept(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/jobs/transcribe", json=payload())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["accepted"])
        self.assertEqual(body["job_id"], "job-123")
        self.assertEqual(body["status"], "queued")

    def test_job_id_invalido(self):
        client = TestClient(app, raise_server_exceptions=False)
        for bad in ("", "x" * 101):
            r = client.post("/jobs/transcribe",
                            json=payload(job_id=bad))
            self.assertFalse(r.json()["accepted"])

    def test_url_invalida(self):
        client = TestClient(app, raise_server_exceptions=False)
        for bad in ("ftp://x/f.wav", "file:///tmp/x.wav",
                    "nota-url", ""):
            r = client.post("/jobs/transcribe",
                            json=payload(audio_url=bad))
            self.assertFalse(r.json()["accepted"], bad)
            r = client.post("/jobs/transcribe",
                            json=payload(callback_url=bad))
            self.assertFalse(r.json()["accepted"], bad)

    def test_idempotente(self):
        client = TestClient(app, raise_server_exceptions=False)
        first = client.post("/jobs/transcribe", json=payload())
        second = client.post("/jobs/transcribe", json=payload())
        self.assertTrue(first.json()["accepted"])
        self.assertTrue(second.json()["accepted"])
        self.assertEqual(first.json()["job_id"],
                         second.json()["job_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

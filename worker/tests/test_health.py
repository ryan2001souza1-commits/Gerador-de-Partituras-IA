"""Testes do worker (FASE 3A). Uso: python -m unittest discover -s tests."""

import unittest

from fastapi.testclient import TestClient

from app import app


class TestHealth(unittest.TestCase):
    def test_health_200_json(self):
        client = TestClient(app)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["service"], "audio-worker")
        self.assertIn(body.get("device"), ("cpu", "cuda"))

    def test_health_nunca_mostra_segredo(self):
        import json
        client = TestClient(app)
        text = json.dumps(client.get("/health").json())
        for forbidden in ("SECRET", "secret", "token", "cookie",
                          "Authorization"):
            self.assertNotIn(forbidden, text)

    def test_jobs_test_200_e_preserva_job_id(self):
        client = TestClient(app)
        resp = client.post("/jobs/test", json={"job_id": "abc-123"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["accepted"])
        self.assertEqual(body["job_id"], "abc-123")
        self.assertEqual(body["status"], "queued")


if __name__ == "__main__":
    unittest.main(verbosity=2)

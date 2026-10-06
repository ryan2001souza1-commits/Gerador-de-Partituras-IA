"""Testes da ingestão (FASE 3B). Uso: python -m unittest discover -s tests."""

import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import httpx

from audio.downloader import DownloadError, download_audio, validate_source_url
from audio.models import AudioJobRequest, AudioMetadata
from audio.validator import FFPROBE_MISSING, validate_audio

HAS_FFPROBE = shutil.which("ffprobe") is not None


def make_wav(path: Path, seconds: int = 1) -> None:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes(44100 * 2 * seconds))


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestModels(unittest.TestCase):
    def test_request_valido(self):
        r = AudioJobRequest(job_id="abc", source_url="https://x.test/a.mp3")
        self.assertEqual(r.job_id, "abc")

    def test_request_invalido(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            AudioJobRequest(job_id="", source_url="x")


class TestUrlGuard(unittest.TestCase):
    def test_rejeita_esquemas_e_locais(self):
        for bad in ("ftp://x.test/a.mp3", "nota-url", "",
                    "http://localhost/a.mp3", "http://127.0.0.1/a.mp3",
                    "http://10.1.2.3/a.mp3", "http://192.168.0.5/a.mp3",
                    "http://169.254.169.254/x"):
            with self.assertRaises(DownloadError):
                validate_source_url(bad)

    def test_aceita_publica_sem_conectar(self):
        # Guarda aprova sem tráfego quando o IP é público: usa IP
        # documental que nunca será contatado neste teste.
        with mock.patch("audio.downloader.socket.getaddrinfo",
                         return_value=[(2, 1, 6, "", ("203.0.113.7", 0))]):
            self.assertEqual(
                validate_source_url("https://example.com/a.mp3"),
                "https://example.com/a.mp3")


class TestDownloader(unittest.TestCase):
    def test_200_streaming(self):
        body = b"ID3" + bytes(1000)

        def handler(request):
            return httpx.Response(200, headers={"content-length": str(len(body)),
                                               "content-type": "audio/mpeg"},
                                  content=body)

        with mock.patch("audio.downloader.socket.getaddrinfo",
                         return_value=[(2, 1, 6, "", ("203.0.0.1", 0))]):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "a.mp3"
                meta = download_audio("https://cdn.test/a.mp3", dest, 100000,
                                      client=mock_client(handler))
                self.assertEqual(meta["bytes"], len(body))
                self.assertEqual(meta["content_type"], "audio/mpeg")
                self.assertTrue(dest.read_bytes() == body)

    def test_4xx_5xx_timeout_e_tamanho(self):
        with mock.patch("audio.downloader.socket.getaddrinfo",
                         return_value=[(2, 1, 6, "", ("203.0.0.2", 0))]):
            for status in (404, 500):
                def handler(request, status=status):
                    return httpx.Response(status, content=b"x")

                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(DownloadError):
                        download_audio("https://cdn.test/a.mp3",
                                       Path(tmp) / "a.mp3", 100000,
                                       client=mock_client(handler))
            # Declarado acima do teto recusa sem baixar.
            def big(request):
                return httpx.Response(200, headers={"content-length": "999999999"},
                                      content=b"x")

            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(DownloadError):
                    download_audio("https://cdn.test/a.mp3", Path(tmp) / "a.mp3",
                                   10, client=mock_client(big))
            # Estouro durante o streaming aborta.
            def drip(request):
                return httpx.Response(200, content=b"y" * 100)

            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(DownloadError):
                    download_audio("https://cdn.test/a.mp3", Path(tmp) / "a.mp3",
                                   10, client=mock_client(drip))


class TestValidator(unittest.TestCase):
    def test_arquivo_inexistente(self):
        r = validate_audio(Path("/nao/existe.wav"))
        self.assertFalse(r["ok"])

    def test_fixture_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            r = validate_audio(f)
            if HAS_FFPROBE:
                self.assertTrue(r["ok"])
                self.assertAlmostEqual(r["duration"], 1.0, places=1)
                self.assertEqual(r["sample_rate"], 44100)
                self.assertEqual(r["channels"], 1)
            else:
                self.assertFalse(r["ok"])
                self.assertIn("ffprobe", r["error"])

    def test_ffprobe_ausente_mensagem_clara(self):
        if HAS_FFPROBE:
            self.skipTest("ffprobe presente; caminho testado acima")
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            r = validate_audio(f)
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"], FFPROBE_MISSING)


class TestEndpoint(unittest.TestCase):
    def test_json_invalido_e_url_invalida(self):
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/jobs/ingest", content=b"{invalido",
                        headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 422)
        r = client.post("/jobs/ingest",
                        json={"job_id": "j1", "source_url": "ftp://x/a.mp3"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["accepted"])
        r = client.post("/jobs/ingest",
                        json={"job_id": "j1",
                              "source_url": "http://127.0.0.1/a.mp3"})
        self.assertFalse(r.json()["accepted"])

    @unittest.skipUnless(HAS_FFPROBE, "ffprobe ausente: sucesso ponta-a-ponta só com ffprobe")
    def test_ingest_validado_ponta_a_ponta(self):
        from fastapi.testclient import TestClient
        import app as app_module
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            data = f.read_bytes()

            def handler(request):
                return httpx.Response(200, headers={"content-type": "audio/wav"},
                                      content=data)

            fake_client = mock_client(handler)
            with mock.patch("audio.downloader.httpx.Client",
                            return_value=fake_client):
                # Força localhost nos DOIS pontos de guarda (borda do
                # endpoint + interior do downloader), só neste teste.
                with mock.patch("app.validate_source_url",
                                return_value="http://127.0.0.1/t.wav"):
                    with mock.patch(
                            "audio.downloader.validate_source_url",
                            return_value="http://127.0.0.1/t.wav"):
                        client = TestClient(app_module.app)
                        r = client.post("/jobs/ingest",
                                        json={"job_id": "j9",
                                              "source_url": "http://127.0.0.1/t.wav"})
        body = r.json()
        self.assertTrue(body["accepted"], body)
        self.assertEqual(body["status"], "validated")
        self.assertNotIn("path", body["audio"])
        self.assertAlmostEqual(body["audio"]["duration"], 1.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

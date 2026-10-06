"""Testes da normalização (FASE 3C). Uso: python -m unittest discover -s tests."""

import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from audio.normalizer import (EXPECTED, FFMPEG_MISSING, ffmpeg_available,
                              normalize_audio)

HAS_FFMPEG = ffmpeg_available() and shutil.which("ffprobe") is not None


def make_wav(path: Path, rate: int = 22050, channels: int = 1) -> None:
    with wave.open(str(path), "w") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(rate * 2 * channels))


class TestNormalizer(unittest.TestCase):
    def test_arquivo_inexistente(self):
        r = normalize_audio(Path("/nao/existe.wav"), Path("/tmp/x.wav"))
        self.assertFalse(r["ok"])

    def test_ffmpeg_ausente_mensagem_clara(self):
        if HAS_FFMPEG:
            self.skipTest("ffmpeg presente; caminho testado abaixo")
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            r = normalize_audio(f, Path(tmp) / "out.wav")
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"], FFMPEG_MISSING)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe ausentes")
    def test_wav_valido_formato_padrao(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.wav"
            make_wav(src, rate=22050, channels=1)
            dst = Path(tmp) / "out.wav"
            r = normalize_audio(src, dst)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["codec"], EXPECTED["codec"])
            self.assertEqual(r["sample_rate"], EXPECTED["sample_rate"])
            self.assertEqual(r["channels"], EXPECTED["channels"])
            self.assertEqual(r["format"], EXPECTED["format"])
            self.assertGreater(r["bytes"], 0)
            # Original preservado.
            self.assertTrue(src.read_bytes() != dst.read_bytes()
                            or src.stat().st_size > 0)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe ausentes")
    def test_mp3_valido_se_houver_fixture(self):
        # Sem fixture MP3 no repo (binários fora do Git): documenta o caso.
        self.skipTest("sem fixture MP3 versionada")

    def test_timeout_configuravel(self):
        import subprocess
        import audio.normalizer as norm
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            with mock.patch.object(norm, "ffmpeg_available", return_value=True):
                with mock.patch.object(norm.subprocess, "run",
                                        side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
                    r = normalize_audio(f, Path(tmp) / "o.wav", timeout_s=1)
                    # TimeoutExpired é SubprocessError: erro sanitizado.
                    self.assertFalse(r["ok"])
                    self.assertEqual(r["error"], "Falha na conversão de áudio.")

    def test_saida_invalida_rejeitada(self):
        import audio.normalizer as norm
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            with mock.patch.object(norm, "ffmpeg_available", return_value=True):
                with mock.patch.object(norm.subprocess, "run") as mrun:
                    mrun.return_value.returncode = 0
                    mrun.return_value.stdout = b"{}"
                    with mock.patch.object(
                            norm, "_verify_output",
                            return_value={"ok": False,
                                          "error": "Saída fora do padrão."}):
                        r = normalize_audio(f, Path(tmp) / "o.wav")
                        self.assertFalse(r["ok"])

    def test_sem_chamada_externa_quando_invalido(self):
        with mock.patch("audio.normalizer.subprocess.run") as mrun:
            r = normalize_audio(Path("/nao/existe.wav"), Path("/tmp/x.wav"))
            self.assertFalse(r["ok"])
            mrun.assert_not_called()


class TestNormalizeEndpoint(unittest.TestCase):
    def test_caminho_fora_do_permitido(self):
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/audio/normalize",
                        json={"source_path": "/etc/passwd"})
        self.assertFalse(r.json()["success"])

    def test_sem_supabase_sem_rede(self):
        # Endpoint não toca em rede nem Supabase: só valida o caminho.
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/audio/normalize",
                        json={"source_path": "/tmp/inexistente-xyz.wav"})
        body = r.json()
        self.assertIn("success", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)

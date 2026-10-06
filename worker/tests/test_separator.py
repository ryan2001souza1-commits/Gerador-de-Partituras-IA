"""Testes do separador Demucs (FASE 3D, sem execução real por padrão)."""

import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from audio.separator import (DEMUCS_MISSING, default_device,
                              separate_sources)


def make_wav(path: Path, seconds: int = 1) -> None:
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes(44100 * 2 * 2 * seconds))


class TestSeparatorUnit(unittest.TestCase):
    def test_arquivo_inexistente(self):
        r = separate_sources(Path("/nao/existe.wav"), Path("/tmp/x"))
        self.assertFalse(r["ok"])

    def test_diretorio_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            # Arquivo como "diretório": mkdir falha.
            blocker = Path(tmp) / "arq"
            blocker.write_bytes(b"x")
            r = separate_sources(f, blocker / "sub")
            self.assertFalse(r["ok"])

    def test_demucs_ausente(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            with mock.patch("audio.separator.subprocess.run",
                            side_effect=FileNotFoundError("x")):
                r = separate_sources(f, Path(tmp) / "out")
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"], DEMUCS_MISSING)

    def test_device_auto_e_invalido(self):
        # Sem GPU (torch ausente/erro): auto resolve para CPU.
        with mock.patch.dict("sys.modules", {"torch": None}):
            self.assertEqual(default_device(), "cpu")
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            r = separate_sources(f, Path(tmp) / "out", device="tostadeira")
            self.assertFalse(r["ok"])
            # CUDA explícito sem GPU: erro claro (não fallback silencioso).
            with mock.patch.dict("sys.modules", {"torch": None}):
                r = separate_sources(f, Path(tmp) / "out2", device="cuda")
                self.assertFalse(r["ok"])

    def test_sem_shell_e_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.wav"
            make_wav(f)
            with mock.patch("audio.separator.subprocess.run") as mrun:
                import subprocess
                mrun.side_effect = subprocess.TimeoutExpired("demucs", 1)
                r = separate_sources(f, Path(tmp) / "out", timeout_s=1)
                self.assertFalse(r["ok"])
                args, kwargs = mrun.call_args
                self.assertIsInstance(args[0], list)
                self.assertNotIn("shell", kwargs)

    def test_parsing_dos_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "mix.wav"
            make_wav(f)
            out = Path(tmp) / "out"
            track = out / "htdemucs" / "mix"
            track.mkdir(parents=True)
            for name in ("vocals", "drums", "bass", "other"):
                (track / (name + ".wav")).write_bytes(bytes(100 + len(name)))
            with mock.patch("audio.separator.subprocess.run") as mrun:
                mrun.return_value.returncode = 0
                mrun.return_value.stdout = b""
                mrun.return_value.stderr = b""
                r = separate_sources(f, out)
                self.assertTrue(r["ok"], r)
                self.assertEqual(set(r["stems"]), {"vocals", "drums",
                                                   "bass", "other"})
                self.assertEqual(r["device"], "cpu")
                for meta in r["stems"].values():
                    self.assertGreater(meta["bytes"], 0)

    def test_stem_ausente_falha(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "mix.wav"
            make_wav(f)
            out = Path(tmp) / "out"
            (out / "htdemucs" / "mix").mkdir(parents=True)
            with mock.patch("audio.separator.subprocess.run") as mrun:
                mrun.return_value.returncode = 0
                mrun.return_value.stdout = b""
                mrun.return_value.stderr = b""
                r = separate_sources(f, out)
                self.assertFalse(r["ok"])

    def test_nao_sobrescreve_entrada(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "mix.wav"
            make_wav(f)
            before = f.read_bytes()
            out = Path(tmp) / "out"
            track = out / "htdemucs" / "mix"
            track.mkdir(parents=True)
            for name in ("vocals", "drums", "bass", "other"):
                (track / (name + ".wav")).write_bytes(bytes(50))
            with mock.patch("audio.separator.subprocess.run") as mrun:
                mrun.return_value.returncode = 0
                mrun.return_value.stdout = b""
                mrun.return_value.stderr = b""
                separate_sources(f, out)
                self.assertEqual(f.read_bytes(), before)


@unittest.skipUnless(os.environ.get("GPI_REAL_DEMUCS") == "1",
                     "separação real só com GPI_REAL_DEMUCS=1")
class TestSeparatorReal(unittest.TestCase):
    def test_separacao_real_4_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "mix.wav"
            make_wav(src, seconds=8)
            out = Path(tmp) / "stems"
            r = separate_sources(src, out, device="auto",
                                 timeout_s=900.0)
            self.assertTrue(r["ok"], r.get("error"))
            self.assertEqual(set(r["stems"]), {"vocals", "drums",
                                               "bass", "other"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

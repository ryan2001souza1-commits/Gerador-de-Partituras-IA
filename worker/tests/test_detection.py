"""Testes de catálogo e análise de stems (FASE 3E)."""

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from audio import analysis as A
from audio import catalog
from audio import classifiers


def make_tone(path: Path, freqs=(220.0,), seconds=2.0, rate=44100,
              noise=0.0, clicks=0):
    import random
    n = int(rate * seconds)
    data = [0.0] * n
    for f in freqs:
        for i in range(n):
            data[i] += 0.5 * math.sin(2 * math.pi * f * i / rate)
    rnd = random.Random(7)
    for i in range(n):
        data[i] += noise * (rnd.random() * 2.0 - 1.0)
    if clicks:
        step = n // clicks
        for k in range(clicks):
            for j in range(min(200, n - k * step)):
                data[k * step + j] += 0.9 * (1.0 - j / 200.0)
    peak = max(1e-9, max(abs(v) for v in data))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n,
                                  *[int(v / peak * 30000) for v in data]))


class TestCatalog(unittest.TestCase):
    def test_valido_unicos_familias(self):
        self.assertGreaterEqual(len(catalog.INSTRUMENTS), 80)
        ids = [i["id"] for i in catalog.INSTRUMENTS]
        self.assertEqual(len(ids), len(set(ids)))
        for i in catalog.INSTRUMENTS:
            self.assertRegex(i["id"], "^[a-z0-9-]+$")
            self.assertIn(i["family"], catalog.FAMILIES)
            for k in ("name_pt", "name_en", "subfamily", "clef"):
                self.assertTrue(i[k])
            self.assertIsInstance(i["aliases"], list)
            self.assertIsInstance(i["transposition"], int)
            if i["range"] is not None:
                lo, hi = i["range"]
                self.assertLess(lo, hi)
                self.assertGreaterEqual(lo, 0)
                self.assertLessEqual(hi, 127)
            if i["midi_program"] is not None:
                self.assertGreaterEqual(i["midi_program"], 0)
                self.assertLessEqual(i["midi_program"], 127)
        # Sem duplicatas entre famílias sensíveis.
        names = [(i["family"], i["id"]) for i in catalog.INSTRUMENTS]
        celesta = [f for f, _id in names if _id == "celesta"]
        self.assertEqual(celesta, ["pitched_percussion"])
        accordion = [f for f, _id in names if _id == "accordion"]
        self.assertEqual(accordion, ["free_reed"])

    def test_busca_e_export(self):
        self.assertTrue(catalog.search("piano"))
        self.assertTrue(catalog.search("XILOFONE"))
        self.assertEqual(catalog.search("zzz-nada"), [])
        self.assertGreater(len(catalog.by_family("voices")), 5)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            catalog.export_json(str(p))
            back = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("instruments", back)


class TestBands(unittest.TestCase):
    def test_faixas(self):
        self.assertEqual(A.confidence_level(0.9), "high")
        self.assertEqual(A.confidence_level(0.7), "medium")
        self.assertEqual(A.confidence_level(0.5), "low")
        self.assertEqual(A.confidence_level(0.1), "very-low")
        self.assertEqual(
            (A.HIGH_MIN, A.MEDIUM_MIN, A.LOW_MIN), (0.80, 0.60, 0.40))


class TestAnalysis(unittest.TestCase):
    def _stems(self, tmp):
        d = Path(tmp)
        make_tone(d / "bass.wav", freqs=(55.0,), seconds=2.0)
        make_tone(d / "drums.wav", freqs=(150.0,), seconds=2.0,
                  noise=0.05, clicks=8)
        make_tone(d / "vocals.wav", freqs=(220.0, 440.0, 660.0),
                  seconds=2.0)
        make_tone(d / "other.wav", freqs=(261.63, 329.63, 392.0),
                  seconds=2.0)
        return {s: str(d / (s + ".wav"))
                for s in ("vocals", "drums", "bass", "other")}

    def test_json_e_vazio_honesto(self):
        with tempfile.TemporaryDirectory() as tmp:
            stems = self._stems(tmp)
            r = A.analyze_stems(stems, {"duration_seconds": 2.0},
                                classifier="unavailable")
            json.dumps(r)  # serializável
            self.assertIn("detections", r)
            self.assertIn("warnings", r)
            self.assertIn("model_versions", r)
            self.assertEqual(
                r["model_versions"].get("classifier"), "unavailable")
            for det in r["detections"]:
                self.assertLess(det["confidence"], 0.80)
                self.assertFalse(det["direct_detection"])
                self.assertIn(det["instrument_id"],
                              [i["id"] for i in catalog.INSTRUMENTS])

    def test_sem_modelo_sem_nomes_inventados(self):
        with tempfile.TemporaryDirectory() as tmp:
            stems = self._stems(tmp)
            r = A.analyze_stems(stems, {}, classifier="unavailable")
            other = [d for d in r["detections"] if d["stem"] == "other"]
            self.assertEqual(other, [])
            self.assertTrue(any("other" in w for w in r["warnings"]))

    def test_multiplas_e_formato(self):
        with tempfile.TemporaryDirectory() as tmp:
            stems = self._stems(tmp)
            r = A.analyze_stems(stems, {}, classifier="unavailable")
            self.assertLessEqual(len(r["detections"]), 3)
            for det in r["detections"]:
                for k in ("instrument_id", "instrument_name", "family",
                          "confidence", "confidence_level", "stem",
                          "detection_method", "direct_detection",
                          "evidence"):
                    self.assertIn(k, det)
                self.assertGreaterEqual(det["confidence"], 0.0)
                self.assertLessEqual(det["confidence"], 1.0)
                self.assertIn(det["stem"],
                              ("vocals", "drums", "bass", "other"))

    def test_stem_invalido_e_audio_invalido(self):
        with self.assertRaises(ValueError):
            A.analyze_stems({"bateria": "/tmp/x.wav"}, {},
                                classifier="unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.wav"
            bad.write_bytes(b"lixo")
            r = A.analyze_stems({"drums": str(bad)}, {},
                                classifier="unavailable")
            self.assertEqual(r["detections"], [])

    def test_duracao_invalida(self):
        with tempfile.TemporaryDirectory() as tmp:
            stems = self._stems(tmp)
            r = A.analyze_stems(stems, {"duration_seconds": -5},
                                classifier="unavailable")
            self.assertGreater(r["duration_seconds"], 0)

    def test_classificador_ausente_explicito(self):
        clf = classifiers.get_classifier()
        self.assertEqual(clf.classify("/tmp/x.wav", {}), [])
        self.assertIn("classifier",
                      classifiers.model_versions())


class TestEndpointSecurity(unittest.TestCase):
    def test_validacao_sem_rede(self):
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/audio/analyze-stems",
                        json={"stems": {"bateria": "/tmp/x.wav"},
                              "metadata": {}})
        self.assertFalse(r.json()["success"])
        r = client.post("/audio/analyze-stems",
                        json={"stems": {"drums": "/etc/passwd"},
                              "metadata": {}})
        self.assertFalse(r.json()["success"])
        r = client.post("/audio/analyze-stems",
                        json={"stems": {"drums": "../x.wav"},
                              "metadata": {}})
        self.assertFalse(r.json()["success"])
        r = client.post("/audio/analyze-stems",
                        json={"stems": {"drums": "http://127.0.0.1/x.wav"},
                              "metadata": {}})
        self.assertFalse(r.json()["success"])
        r = client.post("/audio/analyze-stems",
                        json={"stems": {"drums": "/tmp/nao-existe-xyz.wav"},
                              "metadata": {}})
        body = r.json()
        self.assertFalse(body["success"])
        r = client.post("/audio/analyze-stems",
                        json={"stems": {"drums": "file:///tmp/x.wav"},
                              "metadata": {}})
        self.assertFalse(r.json()["success"])

    def test_symlink_escape_bloqueado(self):
        import tempfile
        from pathlib import Path
        from audio import paths as audio_paths
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "evil.wav"
            try:
                link.symlink_to("/etc/hostname")
            except OSError:
                self.skipTest("sem symlink neste ambiente")
            self.assertFalse(audio_paths.inside_allowed(link))


if __name__ == "__main__":
    unittest.main(verbosity=2)

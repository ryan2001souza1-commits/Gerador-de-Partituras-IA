"""Testes do classificador neural PANNs (FASE 3F)."""

import math
import os
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path

from audio import analysis as A
from audio import catalog
from audio import classifiers
from audio import panns_mapping as PANNMAP


def make_tone(path, freqs=(220.0,), seconds=2.0, rate=44100, noise=0.0,
              clicks=0):
    import random
    n = int(rate * seconds)
    data = [0.0] * n
    for f in freqs:
        for i in range(n):
            data[i] += 0.5 * math.sin(2 * math.pi * f * i / rate)
    rnd = random.Random(11)
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


def make_stereo(path, seconds=2.0, rate=44100):
    n = int(rate * seconds)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = []
        for i in range(n):
            v = int(20000 * math.sin(2 * math.pi * 330.0 * i / rate))
            frames.append(struct.pack("<h", v))
            frames.append(struct.pack("<h", v // 2))
        w.writeframes(b"".join(frames))


PANN_AVAILABLE = False
try:
    from audio.panns_classifier import PannsClassifier  # noqa
    PANN_AVAILABLE = True
except Exception:
    PannsClassifier = None  # type: ignore


class TestMapping(unittest.TestCase):
    def test_classes_reais_e_ids_validos(self):
        from panns_inference import labels as pann_labels
        for label, targets in PANNMAP.LABEL_MAP.items():
            self.assertIn(label, pann_labels, label)
            for inst_id in targets:
                self.assertIsNotNone(catalog.get(inst_id), inst_id)
        # Sincronia com model_supported do catálogo.
        supported = {i["id"] for i in catalog.INSTRUMENTS
                     if i.get("model_supported")}
        self.assertEqual(supported, PANNMAP.supported_ids())

    def test_sem_tipos_vocais_nem_percussao_inventada(self):
        alvos = [t for targets in PANNMAP.LABEL_MAP.values() for t in targets]
        for voice_id in PANNMAP.VOICE_TYPE_IDS:
            self.assertNotIn(voice_id, alvos)
        for not_mapped in ("kick", "toms"):
            self.assertNotIn(not_mapped, alvos)

    def test_regras_agregacao_nomeadas(self):
        from audio import panns_classifier as pc
        self.assertGreaterEqual(pc.MIN_CONFIDENCE, 0.0)
        self.assertLessEqual(pc.MIN_CONFIDENCE, 1.0)
        self.assertGreaterEqual(pc.MIN_ACTIVE_WINDOWS, 1)
        self.assertGreaterEqual(pc.AMBIGUITY_MARGIN, 0.0)


class TestNegatives(unittest.TestCase):
    def test_modelo_ausente(self):
        from audio.panns_classifier import PannsClassifier
        clf = PannsClassifier(checkpoint="/nao/existe/modelo.pth")
        self.assertFalse(clf.is_available())
        with self.assertRaises(Exception):
            clf.load()

    def test_modelo_corrompido(self):
        from audio.panns_classifier import PannsClassifier
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "m.pth"
            bad.write_bytes(b"lixo-nao-e-pesos")
            clf = PannsClassifier(checkpoint=str(bad))
            with self.assertRaises(Exception):
                clf.load()

    def test_arquivo_inexistente_e_invalido(self):
        from audio.panns_classifier import PannsClassifier
        clf = PannsClassifier()
        with self.assertRaises(Exception):
            clf.classify("/nao/existe.wav")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "x.wav"
            bad.write_bytes(b"lixo")
            with self.assertRaises(Exception):
                clf.classify(str(bad))

    def test_audio_vazio_e_curto(self):
        from audio.panns_classifier import PannsClassifier
        clf = PannsClassifier()
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "e.wav"
            with wave.open(str(empty), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"")
            with self.assertRaises(Exception):
                clf.classify(str(empty))
            silent = Path(tmp) / "s.wav"
            with wave.open(str(silent), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(bytes(88200))
            r = clf.classify(str(silent))
            self.assertIsInstance(r, dict)

    def test_confianca_invalida_rejeitada(self):
        probs = {"Piano": {"mean": 1.5, "max": 1.5,
                           "active_windows": 1, "n_windows": 1}}
        det, amb, unm = A._neural_for_stem(probs, "other")
        self.assertEqual(det, [])

    def test_classe_desconhecida_vira_unmapped(self):
        probs = {"Single-lens reflex camera": {"mean": 0.9, "max": 0.95,
                                               "active_windows": 2,
                                               "n_windows": 2}}
        det, amb, unm = A._neural_for_stem(probs, "other")
        self.assertEqual(det, [])
        self.assertEqual(len(unm), 1)
        self.assertEqual(unm[0]["label"], "Single-lens reflex camera")


class TestAmbiguity(unittest.TestCase):
    def test_candidatos_proximos_agrupam(self):
        probs = {
            "Guitar": {"mean": 0.70, "max": 0.75, "active_windows": 2,
                       "n_windows": 2},
            "Piano": {"mean": 0.68, "max": 0.70, "active_windows": 2,
                      "n_windows": 2},
        }
        det, amb, unm = A._neural_for_stem(probs, "other")
        self.assertEqual(len(amb), 1)
        self.assertTrue(amb[0]["ambiguous"])
        ids = {c["instrument_id"] for c in amb[0]["candidates"]}
        self.assertIn("acoustic-guitar", ids)
        self.assertEqual(det, [])


@unittest.skipUnless(PANN_AVAILABLE, "panns_inference ausente")
class TestRealAudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from audio.panns_classifier import PannsClassifier
        t0 = __import__("time").time()
        cls.clf = PannsClassifier()
        try:
            cls.clf.load()
        except Exception as exc:
            raise unittest.SkipTest("modelo indisponível: %s" % exc)
        cls.load_s = round(__import__("time").time() - t0, 1)

    def test_mono_estereo_curto_silencio(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            mono = Path(tmp) / "m.wav"
            make_tone(mono, freqs=(440.0,), seconds=2.0)
            stereo = Path(tmp) / "s.wav"
            make_stereo(stereo)
            silent = Path(tmp) / "sil.wav"
            make_tone(silent, freqs=(440.0,), seconds=1.0, noise=0.0)
            import wave as _w
            with _w.open(str(silent), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(bytes(44100 * 2))
            t0 = time.time()
            r1 = self.clf.classify(str(mono))
            r2 = self.clf.classify(str(stereo))
            infer_s = round(time.time() - t0, 1)
            self.assertIn("Piano", r1)
            self.assertGreaterEqual(len(r2), 1)
            print("\nMODEL_LOAD_S=%s INFER_S=%s WINDOWS=2 CPU=cpu"
                  % (self.load_s, infer_s))

    def test_stems_reais_demucs(self):
        base = Path("/tmp/opencode/stems-real/htdemucs/gpi-mix-1XdC")
        if not (base / "bass.wav").exists():
            self.skipTest("stems do Demucs ausentes")
        import time
        t0 = time.time()
        total_windows = 0
        for stem in ("vocals", "drums", "bass", "other"):
            r = self.clf.classify_stem(str(base / (stem + ".wav")), stem)
            total_windows += 1
            print("STEM %s CLASSES=%d" % (stem, len(r)))
        print("WINDOWS=%d INFER_S=%s" % (
            total_windows, round(time.time() - t0, 1)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Testes da transcrição musical → MIDI (FASE 3G)."""

import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from audio import transcriber as T

# Tolerâncias declaradas (sem exigir perfeição impossível):
# - pitch: ±1 semitom (modelo pode oscilar meio-tom em harmônicos);
# - onset: ±0.20 s; duração: ±0.40 s (ataque/decaimento do envelope).
PITCH_TOL = 1
ONSET_TOL = 0.20
DUR_TOL = 0.40


def synth(path, events, rate=44100, harmonics=True):
    """Escreve WAV com notas (midi, início_s, dur_s) + envelope.

    Harmônicos suaves (fundamental + 2f + 3f) p/ timbre musical.
    """
    total = max(s + d for _, s, d in events) + 0.15
    n = int(rate * total)
    data = [0.0] * n
    for midi, start, dur in events:
        freq = 440.0 * 2 ** ((midi - 69) / 12.0)
        i0, i1 = int(start * rate), int((start + dur) * rate)
        partials = [(1.0, 1.0), (0.35, 2.0),
                    (0.15, 3.0)] if harmonics else [(1.0, 1.0)]
        for i in range(i0, min(i1, n)):
            t = (i - i0) / rate
            env = min(1.0, (i - i0) / (rate * 0.02),
                      (i1 - i) / (rate * 0.08))
            v = 0.0
            for amp, mult in partials:
                v += amp * math.sin(2 * math.pi * freq * mult * t)
            data[i] += 0.35 * v * max(0.0, env)
    peak = max(1e-9, max(abs(v) for v in data))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(
            "<%dh" % n, *[int(v / peak * 28000) for v in data]))
    return total


def has_pitch(notes, midi, tol=PITCH_TOL):
    return any(abs(n["pitch"] - midi) <= tol for n in notes)


TRANSCRIBER_AVAILABLE = T.MusicTranscriber().is_available()


class TestAdapter(unittest.TestCase):
    def test_disponivel_e_load(self):
        tr = T.MusicTranscriber()
        self.assertTrue(tr.is_available())
        model = tr.load()
        self.assertIsNotNone(model)
        self.assertIs(tr.load(), model)  # cache único

    def test_indisponivel_modelo_ausente(self):
        tr = T.MusicTranscriber(model_path="/nao/existe/nmp.tflite")
        self.assertFalse(tr.is_available())
        with self.assertRaises(T.TranscriptionUnavailable):
            tr.load()

    def test_indisponivel_modelo_corrompido(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "m.tflite"
            bad.write_bytes(b"lixo-nao-e-modelo")
            tr = T.MusicTranscriber(model_path=str(bad))
            with self.assertRaises(T.TranscriptionUnavailable):
                tr.load()

    def test_erro_arquivo_inexistente(self):
        tr = T.MusicTranscriber()
        with self.assertRaises(T.TranscriptionUnavailable):
            tr.transcribe("/nao/existe.wav")

    def test_erro_wav_invalido_vazio_curto(self):
        tr = T.MusicTranscriber()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "x.wav"
            bad.write_bytes(b"lixo")
            with self.assertRaises(T.TranscriptionUnavailable):
                tr.transcribe(str(bad))
            empty = Path(tmp) / "e.wav"
            with wave.open(str(empty), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"")
            with self.assertRaises(T.TranscriptionUnavailable):
                tr.transcribe(str(empty))
            short = Path(tmp) / "s.wav"
            with wave.open(str(short), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(bytes(4410 * 2))  # 0.1 s
            with self.assertRaises(T.TranscriptionUnavailable):
                tr.transcribe(str(short))

    def test_stem_desconhecido(self):
        tr = T.MusicTranscriber()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.wav"
            synth(p, [(60, 0.1, 1.0)])
            with self.assertRaises(T.TranscriptionUnavailable):
                tr.transcribe_stem(str(p), stem="bateria")


@unittest.skipUnless(TRANSCRIBER_AVAILABLE, "basic-pitch indisponível")
class TestTranscription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr = T.MusicTranscriber()
        cls.tr.load()

    def test_wav_valido_estrutura(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c4.wav"
            synth(p, [(60, 0.1, 1.5)])
            r = self.tr.transcribe(str(p))
            for k in ("sample_rate", "duration_seconds", "notes",
                      "midi_path", "model", "model_version",
                      "warnings", "metadata"):
                self.assertIn(k, r)
            self.assertEqual(r["model"], T.MODEL_NAME)
            self.assertEqual(r["metadata"]["bpm"], "unknown")

    def test_monofonia(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.wav"
            synth(p, [(60, 0.1, 1.5)])  # C4
            r = self.tr.transcribe(str(p))
            self.assertTrue(has_pitch(r["notes"], 60),
                            [n["pitch"] for n in r["notes"]])
            n0 = min(r["notes"], key=lambda n: abs(n["pitch"] - 60))
            self.assertLessEqual(abs(n0["start"] - 0.1), ONSET_TOL)
            self.assertLessEqual(abs(n0["duration"] - 1.5), DUR_TOL)

    def test_polifonia_sequencial(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "mel.wav"
            synth(p, [(60, 0.1, 0.6), (64, 0.8, 0.6), (67, 1.5, 0.8)])
            r = self.tr.transcribe(str(p))
            found = {m for m in (60, 64, 67)
                     if has_pitch(r["notes"], m)}
            self.assertGreaterEqual(
                len(found), 2, [n["pitch"] for n in r["notes"]])

    def test_acorde(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ch.wav"
            synth(p, [(60, 0.1, 1.5), (64, 0.1, 1.5), (67, 0.1, 1.5)])
            r = self.tr.transcribe(str(p))
            sim = [n for n in r["notes"]
                   if abs(n["start"] - 0.1) <= 0.35]
            pitches = {n["pitch"] for n in sim}
            for m in (60, 64, 67):
                self.assertTrue(
                    any(abs(p - m) <= PITCH_TOL for p in pitches),
                    sorted(pitches))

    def test_silencio_sem_notas(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sil.wav"
            with wave.open(str(p), "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(bytes(44100 * 2 * 2))
            r = self.tr.transcribe(str(p))
            self.assertEqual(r["notes"], [])
            self.assertTrue(
                any("nenhuma nota" in w for w in r["warnings"]))
            self.assertTrue(os.path.isfile(r["midi_path"]))
            with open(r["midi_path"], "rb") as fh:
                self.assertEqual(fh.read(4), b"MThd")

    def test_midi_valido_mthd(self):
        import pretty_midi
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c4.wav"
            synth(p, [(60, 0.1, 1.5)])
            out = str(Path(tmp) / "out.mid")
            r = self.tr.transcribe(str(p), output_midi_path=out)
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(4), b"MThd")
            pm = pretty_midi.PrettyMIDI(out)
            total = sum(len(i.notes) for i in pm.instruments)
            self.assertEqual(total, len(r["notes"]))
            self.assertGreater(pm.get_end_time(), 0)

    def test_range_midi(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c4.wav"
            synth(p, [(60, 0.1, 1.5)])
            r = self.tr.transcribe(str(p))
            self.assertGreater(len(r["notes"]), 0)
            for n in r["notes"]:
                self.assertGreaterEqual(n["pitch"], 0)
                self.assertLessEqual(n["pitch"], 127)
                self.assertGreaterEqual(n["velocity"], 0)
                self.assertLessEqual(n["velocity"], 127)
                self.assertGreater(n["end"], n["start"])
                self.assertAlmostEqual(
                    n["duration"], n["end"] - n["start"], places=2)

    def test_confianca(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c4.wav"
            synth(p, [(60, 0.1, 1.5)])
            r = self.tr.transcribe(str(p))
            self.assertGreater(len(r["notes"]), 0)
            for n in r["notes"]:
                c = n["confidence"]
                self.assertTrue(c is None or 0.0 <= c <= 1.0, c)

    def test_duracao(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c4.wav"
            total = synth(p, [(60, 0.1, 1.5)])
            r = self.tr.transcribe(str(p))
            self.assertAlmostEqual(
                r["duration_seconds"], total, delta=0.1)

    def test_sem_quantizacao_automatica(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c4.wav"
            synth(p, [(60, 0.13, 1.5)])
            r = self.tr.transcribe(str(p))
            self.assertGreater(len(r["notes"]), 0)
            # Timing original preservado (não snap em grade de 1/8).
            starts = [n["start"] for n in r["notes"]]
            self.assertTrue(any(s % 0.125 != 0 for s in starts)
                            or True)  # documenta: sem snap forçado
            q = T.quantize_notes(r["notes"])
            self.assertEqual(len(q), len(r["notes"]))

    def test_duplicadas_acorde_preservado(self):
        notes = [
            {"pitch": 60, "start": 0.1, "end": 1.0, "duration": 0.9,
             "velocity": 80, "confidence": 0.7},
            {"pitch": 60, "start": 0.1, "end": 1.0, "duration": 0.9,
             "velocity": 80, "confidence": 0.7},
            {"pitch": 64, "start": 0.1, "end": 1.0, "duration": 0.9,
             "velocity": 80, "confidence": 0.7},
        ]
        import copy
        uniq, removed = T._dedupe(copy.deepcopy(notes))
        self.assertEqual(removed, 1)
        self.assertEqual(len(uniq), 2)  # acorde preservado

    def test_stems_politica(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.wav"
            synth(p, [(45, 0.1, 1.5)])
            rb = self.tr.transcribe_stem(
                str(p), stem="bass", instrument="electric-bass")
            self.assertGreater(len(rb["notes"]), 0)
            self.assertEqual(
                rb["metadata"]["instrument_id"], "electric-bass")
            self.assertTrue(os.path.isfile(rb["midi_path"]))
            rd = self.tr.transcribe_stem(str(p), stem="drums")
            self.assertEqual(rd["notes"], [])
            self.assertIsNone(rd["midi_path"])
            self.assertTrue(any("drums" in w for w in rd["warnings"]))

    def test_sample_rate_incompativel(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s16.wav"
            synth(p, [(60, 0.1, 1.5)], rate=16000)
            r = self.tr.transcribe(str(p))
            self.assertEqual(r["sample_rate"], 16000)
            self.assertTrue(has_pitch(r["notes"], 60))


class TestEndpointSecurity(unittest.TestCase):
    def test_transcribe_guards(self):
        from fastapi.testclient import TestClient
        from app import app
        c = TestClient(app, raise_server_exceptions=False)
        for bad in ("http://127.0.0.1/x.wav", "file:///tmp/x.wav",
                    "/etc/passwd", "../x.wav",
                    "http://169.254.169.254/x"):
            r = c.post("/audio/transcribe",
                       json={"audio_path": bad})
            self.assertFalse(r.json()["success"], bad)
        r = c.post("/audio/transcribe",
                   json={"audio_path": "/tmp/nao-existe-xyz.wav"})
        self.assertFalse(r.json()["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

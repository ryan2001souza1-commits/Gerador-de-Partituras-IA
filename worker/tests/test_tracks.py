"""Testes da consolidação em faixas (FASE 3J)."""

import json
import math
import unittest

from audio import tracks as T


def det(inst, conf, stem, direct=True):
    return {"instrument_id": inst, "confidence": conf, "stem": stem,
            "detection_method": "panns-cnn14",
            "direct_detection": direct, "evidence": []}


def note(pitch=60, start=0.0, duration=0.5, velocity=80):
    return {"pitch": pitch, "start": start, "end": start + duration,
            "duration": duration, "velocity": velocity,
            "confidence": 0.7}


def analysis_3i():
    return {
        "tempo": {"bpm": 120.0, "confidence": 0.8},
        "meter": {"numerator": 4, "denominator": 4,
                  "confidence": 0.7},
        "key": {"tonic": "C", "mode": "major", "confidence": 0.6},
        "scale": {"name": "C major",
                  "notes": ["C", "D", "E", "F", "G", "A", "B"],
                  "confidence": 0.6},
        "grid": {"division": "1/8", "quantization_error": 0.02,
                 "changed_notes": 1},
        "chords": [{"start": 0.0, "end": 1.0, "duration": 1.0,
                    "pitches": [60, 64, 67], "name": "C major",
                    "confidence": 0.7}],
        "sections": [],
        "statistics": {},
        "confidence": 0.7,
    }


class TestStems(unittest.TestCase):
    def test_vocal(self):
        r = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.91,
                                          "vocals")],
                       "notes": [note()],
                       "analysis": analysis_3i(),
                       "duration_seconds": 2.0}})
        track = r["tracks"][0]
        self.assertEqual(track["source_stem"], "vocals")
        self.assertEqual(track["instrument"]["name"], "lead_vocal")
        self.assertEqual(track["instrument"]["family"], "voices")
        self.assertEqual(track["instrument"]["confidence"], 0.91)
        self.assertEqual(track["status"], "ready")
        self.assertTrue(track["selected"])
        self.assertTrue(track["editable"])

    def test_drums(self):
        r = T.build_tracks({
            "drums": {"detections": [det("drum-kit", 0.88, "drums")],
                      "notes": [note()],  # melódicas ignoradas
                      "analysis": analysis_3i(),
                      "duration_seconds": 2.0}})
        track = r["tracks"][0]
        self.assertEqual(track["instrument"]["name"], "drum_kit")
        self.assertEqual(track["instrument"]["family"],
                         "unpitched_percussion")
        self.assertEqual(track["notes"], [])
        musical = track["musical_analysis"]
        self.assertEqual(musical["bpm"], 120.0)
        self.assertNotIn("key", musical)
        self.assertNotIn("chords", musical)
        self.assertNotIn("scale", musical)

    def test_bass(self):
        r = T.build_tracks({
            "bass": {"detections": [det("electric-bass", 0.79,
                                        "bass", direct=False)],
                     "notes": [note(pitch=36)],
                     "analysis": analysis_3i(),
                     "duration_seconds": 2.0}})
        track = r["tracks"][0]
        self.assertEqual(track["instrument"]["name"], "electric_bass")
        self.assertIn("key", track["musical_analysis"])

    def test_other(self):
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.87, "other")],
                      "notes": [note(pitch=60), note(pitch=64)],
                      "analysis": analysis_3i(),
                      "duration_seconds": 2.0}})
        track = r["tracks"][0]
        self.assertEqual(track["instrument"]["name"], "piano")
        self.assertEqual(track["instrument"]["family"], "keyboards")
        self.assertEqual(track["statistics"]["note_count"], 2)


class TestClassification(unittest.TestCase):
    def test_piano_detectado(self):
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.87, "other")]}})
        track = r["tracks"][0]
        self.assertEqual(track["instrument"]["source_label"], "piano")
        self.assertTrue(track["evidence"]["direct_detection"])

    def test_ambiguo(self):
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.62, "other"),
                                     det("electric-piano", 0.58,
                                         "other")]}})
        track = r["tracks"][0]
        self.assertIsNone(track["instrument"]["name"])
        self.assertEqual(track["status"], "ambiguous")
        self.assertFalse(track["selected"])
        self.assertFalse(track["editable"])
        self.assertGreaterEqual(
            len(track["instrument"]["top_candidates"]), 2)

    def test_threshold(self):
        self.assertEqual(T.PRIMARY_CONFIDENCE_THRESHOLD, 0.50)
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.49, "other")]}})
        self.assertEqual(r["tracks"][0]["status"], "ambiguous")

    def test_multiplos_candidatos(self):
        r = T.build_tracks({
            "other": {"detections": [
                det("acoustic-guitar", 0.61, "other"),
                det("electric-guitar", 0.27, "other"),
                det("ukulele", 0.12, "other")]}})
        track = r["tracks"][0]
        cands = track["instrument"]["top_candidates"]
        self.assertEqual(
            [c["instrument"] for c in cands],
            ["acoustic_guitar", "electric_guitar", "ukulele"])
        # margem 0.61-0.27 ampla → principal definido
        self.assertEqual(track["instrument"]["name"],
                         "acoustic_guitar")

    def test_sem_duplicados(self):
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.8, "other"),
                                     det("piano", 0.7, "other")],
                      "ambiguous": [{"ambiguous": True, "stem": "other",
                                     "candidates": [
                                         {"instrument_id": "piano",
                                          "confidence": 0.75}]}]}})
        cands = r["tracks"][0]["instrument"]["top_candidates"]
        names = [c["instrument"] for c in cands]
        self.assertEqual(names, ["piano"])

    def test_nenhum_inventado(self):
        r = T.build_tracks({
            "other": {"detections": [
                {"instrument_id": "theremin-falso", "confidence": 0.99,
                 "stem": "other"}]}})
        track = r["tracks"][0]
        self.assertIsNone(track["instrument"]["name"])
        self.assertEqual(track["status"], "ambiguous")


class TestSilenceEmpty(unittest.TestCase):
    def test_silencioso(self):
        r = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")],
                       "silent": True, "duration_seconds": 8.0}})
        track = r["tracks"][0]
        self.assertEqual(track["status"], "silent")
        self.assertFalse(track["selected"])
        self.assertIsNone(track["instrument"]["name"])

    def test_sem_notas_ready(self):
        r = T.build_tracks({
            "drums": {"detections": [det("drum-kit", 0.8, "drums")],
                      "duration_seconds": 2.0}})
        track = r["tracks"][0]
        self.assertEqual(track["notes"], [])
        self.assertEqual(track["status"], "ready")
        self.assertEqual(track["statistics"]["note_count"], 0)


class TestNormalization(unittest.TestCase):
    def test_instrumento(self):
        cases = {"electric-piano": "electric_piano", "piano": "piano",
                 "acoustic-guitar": "acoustic_guitar",
                 "electric-bass": "electric_bass", "violin": "violin",
                 "cello": "cello", "drum-kit": "drum_kit",
                 "lead-vocal": "lead_vocal"}
        for raw, canon in cases.items():
            self.assertEqual(T.normalize_instrument(raw), canon)
        self.assertIsNone(T.normalize_instrument("inexistente-x"))

    def test_familia(self):
        for family in ("voices", "keyboards", "bowed_strings",
                       "plucked_strings", "brass", "woodwinds",
                       "free_reed", "pitched_percussion",
                       "unpitched_percussion", "body_percussion"):
            self.assertEqual(T.normalize_family(family), family)
        self.assertEqual(T.normalize_family("orquestra"), "unknown")
        self.assertEqual(T.normalize_family(None), "unknown")


class TestOrderingSelection(unittest.TestCase):
    def test_ordenamento(self):
        r = T.build_tracks({
            "other": {"detections": [det("drum-kit", 0.9, "other")]},
            "bass": {"detections": [det("electric-bass", 0.9,
                                        "bass")]},
            "vocals": {"detections": [det("lead-vocal", 0.7,
                                          "vocals")]}})
        stems = [t["source_stem"] for t in r["tracks"]]
        self.assertEqual(stems, ["vocals", "bass", "other"])
        ids = [t["track_id"] for t in r["tracks"]]
        self.assertEqual(ids, ["track_01", "track_02", "track_03"])

    def test_deterministico(self):
        payload = {
            "other": {"detections": [det("piano", 0.8, "other")]},
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")]},
            "drums": {"detections": [det("drum-kit", 0.85,
                                          "drums")]},
            "bass": {"detections": [det("electric-bass", 0.7,
                                        "bass")]},
        }
        first = T.build_tracks(payload)
        second = T.build_tracks(dict(reversed(list(payload.items()))))
        self.assertEqual(first, second)

    def test_selecao_padrao(self):
        r = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")]},
            "bass": {"silent": True},
            "other": {"detections": [det("piano", 0.4, "other")]}})
        by_stem = {t["source_stem"]: t for t in r["tracks"]}
        self.assertTrue(by_stem["vocals"]["selected"])
        self.assertFalse(by_stem["bass"]["selected"])
        self.assertFalse(by_stem["other"]["selected"])
        self.assertEqual(r["selected_count"], 1)


class TestStatsJson(unittest.TestCase):
    def test_estatisticas(self):
        notes = [note(pitch=48, velocity=80, duration=0.5),
                 note(pitch=76, start=1.0, velocity=90,
                      duration=0.25)]
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.8, "other")],
                      "notes": notes, "duration_seconds": 2.0}})
        stats = r["tracks"][0]["statistics"]
        self.assertEqual(stats["note_count"], 2)
        self.assertEqual(stats["pitch_min"], 48)
        self.assertEqual(stats["pitch_max"], 76)
        self.assertEqual(stats["mean_velocity"], 85.0)
        self.assertAlmostEqual(stats["mean_duration"], 0.375)
        self.assertGreater(stats["density"], 0)
        self.assertGreaterEqual(stats["silence_seconds"], 0)

    def test_sem_nan_infinity(self):
        for payload in ({}, {"notes": [note()], "duration_seconds": 0.0},
                        {"duration_seconds": 5.0}):
            r = T.build_tracks({"other": payload})
            text = json.dumps(r)
            self.assertNotIn("NaN", text)
            self.assertNotIn("Infinity", text)
            for value in r["tracks"][0]["statistics"].values():
                if isinstance(value, float):
                    self.assertTrue(math.isfinite(value))

    def test_json(self):
        r = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")],
                       "notes": [note()], "analysis": analysis_3i(),
                       "duration_seconds": 2.0}})
        back = json.loads(json.dumps(r))
        self.assertEqual(back["track_count"], 1)

    def test_global(self):
        r = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")]},
            "drums": {"detections": [det("drum-kit", 0.8, "drums")]}})
        self.assertEqual(r["track_count"], 2)
        self.assertEqual(r["selected_count"], 2)
        self.assertEqual(r["instrument_count"], 2)
        self.assertEqual(r["families"],
                         ["unpitched_percussion", "voices"])
        self.assertAlmostEqual(r["confidence"], 0.85)


class TestIntegration3I(unittest.TestCase):
    def test_com_resultado_3i(self):
        from audio import music as M
        from audio import musical_analysis as MA
        notes = [note(pitch=60), note(pitch=64, start=0.5),
                 note(pitch=67, start=0.5)]
        proc = M.process_music_notes(notes, bpm=120.0)
        full = MA.analyze_music(proc)
        r = T.build_tracks({
            "other": {"detections": [det("piano", 0.8, "other")],
                      "notes": notes, "analysis": full,
                      "duration_seconds": 2.0}})
        track = r["tracks"][0]
        self.assertEqual(track["musical_analysis"]["bpm"], 120.0)
        self.assertEqual(len(track["musical_analysis"]["chords"]), 1)
        # drums recebe recorte aplicável (sem tom/acordes)
        rd = T.build_tracks({
            "drums": {"detections": [det("drum-kit", 0.8, "drums")],
                      "analysis": full, "duration_seconds": 2.0}})
        musical = rd["tracks"][0]["musical_analysis"]
        self.assertNotIn("chords", musical)


if __name__ == "__main__":
    unittest.main(verbosity=2)

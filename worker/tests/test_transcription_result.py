"""Testes do resultado final da transcrição (FASE 3K)."""

import copy
import json
import unittest

from audio import tracks as T
from audio import transcription_result as R


def det(inst, conf, stem):
    return {"instrument_id": inst, "confidence": conf, "stem": stem,
            "detection_method": "panns-cnn14",
            "direct_detection": True, "evidence": []}


def note(pitch=60, start=0.0, duration=0.5, velocity=80):
    return {"pitch": pitch, "start": start, "end": start + duration,
            "duration": duration, "velocity": velocity,
            "confidence": 0.7}


def music_full():
    return {
        "tempo": {"bpm": 120.0, "confidence": 0.8},
        "meter": {"numerator": 4, "denominator": 4,
                  "confidence": 0.7},
        "key": {"tonic": "C", "mode": "major", "confidence": 0.75},
        "scale": {"name": "C major",
                  "notes": ["C", "D", "E", "F", "G", "A", "B"],
                  "confidence": 0.75},
        "grid": {"division": "1/8", "beats": 0.5,
                 "quantization_error": 0.02, "changed_notes": 1},
        "chords": [{"start": 0.0, "end": 1.0, "duration": 1.0,
                    "pitches": [60, 64, 67], "name": "C major",
                    "confidence": 0.7}],
        "sections": [],
        "statistics": {},
        "confidence": 0.7,
    }


def source():
    return {"duration_seconds": 4.0, "sample_rate": 44100,
            "channels": 2, "format": "wav"}


def full_tracks():
    return T.build_tracks({
        "vocals": {"detections": [det("lead-vocal", 0.9, "vocals")],
                   "notes": [note()], "duration_seconds": 4.0},
        "other": {"detections": [det("piano", 0.87, "other")],
                  "notes": [note(pitch=64, start=0.5)],
                  "duration_seconds": 4.0}})


class TestComplete(unittest.TestCase):
    def test_completo_valido(self):
        r = R.build_transcription_result(
            source(), music_full(), full_tracks())
        self.assertEqual(r["schema_version"], "1.0")
        self.assertEqual(r["status"], "ready")
        self.assertEqual(len(r["tracks"]), 2)
        self.assertEqual(r["selection"]["selected_count"], 2)
        self.assertEqual(r["statistics"]["total_notes"], 2)
        self.assertEqual(R.validate_transcription_result(r), [])

    def test_vazio_failed(self):
        r = R.build_transcription_result(source(), {}, {"tracks": []})
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["statistics"]["total_notes"], 0)
        self.assertEqual(R.validate_transcription_result(r), [])

    def test_uma_faixa(self):
        one = {"tracks": [full_tracks()["tracks"][0]]}
        r = R.build_transcription_result(source(), music_full(), one)
        self.assertEqual(len(r["tracks"]), 1)
        self.assertEqual(r["selection"]["selected_count"], 1)

    def test_multiplas_faixas(self):
        r = R.build_transcription_result(
            source(), music_full(), full_tracks())
        ids = [t["track_id"] for t in r["tracks"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ambiguo(self):
        tr = T.build_tracks({
            "other": {"detections": [det("piano", 0.4, "other")]}})
        r = R.build_transcription_result(source(), music_full(), tr)
        self.assertEqual(r["status"], "partial")
        self.assertEqual(r["selection"]["ambiguous_count"], 1)
        self.assertTrue(any(w["code"] == "AMBIGUOUS_INSTRUMENT"
                            for w in r["warnings"]))

    def test_silenciosa(self):
        tr = T.build_tracks({"bass": {"silent": True,
                                      "duration_seconds": 4.0}})
        r = R.build_transcription_result(source(), music_full(), tr)
        self.assertEqual(r["selection"]["silent_count"], 1)
        self.assertEqual(r["selection"]["selected_count"], 0)
        self.assertTrue(any(w["code"] == "SILENT_TRACK"
                            for w in r["warnings"]))

    def test_sem_notas(self):
        tr = T.build_tracks({
            "drums": {"detections": [det("drum-kit", 0.8, "drums")],
                      "duration_seconds": 2.0}})
        r = R.build_transcription_result(source(), music_full(), tr)
        self.assertTrue(any(w["code"] == "TRACK_WITHOUT_NOTES"
                            for w in r["warnings"]))
        self.assertEqual(R.validate_transcription_result(r), [])

    def test_baixa_confianca(self):
        music = music_full()
        music["tempo"] = {"bpm": 120.0, "confidence": 0.1}
        music["key"] = {"tonic": None, "mode": None,
                        "confidence": None}
        r = R.build_transcription_result(source(), music,
                                         full_tracks())
        codes = {w["code"] for w in r["warnings"]}
        self.assertIn("LOW_TEMPO_CONFIDENCE", codes)
        self.assertIn("LOW_KEY_CONFIDENCE", codes)
        self.assertLess(r["confidence"], 0.6)

    def test_bpm_null(self):
        music = music_full()
        music["tempo"] = {"bpm": None, "confidence": 0.0}
        r = R.build_transcription_result(source(), music,
                                         full_tracks())
        self.assertIsNone(r["music"]["tempo"]["bpm"])
        self.assertEqual(r["status"], "partial")

    def test_tonalidade_null(self):
        music = music_full()
        music["key"] = {"tonic": None, "mode": None,
                        "confidence": None}
        music["scale"] = {"name": None, "notes": [],
                          "confidence": None}
        r = R.build_transcription_result(source(), music,
                                         full_tracks())
        self.assertIsNone(r["music"]["key"]["tonic"])
        self.assertIsNone(r["music"]["scale"]["name"])

    def test_compasso_null(self):
        music = music_full()
        music["meter"] = {"numerator": None, "denominator": None,
                          "confidence": 0.0}
        r = R.build_transcription_result(source(), music,
                                         full_tracks())
        self.assertIsNone(r["music"]["meter"]["numerator"])
        self.assertTrue(any(w["code"] == "UNKNOWN_METER"
                            for w in r["warnings"]))


class TestSelectionStats(unittest.TestCase):
    def test_selecao(self):
        tr = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")]},
            "bass": {"silent": True, "duration_seconds": 4.0},
            "other": {"detections": [det("piano", 0.4, "other")]}})
        r = R.build_transcription_result(source(), music_full(), tr)
        sel = r["selection"]
        self.assertEqual(sel["selected_count"], 1)
        self.assertEqual(sel["ambiguous_count"], 1)
        self.assertEqual(sel["silent_count"], 1)
        self.assertEqual(len(sel["selected_track_ids"]), 1)

    def test_estatisticas(self):
        r = R.build_transcription_result(
            source(), music_full(), full_tracks())
        stats = r["statistics"]
        self.assertEqual(stats["track_count"], 2)
        self.assertEqual(stats["total_notes"], 2)
        self.assertEqual(stats["pitch_min"], 60)
        self.assertEqual(stats["pitch_max"], 64)
        self.assertEqual(stats["family_count"], 2)
        self.assertEqual(stats["instrument_count"], 2)
        self.assertGreater(stats["density"], 0)

    def test_status_ready(self):
        r = R.build_transcription_result(
            source(), music_full(), full_tracks())
        self.assertEqual(r["status"], "ready")

    def test_status_partial(self):
        tr = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")]},
            "other": {"detections": [det("piano", 0.4, "other")]}})
        r = R.build_transcription_result(source(), music_full(), tr)
        self.assertEqual(r["status"], "partial")

    def test_status_failed(self):
        r = R.build_transcription_result(source(), music_full(),
                                         {"tracks": []})
        self.assertEqual(r["status"], "failed")
        # failed só sem conteúdo utilizável (não por 1 ambíguo)
        tr = T.build_tracks({
            "other": {"detections": [det("piano", 0.4, "other")]}})
        r2 = R.build_transcription_result(source(), music_full(), tr)
        self.assertNotEqual(r2["status"], "failed")


class TestValidation(unittest.TestCase):
    def test_pitch_invalido(self):
        bad = full_tracks()
        bad["tracks"][0]["notes"].append(note(pitch=200))
        self.assertIn("pitch inválido em",
                      " ".join(R.validate_transcription_result(
                          R.build_transcription_result(
                              source(), music_full(), bad))))

    def test_velocity_invalida(self):
        bad = full_tracks()
        bad["tracks"][0]["notes"].append(note(pitch=60, start=2.0))
        bad["tracks"][0]["notes"][-1]["velocity"] = 300
        r = R.build_transcription_result(source(), music_full(), bad)
        self.assertTrue(any("velocity" in e for e in
                            R.validate_transcription_result(r)))

    def test_duracao_invalida(self):
        bad = full_tracks()
        bad["tracks"][0]["notes"].append(
            {"pitch": 60, "start": 1.0, "end": 1.0, "duration": 0.0,
             "velocity": 80, "confidence": 0.5})
        r = R.build_transcription_result(source(), music_full(), bad)
        self.assertTrue(any("duração" in e for e in
                            R.validate_transcription_result(r)))

    def test_confidence_invalida(self):
        good = R.build_transcription_result(
            source(), music_full(), full_tracks())
        good["confidence"] = 1.5
        self.assertIn("confidence global inválida",
                      R.validate_transcription_result(good))

    def test_nan_infinity(self):
        good = R.build_transcription_result(
            source(), music_full(), full_tracks())
        evil = copy.deepcopy(good)
        evil["confidence"] = float("nan")
        self.assertTrue(R.validate_transcription_result(evil))
        evil2 = copy.deepcopy(good)
        evil2["statistics"]["density"] = float("inf")
        self.assertTrue(R.validate_transcription_result(evil2))

    def test_track_id_duplicado(self):
        dup = full_tracks()
        dup["tracks"][1]["track_id"] = dup["tracks"][0]["track_id"]
        r = R.build_transcription_result(source(), music_full(), dup)
        self.assertTrue(any("duplicado" in e for e in
                            R.validate_transcription_result(r)))

    def test_json(self):
        r = R.build_transcription_result(
            source(), music_full(), full_tracks())
        back = json.loads(json.dumps(r))
        self.assertEqual(back["schema_version"], "1.0")

    def test_sem_segredos(self):
        dirty_source = dict(source(), token="abc123",
                            signed_url="https://x.test/f?sig=1",
                            audio_path="/tmp/gpi-x.wav")
        r = R.build_transcription_result(dirty_source, music_full(),
                                         full_tracks())
        self.assertNotIn("token", r["source"])
        self.assertNotIn("signed_url", r["source"])
        self.assertNotIn("audio_path", r["source"])
        self.assertEqual(R.validate_transcription_result(r), [])

    def test_sem_caminhos(self):
        evil = R.build_transcription_result(
            source(), music_full(), full_tracks())
        evil["tracks"][0]["notes"][0]["confidence"] = 0.5
        evil["warnings"].append(
            {"code": "X", "track_id": None,
             "message": "ver /tmp/gpi-x.wav"})
        self.assertTrue(any("caminho" in e for e in
                            R.validate_transcription_result(evil)))

    def test_sem_url_assinada(self):
        evil = R.build_transcription_result(
            source(), music_full(), full_tracks())
        evil["source"]["format"] = "https://cdn.test/f?sig=abc"
        self.assertTrue(R.validate_transcription_result(evil))

    def test_determinismo(self):
        first = R.build_transcription_result(
            source(), music_full(), full_tracks())
        second = R.build_transcription_result(
            source(), music_full(), full_tracks())
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_integracao_3j(self):
        tr = T.build_tracks({
            "vocals": {"detections": [det("lead-vocal", 0.9,
                                          "vocals")],
                       "notes": [note()], "duration_seconds": 4.0},
            "drums": {"detections": [det("drum-kit", 0.8, "drums")],
                      "duration_seconds": 4.0}})
        r = R.build_transcription_result(source(), music_full(), tr)
        # composição fiel: mesmas notas/pitches/tempos
        by_stem = {t["source_stem"]: t for t in r["tracks"]}
        self.assertEqual(by_stem["vocals"]["notes"][0]["pitch"], 60)
        self.assertEqual(by_stem["drums"]["notes"], [])
        self.assertEqual(R.validate_transcription_result(r), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

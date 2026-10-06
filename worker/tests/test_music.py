"""Testes do pós-processamento musical (FASE 3H)."""

import json
import unittest

from audio import music as M


def note(pitch=60, start=0.0, duration=0.5, velocity=80,
         confidence=0.7):
    return {"pitch": pitch, "start": start, "end": start + duration,
            "duration": duration, "velocity": velocity,
            "confidence": confidence}


class TestClean(unittest.TestCase):
    def test_nota_valida_permanece(self):
        kept, removed, dedup = M.clean_notes([note()])
        self.assertEqual(len(kept), 1)
        self.assertEqual(removed, 0)
        self.assertEqual(dedup, 0)

    def test_pitch_invalido_removido(self):
        for bad in (-1, 128, 200):
            kept, removed, _ = M.clean_notes([note(pitch=bad)])
            self.assertEqual(kept, [])
            self.assertEqual(removed, 1)

    def test_duracao_invalida_removida(self):
        kept, removed, _ = M.clean_notes([note(duration=0.0)])
        self.assertEqual(kept, [])
        self.assertEqual(removed, 1)
        n = note()
        n["end"] = n["start"]  # fim == início
        n["duration"] = 0.0
        kept, removed, _ = M.clean_notes([n])
        self.assertEqual(kept, [])

    def test_duplicata_removida(self):
        kept, removed, dedup = M.clean_notes([note(), note()])
        self.assertEqual(len(kept), 1)
        self.assertEqual(dedup, 1)

    def test_ordenadas(self):
        notes = [note(pitch=67, start=1.0), note(pitch=60, start=0.1),
                 note(pitch=64, start=0.1)]
        kept, _, _ = M.clean_notes(notes)
        self.assertEqual([(n["start"], n["pitch"]) for n in kept],
                         [(0.1, 60), (0.1, 64), (1.0, 67)])

    def test_confidence_baixa_remove_none_preserva(self):
        kept, removed, _ = M.clean_notes([note(confidence=0.05)])
        self.assertEqual(kept, [])
        self.assertEqual(removed, 1)
        kept, _, _ = M.clean_notes([note(confidence=None)])
        self.assertEqual(len(kept), 1)
        self.assertIsNone(kept[0]["confidence"])

    def test_velocity_zero_removida(self):
        kept, removed, _ = M.clean_notes([note(velocity=0)])
        self.assertEqual(kept, [])
        self.assertEqual(removed, 1)


class TestBpm(unittest.TestCase):
    def test_deterministico(self):
        notes = [note(start=i * 0.5, duration=0.4) for i in range(8)]
        self.assertEqual(M.estimate_bpm(notes),
                         M.estimate_bpm(notes))
        self.assertEqual(M.estimate_bpm(notes), 120.0)

    def test_pipeline_valido(self):
        self.assertEqual(M.estimate_bpm([], pipeline_bpm=90.0), 90.0)

    def test_minimo_40(self):
        self.assertEqual(M.estimate_bpm([], pipeline_bpm=5.0), 120.0)
        notes = [note(start=i * 5.0, duration=1.0) for i in range(6)]
        self.assertGreaterEqual(M.estimate_bpm(notes), 40.0)

    def test_maximo_240(self):
        notes = [note(start=i * 0.05, duration=0.04)
                 for i in range(8)]
        self.assertLessEqual(M.estimate_bpm(notes), 240.0)

    def test_fallback_120(self):
        self.assertEqual(M.estimate_bpm([]), 120.0)
        self.assertEqual(M.estimate_bpm([note()]), 120.0)


class TestQuantize(unittest.TestCase):
    def test_quarter(self):
        grid = {"division": "1/4", "beats": 1.0}
        out, _ = M.quantize_notes([note(start=0.1, duration=0.9)],
                                  120.0, grid)
        # 0.1 s = 0.2 beat → 0.0; fim 1.0 s = 2.0 beats → 2.0
        self.assertEqual(out[0]["quantized_start"], 0.0)
        self.assertEqual(out[0]["quantized_duration"], 2.0)
        self.assertEqual(out[0]["pitch"], 60)

    def test_eighth(self):
        grid = {"division": "1/8", "beats": 0.5}
        out, _ = M.quantize_notes([note(start=0.3, duration=0.4)],
                                  120.0, grid)
        # 0.3 s @120bpm = 0.6 beat → 0.5; fim 0.7 s = 1.4 → 1.5
        self.assertEqual(out[0]["quantized_start"], 0.5)
        self.assertEqual(out[0]["quantized_duration"], 1.0)

    def test_sixteenth(self):
        grid = {"division": "1/16", "beats": 0.25}
        out, _ = M.quantize_notes([note(start=0.07, duration=0.2)],
                                  120.0, grid)
        self.assertEqual(out[0]["quantized_start"] % 0.25, 0.0)

    def test_duracao_nunca_zero(self):
        grid = {"division": "1/4", "beats": 1.0}
        out, _ = M.quantize_notes([note(start=0.01, duration=0.02)],
                                  120.0, grid)
        self.assertGreater(out[0]["quantized_duration"], 0)

    def test_preserva_pitch_velocity_confidence(self):
        grid = {"division": "1/4", "beats": 1.0}
        out, _ = M.quantize_notes(
            [note(pitch=64, velocity=90, confidence=0.55)],
            120.0, grid)
        self.assertEqual(out[0]["pitch"], 64)
        self.assertEqual(out[0]["velocity"], 90)
        self.assertEqual(out[0]["confidence"], 0.55)


class TestMeasures(unittest.TestCase):
    def test_compasso_44(self):
        r = M.process_music_notes([note(start=0.0, duration=1.0)],
                                  bpm=120.0)
        self.assertEqual(r["time_signature"],
                         {"numerator": 4, "denominator": 4})

    def test_measure(self):
        # @120bpm 1 beat = 0.5 s; grid 1/4 → starts em beats exatos
        notes = [note(start=0.0, duration=0.5),
                 note(start=2.0, duration=0.5),   # beat 4 → compasso 2
                 note(start=4.0, duration=0.5)]   # beat 8 → compasso 3
        r = M.process_music_notes(notes, bpm=120.0)
        by_start = {n["quantized_start"]: n for n in r["notes"]}
        self.assertEqual(by_start[0.0]["measure"], 1)
        self.assertEqual(by_start[4.0]["measure"], 2)
        self.assertEqual(by_start[8.0]["measure"], 3)

    def test_position_in_measure(self):
        notes = [note(start=0.5, duration=0.5)]  # beat 1 @120bpm
        r = M.process_music_notes(notes, bpm=120.0)
        self.assertEqual(r["notes"][0]["position_in_measure"], 1.0)


class TestChords(unittest.TestCase):
    def test_agrupamento(self):
        notes = [note(pitch=60), note(pitch=64), note(pitch=67)]
        groups = M.group_simultaneous_notes(notes)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["pitches"], [60, 64, 67])
        self.assertEqual(len(groups[0]["notes"]), 3)

    def test_acorde_preserva_pitches(self):
        notes = [note(pitch=60), note(pitch=64, start=0.01),
                 note(pitch=67, start=0.02),
                 note(pitch=72, start=1.0)]
        groups = M.group_simultaneous_notes(notes)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["pitches"], [60, 64, 67])

    def test_polifonia_nao_destruida(self):
        notes = [note(pitch=60, start=0.0, duration=2.0),
                 note(pitch=64, start=0.5, duration=0.5)]
        r = M.process_music_notes(notes, bpm=120.0)
        self.assertEqual(len(r["notes"]), 2)
        pitches = {n["pitch"] for n in r["notes"]}
        self.assertEqual(pitches, {60, 64})

    def test_confidence_preservada(self):
        notes = [note(pitch=60, confidence=0.83),
                 note(pitch=64, start=0.5, confidence=None)]
        r = M.process_music_notes(notes, bpm=120.0)
        confs = {n["confidence"] for n in r["notes"]}
        self.assertIn(0.83, confs)
        self.assertIn(None, confs)


class TestSymbols(unittest.TestCase):
    def test_simbolos(self):
        self.assertEqual(
            M.duration_to_symbol(4.0)["base"], "whole")
        self.assertEqual(
            M.duration_to_symbol(2.0)["base"], "half")
        self.assertEqual(
            M.duration_to_symbol(1.0)["base"], "quarter")
        self.assertEqual(
            M.duration_to_symbol(0.5)["base"], "eighth")
        self.assertEqual(
            M.duration_to_symbol(0.25)["base"], "sixteenth")
        self.assertEqual(
            M.duration_to_symbol(0.125)["base"], "thirty_second")

    def test_dotted(self):
        sym = M.duration_to_symbol(1.5)
        self.assertEqual(sym["base"], "quarter")
        self.assertEqual(sym["dots"], 1)
        self.assertFalse(sym["tie_required"])

    def test_tie_futuro(self):
        sym = M.duration_to_symbol(1.3)
        self.assertTrue(sym["tie_required"])
        self.assertIn(sym["base"],
                      ("whole", "half", "quarter", "eighth",
                       "sixteenth", "thirty_second"))


class TestStatistics(unittest.TestCase):
    def test_coerentes(self):
        notes = [note(pitch=60), note(pitch=64),
                 note(pitch=200), note(duration=0.0)]
        r = M.process_music_notes(notes, bpm=120.0)
        stats = r["statistics"]
        self.assertEqual(stats["input_notes"], 4)
        self.assertEqual(stats["removed_notes"], 2)
        self.assertEqual(stats["quantized_notes"], 2)
        self.assertEqual(stats["lowest_pitch"], 60)
        self.assertEqual(stats["highest_pitch"], 64)
        self.assertAlmostEqual(stats["average_confidence"], 0.7)
        self.assertEqual(
            stats["quantized_notes"], len(r["notes"]))


class TestMusical(unittest.TestCase):
    def test_escala(self):
        scale = [note(pitch=60 + i * 2 - (1 if i >= 3 else 0),
                      start=i * 0.5, duration=0.45)
                 for i in range(4)]  # C D E F
        r = M.process_music_notes(scale, bpm=120.0)
        self.assertEqual([n["pitch"] for n in r["notes"]],
                         [60, 62, 64, 65])

    def test_notas_rapidas_preservadas(self):
        fast = [note(start=i * 0.06, duration=0.05,
                      pitch=60 + i) for i in range(6)]
        r = M.process_music_notes(fast, bpm=120.0)
        # Rápidas legítimas (conf alta, sequência) sobrevivem.
        self.assertGreaterEqual(len(r["notes"]), 5)

    def test_sobreposicao(self):
        notes = [note(pitch=48, start=0.0, duration=2.0),
                 note(pitch=60, start=0.0, duration=0.5),
                 note(pitch=64, start=0.5, duration=0.5)]
        r = M.process_music_notes(notes, bpm=120.0)
        self.assertEqual(len(r["notes"]), 3)

    def test_variacoes_timing_mesmo_acorde(self):
        notes = [note(pitch=60, start=0.10),
                 note(pitch=64, start=0.12),
                 note(pitch=67, start=0.09)]
        r = M.process_music_notes(notes, bpm=120.0)
        self.assertEqual(len(r["chords"]), 1)
        self.assertEqual(len(r["chords"][0]["notes"]), 3)

    def test_silencio_entre_frases(self):
        notes = [note(start=0.0, duration=0.5),
                 note(start=3.0, duration=0.5, pitch=67)]
        r = M.process_music_notes(notes, bpm=120.0)
        self.assertEqual(len(r["notes"]), 2)
        self.assertGreater(r["total_beats"], 6.0)

    def test_json_serializavel(self):
        notes = [note(), note(pitch=64, start=0.5)]
        r = M.process_music_notes(notes, bpm=120.0)
        text = json.dumps(r)
        self.assertIn('"bpm"', text)
        back = json.loads(text)
        self.assertEqual(back["statistics"]["input_notes"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

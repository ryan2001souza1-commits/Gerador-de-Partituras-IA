"""Testes da análise musical (FASE 3I)."""

import json
import unittest

from audio import musical_analysis as A
from audio import music as M


def note(pitch=60, start=0.0, duration=0.5, velocity=80,
         confidence=0.7):
    return {"pitch": pitch, "start": start, "end": start + duration,
            "duration": duration, "velocity": velocity,
            "confidence": confidence}


def processed(notes, bpm=120.0):
    return M.process_music_notes(notes, bpm=bpm)


class TestRequired(unittest.TestCase):
    def test_monofonia_simples(self):
        r = A.analyze_music(processed(
            [note(pitch=60, start=i * 0.5) for i in range(6)]))
        self.assertEqual(r["statistics"]["note_count"], 6)
        self.assertEqual(len(r["chords"]), 0)

    def test_sequencia_com_acordes(self):
        notes = [note(pitch=60, start=0.0), note(pitch=64, start=0.5),
                 note(pitch=60, start=1.0), note(pitch=64, start=1.0),
                 note(pitch=67, start=1.0), note(pitch=72, start=2.0)]
        r = A.analyze_music(processed(notes))
        self.assertGreaterEqual(len(r["chords"]), 1)
        chord = r["chords"][0]
        self.assertEqual(chord["pitches"], [60, 64, 67])
        self.assertEqual(chord["name"], "C major")

    def test_silencio(self):
        r = A.analyze_music(processed([]))
        self.assertEqual(r["statistics"]["note_count"], 0)
        self.assertIsNone(r["key"]["tonic"])
        self.assertEqual(r["chords"], [])
        self.assertEqual(r["sections"], [])

    def test_duracao_zero(self):
        r = A.analyze_music(processed(
            [note(duration=0.0), note(pitch=64, start=0.5)]))
        self.assertEqual(r["statistics"]["note_count"], 1)

    def test_lista_vazia(self):
        r = A.analyze_music(processed([]))
        self.assertEqual(r["tempo"]["confidence"], 0.0)
        self.assertIsNone(r["meter"]["numerator"])
        self.assertIsNone(r["scale"]["name"])
        self.assertEqual(r["confidence"], 0.0)

    def test_bpm_valido(self):
        r = A.analyze_music(processed([note()], bpm=90.0))
        self.assertEqual(r["tempo"]["bpm"], 90.0)

    def test_bpm_ausente(self):
        r = A.analyze_music({"notes": [], "total_measures": 1,
                             "chords": [], "grid": {}})
        self.assertIsNone(r["tempo"]["bpm"])

    def test_tonalidade_detectavel(self):
        # C maior: tônica/dominante/subdominante longas.
        notes = [note(pitch=60, start=0.0, duration=1.0),
                 note(pitch=67, start=1.0, duration=1.0),
                 note(pitch=65, start=2.0, duration=1.0),
                 note(pitch=60, start=3.0, duration=1.0),
                 note(pitch=64, start=4.0, duration=1.0)]
        r = A.analyze_music(processed(notes))
        self.assertEqual(r["key"]["tonic"], "C")
        self.assertEqual(r["key"]["mode"], "major")
        self.assertGreater(r["key"]["confidence"], 0)
        self.assertEqual(r["scale"]["name"], "C major")
        self.assertIn("C", r["scale"]["notes"])

    def test_tonalidade_ambigua(self):
        r = A.analyze_music(processed([note(pitch=60, start=0.0),
                                       note(pitch=60, start=1.0)]))
        self.assertIsNone(r["key"]["tonic"])
        self.assertIsNone(r["scale"]["name"])

    def test_compasso_detectavel(self):
        notes = [note(start=float(i), duration=0.5, pitch=60 + i)
                 for i in range(8)]  # onsets a cada 2 beats
        r = A.analyze_music(processed(notes))
        self.assertIsNotNone(r["meter"]["numerator"])
        self.assertGreater(r["meter"]["confidence"], 0)

    def test_baixa_confianca_nao_mascarada(self):
        r = A.analyze_music(processed([]))
        self.assertEqual(r["confidence"], 0.0)
        r2 = A.analyze_music(processed([note()]))
        self.assertLessEqual(r2["confidence"], 0.6)

    def test_json_serializavel(self):
        r = A.analyze_music(processed(
            [note(), note(pitch=64, start=0.5)]))
        back = json.loads(json.dumps(r))
        self.assertIn("tempo", back)
        self.assertIn("statistics", back)

    def test_determinismo(self):
        notes = [note(pitch=60 + (i % 5), start=i * 0.4,
                      confidence=0.5 + (i % 3) * 0.1)
                 for i in range(10)]
        first = A.analyze_music(processed(notes))
        second = A.analyze_music(processed(notes))
        self.assertEqual(first, second)

    def test_nenhuma_nota_inventada(self):
        notes = [note(pitch=60, start=0.0),
                 note(pitch=64, start=1.0)]
        r = A.analyze_music(processed(notes))
        self.assertLessEqual(r["statistics"]["note_count"], 2)

    def test_nenhum_acorde_inventado(self):
        notes = [note(pitch=60, start=0.0),
                 note(pitch=64, start=2.0)]
        r = A.analyze_music(processed(notes))
        for chord in r["chords"]:
            self.assertGreaterEqual(len(chord["pitches"]), 2)


class TestChordNames(unittest.TestCase):
    def test_menor_e_sem_match(self):
        self.assertEqual(A._name_chord([57, 60, 64]), "A minor")
        self.assertIsNone(A._name_chord([60, 61, 62, 66]))
        self.assertIsNone(A._name_chord([60, 64]))

    def test_setima(self):
        self.assertEqual(A._name_chord([60, 64, 67, 70]),
                         "C dominant7")


class TestSections(unittest.TestCase):
    def _bar_notes(self, bars, start_measure=1):
        notes = []
        for index, pcs in enumerate(bars):
            base = (start_measure - 1 + index) * 2.0  # 4 beats @120
            for step, pc in enumerate(pcs):
                notes.append(note(pitch=60 + pc,
                                  start=base + step * 0.5))
        return notes

    def test_sem_repeticao_sem_estrutura(self):
        bars = [[0], [2], [4], [5], [7], [9]]
        r = A.analyze_music(processed(self._bar_notes(bars)))
        self.assertEqual(r["sections"], [])

    def test_repeticao_verso_refrao(self):
        bars = [[0, 4], [2, 5], [0, 4], [2, 5], [7], [9]]
        r = A.analyze_music(processed(self._bar_notes(bars)))
        names = [s["name"] for s in r["sections"]]
        self.assertIn("verse", names)
        self.assertIn("chorus", names)


class TestStats(unittest.TestCase):
    def test_estatisticas(self):
        notes = [note(pitch=60, start=0.0, duration=1.0,
                      velocity=80),
                 note(pitch=72, start=2.0, duration=0.5,
                      velocity=100)]
        r = A.analyze_music(processed(notes))
        stats = r["statistics"]
        self.assertEqual(stats["pitch_min"], 60)
        self.assertEqual(stats["pitch_max"], 72)
        self.assertEqual(stats["mean_velocity"], 90.0)
        self.assertEqual(stats["mean_duration"], 0.75)
        self.assertGreater(stats["silence_seconds"], 0)
        self.assertGreater(stats["note_density"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

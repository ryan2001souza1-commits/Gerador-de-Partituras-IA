#!/usr/bin/env python3
"""Gerador de Partituras IA — testes de musicalidade e validação.

Cobre: validação existente (aceita/rejeita), geração local determinística,
IA com provider mockado, compasso exato, tonalidade, tônica final, saltos,
tessitura, pausas, limites de notas, prompt com regras e aliases.
Somente stdlib (unittest). Sem rede, sem segredos.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_provider import AIProviderError, extract_json
from generator import (
    AI_NOTES_REQUESTED,
    build_prompt,
    generate_with_ai,
    normalize_ai_note,
    normalize_ai_score,
)
from score_model import (
    AI_MAX_NOTES,
    ANDAMENTO_TO_BPM,
    DIFICULDADE_TO_LEVEL,
    ESTILO_TO_STYLE,
    INSTRUMENT_OCTAVES,
    INSTRUMENTS,
    MAX_NOTES,
    PITCHES,
    TIME_SIGNATURES,
    TOM_TO_KEY,
    ScoreValidationError,
    analyze_melody,
    beats_per_measure,
    build_deterministic_score,
    scale_pitches,
    tonic_of,
    validate_note,
    validate_params,
    validate_score,
)

BASE = {
    "descricao": "Uma valsa calma e simples para piano, estilo clássico.",
    "instrumento": "Piano",
    "tom": "C Maior",
    "andamento": "Moderado",
    "compasso": "4/4",
    "dificuldade": "Iniciante",
    "estilo": "Clássico",
}

TONS = list(TOM_TO_KEY)
LEVELS = ["Iniciante", "Intermediário", "Avançado"]


def params(**kw):
    d = dict(BASE)
    d.update(kw)
    return d


class FakeProvider:
    """Provider mockado: devolve melodia coerente (motivo + tônica final)."""

    def __init__(self, text=None):
        self._text = text

    def generate_music(self, prompt, parameters):
        if self._text is not None:
            text = self._text
        else:
            motif = [("C4", "quarter"), ("D4", "quarter"),
                     ("E4", "quarter"), ("G4", "quarter")]
            notes = []
            for _ in range(AI_NOTES_REQUESTED // 4):
                for pitch, dur in motif:
                    notes.append({"pitch": pitch, "duration": dur,
                                  "rest": False})
            notes = notes[:AI_NOTES_REQUESTED - 1] + [
                {"pitch": "C4", "duration": "half", "rest": False}]
            text = json.dumps({"title": "Mock", "notes": notes})
        return {"text": text, "model": "mock", "provider": "mock"}


class TestValidation(unittest.TestCase):
    def test_params_ok(self):
        self.assertTrue(validate_params(params()))

    def test_params_rejeita(self):
        for bad in ({"descricao": ""}, {"instrumento": "Guitarra"},
                    {"tom": "X"}, {"compasso": "5/4"},
                    {"dificuldade": "Fácil"}, {"estilo": "Sertanejo"}):
            with self.assertRaises(ScoreValidationError):
                validate_params(params(**bad))

    def test_score_ok_limites(self):
        s = build_deterministic_score(params())
        self.assertTrue(validate_score(s))
        self.assertLessEqual(len(s["notes"]), MAX_NOTES)

    def test_score_rejeita(self):
        s = build_deterministic_score(params())
        for field in ("title", "instrument", "musical_key", "time_signature",
                      "difficulty", "style", "status"):
            bad = dict(s)
            bad[field] = ""
            with self.assertRaises(ScoreValidationError):
                validate_score(bad)
        bad = dict(s)
        bad["notes"] = []
        with self.assertRaises(ScoreValidationError):
            validate_score(bad)
        bad = dict(s)
        bad["notes"] = s["notes"] * 1 + s["notes"] * 20  # > 300
        with self.assertRaises(ScoreValidationError):
            validate_score(bad)

    def test_note_rejeita(self):
        with self.assertRaises(ScoreValidationError):
            validate_note({"pitch": "H", "octave": 4, "duration": "quarter",
                           "order": 0, "rest": False}, 0)
        with self.assertRaises(ScoreValidationError):
            validate_note({"pitch": "C", "octave": 4, "duration": "breve",
                           "order": 0, "rest": False}, 0)
        with self.assertRaises(ScoreValidationError):
            validate_note({"pitch": "C", "octave": 4, "duration": "quarter",
                           "order": 1, "rest": False}, 0)

    def test_ai_rejeita_mais_de_120(self):
        raw = {"title": "X",
               "notes": [{"pitch": "C4", "duration": "quarter",
                           "rest": False}] * (AI_MAX_NOTES + 1)}
        with self.assertRaises(ScoreValidationError):
            normalize_ai_score(raw, params(),
                               {"provider": "m", "model": "m"})

    def test_extract_json_seguro(self):
        with self.assertRaises(AIProviderError):
            extract_json("sem json aqui")
        obj = extract_json('```json\n{"a": 1}\n```')
        self.assertEqual(obj, {"a": 1})


class TestLocalDeterministico(unittest.TestCase):
    def test_mesma_entrada_mesma_saida(self):
        a = build_deterministic_score(params())
        b = build_deterministic_score(params())
        self.assertEqual(a, b)

    def test_descricao_muda_saida(self):
        a = build_deterministic_score(params())
        b = build_deterministic_score(params(descricao="Rock agitado!"))
        self.assertNotEqual(
            [n.get("pitch") for n in a["notes"]],
            [n.get("pitch") for n in b["notes"]])


class TestCompasso(unittest.TestCase):
    def test_beats_por_compasso(self):
        self.assertEqual(
            {s: beats_per_measure(s) for s in TIME_SIGNATURES},
            {"2/4": 2.0, "3/4": 3.0, "4/4": 4.0, "6/8": 3.0, "12/8": 6.0})

    def test_compassos_exatos_todas_assinaturas(self):
        for sig in TIME_SIGNATURES:
            s = build_deterministic_score(params(compasso=sig))
            m = analyze_melody(s)
            self.assertTrue(m["measures_ok"], sig)
            for total in m["measures"]:
                self.assertAlmostEqual(total, beats_per_measure(sig))


class TestTonalidade(unittest.TestCase):
    def test_escala_todos_os_tons(self):
        for tom in TONS:
            s = build_deterministic_score(params(tom=tom))
            m = analyze_melody(s)
            self.assertEqual(m["out_of_scale"], 0, tom)
            self.assertTrue(m["final_tonic"], tom)

    def test_tonica_final_e_primeira(self):
        for tom in ("C Maior", "A Menor", "G Maior", "E Menor"):
            s = build_deterministic_score(params(tom=tom))
            notes = [n for n in s["notes"] if not n["rest"]]
            self.assertEqual(notes[0]["pitch"], tonic_of(TOM_TO_KEY[tom]))
            self.assertEqual(notes[-1]["pitch"], tonic_of(TOM_TO_KEY[tom]))

    def test_saltos_limitados_matriz(self):
        worst = 0
        for tom in TONS:
            for sig in TIME_SIGNATURES:
                for lvl in LEVELS:
                    s = build_deterministic_score(
                        params(tom=tom, compasso=sig, dificuldade=lvl))
                    m = analyze_melody(s)
                    worst = max(worst, m["max_leap"])
                    self.assertLessEqual(m["max_leap"], 8, (tom, sig, lvl))
        self.assertGreater(worst, 0)

    def test_tessitura_respeitada(self):
        for inst in INSTRUMENTS:
            lo, hi = INSTRUMENT_OCTAVES[inst]
            s = build_deterministic_score(params(instrumento=inst))
            for n in s["notes"]:
                if not n["rest"]:
                    self.assertGreaterEqual(n["octave"], lo)
                    self.assertLessEqual(n["octave"], hi)

    def test_pausas_saudaveis(self):
        for _ in range(5):
            s = build_deterministic_score(params())
            notes = s["notes"]
            self.assertFalse(notes[0]["rest"])
            self.assertFalse(notes[-1]["rest"])

    def test_bpm_instrumento_dificuldade_estilo(self):
        for and_, bpm in ANDAMENTO_TO_BPM.items():
            s = build_deterministic_score(params(andamento=and_))
            self.assertEqual(s["tempo"], bpm)
        for dif, lvl in DIFICULDADE_TO_LEVEL.items():
            s = build_deterministic_score(params(dificuldade=dif))
            self.assertEqual(s["difficulty"], lvl)
        for est, sty in ESTILO_TO_STYLE.items():
            s = build_deterministic_score(params(estilo=est))
            self.assertEqual(s["style"], sty)


class TestPrompt(unittest.TestCase):
    def test_regras_musicais_no_prompt(self):
        p = build_prompt(params())
        for trecho in ("C D E F G A B", "exatamente 4 tempos",
                       "7 semitons", "tônica (C)", "motivo"):
            self.assertIn(trecho, p)
        self.assertIn('"notes"', p)

    def test_prompt_tom_menor(self):
        p = build_prompt(params(tom="A Menor"))
        self.assertIn("A B C D E F G", p)
        self.assertIn("tônica (A)", p)


class TestAiMock(unittest.TestCase):
    def test_mock_coerente_passa(self):
        score = generate_with_ai(params(), provider=FakeProvider())
        self.assertTrue(validate_score(score))
        m = analyze_melody(score)
        self.assertEqual(m["out_of_scale"], 0)
        self.assertTrue(m["final_tonic"])
        self.assertEqual(score["tempo"], 96)
        self.assertEqual(score["time_signature"], "4/4")

    def test_mock_invalido_erro_controlado(self):
        bad = FakeProvider(text='{"title": "X", "notes": []}')
        with self.assertRaises(ScoreValidationError):
            generate_with_ai(params(), provider=bad)
        with self.assertRaises(ScoreValidationError):
            normalize_ai_note({"pitch": "H4", "duration": "quarter",
                               "rest": False}, 0)

    def test_alias_duracao(self):
        n = normalize_ai_note({"pitch": "C4", "duration": "Seminima",
                               "rest": False}, 0)
        self.assertEqual(n["duration"], "quarter")


if __name__ == "__main__":
    unittest.main(verbosity=2)

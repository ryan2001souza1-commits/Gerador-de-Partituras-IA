"""Gerador de Partituras IA — modelo musical interno.

Representa uma partitura como estrutura de dados validada (sem IA
externa). A geração atual é determinística e baseada em regras; a
futura IA deverá produzir este MESMO formato.

Formato canônico de uma partitura (score):
    {
      "title": str,
      "instrument": str (rótulo PT, ex. "Piano"),
      "musical_key": str canônico (ex. "C", "Cm"),
      "tempo": int (BPM),
      "time_signature": str (ex. "4/4"),
      "difficulty": str canônico (beginner|intermediate|advanced),
      "style": str canônico (ex. "romantic"),
      "notes": [ {pitch, octave, duration, order, rest}, ... ],
      "labels": {rótulos PT originais para exibição},
      "status": "generated-rule-based",
    }

Somente biblioteca padrão.
"""

import hashlib
import random

DESCRIPTION_MAX = 2000

# Limites antiabuso: partitura nunca passa de 300 notas; a IA é
# limitada a 120 (custo/latência), o gerador local usa 12–24.
MAX_NOTES = 300
AI_MAX_NOTES = 120

INSTRUMENTS = ["Piano", "Violão", "Violino", "Flauta", "Baixo", "Bateria", "Outro"]

TOM_TO_KEY = {
    "C Maior": "C", "D Maior": "D", "E Maior": "E", "F Maior": "F",
    "G Maior": "G", "A Maior": "A", "B Maior": "B",
    "C Menor": "Cm", "D Menor": "Dm", "E Menor": "Em", "F Menor": "Fm",
    "G Menor": "Gm", "A Menor": "Am", "B Menor": "Bm",
}

ANDAMENTO_TO_BPM = {
    "Muito lento": 50, "Lento": 70, "Moderado": 96,
    "Rápido": 128, "Muito rápido": 160,
}
BPM_MIN = 20
BPM_MAX = 300

TIME_SIGNATURES = ["2/4", "3/4", "4/4", "6/8", "12/8"]

DIFICULDADE_TO_LEVEL = {
    "Iniciante": "beginner", "Intermediário": "intermediate", "Avançado": "advanced",
}

ESTILO_TO_STYLE = {
    "Clássico": "classical", "Romântico": "romantic", "Jazz": "jazz",
    "Blues": "blues", "Pop": "pop", "Rock": "rock", "Gospel": "gospel",
    "Cinematográfico": "cinematic", "Épico": "epic", "Personalizado": "custom",
}

PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
OCTAVE_MIN = 0
OCTAVE_MAX = 8
DURATIONS = ["whole", "half", "quarter", "eighth", "sixteenth"]

# Durações em tempos de semínima.
DURATION_BEATS = {"whole": 4.0, "half": 2.0, "quarter": 1.0,
                  "eighth": 0.5, "sixteenth": 0.25}
# Tempos por compasso (unidade = semínima).
MEASURE_BEATS = {"2/4": 2.0, "3/4": 3.0, "4/4": 4.0, "6/8": 3.0, "12/8": 6.0}

# Tessitura aproximada por instrumento (oitavas).
INSTRUMENT_OCTAVES = {
    "Piano": (3, 5), "Violão": (3, 4), "Violino": (4, 6), "Flauta": (5, 6),
    "Baixo": (2, 3), "Bateria": (3, 4), "Outro": (4, 5),
}

# Durações ponderadas por nível (soma irrelevante; random.choices normaliza).
DIFFICULTY_DURATIONS = {
    "beginner": (["half", "quarter", "quarter", "quarter", "eighth"], [1, 3, 3, 3, 1]),
    "intermediate": (["half", "quarter", "quarter", "eighth", "eighth"], [1, 3, 3, 2, 2]),
    "advanced": (["quarter", "eighth", "eighth", "sixteenth", "half"], [2, 3, 3, 2, 1]),
}


class ScoreValidationError(ValueError):
    """Erro controlado de validação musical (mensagem segura p/ usuário)."""


def validate_params(data):
    """Valida os parâmetros de entrada (rótulos PT do formulário)."""
    if not isinstance(data, dict):
        raise ScoreValidationError("Dados inválidos.")
    descricao = data.get("descricao")
    if not isinstance(descricao, str) or not descricao.strip():
        raise ScoreValidationError("Descrição é obrigatória.")
    if len(descricao.strip()) > DESCRIPTION_MAX:
        raise ScoreValidationError("Descrição deve ter no máximo 2000 caracteres.")
    for field, allowed in (
        ("instrumento", INSTRUMENTS),
        ("tom", list(TOM_TO_KEY)),
        ("andamento", list(ANDAMENTO_TO_BPM)),
        ("compasso", TIME_SIGNATURES),
        ("dificuldade", list(DIFICULDADE_TO_LEVEL)),
        ("estilo", list(ESTILO_TO_STYLE)),
    ):
        value = data.get(field)
        if not isinstance(value, str) or value not in allowed:
            raise ScoreValidationError('Valor inválido para o campo "{}".'.format(field))
    return True


def validate_note(note, order):
    """Valida uma única nota contra o modelo. Erros controlados."""
    if not isinstance(note, dict):
        raise ScoreValidationError("Nota inválida na posição {}.".format(order))
    rest = note.get("rest", False)
    if not isinstance(rest, bool):
        raise ScoreValidationError("Nota inválida na posição {}.".format(order))
    pitch = note.get("pitch")
    if rest:
        if pitch is not None:
            raise ScoreValidationError("Pausa não deve ter altura definida.")
    else:
        if pitch not in PITCHES:
            raise ScoreValidationError("Altura inválida na posição {}.".format(order))
    octave = note.get("octave")
    if not isinstance(octave, int) or not (OCTAVE_MIN <= octave <= OCTAVE_MAX):
        raise ScoreValidationError("Oitava inválida na posição {}.".format(order))
    if note.get("duration") not in DURATIONS:
        raise ScoreValidationError("Duração inválida na posição {}.".format(order))
    if note.get("order") != order:
        raise ScoreValidationError("Ordem inválida na posição {}.".format(order))
    return True


def validate_score(score):
    """Validação rigorosa da partitura completa."""
    if not isinstance(score, dict):
        raise ScoreValidationError("Partitura inválida.")
    for field in ("title", "instrument", "musical_key", "time_signature",
                  "difficulty", "style", "status"):
        if not isinstance(score.get(field), str) or not score[field]:
            raise ScoreValidationError('Campo "{}" inválido na partitura.'.format(field))
    if score["instrument"] not in INSTRUMENTS:
        raise ScoreValidationError("Instrumento inválido na partitura.")
    if score["musical_key"] not in set(TOM_TO_KEY.values()):
        raise ScoreValidationError("Tonalidade inválida na partitura.")
    tempo = score.get("tempo")
    if not isinstance(tempo, int) or not (BPM_MIN <= tempo <= BPM_MAX):
        raise ScoreValidationError("BPM fora do intervalo permitido.")
    if score["time_signature"] not in TIME_SIGNATURES:
        raise ScoreValidationError("Fórmula de compasso inválida na partitura.")
    if score["difficulty"] not in set(DIFICULDADE_TO_LEVEL.values()):
        raise ScoreValidationError("Dificuldade inválida na partitura.")
    if score["style"] not in set(ESTILO_TO_STYLE.values()):
        raise ScoreValidationError("Estilo inválido na partitura.")
    notes = score.get("notes")
    if not isinstance(notes, list) or not notes:
        raise ScoreValidationError("A partitura precisa de ao menos uma nota.")
    if len(notes) > MAX_NOTES:
        raise ScoreValidationError("A partitura excede o máximo de notas.")
    for i, note in enumerate(notes):
        validate_note(note, i)
    return True


def _scale_degrees(root, minor):
    """Graus diatônicos (semitons a partir da tônica)."""
    intervals = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    root_idx = PITCHES.index(root)
    return [(root_idx + s) % 12 for s in intervals]


def scale_pitches(key):
    """Alturas da escala (classes) em ordem, ex. C Maior -> [C D E F G A B]."""
    minor = key.endswith("m")
    root = key[:-1] if minor else key
    return [PITCHES[s] for s in _scale_degrees(root, minor)]


def tonic_of(key):
    """Tônica (classe) da tonalidade canônica, ex. Cm -> C."""
    return key[:-1] if key.endswith("m") else key


def beats_per_measure(time_signature):
    """Tempos de semínima por compasso."""
    return MEASURE_BEATS.get(time_signature, 4.0)


def _tonic_midi(root_idx, octave):
    return (octave + 1) * 12 + root_idx


def _nearest_scale_midi(midi, scale_semis, lo=None, hi=None):
    """Aproxima para o tom diatônico mais próximo (nunca sai de [lo, hi])."""
    best, best_dist = midi, 99
    for cand in range(midi - 6, midi + 7):
        if cand % 12 not in scale_semis:
            continue
        if (lo is not None and cand < lo) or (hi is not None and cand > hi):
            continue
        if abs(cand - midi) < best_dist:
            best_dist, best = abs(cand - midi), cand
    return best


def _nearest_tonic(midi, root_idx, lo, hi):
    """Tônica (MIDI) mais próxima, dentro da tessitura."""
    import math
    best, best_dist = max(lo, min(hi, midi)), 999
    k0 = math.ceil((lo - root_idx) / 12)
    k1 = math.floor((hi - root_idx) / 12)
    for k in range(k0, k1 + 1):
        cand = 12 * k + root_idx
        if abs(cand - midi) < best_dist:
            best_dist, best = abs(cand - midi), cand
    return best


def _near_octave(midi, ref):
    while midi - ref > 6:
        midi -= 12
    while ref - midi > 6:
        midi += 12
    return midi


def analyze_melody(score):
    """Métricas musicais (nunca lança; para testes e auditoria)."""
    out = {"measures": [], "measures_ok": False, "out_of_scale": 0,
           "max_leap": 0, "final_tonic": False, "rests": 0, "total_beats": 0.0}
    notes = score.get("notes")
    if not isinstance(notes, list) or not notes:
        return out
    key = score.get("musical_key") if isinstance(score.get("musical_key"), str) else "C"
    sig = score.get("time_signature") if isinstance(score.get("time_signature"), str) else "4/4"
    if key not in set(TOM_TO_KEY.values()):
        key = "C"
    beats = MEASURE_BEATS.get(sig, 4.0)
    scale = scale_pitches(key)
    tonic = tonic_of(key)
    acc, prev, last_pitch = 0.0, None, None
    for n in notes:
        if not isinstance(n, dict):
            continue
        d = DURATION_BEATS.get(n.get("duration"), 0.0)
        acc = round(acc + d, 4)
        out["total_beats"] = round(out["total_beats"] + d, 4)
        if acc >= beats - 0.0001:
            out["measures"].append(acc)
            acc = 0.0
        if n.get("rest"):
            out["rests"] += 1
            continue
        pitch = n.get("pitch")
        if pitch not in PITCHES:
            continue
        if pitch not in scale:
            out["out_of_scale"] += 1
        octave = n.get("octave") if isinstance(n.get("octave"), int) else 4
        midi = (octave + 1) * 12 + PITCHES.index(pitch)
        if prev is not None:
            out["max_leap"] = max(out["max_leap"], abs(midi - prev))
        prev, last_pitch = midi, pitch
    out["measures_ok"] = bool(out["measures"]) and acc < 0.0001
    for m in out["measures"]:
        if abs(m - beats) > 0.0001:
            out["measures_ok"] = False
    out["final_tonic"] = (last_pitch == tonic)
    return out


def _fill_measure(rng, beats, vocab, min_unit):
    """Preenche um compasso exatamente (soma = beats)."""
    durs = []
    remaining = beats
    guard = 0
    while remaining > 0.0001 and guard < 64:
        guard += 1
        choices = []
        for dur, b, w in vocab:
            if b > remaining + 0.0001:
                continue
            r = (remaining - b) % min_unit
            if r < 0.0002 or r > min_unit - 0.0002:
                choices.append((dur, w))
        if not choices:
            for dur, b, w in reversed(vocab):
                if b <= remaining + 0.0001:
                    choices = [(dur, 1)]
                    break
            if not choices:
                break
        total = sum(w for _, w in choices)
        roll = rng.randrange(total) if total > 1 else 0
        pick = choices[0][0]
        for dur, w in choices:
            if roll < w:
                pick = dur
                break
            roll -= w
        durs.append(pick)
        remaining = round(remaining - DURATION_BEATS[pick], 4)
    return durs


def build_deterministic_score(data):
    """Gera partitura determinística (regras) a partir dos parâmetros.

    Mesma entrada → mesma saída (seed via SHA-256). Sem IA externa.
    Melodia com estrutura (motivo + variação + cadência na tônica),
    compassos preenchidos exatamente, graus conjuntos com saltos
    limitados e sem teletransporte de oitava.
    A saída é validada por validate_score antes de retornar.
    """
    validate_params(data)

    instrumento = data["instrumento"]
    key = TOM_TO_KEY[data["tom"]]
    bpm = ANDAMENTO_TO_BPM[data["andamento"]]
    level = DIFICULDADE_TO_LEVEL[data["dificuldade"]]
    style = ESTILO_TO_STYLE[data["estilo"]]

    seed_src = "|".join([
        data["descricao"].strip(), instrumento, key, str(bpm),
        data["compasso"], level, style,
    ])
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_src.encode("utf-8")).digest()[:8], "big"))

    minor = key.endswith("m")
    root = key[:-1] if minor else key
    root_idx = PITCHES.index(root)
    scale = _scale_degrees(root, minor)
    lo_oct, hi_oct = INSTRUMENT_OCTAVES[instrumento]
    measure_beats = MEASURE_BEATS[data["compasso"]]
    vocab = {
        "beginner": [("half", 2.0, 1), ("quarter", 1.0, 6)],
        "intermediate": [("half", 2.0, 1), ("quarter", 1.0, 5), ("eighth", 0.5, 3)],
        "advanced": [("half", 2.0, 1), ("quarter", 1.0, 4), ("eighth", 0.5, 4), ("sixteenth", 0.25, 2)],
    }[level]
    min_unit = {"beginner": 1.0, "intermediate": 0.5, "advanced": 0.25}[level]
    max_leap = {"beginner": 4, "intermediate": 5, "advanced": 7}[level]

    lo_midi = (lo_oct + 1) * 12
    hi_midi = (hi_oct + 1) * 12 + 11
    mid_oct = round((lo_oct + hi_oct) / 2)
    tonic_mid = _nearest_scale_midi(_tonic_midi(root_idx, mid_oct), scale, lo_midi, hi_midi)
    midi = tonic_mid
    direction = -1 if rng.randrange(2) == 0 else 1
    resolve = 0

    measures = 4 + rng.randrange(3)  # 4–6 compassos
    notes = []
    order = 0
    prev_midi = None
    motif_rhythm = None
    motif_first = None
    for m in range(measures):
        is_last = (m == measures - 1)
        final_tonic = None
        band_lo, band_hi = lo_midi, hi_midi
        if is_last:
            final_tonic = _nearest_tonic(midi, root_idx, lo_midi, hi_midi)
            band_lo, band_hi = max(lo_midi, final_tonic - 8), min(hi_midi, final_tonic + 8)
            resolve = 0
        if m == 0 or rng.random() >= 0.55:
            durs = _fill_measure(rng, measure_beats, vocab, min_unit)
            if m == 0:
                motif_rhythm = durs
        else:
            durs = list(motif_rhythm)
        for di, dur in enumerate(durs):
            is_first = (order == 0)
            is_final = is_last and (di == len(durs) - 1)
            if not is_first and not is_final and rng.random() < 0.08:
                notes.append({"pitch": None, "octave": lo_oct,
                              "duration": dur, "order": order, "rest": True})
                order += 1
                continue
            if is_final:
                midi = final_tonic
            elif is_first:
                midi = tonic_mid
                motif_first = midi
            else:
                if di == 0 and not is_last and motif_first is not None and rng.random() < 0.30:
                    cand = max(band_lo, min(band_hi, _near_octave(motif_first, midi) + rng.randrange(-1, 2)))
                    midi = _nearest_scale_midi(cand, scale, band_lo, band_hi)
                else:
                    if resolve > 0:
                        delta = -direction * rng.randrange(1, 3)
                        resolve -= 1
                    elif final_tonic is not None and rng.random() < (1.0 if is_last else 0.70):
                        toward = 1 if final_tonic >= midi else -1
                        delta = toward * rng.randrange(1, 3)
                        direction = toward
                    elif rng.random() < 0.65:
                        delta = (0 if rng.random() < 0.18 else direction * rng.randrange(1, 3))
                        if delta != 0:
                            direction = 1 if delta > 0 else -1
                    else:
                        direction = -direction
                        delta = direction * rng.randrange(1, 3)
                        if rng.random() < 0.12:
                            delta = direction * rng.randrange(3, max_leap + 1)
                    target = midi + delta
                    if abs(target - midi) > max_leap:
                        target = midi + (max_leap if target > midi else -max_leap)
                    target = _nearest_scale_midi(target, scale)
                    target = max(band_lo, min(band_hi, target))
                    target = _nearest_scale_midi(target, scale, band_lo, band_hi)
                    midi = target
                    prev = prev_midi if prev_midi is not None else midi
                    if abs(midi - prev) >= 5:
                        resolve = 2
                        direction = 1 if midi > prev else -1
            pc = PITCHES[midi % 12]
            if not is_final and prev_midi is not None and abs(midi - prev_midi) > 8:
                midi = _nearest_scale_midi(
                    max(band_lo, min(band_hi, prev_midi + (7 if midi > prev_midi else -7))),
                    scale, band_lo, band_hi)
                pc = PITCHES[midi % 12]
            notes.append({"pitch": pc, "octave": midi // 12 - 1,
                          "duration": dur, "order": order, "rest": False})
            order += 1
            prev_midi = midi

    score = {
        "title": "{} para {} em {}".format(data["estilo"], instrumento, data["tom"]),
        "instrument": instrumento,
        "musical_key": key,
        "tempo": bpm,
        "time_signature": data["compasso"],
        "difficulty": level,
        "style": style,
        "notes": notes,
        "labels": {
            "instrumento": instrumento,
            "tom": data["tom"],
            "andamento": data["andamento"],
            "compasso": data["compasso"],
            "dificuldade": data["dificuldade"],
            "estilo": data["estilo"],
        },
        "status": "generated-rule-based",
    }
    validate_score(score)
    return score

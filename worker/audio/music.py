"""Pós-processamento musical e quantização (FASE 3H).

Camada determinística (stdlib apenas, sem IA/GPU) que recebe notas
MIDI detectadas pelo Basic Pitch e produz uma representação musical
limpa, pronta para futura geração de partitura.

Pipeline: clean_notes → estimate_bpm → choose_quantization_grid →
quantize_notes → measures → duration_to_symbol →
group_simultaneous_notes → process_music_notes (JSON).

Todos os thresholds abaixo são configuráveis e documentados. Nada
aqui inventa notas, altera pitch detectado ou varia aleatoriamente.
"""

import math

# ---------------- Thresholds configuráveis (documentados) ----------------
MIN_CONFIDENCE_KEEP = 0.15  # confidence < isto remove (None preserva)
ARTIFACT_DURATION_S = 0.05  # abaixo disto = candidato a artefato
ISOLATION_WINDOW_S = 0.25  # vizinhança p/ decidir isolamento
WEAK_ECHO_CONF = 0.25  # eco fraco: conf < isto perto de nota forte
STRONG_REF_CONF = 0.60  # nota de referência do eco fraco
WEAK_ECHO_WINDOW_S = 0.06  # onset do eco dentro disto da referência
DEDUP_START_TOL_S = 0.02  # duplicata: mesmo pitch + |Δstart| <= isto
DEDUP_END_TOL_S = 0.03  # ... e |Δend| <= isto
CHORD_ONSET_TOL_S = 0.035  # onsets dentro disto = simultâneos
DEFAULT_BPM = 120.0
MIN_BPM = 40.0
MAX_BPM = 240.0
MIN_BPM_SOURCES = 4  # onsets mínimos p/ estimar BPM dos eventos
SNAP_TOLERANCE_BEATS = 0.06  # deslocamento além disto é contabilizado

# Grade rítmica: divisão → beats (4/4; 1 beat = semínima).
GRID_BEATS = {
    "1/1": 4.0,
    "1/2": 2.0,
    "1/4": 1.0,
    "1/8": 0.5,
    "1/16": 0.25,
    "1/32": 0.125,
}
# Compasso atual + ganchos futuros (numerador, denominador, beats).
TIME_SIGNATURES = {
    "4/4": {"numerator": 4, "denominator": 4, "beats_per_bar": 4},
    "3/4": {"numerator": 3, "denominator": 4, "beats_per_bar": 3},
    "2/4": {"numerator": 2, "denominator": 4, "beats_per_bar": 2},
    "6/8": {"numerator": 6, "denominator": 8, "beats_per_bar": 3.0},
}
CURRENT_TIME_SIGNATURE = "4/4"

# Símbolos de duração: nome → beats (4/4).
DURATION_SYMBOLS = [
    ("whole", 4.0),
    ("half", 2.0),
    ("quarter", 1.0),
    ("eighth", 0.5),
    ("sixteenth", 0.25),
    ("thirty_second", 0.125),
]
_SYMBOL_EPS = 1e-6


def _round3(value):
    return round(float(value), 3)


def _snap_half_up(value):
    """round() determinístico (half-up; sem banker's rounding)."""
    return math.floor(float(value) + 0.5)


def _as_note_event(note):
    """Valida a forma NoteEvent; devolve dict normalizado ou None."""
    try:
        pitch = int(note["pitch"])
        start = float(note["start"])
        end = float(note["end"])
        velocity = int(note["velocity"])
    except (KeyError, TypeError, ValueError):
        return None
    conf = note.get("confidence", None)
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            return None
    try:
        duration = float(note.get("duration", end - start))
    except (TypeError, ValueError):
        return None
    return {
        "pitch": pitch,
        "start": _round3(start),
        "end": _round3(end),
        "duration": _round3(duration),
        "velocity": velocity,
        "confidence": conf,
    }


def clean_notes(notes, min_confidence=MIN_CONFIDENCE_KEEP):
    """Limpa notas sem inventar nada.

    Remove: pitch fora de 0–127, velocity fora de 1–127,
    duração <= 0, confidence < mínimo (None sempre preservado).
    Ordena por (start, pitch) e elimina duplicatas praticamente
    idênticas (mantém maior confidence, depois maior duração).
    Retorna (notas_limpas, removidas_total, deduplicadas).
    """
    valid, removed = [], 0
    for raw in notes or []:
        n = _as_note_event(raw)
        if n is None:
            removed += 1
            continue
        if not 0 <= n["pitch"] <= 127:
            removed += 1
            continue
        if not 1 <= n["velocity"] <= 127:
            removed += 1
            continue
        if not n["duration"] > 0:
            removed += 1
            continue
        conf = n["confidence"]
        if conf is not None and not 0.0 <= conf <= 1.0:
            removed += 1
            continue
        if conf is not None and conf < min_confidence:
            removed += 1
            continue
        valid.append(n)
    valid.sort(key=lambda n: (n["start"], n["pitch"]))
    unique, deduped = [], 0
    for n in valid:
        merged = False
        for kept in reversed(unique):
            if kept["start"] - n["start"] > DEDUP_START_TOL_S:
                break
            if (kept["pitch"] == n["pitch"]
                    and abs(kept["start"] - n["start"])
                    <= DEDUP_START_TOL_S
                    and abs(kept["end"] - n["end"])
                    <= DEDUP_END_TOL_S):
                deduped += 1
                merged = True
                old_conf = kept["confidence"]
                new_conf = n["confidence"]
                if (new_conf is not None
                        and (old_conf is None or new_conf > old_conf)):
                    kept.update(n)
                elif n["duration"] > kept["duration"] and (
                        new_conf == old_conf):
                    kept.update(n)
                break
        if not merged:
            unique.append(dict(n))
    unique.sort(key=lambda n: (n["start"], n["pitch"]))
    return unique, removed, deduped


def _median(values):
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _clamp_bpm(bpm):
    try:
        bpm = float(bpm)
    except (TypeError, ValueError):
        return DEFAULT_BPM
    if not math.isfinite(bpm):
        return DEFAULT_BPM
    return _round3(max(MIN_BPM, min(MAX_BPM, bpm)))


def estimate_bpm(notes, pipeline_bpm=None, audio_bpm=None):
    """BPM determinístico (mesma entrada → mesma saída).

    Prioridade: 1) pipeline_bpm válido (40–240); 2) audio_bpm válido
    (gancho p/ futura detecção no áudio; hoje sempre ausente);
    3) mediana dos intervalos entre onsets (>=4 onsets);
    4) fallback 120.
    """
    for candidate in (pipeline_bpm, audio_bpm):
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and MIN_BPM <= value <= MAX_BPM:
            return _round3(value)
    onsets = sorted({n["start"] for n in notes or []})
    if len(onsets) >= MIN_BPM_SOURCES:
        gaps = [b - a for a, b in zip(onsets, onsets[1:]) if b > a]
        if gaps:
            guess = 60.0 / _median(gaps)
            if math.isfinite(guess) and guess > 0:
                return _clamp_bpm(guess)
    return DEFAULT_BPM


def choose_quantization_grid(notes, bpm):
    """Escolhe a grade mais grosseira que resolve as notas curtas.

    Usa o percentil 25 das durações (em beats): a grade é a maior
    divisão <= p25. Determinístico; nunca excessivamente fina sem
    motivo (dur.s curtas reais).
    """
    if not notes:
        return {"division": "1/4", "beats": 1.0}
    try:
        spb = 60.0 / float(bpm)
    except (TypeError, ValueError, ZeroDivisionError):
        spb = 60.0 / DEFAULT_BPM
    durations = sorted(n["duration"] / spb for n in notes
                       if n["duration"] > 0)
    if not durations:
        return {"division": "1/4", "beats": 1.0}
    index = min(len(durations) - 1, len(durations) // 4)
    reference = durations[index]
    ordered = sorted(GRID_BEATS.items(), key=lambda kv: kv[1],
                     reverse=True)
    for division, beats in ordered:
        if beats <= reference + _SYMBOL_EPS:
            return {"division": division, "beats": beats}
    return {"division": "1/32", "beats": 0.125}


def quantize_notes(notes, bpm, grid,
                   snap_tolerance_beats=SNAP_TOLERANCE_BEATS,
                   total_seconds=None):
    """Snapping determinístico (half-up) para a grade.

    Preserva pitch/velocity/confidence. Duração mínima = 1 passo da
    grade (nunca <= 0); fim nunca além da duração total. Retorna
    (notas_quantizadas, além_da_tolerância).
    """
    try:
        grid_beats = float(grid["beats"] if isinstance(grid, dict)
                           else GRID_BEATS[grid])
    except (KeyError, TypeError, ValueError):
        grid_beats = 1.0
    if grid_beats <= 0:
        grid_beats = 1.0
    try:
        bps = float(bpm) / 60.0
    except (TypeError, ValueError):
        bps = DEFAULT_BPM / 60.0
    if bps <= 0:
        bps = DEFAULT_BPM / 60.0
    if total_seconds is None:
        total_seconds = max((n["end"] for n in notes), default=0.0)
    total_beats = float(total_seconds) * bps
    out, beyond = [], 0
    for n in notes:
        start_beat = n["start"] * bps
        end_beat = n["end"] * bps
        q_start = _snap_half_up(start_beat / grid_beats) * grid_beats
        q_end = _snap_half_up(end_beat / grid_beats) * grid_beats
        if abs(start_beat - q_start) > snap_tolerance_beats:
            beyond += 1
        if abs(end_beat - q_end) > snap_tolerance_beats:
            beyond += 1
        q_start = max(0.0, min(q_start, total_beats))
        q_end = max(q_start + grid_beats,
                    min(q_end, total_beats + grid_beats))
        if q_start >= total_beats and total_beats > 0:
            q_start = max(0.0, total_beats - grid_beats)
            q_end = total_beats
        q = dict(n)
        q["quantized_start"] = _round3(q_start)
        q["quantized_duration"] = _round3(q_end - q_start)
        out.append(q)
    out.sort(key=lambda n: (n["quantized_start"], n["pitch"]))
    return out, beyond


def _measure_info(beat, beats_per_bar):
    measure = int(beat // beats_per_bar) + 1
    position = _round3(beat % beats_per_bar)
    return measure, position


def assign_measures(notes, time_signature=CURRENT_TIME_SIGNATURE,
                    quantized=False):
    """Preenche beat/measure/position_in_measure (compasso dado)."""
    spec = TIME_SIGNATURES.get(time_signature,
                              TIME_SIGNATURES[CURRENT_TIME_SIGNATURE])
    beats_per_bar = float(spec["beats_per_bar"])
    out = []
    for n in notes:
        beat = (n["quantized_start"] if quantized
                else _round3(n["start"]))
        if quantized:
            beat_value = float(beat)
        else:
            beat_value = beat
        measure, position = _measure_info(
            max(0.0, beat_value), beats_per_bar)
        q = dict(n)
        q["beat"] = _round3(beat_value)
        q["measure"] = measure
        q["position_in_measure"] = position
        out.append(q)
    return out


def duration_to_symbol(beats):
    """Duração quantizada → símbolo musical (+ dots / tie futuro).

    Exato (com 0–2 dots) → tie_required False. Sem representação
    exata → base mais próxima por baixo + tie_required True
    (decomposição em ties = etapa futura, nunca símbolo inválido).
    """
    try:
        value = float(beats)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return {"base": "thirty_second", "beats": _round3(value),
                "dots": 0, "tie_required": True}
    for base, base_beats in DURATION_SYMBOLS:
        for dots in (0, 1, 2):
            dotted = base_beats * (2.0 - 0.5 ** dots)
            if abs(value - dotted) <= _SYMBOL_EPS:
                return {"base": base, "beats": _round3(value),
                        "dots": dots, "tie_required": False}
    base = "thirty_second"
    for name, base_beats in DURATION_SYMBOLS:
        if base_beats <= value + _SYMBOL_EPS:
            base = name
            break
    return {"base": base, "beats": _round3(value), "dots": 0,
            "tie_required": True}


def group_simultaneous_notes(notes, onset_tolerance_s=CHORD_ONSET_TOL_S,
                             quantized=False):
    """Agrupa onsets simultâneos em ChordEvents (sem nomear acordes)."""
    key = "quantized_start" if quantized else "start"
    ordered = sorted(notes, key=lambda n: (n[key], n["pitch"]))
    groups = []
    for n in ordered:
        placed = False
        for group in reversed(groups):
            if n[key] - group["start"] > onset_tolerance_s:
                break
            if abs(n[key] - group["start"]) <= onset_tolerance_s:
                group["notes"].append(n)
                group["pitches"].append(n["pitch"])
                group["duration"] = _round3(max(
                    group["duration"],
                    (n["quantized_duration"] if quantized
                     else n["duration"])))
                placed = True
                break
        if not placed:
            groups.append({
                "start": n[key],
                "duration": (n["quantized_duration"] if quantized
                             else n["duration"]),
                "notes": [n],
                "pitches": [n["pitch"]],
            })
    for group in groups:
        group["notes"].sort(key=lambda n: n["pitch"])
        group["pitches"] = sorted(group["pitches"])
    groups.sort(key=lambda g: g["start"])
    return groups


def remove_artifacts(notes):
    """Heurísticas conservadoras (nunca muda pitch).

    Remove apenas: (a) nota ultra-curta isolada E de confidence
    baixa (None nunca pune); (b) eco fraco: mesma pitch, onset a
    <=0.06 s de nota forte sobreposta. Curta sozinha, acorde e
    polifonia sobreposta são sempre preservados.
    Retorna (notas, removidas).
    """
    if len(notes) <= 1:
        return [dict(n) for n in notes], 0
    ordered = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
    drop = set()
    for i, n in enumerate(ordered):
        if i in drop:
            continue
        conf = n["confidence"]
        short = n["duration"] < ARTIFACT_DURATION_S
        if short and conf is not None and conf < WEAK_ECHO_CONF:
            isolated = True
            for j, other in enumerate(ordered):
                if i == j or j in drop:
                    continue
                if other["pitch"] != n["pitch"]:
                    continue
                if abs(other["start"] - n["start"]) <= ISOLATION_WINDOW_S:
                    isolated = False
                    break
                if (other["start"] < n["end"] and other["end"]
                        > n["start"]):
                    isolated = False
                    break
            if isolated:
                drop.add(i)
                continue
        if conf is not None and conf < WEAK_ECHO_CONF:
            for j, other in enumerate(ordered):
                if i == j or j in drop:
                    continue
                ref = other["confidence"]
                if ref is None or ref < STRONG_REF_CONF:
                    continue
                if other["pitch"] != n["pitch"]:
                    continue
                if abs(n["start"] - other["start"]) \
                        <= WEAK_ECHO_WINDOW_S:
                    if other["start"] < n["end"] and other["end"] \
                            > n["start"]:
                        drop.add(i)
                        break
    kept = [dict(n) for i, n in enumerate(ordered) if i not in drop]
    return kept, len(drop)


def _statistics(input_count, removed, deduped, quantized, groups,
                notes):
    confidences = [n["confidence"] for n in notes
                   if n["confidence"] is not None]
    pitches = [n["pitch"] for n in notes]
    return {
        "input_notes": input_count,
        "removed_notes": removed,
        "deduplicated_notes": deduped,
        "quantized_notes": len(quantized),
        "chord_groups": len(groups),
        "lowest_pitch": min(pitches) if pitches else None,
        "highest_pitch": max(pitches) if pitches else None,
        "average_confidence": (
            round(sum(confidences) / len(confidences), 4)
            if confidences else None),
    }


def process_music_notes(notes, bpm=None, audio_bpm=None,
                        time_signature=CURRENT_TIME_SIGNATURE,
                        grid=None,
                        snap_tolerance_beats=SNAP_TOLERANCE_BEATS):
    """Função principal: notas brutas → representação musical limpa.

    Determinística e JSON-serializável. Nunca inventa notas.
    """
    raw = list(notes or [])
    input_count = len(raw)
    cleaned, removed, deduped = clean_notes(raw)
    kept, artifacts = remove_artifacts(cleaned)
    removed += artifacts
    final_bpm = estimate_bpm(kept, pipeline_bpm=bpm,
                             audio_bpm=audio_bpm)
    grid_info = grid if isinstance(grid, dict) else (
        {"division": grid, "beats": GRID_BEATS[grid]}
        if grid in GRID_BEATS else
        choose_quantization_grid(kept, final_bpm))
    total_seconds = max([n["end"] for n in kept], default=0.0)
    quantized, _beyond = quantize_notes(
        kept, final_bpm, grid_info,
        snap_tolerance_beats=snap_tolerance_beats,
        total_seconds=total_seconds)
    with_measures = assign_measures(
        quantized, time_signature=time_signature, quantized=True)
    for n in with_measures:
        n["duration_symbol"] = duration_to_symbol(
            n["quantized_duration"])
    groups = group_simultaneous_notes(with_measures, quantized=True)
    spec = TIME_SIGNATURES.get(time_signature,
                               TIME_SIGNATURES[CURRENT_TIME_SIGNATURE])
    beats_per_bar = float(spec["beats_per_bar"])
    bps = final_bpm / 60.0
    total_beats = _round3(total_seconds * bps)
    total_measures = max(1, int(math.ceil(total_beats / beats_per_bar))
                         if total_beats > 0 else 1)
    statistics = _statistics(input_count, removed, deduped,
                             with_measures, groups, with_measures)
    return {
        "bpm": final_bpm,
        "time_signature": {
            "numerator": spec["numerator"],
            "denominator": spec["denominator"],
        },
        "grid": {"division": grid_info["division"],
                 "beats": grid_info["beats"]},
        "total_beats": total_beats,
        "total_measures": total_measures,
        "statistics": statistics,
        "notes": with_measures,
        "chords": groups,
    }


def transcribe_and_process(audio_path, bpm=None, stem=None,
                           instrument=None):
    """Integração isolada (futura): transcreve e pós-processa.

    Não altera o comportamento atual de produção — apenas encadeia
    MusicTranscriber → process_music_notes sob demanda.
    """
    from audio.transcriber import MusicTranscriber
    transcriber = MusicTranscriber()
    if stem is not None:
        result = transcriber.transcribe_stem(
            audio_path, stem=stem, instrument=instrument)
    else:
        result = transcriber.transcribe(
            audio_path, instrument=instrument)
    processed = process_music_notes(result["notes"], bpm=bpm)
    return {"transcription": result, "processed": processed}

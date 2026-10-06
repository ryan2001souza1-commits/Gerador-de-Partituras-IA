"""Análise musical real sobre a saída da FASE 3H (FASE 3I).

NOTA DE ARQUITETURA: `worker/audio/analysis.py` já existe (análise de
stems das FASEs 3E/3F, importada por `app.py`). Para preservar as fases
anteriores, esta camada vive neste módulo separado e recebe o dict
produzido por `music.process_music_notes` — nunca toca em Demucs,
Basic Pitch ou PANNs.

Camada determinística (stdlib apenas, sem IA/GPU, sem rede): mesma
entrada → mesma saída. `null` é sempre preferível a palpite falso;
confianças baixas nunca são mascaradas.
"""

import math

# Perfis Krumhansl-Schmuckler (correlação com histograma de classes
# de pitch ponderado por duração). Documentados e fixos.
KS_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39,
            3.66, 2.29, 2.88)
KS_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98,
            2.69, 3.34, 3.17)
PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#",
               "A", "A#", "B")
MAJOR_SCALE_STEPS = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE_STEPS = (0, 2, 3, 5, 7, 8, 10)

MIN_KEY_DISTINCT_PC = 2  # < isto = evidência insuficiente p/ tom
MIN_KEY_CORRELATION = 0.30  # abaixo disto = tonalidade null
MIN_METER_NOTES = 4  # < isto = compasso null
METER_CANDIDATES = ("4/4", "3/4", "2/4", "6/8")
METER_BEATS = {"4/4": 4.0, "3/4": 3.0, "2/4": 2.0, "6/8": 3.0}
MIN_SECTION_MEASURES = 4  # < isto = sem detecção de estrutura
MIN_REPEAT_BARS = 2  # repetição mínima p/ verso/refrão
ONSET_BEAT_TOL = 0.06  # tolerância p/ coerência de grade (beats)
CHORD_MIN_NOTES = 2  # grupo com < isto não conta como acorde

# Templates de acordes: nome → intervalos (a partir da fundamental).
# Somente tríades + sétimas básicas; sem match = nome null.
CHORD_TEMPLATES = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "diminished": (0, 3, 6),
    "augmented": (0, 4, 8),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "major7": (0, 4, 7, 11),
    "minor7": (0, 3, 7, 10),
    "dominant7": (0, 4, 7, 10),
}


def _round3(value):
    return round(float(value), 3)


def _mean(values):
    return sum(values) / len(values) if values else None


def _pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs)
                    * sum((y - my) ** 2 for y in ys))
    if den <= 0:
        return 0.0
    return num / den


def _pitch_class_histogram(notes):
    """Histograma de 12 classes ponderado por duração."""
    hist = [0.0] * 12
    for n in notes or []:
        try:
            weight = max(0.0, float(n.get("duration", 0.0)))
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            continue
        hist[int(n["pitch"]) % 12] += weight
    return hist


def _rotate(profile, tonic):
    return tuple(profile[(i - tonic) % 12] for i in range(12))


def estimate_key(notes):
    """Tonalidade via perfis Krumhansl-Schmuckler (determinístico).

    Retorna {"tonic","mode","confidence","method"} ou todos null
    quando a evidência é insuficiente (vazio, 1 classe de pitch,
    correlação < 0.30 ou empate exato no topo).
    """
    empty = {"tonic": None, "mode": None, "confidence": None,
             "method": "krumhansl-schmuckler"}
    hist = _pitch_class_histogram(notes)
    if sum(hist) <= 0:
        return empty
    if sum(1 for v in hist if v > 0) < MIN_KEY_DISTINCT_PC:
        return empty
    scored = []
    for tonic in range(12):
        scored.append((PITCH_NAMES[tonic], "major",
                       _pearson(hist, _rotate(KS_MAJOR, tonic))))
        scored.append((PITCH_NAMES[tonic], "minor",
                       _pearson(hist, _rotate(KS_MINOR, tonic))))
    scored.sort(key=lambda s: s[2], reverse=True)
    best, second = scored[0], scored[1]
    if best[2] < MIN_KEY_CORRELATION:
        return empty
    if best[2] == second[2]:
        return empty  # empate exato = ambíguo
    margin = best[2] - max(0.0, second[2])
    confidence = _round3(max(0.0, min(1.0, best[2] * 0.7 + margin)))
    if confidence <= 0:
        return empty
    return {"tonic": best[0], "mode": best[1],
            "confidence": confidence,
            "method": "krumhansl-schmuckler"}


def derive_scale(key):
    """Escala provável derivada da tonalidade (null sem tom)."""
    empty = {"name": None, "notes": [], "confidence": None}
    if not key or not key.get("tonic") or not key.get("mode"):
        return empty
    tonic = PITCH_NAMES.index(key["tonic"])
    steps = (MAJOR_SCALE_STEPS if key["mode"] == "major"
             else MINOR_SCALE_STEPS)
    if key["mode"] not in ("major", "minor"):
        return empty
    pcs = sorted((tonic + s) % 12 for s in steps)
    name = "%s %s" % (key["tonic"],
                      "major" if key["mode"] == "major"
                      else "natural minor")
    return {"name": name,
            "notes": [PITCH_NAMES[p] for p in pcs],
            "confidence": key.get("confidence")}


def analyze_tempo(processed):
    """Reutiliza o BPM da 3H + coerência de grade como confidence.

    confidence = fração média de alinhamento onset↔beat (0–1);
    0.0 quando BPM é fallback sem evidência. Nunca inventa valor.
    """
    bpm = (processed or {}).get("bpm")
    notes = (processed or {}).get("notes") or []
    try:
        bpm_value = float(bpm)
    except (TypeError, ValueError):
        return {"bpm": None, "confidence": 0.0,
                "method": "unavailable"}
    if not notes:
        return {"bpm": _round3(bpm_value), "confidence": 0.0,
                "method": "fallback-no-evidence"}
    bps = bpm_value / 60.0
    scores = []
    for n in notes:
        beat = float(n.get("quantized_start", 0.0))
        dist = abs(beat - round(beat))
        scores.append(max(0.0, 1.0 - dist / 0.5))
    onsets = sorted({float(n.get("start", 0.0)) for n in notes})
    method = ("fallback-no-evidence" if len(onsets) < 4
              else "reuse-3h-onset-coherence")
    if len(onsets) < 4:
        return {"bpm": _round3(bpm_value), "confidence": 0.0,
                "method": method}
    _ = bps
    return {"bpm": _round3(bpm_value),
            "confidence": _round3(_mean(scores)),
            "method": method}


def analyze_meter(processed):
    """Compasso por coincidência de onsets em grades candidatas.

    Para cada candidato (4/4, 3/4, 2/4, 6/8): fração de onsets
    dentro da tolerância de linhas de compasso. Melhor vence;
    empate ou <4 notas → null (4/4 nunca assumido sem evidência).
    """
    notes = (processed or {}).get("notes") or []
    empty = {"numerator": None, "denominator": None,
             "confidence": 0.0, "method": "bar-coincidence"}
    if len(notes) < MIN_METER_NOTES:
        return empty
    onsets = sorted({float(n.get("quantized_start", 0.0))
                     for n in notes})
    scored = []
    for cand in METER_CANDIDATES:
        bar = METER_BEATS[cand]
        hits = sum(1 for o in onsets
                   if abs((o % bar) - 0.0) <= ONSET_BEAT_TOL
                   or abs((o % bar) - bar) <= ONSET_BEAT_TOL)
        scored.append((cand, hits / len(onsets)))
    scored.sort(key=lambda s: s[1], reverse=True)
    if scored[0][1] == scored[1][1]:
        return empty  # empate = ambíguo
    num, den = scored[0][0].split("/")
    margin = scored[0][1] - scored[1][1]
    return {"numerator": int(num), "denominator": int(den),
            "confidence": _round3(
                max(0.0, min(1.0, scored[0][1] * 0.6 + margin))),
            "method": "bar-coincidence"}


def analyze_grid(processed):
    """Reutiliza a grade 3H + erro médio e notas alteradas.

    Erro em beats (|start*bps − quantized_start|); notas alteradas
    conta desvios > 1ns.
    """
    grid = (processed or {}).get("grid") or {}
    notes = (processed or {}).get("notes") or []
    try:
        bps = float((processed or {}).get("bpm", 120.0)) / 60.0
    except (TypeError, ValueError):
        bps = DEFAULT_BPM / 60.0
    if bps <= 0:
        bps = DEFAULT_BPM / 60.0
    errors, changed = [], 0
    for n in notes:
        try:
            original = float(n.get("start", 0.0)) * bps
            quant = float(n.get("quantized_start", original))
        except (TypeError, ValueError):
            continue
        errors.append(abs(original - quant))
        if abs(original - quant) > 1e-9:
            changed += 1
    return {"division": grid.get("division"),
            "beats": grid.get("beats"),
            "quantization_error": (
                _round3(_mean(errors)) if errors else 0.0),
            "changed_notes": changed}


def _name_chord(pitches):
    """Nomeia tríades/sétimas básicas; None se sem match (sem chute)."""
    pcs = sorted({p % 12 for p in pitches})
    if len(pcs) < 3:
        return None
    pcs_set = set(pcs)
    for root in pcs:
        intervals = tuple(sorted((p - root) % 12 for p in pcs))
        for name, template in CHORD_TEMPLATES.items():
            if set(template) == pcs_set and intervals[0] == 0:
                return "%s %s" % (PITCH_NAMES[root], name)
    # Inversão: tenta rotações da fundamental antes de desistir.
    for root in pcs:
        intervals = set((p - root) % 12 for p in pcs)
        for name, template in CHORD_TEMPLATES.items():
            if intervals == set(template):
                return "%s %s" % (PITCH_NAMES[root], name)
    return None


def analyze_chords(processed):
    """Acordes a partir dos grupos 3H (pitches sempre; nome só c/ match)."""
    groups = (processed or {}).get("chords") or []
    notes_by_start = {}
    for n in (processed or {}).get("notes") or []:
        notes_by_start.setdefault(n.get("quantized_start"), []).append(n)
    chords = []
    for group in groups:
        pitches = sorted(group.get("pitches") or [])
        if len(pitches) < CHORD_MIN_NOTES:
            continue
        members = group.get("notes") or []
        ends = []
        confs = []
        for m in members:
            try:
                ends.append(float(m.get("quantized_start", 0.0))
                            + float(m.get("quantized_duration", 0.0)))
            except (TypeError, ValueError):
                pass
            if m.get("confidence") is not None:
                try:
                    confs.append(float(m["confidence"]))
                except (TypeError, ValueError):
                    pass
        start = group.get("start", 0.0)
        end = max(ends) if ends else start
        chords.append({
            "start": _round3(start),
            "end": _round3(end),
            "duration": _round3(max(0.0, end - start)),
            "pitches": pitches,
            "name": _name_chord(pitches),
            "confidence": (_round3(_mean(confs))
                           if confs else None),
        })
    chords.sort(key=lambda c: (c["start"], c["pitches"]))
    return chords


def _bar_fingerprint(processed, measure):
    """Assinatura determinística de um compasso (classes + onsets)."""
    items = []
    for n in (processed or {}).get("notes") or []:
        if n.get("measure") == measure:
            items.append((int(n["pitch"]) % 12,
                          _round3(float(n.get("quantized_start", 0.0))
                                  % 4.0)))
    return tuple(sorted(items))


def analyze_sections(processed):
    """Estrutura por repetição de compassos (sem repetição = []).

    Blocos repetidos (≥2 compassos idênticos): primeiro = verse,
    repetição = chorus; compassos antes = intro, entre blocos =
    bridge, após o último = outro. Nomes só com evidência de
    repetição exata.
    """
    total = (processed or {}).get("total_measures", 0) or 0
    if total < MIN_SECTION_MEASURES:
        return []
    prints = {m: _bar_fingerprint(processed, m)
              for m in range(1, total + 1)}
    best = None  # (início A, início B, tamanho)
    for length in range(total // 2, MIN_REPEAT_BARS - 1, -1):
        found = None
        for a in range(1, total - 2 * length + 2):
            seq_a = [prints[a + k] for k in range(length)]
            if not any(seq_a):
                continue
            for b in range(a + length, total - length + 2):
                if [prints[b + k] for k in range(length)] == seq_a:
                    found = (a, b, length)
                    break
            if found:
                break
        if found:
            best = found
            break
    if not best:
        return []
    first, second, length = best
    sections = []
    if first > 1:
        sections.append({"name": "intro", "start_measure": 1,
                         "end_measure": first - 1,
                         "confidence": 0.6})
    sections.append({"name": "verse", "start_measure": first,
                     "end_measure": first + length - 1,
                     "confidence": 0.7})
    gap_start, gap_end = first + length, second - 1
    if gap_end >= gap_start:
        sections.append({"name": "bridge",
                         "start_measure": gap_start,
                         "end_measure": gap_end,
                         "confidence": 0.5})
    sections.append({"name": "chorus", "start_measure": second,
                     "end_measure": second + length - 1,
                     "confidence": 0.7})
    tail = second + length
    if tail <= total:
        sections.append({"name": "outro", "start_measure": tail,
                         "end_measure": total, "confidence": 0.6})
    return sections


def analyze_statistics(processed, chords, sections):
    """Estatísticas descritivas (só do que existe; resto null/0)."""
    notes = (processed or {}).get("notes") or []
    duration = 0.0
    for n in notes:
        try:
            end = float(n.get("start", 0.0)) + float(
                n.get("duration", 0.0))
        except (TypeError, ValueError):
            continue
        duration = max(duration, end)
    duration = _round3(duration)
    velocities = []
    durations = []
    pitches = []
    for n in notes:
        try:
            velocities.append(int(n["velocity"]))
            durations.append(float(n["duration"]))
            pitches.append(int(n["pitch"]))
        except (TypeError, ValueError, KeyError):
            continue
    covered = sorted(
        (float(n["start"]), float(n["start"]) + float(n["duration"]))
        for n in notes
        if isinstance(n.get("start"), (int, float))
        and isinstance(n.get("duration"), (int, float)))
    sounding = 0.0
    cursor = None
    for start, end in covered:
        if end <= start:
            continue
        if cursor is None:
            cursor = start
        sounding += max(0.0, end - max(start, cursor))
        cursor = max(cursor, end)
    silence = _round3(max(0.0, duration - sounding))
    return {
        "note_count": len(notes),
        "pitch_min": min(pitches) if pitches else None,
        "pitch_max": max(pitches) if pitches else None,
        "mean_velocity": (_round3(_mean(velocities))
                          if velocities else None),
        "mean_duration": (_round3(_mean(durations))
                          if durations else None),
        "measure_count": (processed or {}).get("total_measures", 0),
        "chord_count": len(chords),
        "note_density": (_round3(len(notes) / duration)
                         if duration > 0 else 0.0),
        "silence_seconds": silence,
    }


def analyze_music(processed):
    """Função pública: resultado 3H → análise musical (JSON det.)."""
    processed = processed if isinstance(processed, dict) else {}
    notes = processed.get("notes") or []
    key = estimate_key(notes)
    scale = derive_scale(key)
    tempo = analyze_tempo(processed)
    meter = analyze_meter(processed)
    grid = analyze_grid(processed)
    chords = analyze_chords(processed)
    sections = analyze_sections(processed)
    statistics = analyze_statistics(processed, chords, sections)
    parts = [key.get("confidence"), tempo.get("confidence"),
             meter.get("confidence")]
    parts = [p for p in parts if p is not None]
    confidence = _round3(_mean(parts)) if parts else 0.0
    return {
        "duration_seconds": statistics and _round3(
            max([float(n.get("start", 0.0)) + float(
                n.get("duration", 0.0)) for n in notes],
                default=0.0)),
        "tempo": tempo,
        "meter": meter,
        "key": key,
        "scale": scale,
        "grid": grid,
        "chords": chords,
        "sections": sections,
        "statistics": dict(statistics,
                           overall_confidence=confidence),
        "confidence": confidence,
    }

"""Resultado final da transcrição musical (FASE 3K).

Composição determinística (stdlib apenas) dos resultados das fases
anteriores em um único JSON validado: source + music (3I) + tracks
(3J) + selection + statistics + warnings + confidence.

Somente compõe dados — nunca altera pitches, tempos, velocities ou
durações, nunca inventa conteúdo, nunca mascara baixa confiança.
"""

import json
import math
import re

SCHEMA_VERSION = "1.0"

STATUS_READY = "ready"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_AMBIGUOUS = "ambiguous"  # status de faixa (3J), não global
STATUS_SILENT = "silent"  # idem
VALID_STATUSES = (STATUS_READY, STATUS_PARTIAL, STATUS_FAILED)

# Thresholds explícitos e testáveis.
LOW_CONFIDENCE = 0.40  # abaixo disto = warning de baixa confiança
WEIGHT_TRACKS = 0.40
WEIGHT_TEMPO = 0.20
WEIGHT_KEY = 0.20
WEIGHT_METER = 0.20

SOURCE_FIELDS = ("duration_seconds", "sample_rate", "channels",
                 "format")
FORBIDDEN_KEYS = {"token", "api_key", "apikey", "secret", "password",
                  "credential", "credentials", "signed_url",
                  "local_path", "file_path", "audio_path",
                  "source_path", "authorization"}
_SUSPICIOUS_VALUE = re.compile(
    r"(^|[\s'\"])(/(tmp|home|root|etc|var|mnt|data)\b|file://|"
    r"https?://|[A-Za-z]:\\)|signed[_-]?url|Bearer\s", re.IGNORECASE)


def _round3(value):
    return round(float(value), 3)


def _finite_or(value, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _sanitize_source(source):
    """Apenas metadados seguros (allowlist; sem paths/segredos)."""
    source = source if isinstance(source, dict) else {}
    out = {}
    duration = _finite_or(source.get("duration_seconds"), 0.0)
    out["duration_seconds"] = _round3(max(0.0, duration))
    for field in ("sample_rate", "channels"):
        value = source.get(field)
        out[field] = int(value) if isinstance(value, int) and value > 0 \
            else None
    fmt = source.get("format")
    out["format"] = str(fmt)[:32] if isinstance(fmt, str) and fmt \
        else None
    return out


def _compose_music(music):
    """Bloco music da 3I (nulls preservados, sem palpites)."""
    music = music if isinstance(music, dict) else {}
    tempo = music.get("tempo") or {}
    key = music.get("key") or {}
    scale = music.get("scale") or {}
    meter = music.get("meter") or {}
    grid = music.get("grid") or {}
    return {
        "tempo": {"bpm": tempo.get("bpm"),
                  "confidence": tempo.get("confidence")},
        "key": {"tonic": key.get("tonic"), "mode": key.get("mode"),
                "confidence": key.get("confidence")},
        "scale": {"name": scale.get("name"),
                  "notes": list(scale.get("notes") or []),
                  "confidence": scale.get("confidence")},
        "meter": {"numerator": meter.get("numerator"),
                  "denominator": meter.get("denominator"),
                  "confidence": meter.get("confidence")},
        "grid": {"division": grid.get("division"),
                 "beats": grid.get("beats"),
                 "quantization_error": grid.get("quantization_error"),
                 "changed_notes": grid.get("changed_notes")},
        "chords": [dict(c) for c in (music.get("chords") or [])],
        "sections": [dict(s) for s in (music.get("sections") or [])],
    }


def _compose_selection(tracks):
    selected = sorted(t["track_id"] for t in tracks if t["selected"])
    return {
        "selected_track_ids": selected,
        "selected_count": len(selected),
        "available_count": sum(1 for t in tracks
                               if t["status"] == "ready"),
        "ambiguous_count": sum(1 for t in tracks
                               if t["status"] == "ambiguous"),
        "silent_count": sum(1 for t in tracks
                            if t["status"] == "silent"),
    }


def _compose_statistics(tracks, duration_seconds):
    total_notes = sum(t["statistics"]["note_count"] for t in tracks)
    pitches, velocities, durations = [], [], []
    chord_total = 0
    for track in tracks:
        for note in track["notes"]:
            try:
                pitches.append(int(note["pitch"]))
                velocities.append(int(note.get("velocity", 0)))
                durations.append(float(note.get("duration", 0.0)))
            except (TypeError, ValueError, KeyError):
                continue
        musical = track.get("musical_analysis") or {}
        chord_total += len(musical.get("chords") or [])
    families = sorted({t["instrument"]["family"] for t in tracks})
    instruments = sorted({t["instrument"]["name"] for t in tracks
                          if t["instrument"]["name"]})
    density = (total_notes / duration_seconds
               if duration_seconds > 0 else 0.0)
    density = density if math.isfinite(density) else 0.0
    return {
        "track_count": len(tracks),
        "selected_count": sum(1 for t in tracks if t["selected"]),
        "ambiguous_count": sum(1 for t in tracks
                               if t["status"] == "ambiguous"),
        "silent_count": sum(1 for t in tracks
                            if t["status"] == "silent"),
        "total_notes": total_notes,
        "total_chords": chord_total,
        "duration_seconds": _round3(max(0.0, duration_seconds)),
        "pitch_min": min(pitches) if pitches else None,
        "pitch_max": max(pitches) if pitches else None,
        "mean_velocity": (_round3(sum(velocities) / len(velocities))
                          if velocities else None),
        "mean_duration": (_round3(sum(durations) / len(durations))
                          if durations else None),
        "density": _round3(density),
        "family_count": len(families),
        "families": families,
        "instrument_count": len(instruments),
        "instruments": instruments,
    }


def _compose_warnings(tracks, music):
    warnings = []
    for track in tracks:
        tid = track["track_id"]
        if track["status"] == "ambiguous":
            warnings.append({
                "code": "AMBIGUOUS_INSTRUMENT", "track_id": tid,
                "message": "Instrumento não identificado com "
                           "confiança suficiente."})
        if track["status"] == "silent":
            warnings.append({
                "code": "SILENT_TRACK", "track_id": tid,
                "message": "Faixa silenciosa; não selecionada."})
        if not track["notes"]:
            warnings.append({
                "code": "TRACK_WITHOUT_NOTES", "track_id": tid,
                "message": "Faixa sem notas MIDI."})
        if track["instrument"]["name"] is None \
                and track["status"] != "silent":
            warnings.append({
                "code": "UNIDENTIFIED_STEM", "track_id": tid,
                "message": "Stem sem instrumento identificado."})
        conf = track["instrument"]["confidence"]
        if conf is not None and conf < LOW_CONFIDENCE:
            warnings.append({
                "code": "LOW_CLASSIFIER_CONFIDENCE", "track_id": tid,
                "message": "Classificação com baixa confiança."})
    tempo = music.get("tempo") or {}
    if tempo.get("bpm") is None:
        warnings.append({
            "code": "LOW_TEMPO_CONFIDENCE", "track_id": None,
            "message": "BPM ausente ou sem confiança."})
    elif (tempo.get("confidence") or 0.0) < LOW_CONFIDENCE:
        warnings.append({
            "code": "LOW_TEMPO_CONFIDENCE", "track_id": None,
            "message": "BPM com baixa confiança."})
    key = music.get("key") or {}
    if key.get("tonic") is None:
        warnings.append({
            "code": "LOW_KEY_CONFIDENCE", "track_id": None,
            "message": "Tonalidade indeterminada."})
    elif (key.get("confidence") or 0.0) < LOW_CONFIDENCE:
        warnings.append({
            "code": "LOW_KEY_CONFIDENCE", "track_id": None,
            "message": "Tonalidade com baixa confiança."})
    meter = music.get("meter") or {}
    if meter.get("numerator") is None:
        warnings.append({
            "code": "UNKNOWN_METER", "track_id": None,
            "message": "Compasso desconhecido."})
    warnings.sort(key=lambda w: (w["code"], w["track_id"] or ""))
    return warnings


def _compose_confidence(tracks, music):
    """Ponderada documentada (faixas 0.4, tempo/key/meter 0.2).

    Cobertura multiplica a parte das faixas: evidência insuficiente
    reduz a confiança em vez de fabricá-la.
    """
    confs = [t["instrument"]["confidence"] for t in tracks
             if t["instrument"]["confidence"] is not None]
    coverage = len(confs) / len(tracks) if tracks else 0.0
    inst = (sum(confs) / len(confs)) if confs else 0.0
    tempo = (music.get("tempo") or {}).get("confidence") or 0.0
    key = (music.get("key") or {}).get("confidence") or 0.0
    meter = (music.get("meter") or {}).get("confidence") or 0.0
    value = (WEIGHT_TRACKS * inst * coverage + WEIGHT_TEMPO * tempo
             + WEIGHT_KEY * key + WEIGHT_METER * meter)
    return _round3(max(0.0, min(1.0, value)))


def _compose_status(tracks, statistics, music):
    # Utilizável = faixa pronta/ambígua (stem real, mesmo sem nome)
    # ou notas. failed só sem nada aproveitável — nunca apenas por
    # instrumento não identificado.
    usable = (any(t["status"] in (STATUS_READY, STATUS_AMBIGUOUS)
                  for t in tracks)
              or statistics["total_notes"] > 0)
    if not tracks or not usable:
        return STATUS_FAILED
    incomplete = (
        any(t["status"] != "ready" for t in tracks)
        or (music.get("tempo") or {}).get("bpm") is None
        or (music.get("key") or {}).get("tonic") is None
        or (music.get("meter") or {}).get("numerator") is None)
    return STATUS_PARTIAL if incomplete else STATUS_READY


def build_transcription_result(source=None, music=None,
                               tracks_result=None):
    """Função pública: fases anteriores → resultado final único."""
    tracks_result = tracks_result if isinstance(tracks_result,
                                                dict) else {}
    tracks = [dict(t) for t in (tracks_result.get("tracks") or [])]
    tracks.sort(key=lambda t: t.get("track_id", ""))
    clean_source = _sanitize_source(source)
    duration = clean_source["duration_seconds"]
    if duration <= 0:
        spans = []
        for track in tracks:
            stats = track.get("statistics") or {}
            spans.append(_finite_or(stats.get("active_seconds"), 0.0)
                         + _finite_or(stats.get("silence_seconds"),
                                      0.0))
        duration = _round3(max(spans, default=0.0))
        clean_source["duration_seconds"] = duration
    composed_music = _compose_music(music)
    selection = _compose_selection(tracks)
    statistics = _compose_statistics(tracks, duration)
    warnings = _compose_warnings(tracks, composed_music)
    confidence = _compose_confidence(tracks, composed_music)
    status = _compose_status(tracks, statistics, composed_music)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": clean_source,
        "music": composed_music,
        "tracks": tracks,
        "selection": selection,
        "statistics": statistics,
        "warnings": warnings,
        "confidence": confidence,
    }


def _scan_strings(node, errors, path="root"):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_KEYS:
                errors.append("segredo/proibido em %s: %s"
                              % (path, key))
            _scan_strings(value, errors, "%s.%s" % (path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _scan_strings(value, errors, "%s[%d]" % (path, index))
    elif isinstance(node, str):
        if _SUSPICIOUS_VALUE.search(node):
            errors.append("caminho/URL/segredo em %s" % path)
    elif isinstance(node, float):
        if math.isnan(node):
            errors.append("NaN em %s" % path)
        elif math.isinf(node):
            errors.append("Infinity em %s" % path)


def validate_transcription_result(result):
    """Validador: devolve lista de erros (vazia = válido)."""
    errors = []
    if not isinstance(result, dict):
        return ["resultado não é objeto"]
    if result.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version inválido")
    if result.get("status") not in VALID_STATUSES:
        errors.append("status inválido")
    tracks = result.get("tracks")
    if not isinstance(tracks, list):
        errors.append("tracks não é lista")
        tracks = []
    seen_ids = set()
    for track in tracks:
        tid = track.get("track_id") if isinstance(track, dict) else None
        if tid in seen_ids:
            errors.append("track_id duplicado: %s" % tid)
        seen_ids.add(tid)
        notes = track.get("notes", []) if isinstance(track, dict) \
            else []
        for note in notes:
            try:
                pitch = int(note["pitch"])
                velocity = int(note.get("velocity", 0))
                duration = float(note.get("duration", -1.0))
                start = float(note.get("start", -1.0))
            except (TypeError, ValueError, KeyError, AttributeError):
                errors.append("nota malformada em %s" % tid)
                continue
            if not 0 <= pitch <= 127:
                errors.append("pitch inválido em %s" % tid)
            if not 0 <= velocity <= 127:
                errors.append("velocity inválida em %s" % tid)
            if duration <= 0:
                errors.append("duração inválida em %s" % tid)
            if start < 0:
                errors.append("tempo inválido em %s" % tid)
    confidence = result.get("confidence")
    if confidence is not None:
        try:
            if not 0.0 <= float(confidence) <= 1.0:
                errors.append("confidence global inválida")
        except (TypeError, ValueError):
            errors.append("confidence global inválida")
    _scan_strings(result, errors)
    try:
        text = json.dumps(result)
    except (TypeError, ValueError):
        errors.append("não serializável em JSON")
        return errors
    if "NaN" in text or "Infinity" in text:
        errors.append("NaN/Infinity no JSON")
    return errors

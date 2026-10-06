"""Consolidação em faixas instrumentais (FASE 3J).

Recebe os resultados das fases anteriores (3E/3F classificação, 3G
transcrição, 3H processamento, 3I análise) e consolida uma estrutura
determinística de faixas — sem reexecutar modelos, sem rede, sem
banco, sem frontend. Stdlib apenas.

Regras de honestidade:
- SOMENTE instrumentos/classes com evidência (detections do
  classificador); nunca inventa instrumento;
- ambiguidade nunca mascarada (name null + status "ambiguous" +
  top_candidates);
- stems silenciosos → status "silent", sem instrumento inventado;
- drums nunca recebe notas melódicas nem tonalidade/escala/acordes;
- nenhum NaN/Infinity; tudo JSON-serializável.
"""

import math

from audio import catalog as catalog_module

# Thresholds explícitos e testáveis.
PRIMARY_CONFIDENCE_THRESHOLD = 0.50  # principal só acima disto
AMBIGUITY_MARGIN = 0.15  # top2 dentro disto = ambíguo
TOP_CANDIDATES_LIMIT = 3  # candidatos guardados por faixa

KNOWN_STEMS = ("vocals", "drums", "bass", "other")

CANONICAL_FAMILIES = [
    "woodwinds",
    "free_reed",
    "brass",
    "pitched_percussion",
    "unpitched_percussion",
    "body_percussion",
    "voices",
    "keyboards",
    "plucked_strings",
    "bowed_strings",
    "unknown",
]

# Ordem determinística de faixas (§12: famílias + "bass" = faixa do
# stem de baixo, que usa este rank em vez do da família).
FAMILY_ORDER = [
    "voices",
    "keyboards",
    "bowed_strings",
    "plucked_strings",
    "brass",
    "woodwinds",
    "free_reed",
    "bass",
    "pitched_percussion",
    "unpitched_percussion",
    "body_percussion",
    "unknown",
]

STATUS_READY = "ready"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_SILENT = "silent"


def _round3(value):
    return round(float(value), 3)


def _finite_or(value, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return number


def normalize_instrument(source_label):
    """ID do catálogo → nome canônico (hífens viram underscores).

    Retorna None para rótulos fora do catálogo (nunca inventa).
    """
    if not isinstance(source_label, str) or not source_label:
        return None
    canonical = source_label.strip().lower().replace("-", "_")
    original = source_label.strip().lower()
    if catalog_module.get(original) is None:
        return None
    return canonical


def normalize_family(family):
    """Família canônica ou "unknown" (sem forçar classificação)."""
    if family in CANONICAL_FAMILIES:
        return family
    return "unknown"


def _family_rank(track):
    family = track.get("instrument", {}).get("family", "unknown")
    if track.get("source_stem") == "bass" and family == "plucked_strings":
        family = "bass"
    try:
        return FAMILY_ORDER.index(family)
    except ValueError:
        return FAMILY_ORDER.index("unknown")


def _collect_candidates(detections, ambiguous):
    """Candidatos únicos ordenados (instrumento canônico, confiança)."""
    seen = {}
    for det in detections or []:
        label = det.get("instrument_id")
        canonical = normalize_instrument(label)
        if canonical is None:
            continue
        conf = _finite_or(det.get("confidence"), 0.0)
        conf = max(0.0, min(1.0, conf))
        if canonical not in seen or conf > seen[canonical][0]:
            seen[canonical] = (conf, label)
    for group in ambiguous or []:
        for cand in group.get("candidates") or []:
            label = cand.get("instrument_id")
            canonical = normalize_instrument(label)
            if canonical is None:
                continue
            conf = _finite_or(cand.get("confidence"), 0.0)
            conf = max(0.0, min(1.0, conf))
            if canonical not in seen or conf > seen[canonical][0]:
                seen[canonical] = (conf, label)
    ordered = sorted(seen.items(),
                     key=lambda item: (-item[1][0], item[0]))
    return [{"instrument": name, "confidence": _round3(conf),
             "source_label": label}
            for name, (conf, label) in
            ordered[:TOP_CANDIDATES_LIMIT]]


def _choose_primary(candidates):
    """Principal só com threshold + margem; senão (None, True)."""
    if not candidates:
        return None, True
    top = candidates[0]
    if top["confidence"] < PRIMARY_CONFIDENCE_THRESHOLD:
        return None, True
    for other in candidates[1:]:
        if top["confidence"] - other["confidence"] < AMBIGUITY_MARGIN:
            return None, True
    return top, False


def _instrument_block(primary, candidates, stem):
    """Bloco instrument (+ top_candidates, sem invenção)."""
    if primary is None:
        return {"name": None, "display_name": None, "family": "unknown",
                "confidence": None, "source_label": None,
                "top_candidates": [
                    {"instrument": c["instrument"],
                     "confidence": c["confidence"]}
                    for c in candidates]}, True
    entry = catalog_module.get(primary["source_label"])
    family = normalize_family(
        entry.get("family") if entry else "unknown")
    display = entry.get("name_pt") if entry else primary["instrument"]
    return {"name": primary["instrument"], "display_name": display,
            "family": family, "confidence": primary["confidence"],
            "source_label": primary["source_label"],
            "top_candidates": [
                {"instrument": c["instrument"],
                 "confidence": c["confidence"]}
                for c in candidates]}, False


def _note_statistics(notes, duration_seconds):
    """Estatísticas por faixa (sem NaN/Infinity)."""
    clean = []
    for n in notes or []:
        try:
            pitch = int(n["pitch"])
            velocity = int(n.get("velocity", 0))
            duration = float(n.get("duration", 0.0))
            end = float(n.get("end", float(n.get("start", 0.0))
                              + duration))
        except (TypeError, ValueError, KeyError):
            continue
        if not 0 <= pitch <= 127 or duration < 0:
            continue
        clean.append((pitch, velocity, duration, end))
    total = _finite_or(duration_seconds, 0.0)
    total = max(0.0, total)
    active = 0.0
    if clean:
        active = max(0.0, max(e for _, _, _, e in clean))
    active = min(active, total) if total > 0 else active
    silence = max(0.0, total - active)
    if not clean:
        return {"note_count": 0, "pitch_min": None, "pitch_max": None,
                "mean_velocity": None, "mean_duration": None,
                "density": 0.0, "active_seconds": _round3(active),
                "silence_seconds": _round3(silence)}
    pitches = [p for p, _, _, _ in clean]
    velocities = [v for _, v, _, _ in clean]
    durations = [d for _, _, d, _ in clean]
    density = len(clean) / active if active > 0 else 0.0
    density = density if math.isfinite(density) else 0.0
    return {"note_count": len(clean),
            "pitch_min": min(pitches), "pitch_max": max(pitches),
            "mean_velocity": _round3(sum(velocities) / len(velocities)),
            "mean_duration": _round3(sum(durations) / len(durations)),
            "density": _round3(density),
            "active_seconds": _round3(active),
            "silence_seconds": _round3(silence)}


def _track_analysis(analysis, stem):
    """Recorte aplicável da FASE 3I (drums: sem tom/escala/acordes)."""
    if not isinstance(analysis, dict):
        return None
    tempo = analysis.get("tempo") or {}
    meter = analysis.get("meter") or {}
    out = {"bpm": tempo.get("bpm"),
           "tempo_confidence": tempo.get("confidence"),
           "meter": {"numerator": meter.get("numerator"),
                     "denominator": meter.get("denominator"),
                     "confidence": meter.get("confidence")},
           "sections": analysis.get("sections") or []}
    if stem == "drums":
        return out
    key = analysis.get("key") or {}
    scale = analysis.get("scale") or {}
    out["key"] = {"tonic": key.get("tonic"), "mode": key.get("mode"),
                  "confidence": key.get("confidence")}
    out["scale"] = {"name": scale.get("name"),
                    "notes": scale.get("notes") or [],
                    "confidence": scale.get("confidence")}
    out["chords"] = analysis.get("chords") or []
    return out


def build_track(stem, detections=(), ambiguous=(), notes=(),
                analysis=None, silent=False, duration_seconds=0.0,
                warnings=()):
    """Uma faixa a partir das evidências do seu stem."""
    if stem not in KNOWN_STEMS:
        raise ValueError("Stem desconhecido: " + str(stem))
    track_warnings = [str(w) for w in (warnings or [])]
    if stem == "drums":
        track_notes = []
        if notes:
            track_warnings.append(
                "drums: notas melódicas ignoradas (percussão)")
    else:
        track_notes = [dict(n) for n in (notes or [])]
    candidates = _collect_candidates(detections, ambiguous)
    if silent:
        instrument = {"name": None, "display_name": None,
                      "family": "unknown", "confidence": None,
                      "source_label": None,
                      "top_candidates": [
                          {"instrument": c["instrument"],
                           "confidence": c["confidence"]}
                          for c in candidates]}
        is_ambiguous = False
        status = STATUS_SILENT
        selected = False
    else:
        primary, is_ambiguous = _choose_primary(candidates)
        instrument, _ = _instrument_block(primary, candidates, stem)
        if is_ambiguous:
            status = STATUS_AMBIGUOUS
            selected = False
            if not candidates:
                track_warnings.append(
                    "sem evidência de instrumento para %s" % stem)
        else:
            status = STATUS_READY
            selected = True
    det_list = [det for det in (detections or [])
                if isinstance(det, dict)]
    methods = {det.get("detection_method") for det in det_list
               if det.get("detection_method")}
    evidence = {
        "classifier": (det_list[0].get("detection_method")
                       if det_list and det_list[0].get(
                           "detection_method") else "unavailable"),
        "classifier_methods": sorted(methods),
        "direct_detection": bool(any(
            det.get("direct_detection") for det in det_list)),
        "stem_type": stem,
        "warnings": track_warnings,
    }
    statistics = _note_statistics(track_notes, duration_seconds)
    return {
        "track_id": "track_%s" % stem,
        "source_stem": stem,
        "instrument": instrument,
        "evidence": evidence,
        "notes": track_notes,
        "statistics": statistics,
        "musical_analysis": _track_analysis(analysis, stem),
        "selected": selected,
        "editable": instrument["name"] is not None,
        "status": status,
    }


def build_tracks(stems):
    """Função pública: {stem: {...}} → consolidação determinística."""
    if not isinstance(stems, dict) or not stems:
        raise ValueError("Stems inválidos.")
    for name in stems:
        if name not in KNOWN_STEMS:
            raise ValueError("Stem desconhecido: " + str(name))
    built = []
    for stem in sorted(stems):
        payload = stems[stem] or {}
        built.append(build_track(
            stem,
            detections=payload.get("detections", ()),
            ambiguous=payload.get("ambiguous", ()),
            notes=payload.get("notes", ()),
            analysis=payload.get("analysis"),
            silent=bool(payload.get("silent", False)),
            duration_seconds=payload.get("duration_seconds", 0.0),
            warnings=payload.get("warnings", ())))
    built.sort(key=lambda t: (
        _family_rank(t),
        -(t["instrument"]["confidence"] or 0.0),
        t["source_stem"]))
    for index, track in enumerate(built, start=1):
        track["track_id"] = "track_%02d" % index
    families = sorted({t["instrument"]["family"] for t in built})
    instruments = sorted({t["instrument"]["name"] for t in built
                          if t["instrument"]["name"]})
    confs = [t["instrument"]["confidence"] for t in built
             if t["instrument"]["confidence"] is not None]
    global_warnings = []
    for track in built:
        for warning in track["evidence"]["warnings"]:
            global_warnings.append("%s: %s" % (
                track["source_stem"], warning))
    return {
        "tracks": built,
        "track_count": len(built),
        "selected_count": sum(1 for t in built if t["selected"]),
        "instrument_count": len(instruments),
        "families": families,
        "confidence": (_round3(sum(confs) / len(confs))
                       if confs else 0.0),
        "warnings": global_warnings,
    }

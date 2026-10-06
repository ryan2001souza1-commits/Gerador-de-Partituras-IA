"""Análise de stems → hipóteses de instrumentos (FASE 3E/3F).

Regra de honestidade: sem classificador neural, NENHUM instrumento
específico é afirmado. Stems recebem hipóteses de presença (família /
papel) com evidências medidas e confiança limitada; o stem `other`
nunca gera hipótese sem modelo. Com modelo neural (PANNs), classes
verificadas geram detecções diretas; resto vira `unmapped_class`.
Limites centralizados abaixo.
"""

from pathlib import Path

from audio import evidence
from audio.catalog import get as catalog_get
from audio.classifiers import get_classifier, model_versions
from audio.panns_classifier import (AMBIGUITY_MARGIN, MIN_ACTIVE_RATIO,
                                    MIN_ACTIVE_WINDOWS, MIN_CONFIDENCE)
from audio.panns_mapping import LABEL_MAP

HIGH_MIN = 0.80
MEDIUM_MIN = 0.60
LOW_MIN = 0.40
HEURISTIC_CAP = 0.79
MIN_ACTIVITY = 0.05

KNOWN_STEMS = ("vocals", "drums", "bass", "other")


def confidence_level(value):
    if value >= HIGH_MIN:
        return "high"
    if value >= MEDIUM_MIN:
        return "medium"
    if value >= LOW_MIN:
        return "low"
    return "very-low"


def _confidence(score):
    score = max(0.0, min(1.0, score))
    return round(min(HEURISTIC_CAP, 0.30 + 0.60 * score), 2)


def _evidence_items(ev, *metrics):
    return [{"metric": m, "value": ev.get(m)} for m in metrics
            if m in ev]


def _voice_hypothesis(ev):
    if ev.get("activity", 0.0) < MIN_ACTIVITY:
        return None, "stem silencioso ou vazio"
    if ev.get("harmonicity", 0.0) < 0.30:
        return None, "sem harmonicidade vocal suficiente"
    centroid = ev.get("spectral_centroid_hz", 0.0) or 0.0
    band_ok = 1.0 if 200.0 <= centroid <= 4000.0 else max(
        0.0, 1.0 - abs(centroid - 1500.0) / 4000.0)
    zcr = ev.get("zcr", 0.0) or 0.0
    zcr_ok = 1.0 if 0.01 <= zcr <= 0.30 else 0.3
    f0 = ev.get("pitch_estimate_hz")
    f0_ok = 1.0 if isinstance(f0, (int, float)) and 75.0 <= f0 <= 1200.0 else 0.4
    score = (ev.get("activity", 0.0) + ev.get("harmonicity", 0.0)
             + band_ok + zcr_ok + f0_ok) / 5.0
    conf = _confidence(score)
    if conf < LOW_MIN:
        return None, "evidência vocal fraca"
    return {
        "instrument_id": "lead-vocal",
        "confidence": conf,
        "confidence_level": confidence_level(conf),
        "stem": "vocals",
        "detection_method": "heuristic-spectral-v1",
        "direct_detection": False,
        "evidence": _evidence_items(
            ev, "activity", "harmonicity", "pitch_estimate_hz",
            "spectral_centroid_hz", "zcr", "spectral_rolloff_hz"),
    }, ""


def _drums_hypothesis(ev):
    if ev.get("activity", 0.0) < MIN_ACTIVITY:
        return None, "stem silencioso ou vazio"
    rate = ev.get("transient_rate", 0.0) or 0.0
    if rate < 0.5:
        return None, "sem atividade percussiva suficiente"
    trans = min(1.0, rate / 8.0)
    crest = min(1.0, max(0.0, (ev.get("crest_db", 0.0) - 6.0) / 18.0))
    unharmonic = 1.0 - min(1.0, ev.get("harmonicity", 0.0))
    score = 0.40 * trans + 0.30 * crest + 0.30 * unharmonic
    conf = _confidence(score)
    if conf < LOW_MIN:
        return None, "evidência percussiva fraca"
    return {
        "instrument_id": "drum-kit",
        "confidence": conf,
        "confidence_level": confidence_level(conf),
        "stem": "drums",
        "detection_method": "heuristic-spectral-v1",
        "direct_detection": False,
        "evidence": _evidence_items(
            ev, "activity", "transient_rate", "crest_db",
            "harmonicity", "band_low"),
    }, ""


def _bass_hypothesis(ev):
    if ev.get("activity", 0.0) < MIN_ACTIVITY:
        return None, "stem silencioso ou vazio"
    sub = ev.get("band_sub", 0.0) or 0.0
    f0 = ev.get("pitch_estimate_hz")
    f0_ok = isinstance(f0, (int, float)) and 30.0 <= f0 <= 250.0
    if sub < 0.25 or not f0_ok:
        return None, "sem fundamental de graves suficiente"
    sub_norm = min(1.0, sub / 0.60)
    score = (0.50 * sub_norm + 0.30 * min(1.0, ev.get("harmonicity", 0.0))
             + 0.20 * min(1.0, ev.get("activity", 0.0)))
    conf = _confidence(score)
    if conf < LOW_MIN:
        return None, "evidência de baixo fraca"
    return {
        "instrument_id": "electric-bass",
        "confidence": conf,
        "confidence_level": confidence_level(conf),
        "stem": "bass",
        "detection_method": "heuristic-spectral-v1",
        "direct_detection": False,
        "evidence": _evidence_items(
            ev, "activity", "band_sub", "pitch_estimate_hz",
            "spectral_centroid_hz", "harmonicity"),
    }, ""


_ANALYZERS = {
    "vocals": ("lead-vocal", _voice_hypothesis),
    "drums": ("drum-kit", _drums_hypothesis),
    "bass": ("electric-bass", _bass_hypothesis),
}


def _passing_candidates(probs):
    """Candidatos que passam na agregação: [(label, stats)]."""
    out = []
    for label, stats in probs.items():
        mean = stats.get("mean", 0.0)
        # Saída inválida do modelo (fora de [0,1]) é descartada.
        if not isinstance(mean, (int, float)) or not 0.0 <= mean <= 1.0:
            continue
        n = stats.get("n_windows", 0)
        if n <= 0:
            continue
        need = min(MIN_ACTIVE_WINDOWS, n)
        if stats.get("mean", 0.0) < MIN_CONFIDENCE:
            continue
        if stats.get("active_windows", 0) < need:
            continue
        if stats.get("active_windows", 0) / n < MIN_ACTIVE_RATIO:
            continue
        out.append((label, stats))
    out.sort(key=lambda item: item[1].get("mean", 0.0), reverse=True)
    return out


def _neural_for_stem(probs, stem):
    """Converte probabilidades em detecções/ambíguo/não-mapeados."""
    detections, ambiguous, unmapped = [], [], []
    passing = _passing_candidates(probs)
    if not passing:
        return detections, ambiguous, unmapped
    expanded = []
    for label, stats in passing:
        targets = LABEL_MAP.get(label)
        if targets is None:
            unmapped.append({"label": label, "mean": stats.get("mean")})
            continue
        for inst_id in targets:
            expanded.append((inst_id, label, stats))
    if not expanded:
        return detections, ambiguous, unmapped
    close = [e for e in expanded
             if expanded[0][2].get("mean", 0.0) - e[2].get("mean", 0.0)
             <= AMBIGUITY_MARGIN]
    if len(close) >= 2:
        ambiguous.append({
            "ambiguous": True,
            "stem": stem,
            "candidates": [
                {"instrument_id": inst_id,
                 "confidence": round(stats.get("mean", 0.0), 2)}
                for inst_id, _label, stats in close],
        })
        claimed = {c[0] for c in close}
    else:
        claimed = set()
    for inst_id, label, stats in expanded:
        if inst_id in claimed:
            continue
        inst = catalog_get(inst_id)
        conf = round(stats.get("mean", 0.0), 2)
        detections.append({
            "instrument_id": inst_id,
            "instrument_name": inst["name_pt"] if inst else inst_id,
            "family": inst["family"] if inst else "unknown",
            "confidence": conf,
            "confidence_level": confidence_level(conf),
            "stem": stem,
            "detection_method": "panns-cnn14",
            "direct_detection": True,
            "evidence": [
                {"type": "model_probability",
                 "value": stats.get("mean")},
                {"type": "model_max", "value": stats.get("max")},
                {"type": "active_windows",
                 "value": "%d/%d" % (stats.get("active_windows", 0),
                                     stats.get("n_windows", 0))},
                {"type": "model_label", "value": label},
            ],
        })
    return detections, ambiguous, unmapped


def analyze_stems(stems, metadata=None, classifier="panns"):
    """Analisa stems {nome: caminho} → dict JSON-serializável.

    Camadas: evidência espectral + hipóteses heurísticas (sempre) e,
    se o classificador neural estiver disponível, detecções diretas.
    Sem modelo: fallback gracioso só-heurístico com aviso.
    Levanta ValueError para nomes de stem desconhecidos.
    """
    if not isinstance(stems, dict) or not stems:
        raise ValueError("Stems inválidos.")
    for name in stems:
        if name not in KNOWN_STEMS:
            raise ValueError("Stem desconhecido: " + str(name))
    metadata = metadata if isinstance(metadata, dict) else {}
    neural = None
    neural_name = "unavailable"
    if classifier != "unavailable":
        try:
            clf = get_classifier(classifier)
            if hasattr(clf, "load"):
                clf.load()
            neural = clf
            neural_name = getattr(clf, "name", classifier)
        except Exception:
            neural = None
    detections, warnings, stems_info, ambiguous = [], [], [], []
    sample_rate, channels, duration = None, None, 0.0
    if neural is None and classifier != "unavailable":
        warnings.append("classificador neural indisponível: somente heurística")
    for name, raw_path in stems.items():
        path = Path(raw_path)
        ev = evidence.measure(path)
        if not ev.get("ok"):
            warnings.append("stem %s ilegível ou inválido" % name)
            continue
        if sample_rate is None:
            sample_rate = ev.get("sample_rate")
            channels = ev.get("channels")
        duration = max(duration, ev.get("duration_seconds", 0.0) or 0.0)
        entry = {"name": name, "duration_seconds": ev.get("duration_seconds"),
                 "unmapped_classes": []}
        stems_info.append(entry)
        if neural is not None:
            try:
                probs = neural.classify_stem(str(path), name)
                det, amb, unm = _neural_for_stem(probs or {}, name)
                detections.extend(det)
                ambiguous.extend(amb)
                entry["unmapped_classes"] = unm
            except Exception:
                warnings.append("stem %s: falha na classificação neural" % name)
        if name == "other" and neural is None:
            warnings.append(
                "stem other sem classificador neural: instrumento "
                "específico indeterminado (Demucs separa fontes, não "
                "instrumentos)")
            continue
        if name == "other":
            continue
        _, analyzer = _ANALYZERS[name]
        hypo, reason = analyzer(ev)
        if hypo is None:
            if reason:
                warnings.append("stem %s: %s" % (name, reason))
            continue
        inst = catalog_get(hypo["instrument_id"])
        hypo["instrument_name"] = inst["name_pt"] if inst else hypo["instrument_id"]
        hypo["family"] = inst["family"] if inst else "unknown"
        detections.append(hypo)
    detections.sort(key=lambda d: d.get("confidence", 0.0), reverse=True)
    declared = metadata.get("duration_seconds")
    if isinstance(declared, (int, float)) and declared > 0:
        duration = declared
    return {
        "duration_seconds": round(float(duration), 3),
        "sample_rate": sample_rate,
        "channels": channels,
        "stems": stems_info,
        "detections": detections,
        "ambiguous": ambiguous,
        "warnings": warnings,
        "model_versions": model_versions(
            neural_name if neural is not None else "unavailable"),
    }

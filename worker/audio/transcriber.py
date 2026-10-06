"""Transcrição musical → MIDI (FASE 3G).

Adapter sobre Spotify Basic Pitch (TFLite, CPU): WAV → notas
polifônicas → MIDI real. Saída normalizada independente da
biblioteca (TranscribedNote/TranscriptionResult como dicts puros).

Regras de honestidade:
- sem modelo: falha explícita (TranscriptionUnavailable), nunca MIDI
  falso ou notas inventadas;
- confidence só quando o modelo fornece amplitude; senão None;
- BPM sempre "unknown" (Basic Pitch não fornece; sem invenção);
- drums: sem transcrição melódica (etapa percussiva futura);
- timing original preservado (quantização só via quantize_notes(),
  nunca automática).
"""

import os
import tempfile
import wave
from pathlib import Path

MODEL_NAME = "basic-pitch-icassp2022"
MODEL_VERSION = "0.4.0-icassp2022-tflite"
FRAMEWORK = "tflite-runtime (CPU)"
MODEL_LICENSE = "Apache-2.0 (Spotify basic-pitch)"
MODEL_SR = 22050
MIN_DURATION_S = 0.5

# Política por stem (sem assumir mesmo processo p/ todos).
STEM_POLICY = {
    "vocals": "melodic",
    "bass": "melodic",
    "other": "polyphonic",
    "drums": "percussive-future",
}

KNOWN_STEMS = ("vocals", "drums", "bass", "other")


class TranscriptionUnavailable(Exception):
    """Modelo ausente/corrompido ou áudio inadequado."""


def _default_model_path():
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        return str(ICASSP_2022_MODEL_PATH)
    except Exception:
        return ""


def _wav_info(path):
    """(sample_rate, channels, duration_s) ou levanta."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            n = w.getnframes()
            width = w.getsampwidth()
    except (OSError, wave.Error, EOFError) as exc:
        raise TranscriptionUnavailable(
            "WAV inválido: %s" % type(exc).__name__)
    if rate <= 0 or channels <= 0 or width not in (1, 2, 4):
        raise TranscriptionUnavailable("WAV inválido.")
    if n <= 0:
        raise TranscriptionUnavailable("áudio vazio.")
    duration = n / float(rate)
    if duration < MIN_DURATION_S:
        raise TranscriptionUnavailable("áudio muito curto.")
    return rate, channels, round(duration, 3)


def _events_to_notes(note_events, midi_notes):
    """Converte saída do modelo em notas normalizadas.

    pitch/start/end/velocity vêm do MIDI do modelo; confidence da
    amplitude do note_event (None quando ausente). Fora de 0–127 é
    rejeitado, não corrigido.
    """
    notes = []
    confidences = []
    for ev in note_events or []:
        try:
            amp = float(ev[3])
            confidences.append(round(max(0.0, min(1.0, amp)), 4))
        except (IndexError, TypeError, ValueError):
            confidences.append(None)
    for i, n in enumerate(midi_notes or []):
        try:
            pitch = int(n.pitch)
            start = round(float(n.start), 3)
            end = round(float(n.end), 3)
            velocity = int(n.velocity)
        except (TypeError, ValueError):
            continue
        if not 0 <= pitch <= 127:
            continue
        if not 0 <= velocity <= 127:
            continue
        if not (end > start and start >= 0.0):
            continue
        conf = confidences[i] if i < len(confidences) else None
        notes.append({
            "pitch": pitch,
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "velocity": velocity,
            "confidence": conf,
        })
    return notes


def _dedupe(notes):
    """Remove duplicações comprovadas (mesmo pitch+início+fim)."""
    seen = set()
    unique, removed = [], 0
    for n in notes:
        key = (n["pitch"], n["start"], n["end"])
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        unique.append(n)
    return unique, removed


def quantize_notes(notes, grid_s=0.125):
    """Etapa opcional: retorna cópia com tempos quantizados.

    Nunca aplicada automaticamente; o timing original é preservado
    no resultado da transcrição.
    """
    out = []
    for n in notes:
        q = dict(n)
        q["start"] = round(round(n["start"] / grid_s) * grid_s, 3)
        q["end"] = max(q["start"] + 0.01,
                       round(round(n["end"] / grid_s) * grid_s, 3))
        q["end"] = round(q["end"], 3)
        q["duration"] = round(q["end"] - q["start"], 3)
        out.append(q)
    return out


class MusicTranscriber:
    """Adapter com lazy-load e cache único em memória."""

    name = "basic-pitch"
    version = MODEL_VERSION

    def __init__(self, model_path=None):
        self.model_path = model_path or _default_model_path()
        self._model = None
        self.load_seconds = None

    def is_available(self):
        if self._model is not None:
            return True
        try:
            import basic_pitch  # noqa: F401
        except ImportError:
            return False
        return bool(self.model_path) and os.path.isfile(self.model_path)

    def load(self):
        """Carrega o modelo (uma vez). Falha limpa se indisponível."""
        if self._model is not None:
            return self._model
        try:
            from basic_pitch.inference import Model
        except ImportError as exc:
            raise TranscriptionUnavailable(
                "basic-pitch ausente: %s" % type(exc).__name__)
        if not self.model_path or not os.path.isfile(self.model_path):
            raise TranscriptionUnavailable("modelo ausente")
        import time
        t0 = time.time()
        try:
            self._model = Model(self.model_path)
        except Exception as exc:
            raise TranscriptionUnavailable(
                "modelo corrompido/incompatível: %s" % type(exc).__name__)
        self.load_seconds = round(time.time() - t0, 2)
        return self._model

    def transcribe(self, audio_path, output_midi_path=None,
                   instrument=None):
        """Transcreve WAV → resultado normalizado + MIDI real."""
        import time
        rate, _channels, duration = _wav_info(Path(audio_path))
        model = self.load()
        from basic_pitch.inference import predict
        t0 = time.time()
        try:
            _out, midi_data, note_events = predict(
                str(audio_path), model)
        except Exception as exc:
            raise TranscriptionUnavailable(
                "falha na inferência: %s" % type(exc).__name__)
        infer_s = round(time.time() - t0, 2)
        midi_notes = []
        for inst in getattr(midi_data, "instruments", []):
            midi_notes.extend(list(getattr(inst, "notes", [])))
        notes = _events_to_notes(note_events, midi_notes)
        notes, removed = _dedupe(notes)
        warnings = []
        if removed:
            warnings.append("removidas %d notas duplicadas" % removed)
        if not notes:
            warnings.append("nenhuma nota detectada")
        if output_midi_path:
            midi_path = str(output_midi_path)
        else:
            tmp = tempfile.NamedTemporaryFile(
                prefix="gpi-midi-", suffix=".mid", delete=False)
            tmp.close()
            midi_path = tmp.name
        try:
            midi_data.write(midi_path)
        except Exception as exc:
            raise TranscriptionUnavailable(
                "saída MIDI ausente: %s" % type(exc).__name__)
        try:
            with open(midi_path, "rb") as fh:
                header = fh.read(4)
                fh.seek(0, 2)
                size = fh.tell()
        except OSError:
            raise TranscriptionUnavailable("saída MIDI ausente")
        if header != b"MThd":
            raise TranscriptionUnavailable("MIDI inválido")
        notes.sort(key=lambda n: (n["start"], n["pitch"]))
        return {
            "sample_rate": rate,
            "duration_seconds": duration,
            "notes": notes,
            "midi_path": midi_path,
            "midi_bytes": size,
            "model": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "inference_seconds": infer_s,
            "warnings": warnings,
            "metadata": {
                "instrument_id": instrument,
                "bpm": "unknown",
            },
        }

    def transcribe_stem(self, audio_path, stem=None, instrument=None):
        """Transcreve um stem respeitando a política por stem.

        drums: sem notas melódicas (percussão = etapa futura), sem
        MIDI falso — retorna vazio com aviso explícito.
        """
        if stem is not None and stem not in KNOWN_STEMS:
            raise TranscriptionUnavailable(
                "Stem desconhecido: " + str(stem))
        if stem == "drums":
            rate, _ch, duration = _wav_info(Path(audio_path))
            return {
                "sample_rate": rate,
                "duration_seconds": duration,
                "notes": [],
                "midi_path": None,
                "midi_bytes": 0,
                "model": MODEL_NAME,
                "model_version": MODEL_VERSION,
                "inference_seconds": 0.0,
                "warnings": ["drums: percussão tratada em etapa "
                             "futura (sem notas melódicas)"],
                "metadata": {
                    "stem": stem,
                    "instrument_id": instrument,
                    "bpm": "unknown",
                },
            }
        result = self.transcribe(audio_path, instrument=instrument)
        result["metadata"]["stem"] = stem
        return result

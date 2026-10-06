"""Classificador PANNs CNN14 (FASE 3F).

Pipeline: WAV → mono 32 kHz → janelas de 10s → CNN14 (CPU) →
probabilidades por janela → agregação temporal → classes finais.
Pesos oficiais (Zenodo record 3987831). Sem GPU obrigatória.
"""

import os
import wave
from pathlib import Path

MODEL_NAME = "Cnn14_mAP=0.431"
MODEL_URL = ("https://zenodo.org/record/3987831/files/"
             "Cnn14_mAP%3D0.431.pth?download=1")
MODEL_SHA256_16 = "0dc499e40e9761ef"
MODEL_SIZE_BYTES = 327428481
MODEL_SAMPLE_RATE = 32000
WINDOW_SECONDS = 10.0
# Guarda anti-download: panns_inference faz wget automático quando o
# checkpoint tem <3e8 bytes. Barrar antes para falha limpa e rápida.
MIN_CHECKPOINT_BYTES = 300000000

# Agregação temporal (configuração central, sem valores escondidos).
MIN_CONFIDENCE = 0.35
MIN_ACTIVE_WINDOWS = 2
MIN_ACTIVE_RATIO = 0.30
AMBIGUITY_MARGIN = 0.08


def default_checkpoint():
    home = os.path.expanduser("~")
    return os.path.join(home, ".cache", "gpi-models", "panns",
                        "Cnn14_mAP0.431.pth")


class PannsUnavailable(Exception):
    """Modelo ausente/corrompido/dependência faltando."""


class PannsClassifier:
    """Adapter com lazy-load e cache único em memória."""

    name = "panns-cnn14"
    version = "Cnn14_mAP=0.431"

    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint or default_checkpoint()
        self._model = None

    def is_available(self):
        if self._model is not None:
            return True
        try:
            return (os.path.isfile(self.checkpoint)
                    and os.path.getsize(self.checkpoint)
                    >= MIN_CHECKPOINT_BYTES)
        except OSError:
            return False

    def load(self):
        """Carrega o modelo (uma vez). Falha limpa se ausente/corrompido."""
        if self._model is not None:
            return self._model
        if not os.path.isfile(self.checkpoint):
            raise PannsUnavailable("checkpoint ausente")
        try:
            if os.path.getsize(self.checkpoint) < MIN_CHECKPOINT_BYTES:
                raise PannsUnavailable("checkpoint inválido/incompleto")
        except OSError:
            raise PannsUnavailable("checkpoint inacessível")
        try:
            from panns_inference import AudioTagging
            model = AudioTagging(checkpoint_path=self.checkpoint,
                                 device="cpu")
        except PannsUnavailable:
            raise
        except Exception as exc:
            raise PannsUnavailable("falha ao carregar: %s"
                                   % type(exc).__name__)
        self._model = model
        return model

    def _read_mono_32k(self, path):
        import numpy as np
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            width = w.getsampwidth()
            n = w.getnframes()
            if rate <= 0 or n <= 0 or channels <= 0:
                raise PannsUnavailable("áudio inválido")
            raw = w.readframes(n)
        if width == 2:
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
        elif width == 4:
            data = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
        elif width == 1:
            data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
        else:
            raise PannsUnavailable("sample width sem suporte")
        data = data.reshape(-1, channels).mean(axis=1)
        if rate != MODEL_SAMPLE_RATE:
            import torch
            import torchaudio
            tensor = torch.from_numpy(data.astype("float32")).unsqueeze(0)
            data = torchaudio.functional.resample(
                tensor, rate, MODEL_SAMPLE_RATE).squeeze(0).numpy().astype(np.float64)
        if data.size == 0:
            raise PannsUnavailable("áudio vazio")
        return data

    def _windows(self, data):
        import numpy as np
        size = int(MODEL_SAMPLE_RATE * WINDOW_SECONDS)
        if data.shape[0] < int(MODEL_SAMPLE_RATE * 0.5):
            raise PannsUnavailable("áudio muito curto")
        chunks = [data[i:i + size]
                  for i in range(0, data.shape[0], size)]
        out = []
        for c in chunks:
            if c.shape[0] < size:
                pad = np.zeros(size - c.shape[0])
                c = np.concatenate([c, pad])
            out.append(c)
        return out

    def classify(self, audio_path):
        """Retorna {label: {mean, max, active_windows, n_windows}}."""
        import numpy as np
        from panns_inference import labels as pann_labels
        model = self.load()
        data = self._read_mono_32k(Path(audio_path))
        chunks = self._windows(data)
        per_label = {}
        for chunk in chunks:
            clip, _ = model.inference(chunk[None, :].astype("float32"))
            probs = np.asarray(clip[0], dtype=np.float64)
            for i, label in enumerate(pann_labels):
                entry = per_label.setdefault(
                    label, {"scores": [], "n": len(chunks)})
                entry["scores"].append(float(probs[i]))
        result = {}
        for label, entry in per_label.items():
            scores = entry["scores"]
            active = sum(1 for s in scores if s >= MIN_CONFIDENCE)
            result[label] = {
                "mean": round(sum(scores) / len(scores), 4),
                "max": round(max(scores), 4),
                "active_windows": active,
                "n_windows": len(scores),
            }
        return result

    def classify_stem(self, audio_path, stem_name):
        """Classifica um stem (mesmo pipeline; stem só rotula a saída)."""
        return self.classify(audio_path)

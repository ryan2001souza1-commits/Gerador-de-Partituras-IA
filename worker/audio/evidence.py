"""Evidências espectrais reais via NumPy (sem modelos neurais).

Mede energia, bandas de frequência, harmonicidade, transientes e
silêncio diretamente do áudio. Sem classificação neural: estes são
FATOS medidos, não palpites.
"""

import struct
import wave
from pathlib import Path

import numpy as np


def read_mono(path: Path, max_seconds: float = 600.0):
    """Lê WAV (PCM16/float32) → (mono float64, sample_rate)."""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        n = w.getnframes()
        if rate <= 0 or n <= 0:
            raise ValueError("Áudio inválido.")
        max_frames = int(rate * max_seconds)
        if n > max_frames:
            n = max_frames
        raw = w.readframes(n)
    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    else:
        raise ValueError("Áudio inválido.")
    data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _frames(signal, size=2048, hop=1024):
    if len(signal) < size:
        pad = np.zeros(size - len(signal))
        return np.array([np.concatenate([signal, pad])])
    idx = range(0, len(signal) - size + 1, hop)
    return np.array([signal[i:i + size] for i in idx])


def measure(path: Path) -> dict:
    """Extrai evidências espectrais. Nunca lança (retorna erro em dict)."""
    try:
        signal, rate = read_mono(path)
    except (OSError, ValueError, EOFError):
        return {"ok": False, "error": "Áudio inválido."}
    duration = len(signal) / rate if rate else 0.0
    if duration <= 0:
        return {"ok": False, "error": "Áudio inválido."}
    frames = _frames(signal)
    window = np.hanning(frames.shape[1])
    win = frames * window
    rms_frames = np.sqrt(np.mean(win ** 2, axis=1) + 1e-12)
    peak = float(np.max(np.abs(signal)))
    rms = float(np.sqrt(np.mean(signal ** 2)))
    silence_ratio = float(np.mean(rms_frames < 10 ** (-45.0 / 20.0)))
    activity = 1.0 - silence_ratio

    spectrum = np.abs(np.fft.rfft(win, axis=1))
    freqs = np.fft.rfftfreq(win.shape[1], d=1.0 / rate)
    centroid = float(np.average(
        np.tile(freqs, (spectrum.shape[0], 1)).ravel(),
        weights=(spectrum.ravel() + 1e-12)))
    cumsum = np.cumsum(spectrum, axis=1)
    total = cumsum[:, -1:] + 1e-12
    # Frames silenciosos zeram a média da curva normalizada, que pode
    # nunca atingir 0.85 (ex. cauda silenciosa) — clampar o índice em
    # vez de lançar IndexError (3M: áudio real com decaimento+silêncio).
    rolloff_idx = int(np.searchsorted(
        (cumsum / total).mean(axis=0), 0.85))
    rolloff_idx = max(0, min(rolloff_idx, len(freqs) - 1))
    rolloff = float(freqs[rolloff_idx])
    bands = [(0.0, 120.0), (120.0, 300.0), (300.0, 2000.0),
             (2000.0, 6000.0), (6000.0, rate / 2.0)]
    band_energy = []
    mean_spec = spectrum.mean(axis=0) + 1e-12
    for lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        band_energy.append(float(mean_spec[mask].sum() / mean_spec.sum()))

    # ZCR médio.
    signs = np.sign(signal)
    signs[signs == 0] = 1
    zcr = float(np.mean(np.abs(np.diff(signs)) > 0) / 2.0)

    # Harmonicity: pico de autocorrelação normalizada (50–2000 Hz).
    harm = 0.0
    pitch_estimate_hz = None
    if len(signal) > rate:
        seg = signal[:rate] - signal[:rate].mean()
        ac = np.correlate(seg, seg, mode="full")[len(seg) - 1:]
        if ac[0] > 1e-12:
            lo_lag = max(1, int(rate / 2000.0))
            hi_lag = min(len(ac) - 1, int(rate / 50.0))
            if hi_lag > lo_lag:
                rel = ac[lo_lag:hi_lag + 1] / ac[0]
                harm = float(np.max(rel))
                harm = max(0.0, min(1.0, harm))
                best_lag = lo_lag + int(np.argmax(rel))
                if harm >= 0.30:
                    pitch_estimate_hz = round(float(rate) / best_lag, 1)

    # Transientes: picos de fluxo espectral por segundo.
    flux = np.sqrt(np.mean(np.diff(spectrum, axis=0) ** 2, axis=1)) \
        if spectrum.shape[0] > 1 else np.array([0.0])
    thresh = flux.mean() + 2.0 * flux.std() if len(flux) > 1 else 0.0
    peaks = 0
    last = -10
    for i in range(1, len(flux) - 1):
        if flux[i] > thresh and flux[i] >= flux[i - 1] \
                and flux[i] >= flux[i + 1] and i - last > 4:
            peaks += 1
            last = i
    transient_rate = peaks / max(duration, 0.01) if duration else 0.0

    crest = float(peak / max(rms, 1e-9))
    return {
        "ok": True,
        "duration_seconds": round(duration, 3),
        "sample_rate": rate,
        "rms": round(rms, 5),
        "peak": round(peak, 5),
        "crest_db": round(20.0 * np.log10(crest), 2),
        "silence_ratio": round(silence_ratio, 4),
        "activity": round(activity, 4),
        "spectral_centroid_hz": round(centroid, 1),
        "spectral_rolloff_hz": round(rolloff, 1),
        "band_sub": round(band_energy[0], 4),
        "band_low": round(band_energy[1], 4),
        "band_mid": round(band_energy[2], 4),
        "band_high_mid": round(band_energy[3], 4),
        "band_air": round(band_energy[4], 4),
        "zcr": round(zcr, 5),
        "harmonicity": round(harm, 4),
        "pitch_estimate_hz": pitch_estimate_hz,
        "transient_rate": round(transient_rate, 3),
    }

"""Calcula el envolvente de amplitud (RMS) del audio, una muestra por frame."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from moviepy import AudioFileClip


def compute_envelope(audio_path: Path, fps: int) -> np.ndarray:
    """Devuelve un vector float32 normalizado [0, 1] con RMS por frame de video.

    Long. resultante = ceil(duration * fps).
    """
    clip = AudioFileClip(str(audio_path))
    try:
        arr = clip.to_soundarray()  # shape (N, channels) float64 en [-1, 1]
    finally:
        clip.close()

    if arr.ndim == 2:
        # Mezcla a mono promediando canales.
        mono = arr.mean(axis=1)
    else:
        mono = arr

    if mono.size == 0:
        return np.zeros(1, dtype=np.float32)

    sample_rate = clip.fps  # MoviePy expone el sample-rate del audio
    samples_per_frame = max(1, sample_rate // fps)
    n_frames = int(np.ceil(len(mono) / samples_per_frame))

    # Pad a múltiplo de samples_per_frame.
    pad = n_frames * samples_per_frame - len(mono)
    if pad > 0:
        mono = np.concatenate([mono, np.zeros(pad, dtype=mono.dtype)])

    chunks = mono.reshape(n_frames, samples_per_frame)
    rms = np.sqrt(np.mean(chunks * chunks, axis=1)).astype(np.float32)

    peak = float(rms.max())
    if peak > 1e-6:
        rms /= peak

    # Suavizado exponencial para evitar parpadeo (ataque rápido, decay lento).
    smoothed = np.empty_like(rms)
    smoothed[0] = rms[0]
    attack, decay = 0.6, 0.15
    for i in range(1, len(rms)):
        a = attack if rms[i] > smoothed[i - 1] else decay
        smoothed[i] = smoothed[i - 1] + a * (rms[i] - smoothed[i - 1])

    return smoothed


def envelope_at(envelope: np.ndarray, frame_idx: int) -> float:
    if envelope.size == 0:
        return 0.0
    return float(envelope[min(frame_idx, len(envelope) - 1)])

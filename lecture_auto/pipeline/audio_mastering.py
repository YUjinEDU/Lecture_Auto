"""Lightweight, deterministic audio mastering DSP chain for lecture speech (S21).

Pure SciPy / NumPy / pyloudnorm implementation -- zero GPU memory overhead,
zero external neural network dependencies. Delivers broadcast/studio-grade
vocal presence and eliminates room boxiness, mic rumble, and harsh sibilance.
"""
from __future__ import annotations

import logging

import numpy as np
import pyloudnorm as pyln
from scipy import signal

logger = logging.getLogger(__name__)

_DEFAULT_SR = 24000
_TARGET_LUFS = -20.0
_TRUE_PEAK_CEILING = 0.95  # ~ -0.45 dBFS


def highpass_filter(wav: np.ndarray, sr: int = _DEFAULT_SR, cutoff_hz: float = 80.0) -> np.ndarray:
    """Apply a 2nd-order zero-phase Butterworth high-pass filter (no phase distortion)."""
    if len(wav) == 0:
        return wav
    sos = signal.butter(2, cutoff_hz, btype="highpass", fs=sr, output="sos")
    # sosfiltfilt provides zero phase distortion and avoids initial transient steps
    padlen = min(len(wav) - 1, int(sr * 0.1))
    if padlen > 6:
        return signal.sosfiltfilt(sos, wav, padlen=padlen).astype(np.float32)
    return signal.sosfilt(sos, wav).astype(np.float32)


def peaking_eq(
    wav: np.ndarray,
    sr: int = _DEFAULT_SR,
    freq_hz: float = 320.0,
    gain_db: float = -1.8,
    q: float = 1.2,
) -> np.ndarray:
    """Second-order peaking / parametric biquad equalizer filter using direct SOS coefficients.

    gain_db > 0: boost, gain_db < 0: cut.
    """
    if len(wav) == 0 or abs(gain_db) < 1e-4:
        return wav

    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * freq_hz / sr
    alpha = np.sin(w0) / (2.0 * q)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * np.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * np.cos(w0)
    a2 = 1.0 - alpha / A

    # Normalized Biquad coefficients in direct SOS format: [b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]
    sos = np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)
    return signal.sosfilt(sos, wav.astype(np.float64)).astype(np.float32)


def de_ess_filter(
    wav: np.ndarray,
    sr: int = _DEFAULT_SR,
    sibilance_freq_hz: float = 6200.0,
    cut_gain_db: float = -2.8,
    q: float = 2.0,
) -> np.ndarray:
    """Tame harsh Korean sibilant resonance (ㅅ, ㅆ, ㅊ, ㅈ) in the 5.5-7.5 kHz band."""
    return peaking_eq(wav, sr=sr, freq_hz=sibilance_freq_hz, gain_db=cut_gain_db, q=q)


def soft_clip_limiter(
    wav: np.ndarray,
    ceiling: float = _TRUE_PEAK_CEILING,
    knee_start: float = 0.80,
) -> np.ndarray:
    """Smooth transparent soft-knee saturation to cap peaks exceeding knee_start.

    Strictly linear for |x| <= knee_start so quiet and normal speech is 100%
    unaltered without any harmonic distortion. Only peaks in the range
    (knee_start, 1.0+] are smoothly curved towards the ceiling using tanh margin.
    """
    if len(wav) == 0:
        return wav
    peak = float(np.max(np.abs(wav)))
    if peak <= knee_start:
        return wav.astype(np.float32)

    signs = np.sign(wav)
    mag = np.abs(wav).astype(np.float64)

    out = mag.copy()
    mask = mag > knee_start
    margin = max(ceiling - knee_start, 1e-4)
    out[mask] = knee_start + margin * np.tanh((mag[mask] - knee_start) / margin)

    return (signs * out).astype(np.float32)


def trim_speech_tail(
    wav: np.ndarray,
    sr: int = _DEFAULT_SR,
    frame_ms: float = 30.0,
    safety_pad_ms: float = 70.0,
    fade_ms: float = 15.0,
) -> np.ndarray:
    """Trim low-energy mumbling/glitch tail from speech using windowed backward VAD.

    Unlike naive point-wise thresholding where a single isolated click/pop sample
    at the end extends the clip by seconds, this scans backwards over 30ms RMS
    energy windows relative to the clip's 90th percentile speech energy.
    Guarantees a 70ms safety pad so Korean terminal consonants (받침) are preserved,
    followed by a smooth 15ms cosine fade-out.
    """
    if wav.ndim > 1:
        wav = np.mean(wav, axis=1)

    if len(wav) < int(sr * 0.2):  # Skip very short clips (<200ms)
        return wav

    frame_len = max(1, int(sr * frame_ms / 1000.0))
    n_frames = len(wav) // frame_len
    if n_frames < 2:
        return wav

    frames = wav[: n_frames * frame_len].reshape(n_frames, frame_len)
    energies = np.sqrt(np.mean(frames**2, axis=1))

    # Reference speech energy (90th percentile)
    p_speech = float(np.percentile(energies, 90))
    if p_speech < 1e-5:
        return wav

    threshold = max(0.005, p_speech * 0.15)

    # Scan backwards from the end for the last sustained voiced window
    last_voiced_frame = n_frames - 1
    while last_voiced_frame > 0 and energies[last_voiced_frame] < threshold:
        last_voiced_frame -= 1

    # Guard: If no frame met the threshold, return original audio without clipping
    if last_voiced_frame == 0 and energies[0] < threshold:
        return wav.astype(np.float32)

    cut_sample = min(len(wav), (last_voiced_frame + 1) * frame_len + int(sr * safety_pad_ms / 1000.0))

    if cut_sample >= len(wav):
        return wav.astype(np.float32)

    trimmed = wav[:cut_sample].astype(np.float32, copy=True)

    # Apply 15ms cosine fade-out at the cut edge to prevent pop noise
    fade_len = min(int(sr * fade_ms / 1000.0), len(trimmed))
    if fade_len > 0:
        ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, fade_len, dtype=np.float32)))
        trimmed[-fade_len:] *= ramp

    return trimmed


def master_lecture_speech(
    wav: np.ndarray,
    sr: int = _DEFAULT_SR,
    target_lufs: float = _TARGET_LUFS,
    hpf_cutoff: float = 80.0,
    boxiness_cut_db: float = -1.8,
    presence_boost_db: float = 1.5,
    deess_cut_db: float = -2.5,
) -> np.ndarray:
    """Run the complete 5-stage studio mastering chain.

    1. High-Pass Filter (80 Hz): Strips HVAC rumble and DC offset.
    2. Boxiness Cut (320 Hz, -1.8 dB): Removes hollow classroom resonance.
    3. Presence Boost (3000 Hz, +1.5 dB): Enhances consonant articulation.
    4. De-esser (6200 Hz, -2.5 dB): Tames piercing high-frequency sibilance.
    5. Soft Limiting & EBU R128 Loudness Normalization (-20 LUFS).

    Pure function, deterministic, returns float32 mono waveform.
    """
    if len(wav) == 0:
        return wav.astype(np.float32)

    if wav.ndim > 1:
        wav = np.mean(wav, axis=1)

    out = wav.astype(np.float32, copy=True)

    # 1. High-pass filter
    out = highpass_filter(out, sr=sr, cutoff_hz=hpf_cutoff)

    # 2. Cut boxy room resonance
    out = peaking_eq(out, sr=sr, freq_hz=320.0, gain_db=boxiness_cut_db, q=1.2)

    # 3. Boost vocal clarity and articulation
    out = peaking_eq(out, sr=sr, freq_hz=3000.0, gain_db=presence_boost_db, q=1.0)

    # 4. De-ess sibilance
    out = de_ess_filter(out, sr=sr, sibilance_freq_hz=6200.0, cut_gain_db=deess_cut_db, q=2.0)

    # 5. Integrated Loudness Normalization
    if len(out) >= int(sr * 0.4):
        try:
            meter = pyln.Meter(sr)
            loudness = meter.integrated_loudness(out.astype(np.float64))
            if np.isfinite(loudness):
                out = pyln.normalize.loudness(out.astype(np.float64), loudness, target_lufs).astype(np.float32)
                # Linear peak scale before soft-limiter to prevent harsh compression
                peak = float(np.max(np.abs(out)))
                if peak > 1.0:
                    out = out / peak * 0.98
        except Exception as e:  # noqa: BLE001
            logger.warning("Loudness normalization fallback: %s", e)

    # 6. Safety Peak Ceiling Limiter
    out = soft_clip_limiter(out, ceiling=_TRUE_PEAK_CEILING)

    return out.astype(np.float32)

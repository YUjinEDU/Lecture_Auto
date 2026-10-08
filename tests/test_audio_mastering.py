"""Tests for audio mastering module (S21)."""
from __future__ import annotations

import numpy as np

from lecture_auto.pipeline.audio_mastering import (
    apply_room_tone_dither,
    de_ess_filter,
    highpass_filter,
    master_lecture_speech,
    peaking_eq,
    soft_clip_limiter,
    synthesize_room_tone,
    trim_speech_tail,
)


def test_empty_audio_handling():
    empty = np.array([], dtype=np.float32)
    assert len(highpass_filter(empty)) == 0
    assert len(peaking_eq(empty)) == 0
    assert len(de_ess_filter(empty)) == 0
    assert len(soft_clip_limiter(empty)) == 0
    assert len(master_lecture_speech(empty)) == 0


def test_highpass_filter_attenuates_low_frequencies():
    sr = 24000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    # 30 Hz sub-bass + 1000 Hz tone
    sig_low = np.sin(2 * np.pi * 30 * t).astype(np.float32)

    # 30Hz energy should be significantly reduced (> 12dB reduction)
    low_energy_before = np.mean(sig_low**2)
    filtered_low = highpass_filter(sig_low, sr=sr, cutoff_hz=80.0)
    low_energy_after = np.mean(filtered_low**2)

    assert low_energy_after < low_energy_before * 0.1


def test_peaking_eq_gain():
    sr = 24000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sig_320 = np.sin(2 * np.pi * 320 * t).astype(np.float32)

    cut = peaking_eq(sig_320, sr=sr, freq_hz=320.0, gain_db=-6.0, q=1.0)
    energy_before = np.mean(sig_320**2)
    energy_after = np.mean(cut**2)

    assert energy_after < energy_before * 0.6


def test_soft_clip_limiter():
    # Signal with over-threshold peaks
    sig = np.array([-1.5, -0.5, 0.0, 0.5, 1.8], dtype=np.float32)
    limited = soft_clip_limiter(sig, ceiling=0.95)

    assert np.max(np.abs(limited)) <= 0.96
    assert np.all(np.isfinite(limited))


def test_master_lecture_speech_deterministic():
    sr = 24000
    np.random.seed(42)
    # 2 seconds of synthetic speech-like signal
    t = np.linspace(0, 2.0, sr * 2, endpoint=False)
    sig = (
        0.5 * np.sin(2 * np.pi * 150 * t)  # male voice fundamental
        + 0.3 * np.sin(2 * np.pi * 1200 * t)  # formant
        + 0.2 * np.sin(2 * np.pi * 6200 * t)  # sibilant
        + 0.1 * np.random.randn(len(t))  # background noise
    ).astype(np.float32)

    out1 = master_lecture_speech(sig, sr=sr)
    out2 = master_lecture_speech(sig, sr=sr)

    # Must be 100% byte-identical
    np.testing.assert_array_equal(out1, out2)
    assert len(out1) == len(sig)
    assert np.max(np.abs(out1)) <= 1.0


def test_trim_speech_tail_trims_low_energy_tail():
    sr = 24000
    # 1.0 second of strong speech tone (0.5 amplitude)
    t_speech = np.linspace(0, 1.0, sr, endpoint=False)
    speech = 0.5 * np.sin(2 * np.pi * 300 * t_speech)
    # 1.0 second of quiet mumbling tail (0.01 amplitude)
    t_tail = np.linspace(0, 1.0, sr, endpoint=False)
    tail = 0.01 * np.sin(2 * np.pi * 100 * t_tail)

    full = np.concatenate([speech, tail]).astype(np.float32)

    trimmed = trim_speech_tail(full, sr=sr, safety_pad_ms=70.0)

    # Should be trimmed close to ~1.07s (speech + 70ms pad), far less than 2.0s
    duration_s = len(trimmed) / sr
    assert 1.0 <= duration_s <= 1.15
    assert len(trimmed) < len(full) * 0.6


def test_trim_speech_tail_preserves_all_quiet_audio():
    sr = 24000
    # 0.5s of near-silent audio (no clear voiced frame)
    quiet = np.ones(sr // 2, dtype=np.float32) * 1e-4
    trimmed = trim_speech_tail(quiet, sr=sr)
    # Should not crash and should preserve the clip
    assert len(trimmed) == len(quiet)


def test_stereo_input_downmixed_to_mono():
    sr = 24000
    stereo = np.ones((sr // 2, 2), dtype=np.float32) * 0.1
    out = master_lecture_speech(stereo, sr=sr)
    assert out.ndim == 1
    assert len(out) == sr // 2


def test_soft_clip_limiter_strictly_linear_below_knee():
    # Signal strictly under knee_start=0.80 should remain exactly identical
    normal_signal = np.array([-0.7, -0.2, 0.0, 0.3, 0.75], dtype=np.float32)
    out = soft_clip_limiter(normal_signal, ceiling=0.95, knee_start=0.80)
    np.testing.assert_allclose(out, normal_signal, atol=1e-6)

    # Signal exceeding knee should be smoothly capped <= ceiling
    overshoot = np.array([0.9, 1.2, 2.0], dtype=np.float32)
    out_over = soft_clip_limiter(overshoot, ceiling=0.95, knee_start=0.80)
    assert np.all(out_over <= 0.95)
    assert np.all(out_over > 0.80)


def test_synthesize_room_tone_properties():
    sr = 24000
    duration_s = 1.5
    target_dbfs = -58.0
    tone1 = synthesize_room_tone(duration_s, sr=sr, target_dbfs=target_dbfs, seed=42)
    tone2 = synthesize_room_tone(duration_s, sr=sr, target_dbfs=target_dbfs, seed=42)

    # Determinism
    np.testing.assert_array_equal(tone1, tone2)
    assert len(tone1) == int(duration_s * sr)

    # Measured RMS level should be very close to target (-58 dBFS +/- 0.5 dB)
    rms = float(np.sqrt(np.mean(tone1**2)))
    measured_dbfs = 20.0 * np.log10(rms)
    assert abs(measured_dbfs - target_dbfs) < 0.5


def test_apply_room_tone_dither_replaces_digital_silence():
    sr = 24000
    # 0.5 seconds of pure digital zero
    digital_zero = np.zeros(int(0.5 * sr), dtype=np.float32)
    dithered = apply_room_tone_dither(digital_zero, sr=sr, target_dbfs=-58.0, seed=42)

    assert len(dithered) == len(digital_zero)
    # Shouldn't be zero anymore
    rms = float(np.sqrt(np.mean(dithered**2)))
    measured_dbfs = 20.0 * np.log10(rms)
    assert -60.0 <= measured_dbfs <= -56.0


def test_master_lecture_speech_with_room_tone_chain():
    sr = 24000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sig = 0.5 * np.sin(2 * np.pi * 200 * t).astype(np.float32)

    # Master with room tone dithering enabled (default)
    mastered = master_lecture_speech(sig, sr=sr, dither_room_tone=True)

    assert len(mastered) == len(sig)
    assert np.max(np.abs(mastered)) <= 0.96
    assert np.all(np.isfinite(mastered))


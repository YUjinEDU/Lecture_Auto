"""Gemini TTS through the BAZE API gateway (``POST /audio/speech``), one slide at a time.

The slide is cut into the same sentence segments the Raon path uses and the pieces are
joined with exact-zero ``_PAUSE_MS`` gaps, because ``pipeline/subtitles.py`` recovers
segment times from those gaps; exact zeros inside the speech are nudged to 1 LSB so they
can't be mistaken for a boundary. The gateway offers prebuilt voices only (no cloning).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from lecture_auto.pipeline.raon_tts import (
    _PAUSE_MS,
    _SAMPLE_RATE,
    _loudness_normalize,
    _slide_gate_failures,
    _trim_lead_tail_silence,
    _write_slide_qc,
    split_into_segments,
)
from lecture_auto.schemas.production import SegmentQC

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"
GEMINI_SYNTH_VERSION = "g1-seg-zero-gap"
DEFAULT_VOICE = "Charon"
DEFAULT_INSTRUCTIONS = "대학 강의를 하는 교수처럼 차분하고 또박또박하게, 너무 빠르지 않게 읽어 주세요."
GEMINI_VOICES = (
    "Aoede", "Achernar", "Autonoe", "Callirrhoe", "Despina", "Erinome", "Gacrux", "Kore",
    "Laomedeia", "Leda", "Pulcherrima", "Sulafat", "Vindemiatrix", "Zephyr", "Achird", "Algenib",
    "Algieba", "Alnilam", "Charon", "Enceladus", "Fenrir", "Iapetus", "Orus", "Puck", "Rasalgethi",
    "Sadachbia", "Sadaltager", "Schedar", "Umbriel", "Zubenelgenubi",
)
MAX_INPUT_CHARS = 4000
MAX_PARALLEL_REQUESTS = 4
MAX_IN_FLIGHT = int(os.environ.get("BAZE_TTS_MAX_IN_FLIGHT", "8"))
PARALLEL_SLIDES = 3
_RETRY_STATUS = {429, 500, 502, 503, 504}
_ONE_LSB = 1.0 / 32768.0


class GeminiTTSError(RuntimeError):
    pass


@dataclass
class BazeTTSClient:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = GEMINI_TTS_MODEL
    timeout: float = 120.0
    retry_delays: Sequence[float] = (2.0, 5.0, 15.0)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    max_in_flight: int = MAX_IN_FLIGHT

    def __post_init__(self) -> None:
        # Shared by every slide and segment thread using this client: the gateway allows 120
        # calls per member per minute, and a call takes ~4 s, so 8 in flight stays under it.
        self._slots = threading.BoundedSemaphore(self.max_in_flight)

    @classmethod
    def from_env(cls) -> BazeTTSClient:
        key = os.environ.get("BAZE_API_KEY", "")
        if not key:
            raise GeminiTTSError("BAZE_API_KEY is not set -- the lecture uses Gemini TTS through BAZE")
        return cls(api_key=key, base_url=os.environ.get("BAZE_BASE_URL", DEFAULT_BASE_URL))

    def speech(self, text: str, voice: str, instructions: str | None) -> np.ndarray:
        """Float32 mono samples at 24 kHz for ``text``."""
        if len(text) > MAX_INPUT_CHARS:
            raise GeminiTTSError(f"segment is {len(text)} chars; the gateway takes at most {MAX_INPUT_CHARS}")
        body = {"model": self.model, "input": text, "voice": voice}
        if instructions:
            body["instructions"] = instructions
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(len(self.retry_delays) + 1):
            req = urllib.request.Request(
                f"{self.base_url.rstrip('/')}/audio/speech/", data=data, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with self._slots, urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    pcm = resp.read()
                break
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode("utf-8", "replace")
                if e.code in _RETRY_STATUS and attempt < len(self.retry_delays):
                    logger.warning("Gemini TTS HTTP %d, retrying in %.0fs: %s", e.code, self.retry_delays[attempt], detail)
                    self.sleep(self.retry_delays[attempt])
                    continue
                raise GeminiTTSError(f"Gemini TTS HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < len(self.retry_delays):
                    logger.warning("Gemini TTS network error, retrying: %s", e)
                    self.sleep(self.retry_delays[attempt])
                    continue
                raise GeminiTTSError(f"Gemini TTS request failed: {e}") from None
        if len(pcm) < 2:
            raise GeminiTTSError("Gemini TTS returned no audio")
        return np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


def voice_identity(voice: str | None, instructions: str | None) -> bytes:
    """What decides a Gemini take besides the text; stands in for the reference-voice bytes in cache keys."""
    return f"gemini|{GEMINI_TTS_MODEL}|{voice or DEFAULT_VOICE}|{instructions or DEFAULT_INSTRUCTIONS}|{GEMINI_SYNTH_VERSION}".encode()


def _no_inner_zeros(piece: np.ndarray) -> np.ndarray:
    out = piece.copy()
    out[out == 0] = _ONE_LSB
    return out


def synthesize_gemini_slide(
    client: BazeTTSClient,
    text: str,
    output_path: Path,
    *,
    voice: str | None = None,
    instructions: str | None = None,
    qc_path: Path | None = None,
) -> tuple[Path, bool]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    voice = voice or DEFAULT_VOICE
    instructions = instructions or DEFAULT_INSTRUCTIONS
    sr = _SAMPLE_RATE
    segments = split_into_segments(text) if text.strip() else []
    if not segments:
        sf.write(str(output_path), np.zeros(int(0.5 * sr), dtype=np.float32), sr)
        if qc_path is not None:
            _write_slide_qc(qc_path, ok=True, gate_reasons=[], stt=None, spoken_text=text, segments=[])
        return output_path, True

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_REQUESTS, len(segments))) as pool:
        raw = list(pool.map(lambda seg: client.speech(seg, voice, instructions), segments))
    pieces = [_trim_lead_tail_silence(p, sr) for p in raw]
    gap = np.zeros(int(sr * _PAUSE_MS / 1000), dtype=np.float32)
    joined = np.concatenate([x for p in pieces for x in (p, gap)][:-1])
    gain_ref = _loudness_normalize(joined, sr)
    scale = float(np.max(np.abs(gain_ref)) / max(float(np.max(np.abs(joined))), 1e-9))
    final = np.concatenate([x for p in pieces for x in (np.clip(_no_inner_zeros(p * scale), -1.0, 1.0), gap)][:-1])
    sf.write(str(output_path), final, sr)

    reasons = _slide_gate_failures(final, sr, len(text), None, check_short=False)
    empty = [i for i, p in enumerate(pieces) if len(p) < int(0.2 * sr) or float(np.max(np.abs(p))) < 0.01]
    if empty:
        reasons.append(f"empty-segments{empty}")
    ok = not reasons
    if not ok:
        logger.error("Gemini slide %s failed the gate: %s", output_path.name, reasons)
    if qc_path is not None:
        _write_slide_qc(
            qc_path, ok=ok, gate_reasons=reasons, stt=None, spoken_text=text,
            segments=[
                SegmentQC(index=i, text=seg, seed=None, call=None, fallback=False, stt_status=None, cer=None)
                for i, seg in enumerate(segments)
            ],
        )
    return output_path, ok

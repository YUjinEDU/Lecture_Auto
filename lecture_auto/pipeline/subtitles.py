"""S14: sentence-level subtitles (SRT/VTT) from already-synthesized slide WAVs.

Pure functions, stdlib + numpy only. Nothing here touches TTS: ``synthesize_raon_slide``
joins segment audio with exact-zero ``_PAUSE_MS`` gaps, so segment times are recovered
from the WAV by detecting those zero runs (no re-synthesis needed).
"""
from __future__ import annotations

import re

import numpy as np

from lecture_auto.pipeline.pronunciation import apply_pronunciation
from lecture_auto.pipeline.raon_tts import _SEGMENT_MAX_CHARS, _SENTENCE_END_RE, _split_long_sentence

Cue = tuple[float, float, str]
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


def segment_spans(
    wav: np.ndarray,
    sr: int,
    n_segments: int,
    seg_chars: list[int] | None = None,
    pause_ms: float = 200,
) -> tuple[list[tuple[float, float]], str]:
    """(start, end) seconds per segment and the method (``"pause"``/``"proportional"``).

    Boundaries are exact-zero runs >= 0.8*pause_ms that do not touch the file edges:
    previous segment ends where the run starts, the next begins where it ends. If the
    run count is not ``n_segments - 1`` the whole duration is split by ``seg_chars``.
    """
    n = len(wav)
    min_run = int(0.8 * pause_ms * sr / 1000)
    z = np.concatenate(([False], np.asarray(wav) == 0, [False]))
    d = np.diff(z.astype(np.int8))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    runs = [(a, b) for a, b in zip(starts, ends) if b - a >= min_run and a > 0 and b < n]
    if len(runs) == n_segments - 1 and n_segments > 0:
        bounds = [0] + [x for a, b in runs for x in (a, b)] + [n]
        return [(bounds[i] / sr, bounds[i + 1] / sr) for i in range(0, len(bounds), 2)], "pause"
    weights = list(seg_chars) if seg_chars and len(seg_chars) == n_segments else [1] * n_segments
    total = max(sum(weights), 1)
    spans, acc = [], 0
    for w in weights:
        spans.append((acc / total * n / sr, (acc + w) / total * n / sr))
        acc += w
    return spans, "proportional"


def written_segments(script: str, spoken_segments: list[str], entries: list[dict]) -> list[str] | None:
    """Recover on-screen text (English terms intact) for each spoken segment, or None.

    Splits the written script like ``split_into_segments`` would (sentences, long ones at
    clause boundaries), maps each unit through ``apply_pronunciation`` and greedily groups
    units until they equal each spoken segment exactly. Any mismatch -> None.
    """
    units: list[tuple[str, str]] = []  # (written, spoken)
    for sent in (s.strip() for s in _SENTENCE_END_RE.split(script.strip()) if s.strip()):
        pieces = [sent]
        if len(apply_pronunciation(sent, entries)) > _SEGMENT_MAX_CHARS:
            pieces = _split_long_sentence(sent, max_chars=_SEGMENT_MAX_CHARS)
        units += [(p, _norm(apply_pronunciation(p, entries))) for p in pieces]
    out, i = [], 0
    for seg in spoken_segments:
        target, acc_w, acc_s = _norm(seg), [], ""
        while i < len(units) and len(acc_s) < len(target):
            acc_w.append(units[i][0])
            acc_s = _norm(f"{acc_s} {units[i][1]}")
            i += 1
        if acc_s != target:
            return None
        out.append(" ".join(acc_w))
    return out if i == len(units) else None


def _wrap(text: str, line_chars: int) -> str:
    if len(text) <= line_chars:
        return text
    mid = len(text) / 2
    spaces = [m.start() for m in re.finditer(" ", text)]
    if not spaces:
        return text
    k = min(spaces, key=lambda p: abs(p - mid))
    return f"{text[:k]}\n{text[k + 1:]}"


def _balanced(sentence: str, max_chars: int) -> list[str]:
    """Split one sentence into the fewest pieces <= max_chars, of near-equal length,
    preferring a cut right after a comma when one sits near the target length."""
    words = sentence.split(" ")
    if len(sentence) <= max_chars or len(words) == 1:
        return [sentence]
    n = -(-len(sentence) // max_chars)
    target = len(sentence) / n
    pieces, cur = [], ""
    for i, w in enumerate(words):
        cur = f"{cur} {w}" if cur else w
        rest = " ".join(words[i + 1:])
        if not rest or len(pieces) == n - 1:
            continue
        nxt = len(cur) + 1 + len(words[i + 1])
        if (w.endswith(",") and len(cur) >= 0.7 * target) or nxt > target * 1.15 or nxt > max_chars:
            pieces.append(cur)
            cur = ""
    pieces.append(cur) if cur else None
    return [p for p in pieces if p]


def split_cue(text: str, start: float, end: float, max_chars: int = 42) -> list[Cue]:
    """Split one segment into cues: sentence boundaries first, long sentences into
    near-equal pieces <= max_chars, very short pieces (< 8 chars, e.g. a lone "거고요.")
    merged into the previous one. Time is proportional to chars; text wrapped to <= 2 lines."""
    pieces: list[str] = []
    for sent in (x for x in _SENTENCE_END_RE.split(_norm(text)) if x):
        for p in _balanced(sent, max_chars):
            if pieces and len(p) < 8 and len(pieces[-1]) + 1 + len(p) <= max_chars + 10:
                pieces[-1] = f"{pieces[-1]} {p}"
            else:
                pieces.append(p)
    if not pieces:
        return []
    total, acc, cues = sum(len(p) for p in pieces), 0, []
    for p in pieces:
        s = start + (end - start) * acc / total
        acc += len(p)
        cues.append((s, start + (end - start) * acc / total, _wrap(p, max(max_chars // 2, (len(p) + 1) // 2))))
    return cues


def _ts(sec: float, sep: str) -> str:
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    return "".join(
        f"{i}\n{_ts(s, ',')} --> {_ts(e, ',')}\n{t}\n\n" for i, (s, e, t) in enumerate(cues, 1)
    )


def to_vtt(cues: list[Cue]) -> str:
    return "WEBVTT\n\n" + "".join(f"{_ts(s, '.')} --> {_ts(e, '.')}\n{t}\n\n" for s, e, t in cues)

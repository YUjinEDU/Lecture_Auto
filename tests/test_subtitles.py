"""S14: subtitles module + scripts/annotate_lecture.py. Synthetic wavs, ffmpeg mocked."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from lecture_auto.pipeline.subtitles import segment_spans, split_cue, to_srt, to_vtt, written_segments
from lecture_auto.schemas.production import SegmentQC, SlideQC
from scripts import annotate_lecture as al

SR = 24000
PAUSE = int(SR * 0.2)


def _tone(n):
    return np.full(n, 0.1, dtype=np.float32)


def _wav(parts):
    out = []
    for i, p in enumerate(parts):
        if i:
            out.append(np.zeros(PAUSE, dtype=np.float32))
        out.append(_tone(p))
    return np.concatenate(out)


def test_spans_pause_exact_samples():
    a, b, c = SR, 2 * SR, SR // 2
    spans, method = segment_spans(_wav([a, b, c]), SR, 3, [10, 20, 5])
    assert method == "pause"
    assert spans[0] == (0.0, a / SR)
    assert spans[1] == ((a + PAUSE) / SR, (a + PAUSE + b) / SR)
    assert spans[2][0] == ((a + PAUSE + b + PAUSE) / SR)
    assert spans[2][1] == (a + b + c + 2 * PAUSE) / SR


def test_spans_count_mismatch_proportional():
    wav = _wav([SR, SR])
    spans, method = segment_spans(wav, SR, 3, [10, 10, 20])
    assert method == "proportional"
    assert spans[0][0] == 0 and abs(spans[-1][1] - len(wav) / SR) < 1e-9
    assert abs((spans[1][1] - spans[1][0]) - 0.25 * len(wav) / SR) < 1e-9
    assert all(spans[i][1] == spans[i + 1][0] for i in range(2))


def test_short_internal_zero_not_boundary():
    first = _tone(SR)
    first[1000:1000 + int(PAUSE * 0.5)] = 0.0
    wav = np.concatenate([first, np.zeros(PAUSE, np.float32), _tone(SR)])
    spans, method = segment_spans(wav, SR, 2, [5, 5])
    assert method == "pause" and len(spans) == 2


ENTRIES = [
    {"written": "Product", "spoken": "프로덕트", "approved": True},
    {"written": "Owner", "spoken": "오너", "approved": True},
]


def test_written_segments_restores_english():
    script = "Product Owner가 중요합니다. 다음으로 갑니다."
    spoken = ["프로덕트 오너가 중요합니다.", "다음으로 갑니다."]
    assert written_segments(script, spoken, ENTRIES) == ["Product Owner가 중요합니다.", "다음으로 갑니다."]
    # grouped sentences in one segment
    assert written_segments(script, ["프로덕트 오너가 중요합니다. 다음으로 갑니다."], ENTRIES) == [script]


def test_written_segments_mismatch_none():
    assert written_segments("Product Owner가 중요합니다.", ["전혀 다른 문장입니다."], ENTRIES) is None
    assert written_segments("A. B.", ["A."], []) is None  # leftover text


def test_split_cue_lines_and_continuity():
    text = "이것은 아주 긴 자막 문장입니다 그래서 두 개의 큐로 나뉘어야 합니다 그리고 줄바꿈도 되어야 하죠"
    cues = split_cue(text, 10.0, 16.0)
    assert len(cues) >= 2
    assert cues[0][0] == 10.0 and abs(cues[-1][1] - 16.0) < 1e-9
    assert all(abs(cues[i][1] - cues[i + 1][0]) < 1e-9 for i in range(len(cues) - 1))
    for _, _, t in cues:
        lines = t.split("\n")
        assert len(lines) <= 2 and all(len(line) <= 42 for line in lines)
    assert split_cue("짧은 문장", 0, 1) == [(0, 1, "짧은 문장")]


def test_srt_vtt_format():
    srt = to_srt([(62.345, 63.0, "안녕")])
    assert srt == "1\n00:01:02,345 --> 00:01:03,000\n안녕\n\n"
    assert to_vtt([(62.345, 63.0, "안녕")]).startswith("WEBVTT\n\n00:01:02.345 --> 00:01:03.000")


# ---------- CLI ----------
LEC = "08_종합설계_05_스크럼_활용_애자일_프로세스"


def _setup(tmp_path, entries_text):
    work, out = tmp_path / "work", tmp_path / "output"
    audio, scripts = work / LEC / "audio", work / LEC / "scripts"
    audio.mkdir(parents=True)
    scripts.mkdir(parents=True)
    (out / LEC).mkdir(parents=True)
    (out / LEC / f"{LEC}.mp4").write_bytes(b"ORIGINAL")
    tl_entries, start = [], 0.0
    for n, (script, spoken_segs) in enumerate(entries_text, 1):
        wav = _wav([SR for _ in spoken_segs])
        p = audio / f"slide_{n:03d}.wav"
        sf.write(str(p), wav, SR, subtype="FLOAT")
        (scripts / f"script_{n:03d}.json").write_text(json.dumps({"slide_number": n, "script": script}, ensure_ascii=False))
        spoken_full = " ".join(spoken_segs)
        qc = SlideQC(
            ok=True, spoken_text_sha256=hashlib.sha256(spoken_full.encode()).hexdigest(),
            segments=[SegmentQC(index=i, text=t, seed=1, call="tts") for i, t in enumerate(spoken_segs)],
            synth_version="x", created_at=datetime.now(timezone.utc),
        )
        (audio / f"slide_{n:03d}.wav.qc.json").write_text(qc.model_dump_json())
        dur = len(wav) / SR
        tl_entries.append({"slide_number": n, "start_seconds": start, "duration_seconds": dur, "wav": p.name,
                           "wav_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "approved": False})
        start += dur
    (out / LEC / f"{LEC}.timeline.json").write_text(json.dumps(
        {"lecture_id": LEC, "mp4": f"{LEC}.mp4", "draft": False, "total_seconds": start, "entries": tl_entries}))
    return work, out


def _qc_path(audio, n):
    return audio / f"slide_{n:03d}.wav.qc.json"


def test_cli_skip_sha_mismatch_and_spoken_fallback(tmp_path):
    items = [
        ("Product Owner가 중요합니다. 다음입니다.", ["프로덕트 오너가 중요합니다.", "다음입니다."]),
        ("두번째 슬라이드입니다.", ["두번째 슬라이드입니다."]),
        ("세번째입니다.", ["세번째입니다."]),
    ]
    work, out = _setup(tmp_path, items)
    audio = work / LEC / "audio"
    # slide 2: wav changed after timeline -> skipped
    sf.write(str(audio / "slide_002.wav"), _wav([SR // 2]), SR, subtype="FLOAT")
    # slide 3: script edited after synthesis -> spoken hash mismatch -> spoken text used
    (work / LEC / "scripts" / "script_003.json").write_text(json.dumps({"slide_number": 3, "script": "고쳐진 대본입니다."}, ensure_ascii=False))
    res = tmp_path / "res"
    s = al.run(LEC, work, out, res, ENTRIES)
    assert s["skipped"] == [2] and s["written"] == 1 and s["spoken"] == 1 and s["pause"] == 2
    srt = (res / f"{LEC}.srt").read_text(encoding="utf-8")
    assert "Product Owner가 중요합니다." in srt and "세번째입니다." in srt and "두번째" not in srt
    data = json.loads((res / f"{LEC}.subtitles.json").read_text(encoding="utf-8"))
    assert data["summary"]["spoken_hash_mismatch"] == [3]
    assert (res / f"{LEC}.vtt").exists()
    assert not (out / LEC / f"{LEC}.srt").exists()  # only --out-dir written


def test_cli_no_qc_single_cue(tmp_path):
    work, out = _setup(tmp_path, [("대본 하나입니다.", ["x"])])
    _qc_path(work / LEC / "audio", 1).unlink()
    s = al.run(LEC, work, out, tmp_path / "res", ENTRIES)
    assert s["proportional"] == 1 and s["written"] == 1 and s["cues"] == 1


def test_cli_burn_copies_audio_keeps_original(tmp_path):
    work, out = _setup(tmp_path, [("대본입니다.", ["대본입니다."])])
    res = tmp_path / "res"
    with patch("scripts.annotate_lecture.subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as run:
        al.run(LEC, work, out, res, ENTRIES, do_burn=True)
    cmd = run.call_args.args[0]
    assert cmd[0] == "ffmpeg" and "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"
    assert cmd[cmd.index("-i") + 1] == str(out / LEC / f"{LEC}.mp4")
    assert cmd[-1] == str(res / f"{LEC}_subtitled.mp4")
    assert any("NanumSquareRound" in c for c in cmd)
    assert (out / LEC / f"{LEC}.mp4").read_bytes() == b"ORIGINAL"

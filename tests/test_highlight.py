"""S15: highlight mapping/drawing + `annotate_lecture --highlight`. Synthetic data, ffmpeg mocked."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pymupdf
import soundfile as sf
from PIL import Image

from lecture_auto.pipeline.highlight import (
    Block, concat_manifest, draw_highlight, emu_box_to_px, load_blocks, map_segment_to_block, slide_pieces,
)
from lecture_auto.schemas.production import SegmentQC, SlideQC
from scripts import annotate_lecture as al

SR = 24000
PAUSE = int(SR * 0.2)
LEC = "08_종합설계_05_스크럼_활용_애자일_프로세스"


def test_emu_to_px():
    # 720pt-wide page rendered at 1440 px -> 2 px/pt; 1 pt = 12700 EMU
    assert emu_box_to_px(12700 * 10, 12700 * 20, 12700 * 100, 12700 * 30, 2.0) == (20, 40, 220, 100)


BLOCKS = [
    Block(0, "스크럼 소개", (0, 0, 10, 10), selectable=False),  # slide title
    Block(1, "Product Owner 는 제품 백로그를 관리한다", (0, 20, 100, 40)),
    Block(2, "스프린트 회고에서 개선점을 찾는다", (0, 50, 100, 70)),
]


def test_mapping_overlap_none_and_title():
    assert map_segment_to_block("그래서 Product Owner 가 제품 백로그를 우선순위대로 관리합니다.", BLOCKS) == 1
    assert map_segment_to_block("회고에서 개선점을 같이 찾아봅니다.", BLOCKS) == 2
    assert map_segment_to_block("자 그럼 다음으로 넘어가 보겠습니다.", BLOCKS) is None
    assert map_segment_to_block("스크럼 소개를 시작합니다.", BLOCKS) is None  # title-only overlap


def test_mapping_sticky_previous_block():
    both = [Block(1, "백로그 관리 우선순위 정리", (0, 0, 1, 1)), Block(2, "백로그 관리 우선순위 조정", (0, 0, 1, 1))]
    seg = "백로그 관리 우선순위 이야기입니다"
    assert map_segment_to_block(seg, both, prev=2) == 2  # tie -> stay on previous
    assert map_segment_to_block(seg, both) == 1


def test_draw_highlight_pixels_and_original_untouched(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(p)
    before = p.read_bytes()
    out = draw_highlight(p, (50, 30, 150, 50))
    assert out.getpixel((100, 40)) != (255, 255, 255) and out.getpixel((100, 40))[2] < 200  # yellow tint inside
    assert out.getpixel((100, 40))[0] == 255
    assert out.getpixel((100, 59)) != (255, 255, 255)  # underline below the box
    for xy in [(5, 5), (195, 95), (100, 95), (10, 40), (190, 40), (100, 10)]:
        assert out.getpixel(xy) == (255, 255, 255)
    assert p.read_bytes() == before and out is not None


def test_slide_pieces_sum_and_merge():
    spans = [(0.0, 1.0), (1.2, 2.0), (2.2, 3.0), (3.2, 4.0)]
    pieces = slide_pieces(spans, [1, 1, None, 2], 4.0)
    assert [b for b, _ in pieces] == [1, None, 2]
    assert abs(sum(d for _, d in pieces) - 4.0) < 1e-9
    assert abs(pieces[0][1] - 2.2) < 1e-9  # first piece includes pause before the next segment
    assert slide_pieces([], [], 5.0) == [(None, 5.0)]


def _make_pdf(path: Path):
    doc = pymupdf.open()
    for text in ("스크럼 애자일 프로세스", "Product Owner"):
        page = doc.new_page(width=720, height=540)
        page.insert_text((60, 80), "Title Heading", fontsize=32)
        page.insert_textbox(pymupdf.Rect(60, 200, 660, 260), text, fontsize=20, fontname="helv")
    doc.save(str(path))


def test_load_blocks_scale(tmp_path):
    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf)
    blocks = load_blocks(pdf, 1440)  # 2 px / pt
    b = blocks[1]
    assert len(b) >= 2 and sum(not x.selectable for x in b) == 1  # exactly the title
    body = next(x for x in b if x.selectable)
    assert abs(body.bbox[0] - 120) < 6 and 380 < body.bbox[1] < 420


def _setup(tmp_path):
    work, out = tmp_path / "work", tmp_path / "output"
    base = work / LEC
    for d in ("audio", "scripts", "input", "rendered"):
        (base / d).mkdir(parents=True)
    (out / LEC).mkdir(parents=True)
    _make_pdf(base / "input" / "x.pdf")
    (out / LEC / f"{LEC}.mp4").write_bytes(b"ORIGINAL")
    scripts = [
        ["스크럼 애자일 프로세스를 봅니다.", "그다음 넘어갑니다."],
        ["Product Owner 가 중요합니다.", "끝입니다."],
    ]
    tl, start = [], 0.0
    for n, segs in enumerate(scripts, 1):
        Image.new("RGB", (1440, 1080), (255, 255, 255)).save(base / "rendered" / f"slide_{n:03d}.png")
        parts = [SR, SR]
        wav = np.concatenate([np.full(parts[0], 0.1, np.float32), np.zeros(PAUSE, np.float32),
                              np.full(parts[1], 0.1, np.float32)])
        p = base / "audio" / f"slide_{n:03d}.wav"
        sf.write(str(p), wav, SR, subtype="FLOAT")
        text = " ".join(segs)
        (base / "scripts" / f"script_{n:03d}.json").write_text(json.dumps({"slide_number": n, "script": text}, ensure_ascii=False))
        qc = SlideQC(ok=True, spoken_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                     segments=[SegmentQC(index=i, text=t, seed=1, call="tts") for i, t in enumerate(segs)],
                     synth_version="x", created_at=datetime.now(timezone.utc))
        (base / "audio" / f"slide_{n:03d}.wav.qc.json").write_text(qc.model_dump_json())
        dur = len(wav) / SR
        tl.append({"slide_number": n, "start_seconds": start, "duration_seconds": dur, "wav": p.name,
                   "wav_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "approved": False})
        start += dur
    (out / LEC / f"{LEC}.timeline.json").write_text(json.dumps(
        {"lecture_id": LEC, "mp4": f"{LEC}.mp4", "draft": False, "total_seconds": start, "entries": tl}))
    return work, out, tl


def test_cli_highlight_manifest_and_originals_unchanged(tmp_path):
    work, out, tl = _setup(tmp_path)
    tl_file = out / LEC / f"{LEC}.timeline.json"
    tl_bytes = tl_file.read_bytes()
    seen: dict = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        seen["manifest"] = Path(cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")
        Path(cmd[-1]).write_bytes(b"NEW")
        return MagicMock(returncode=0, stderr="")

    res = tmp_path / "res"
    with patch("scripts.annotate_lecture.subprocess.run", side_effect=fake):
        s = al.run_highlight(LEC, work, out, res, [])
    durs = [float(x) for x in re.findall(r"^duration ([0-9.]+)$", seen["manifest"], re.M)]
    files = re.findall(r"^file '(.*)'$", seen["manifest"], re.M)
    assert abs(sum(durs) - sum(e["duration_seconds"] for e in tl)) < 0.001
    # slide order: slide-1 frames come before slide-2 frames; last file repeated by the concat format
    assert len(files) == len(durs) + 1 and files[-1] == files[-2]
    nums = [int(re.search(r"slide_(\d+)", f).group(1)) for f in files]
    assert nums == sorted(nums)
    # per-slide piece durations sum to that slide's WAV length (1 ms)
    for n, e in enumerate(tl, 1):
        got = sum(d for d, f in zip(durs, files) if f"slide_{n:03d}" in f)
        assert abs(got - e["duration_seconds"]) < 0.001
    assert all(Path(a).is_absolute() for a in seen["cmd"] if a.endswith((".txt", ".wav", ".mp4")))
    assert (res / f"{LEC}_annotated.mp4").read_bytes() == b"NEW"
    data = json.loads((res / f"{LEC}.highlight.json").read_text(encoding="utf-8"))
    assert data["summary"]["segments"] == 4 and data["summary"]["highlighted"] >= 1
    assert not list(res.glob("*.annotate_tmp"))
    assert (out / LEC / f"{LEC}.mp4").read_bytes() == b"ORIGINAL" and tl_file.read_bytes() == tl_bytes
    assert s["slides"] == 2


def test_cli_highlight_slides_subset_and_burn(tmp_path):
    work, out, tl = _setup(tmp_path)
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"X")
        return MagicMock(returncode=0, stderr="")

    with patch("scripts.annotate_lecture.subprocess.run", side_effect=fake):
        s = al.run_highlight(LEC, work, out, tmp_path / "res", [], slides=al.parse_slides("2-2"), do_burn=True)
    assert s["slides"] == 1 and len(calls) == 2  # encode + burn
    assert abs(s["seconds"] - tl[1]["duration_seconds"]) < 0.001
    assert al.parse_slides("3-5,9") == {3, 4, 5, 9}

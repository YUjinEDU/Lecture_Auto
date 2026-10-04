"""S15: map each narrated segment to the slide text block it talks about, and draw a highlight.

Deterministic and lexical (no LLM): a token is the first 2-3 hangul syllables of a word
(drops most particles/endings) or a lowercased latin word. Blocks are scored against a
segment by IDF-weighted cosine overlap; below ``MIN_SCORE`` nothing is highlighted.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

MIN_SCORE = 0.22  # tuned on lecture 08 (see S15 report): below this the best block is usually noise
MIN_HITS = 2  # at least two distinct shared tokens (or one very short block, see below)
STICKY = 0.75  # keep the previous block if it scores >= STICKY * best
_EMU_PER_PT = 12700
_TOKEN = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]+")

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Block:
    id: int
    text: str
    bbox: Box  # px (x0, y0, x1, y1)
    selectable: bool = True  # False: slide title / footer, never highlighted


def emu_box_to_px(left: int, top: int, width: int, height: int, scale: float) -> Box:
    """EMU box -> pixel box; ``scale`` = PNG px per PDF point."""
    f = scale / _EMU_PER_PT
    return (left * f, top * f, (left + width) * f, (top + height) * f)


def tokens(text: str) -> set[str]:
    out = set()
    for m in _TOKEN.finditer(text):
        w = m.group()
        out.add(w.lower() if w[0].isascii() else w[:3] if len(w) >= 4 else w[:2])
    return out


def load_blocks(pdf_path: Path, png_width_px: float) -> dict[int, list[Block]]:
    """slide_number -> text blocks (px coords for a PNG ``png_width_px`` wide).

    The first (topmost) title-role block is the slide title and the block starting in the
    bottom 10% is the footer/page number; both are kept but marked non-selectable.
    """
    import pymupdf

    from lecture_auto.pipeline.parser_pdf import parse_pdf

    doc = pymupdf.open(str(pdf_path))
    out: dict[int, list[Block]] = {}
    for rec, page in zip(parse_pdf(pdf_path), doc):
        scale = png_width_px / page.rect.width
        shapes = [s for s in rec.shapes if s.has_text]
        titles = [s for s in shapes if s.text_role == "title"]
        title_id = min(titles, key=lambda s: s.top).shape_id if titles else None
        foot_top = 0.9 * page.rect.height * _EMU_PER_PT
        out[rec.slide_number] = [
            Block(
                s.shape_id,
                " ".join(p.full_text for p in s.paragraphs),
                emu_box_to_px(s.left, s.top, s.width, s.height, scale),
                s.shape_id != title_id and s.top < foot_top,
            )
            for s in shapes
        ]
    return out


def map_segment(seg_text: str, blocks: list[Block], prev: int | None = None) -> tuple[int | None, float]:
    """-> (block id or None, score) for one segment."""
    cand = [b for b in blocks if b.selectable]
    if not cand:
        return None, 0.0
    seg = tokens(seg_text)
    btoks = {b.id: tokens(b.text) for b in cand}
    df: dict[str, int] = {}
    for ts in btoks.values():
        for t in ts:
            df[t] = df.get(t, 0) + 1
    w = lambda t: math.log(1 + len(cand) / df.get(t, 1))  # noqa: E731  (unseen token -> max weight, never matched)
    seg_w = math.fsum(w(t) for t in seg)
    scores: dict[int, float] = {}
    for b in cand:
        ts = btoks[b.id]
        hits = seg & ts
        # one hit is enough only for a (near) one-token block, otherwise it is chance overlap
        if not hits or (len(hits) < MIN_HITS and len(ts) > 1):
            continue
        scores[b.id] = round(math.fsum(w(t) for t in hits) / math.sqrt(seg_w * math.fsum(w(t) for t in ts)), 6)
    if not scores:
        return None, 0.0
    best = max(scores, key=lambda k: (scores[k], -k))
    if scores[best] < MIN_SCORE:
        return None, scores[best]
    if prev in scores and scores[prev] >= max(STICKY * scores[best], MIN_SCORE):
        return prev, scores[prev]
    return best, scores[best]


def map_segment_to_block(seg_text: str, blocks: list[Block], prev: int | None = None) -> int | None:
    return map_segment(seg_text, blocks, prev)[0]


def draw_highlight(png: Path | Image.Image, bbox_px: Box, pad: int = 6) -> Image.Image:
    """New RGB image: translucent yellow marker (alpha 0.30) over the box + underline below it."""
    base = (png if isinstance(png, Image.Image) else Image.open(png)).convert("RGBA")
    x0, y0, x1, y1 = (round(v) for v in bbox_px)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([x0, y0, x1, y1], fill=(255, 235, 0, 77))
    d.rectangle([x0, y1 + 2, x1, y1 + 4], fill=(230, 120, 0, 230))
    return Image.alpha_composite(base, layer).convert("RGB")


def slide_pieces(spans: list[tuple[float, float]], block_ids: list[int | None], wav_seconds: float):
    """Segment timing -> [(block_id|None, duration)] covering exactly ``wav_seconds``.

    A piece runs from its segment start to the next segment start (pauses belong to the
    preceding piece; the first starts at 0, the last ends at the WAV end). Consecutive
    segments on the same block merge.
    """
    if not spans:
        return [(None, wav_seconds)]
    edges = [0.0] + [s for s, _ in spans[1:]] + [wav_seconds]
    pieces: list[list] = []
    for bid, a, b in zip(block_ids, edges, edges[1:]):
        if pieces and pieces[-1][0] == bid:
            pieces[-1][1] += b - a
        else:
            pieces.append([bid, b - a])
    return [(b, d) for b, d in pieces]


def concat_manifest(items: list[tuple[Path, float]]) -> str:
    """ffmpeg concat-demuxer text for (png, duration) items (last file repeated, as assemble_video)."""
    q = lambda p: str(Path(p).resolve()).replace("'", "'\\''")  # noqa: E731
    body = "".join(f"file '{q(p)}'\nduration {d:.6f}\n" for p, d in items)
    return body + f"file '{q(items[-1][0])}'\n"

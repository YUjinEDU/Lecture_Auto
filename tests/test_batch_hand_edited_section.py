"""A section whose every slide was hand-edited skips the LLM (its output would be discarded)."""
import json
from pathlib import Path

from lecture_auto.pipeline.cache import content_hash, write_cache_hash
from scripts.batch_generate_lectures import _section_fully_hand_edited


def _write(scripts_dir: Path, n: int, text: str, edited: bool) -> None:
    p = scripts_dir / f"script_{n:03d}.json"
    generated = json.dumps({"slide_number": n, "script": text}, ensure_ascii=False)
    p.write_text(generated, encoding="utf-8")
    write_cache_hash(p, content_hash(generated))
    if edited:
        p.write_text(json.dumps({"slide_number": n, "script": text + " 고침"}, ensure_ascii=False), encoding="utf-8")


def test_all_edited_true_one_untouched_false(tmp_path: Path):
    _write(tmp_path, 1, "가", edited=True)
    _write(tmp_path, 2, "나", edited=True)
    assert _section_fully_hand_edited(tmp_path, [1, 2])
    _write(tmp_path, 3, "다", edited=False)
    assert not _section_fully_hand_edited(tmp_path, [1, 2, 3])
    assert not _section_fully_hand_edited(tmp_path, [4])  # missing file is not an edit

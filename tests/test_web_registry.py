import json
import os
import subprocess
import sys
from pathlib import Path

from lecture_auto.web.registry import (
    load_web_lectures,
    new_lecture_id,
    save_web_lectures,
)

ROOT = Path(__file__).resolve().parent.parent


def test_roundtrip_restores_paths_and_marks_web(tmp_path):
    reg = tmp_path / "lectures.json"
    save_web_lectures([{"id": "12_x", "name": "x", "subject": "s", "pptx": Path("data/web/uploads/12_x/a.pptx")}], reg)
    assert json.loads(reg.read_text(encoding="utf-8"))[0]["pptx"] == "data/web/uploads/12_x/a.pptx"
    [item] = load_web_lectures(reg)
    assert item["pptx"] == Path("data/web/uploads/12_x/a.pptx")
    assert item["web"] is True


def test_missing_registry_is_empty(tmp_path):
    assert load_web_lectures(tmp_path / "nope.json") == []


def test_new_id_takes_next_number_and_avoids_substring_clash():
    existing = ["01_a", "11_종합설계_07_시스템구조_30분이상"]
    assert new_lecture_id("06 Product/Backlog", existing) == "12_06_Product_Backlog"
    assert new_lecture_id("x", ["12_x_y", "11_q"]) == "13_x"


def test_batch_lectures_include_registry_entries(tmp_path):
    reg = tmp_path / "lectures.json"
    save_web_lectures([{"id": "99_webtest", "name": "w", "subject": "s", "pdf": Path("a.pdf")}], reg)
    code = "import scripts.batch_generate_lectures as b; print([l['id'] for l in b.LECTURES][-1])"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
        env={**os.environ, "LECTURE_AUTO_WEB_REGISTRY": str(reg)},
    )
    assert out.stdout.strip() == "99_webtest"

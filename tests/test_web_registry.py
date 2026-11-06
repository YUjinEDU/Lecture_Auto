import json
from pathlib import Path

from lecture_auto.web.registry import (
    load_web_lectures,
    save_web_lectures,
)


def test_roundtrip_restores_paths_and_marks_web(tmp_path):
    reg = tmp_path / "lectures.json"
    save_web_lectures([{"id": "12_x", "name": "x", "subject": "s", "pptx": Path("data/web/uploads/12_x/a.pptx")}], reg)
    assert json.loads(reg.read_text(encoding="utf-8"))[0]["pptx"] == "data/web/uploads/12_x/a.pptx"
    [item] = load_web_lectures(reg)
    assert item["pptx"] == Path("data/web/uploads/12_x/a.pptx")
    assert item["web"] is True


def test_missing_registry_is_empty(tmp_path):
    assert load_web_lectures(tmp_path / "nope.json") == []

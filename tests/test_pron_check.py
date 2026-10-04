"""S13: pronunciation pre-check (find_unlisted_latin_tokens + batch --check). No GPU/network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lecture_auto.pipeline.pronunciation import find_unlisted_latin_tokens
from scripts import batch_generate_lectures as bgl

_LEC = {"id": "testlec", "name": "t", "subject": "t", "pdf": Path("x.pdf")}


def test_multiword_key_covers_its_parts():
    entries = [{"written": "Burndown Chart", "spoken": "번다운 차트", "approved": True}]
    assert find_unlisted_latin_tokens("오늘은 Burndown Chart를 봅니다", entries) == []


def test_unapproved_stays_approved_disappears():
    entries = [
        {"written": "API", "spoken": "에이피아이", "approved": True},
        {"written": "Kanban", "spoken": "칸반", "approved": False},
    ]
    assert find_unlisted_latin_tokens("API와 Kanban", entries) == ["Kanban"]


def test_particles_dedupe_and_first_seen_order():
    assert find_unlisted_latin_tokens("Zed를 쓰고 API를, 다시 Zed와 CI-CD", []) == ["Zed", "API", "CI-CD"]


def _run_check(monkeypatch, tmp_path, argv_tail):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bgl, "LECTURES", [_LEC])
    monkeypatch.setattr("sys.argv", ["b.py", *argv_tail])
    bgl.main()


def _write_scripts(tmp_path, texts):
    d = tmp_path / "data" / "work_batch" / "testlec" / "scripts"
    d.mkdir(parents=True)
    for n, t in texts.items():
        (d / f"script_{n:03d}.json").write_text(
            json.dumps({"slide_number": n, "script": t}, ensure_ascii=False), encoding="utf-8")


def test_check_unlisted_exits_1_with_slide_numbers(monkeypatch, tmp_path, capsys):
    _write_scripts(tmp_path, {1: "안녕", 2: "Zed를 씁니다", 3: "다시 Zed"})
    with pytest.raises(SystemExit) as e:
        _run_check(monkeypatch, tmp_path, ["--only", "testlec", "--check"])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "Zed" in out and "2" in out and "3" in out


def test_check_clean_exits_0(monkeypatch, tmp_path):
    _write_scripts(tmp_path, {1: "한글만"})
    _run_check(monkeypatch, tmp_path, ["--only", "testlec", "--check"])


def test_check_without_only_errors(monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as e:
        _run_check(monkeypatch, tmp_path, ["--check"])
    assert e.value.code == 2


def test_check_without_scripts_errors(monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as e:
        _run_check(monkeypatch, tmp_path, ["--only", "testlec", "--check"])
    assert e.value.code not in (0, None)

"""S13: pronunciation pre-check (find_unlisted_latin_tokens + batch --check). No GPU/network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lecture_auto.pipeline.pronunciation import (
    find_speakability_risks,
    find_unlisted_latin_tokens,
)
from lecture_auto.production import batch as bgl

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


_RISK_ENTRIES = [
    {"written": "API", "spoken": "에이피아이", "approved": True},
    {"written": "/api/loans", "spoken": "슬래시 에이피아이 슬래시 론즈", "approved": True},
]


def _kinds(text):
    return {kind for kind, _ in find_speakability_risks(text, _RISK_ENTRIES)}


def test_speakability_flags_each_known_failure_shape():
    assert _kinds("목록은 GET /api/books로 조회합니다.") == {"path"}
    assert "dotted" in _kinds("ERD는 dbdiagram.io나 쓰죠.")
    assert "query" in _kinds("제목 검색은 GET /api/books?title=로 표현합니다.")
    dense = "예를 들어 US-11 도서 대출은 LoanService, LoanEntity, POST /api/loans로 이어지고, US-13 반납은 ReturnService와 연결됩니다."
    assert "dense" in _kinds(dense)


def test_speakability_leaves_fine_text_alone():
    assert _kinds("세 역할은 Product Owner, Scrum Master, Developer이고 Spring Boot 3.x도 씁니다.") == set()
    assert _kinds("대출은 POST /api/loans로 만듭니다.") == set()
    assert _kinds("짧은 문장에 LoanService 하나만 있습니다.") == set()


def test_check_prints_speakability_risks_without_changing_the_exit_code(monkeypatch, tmp_path, capsys):
    _write_scripts(tmp_path, {1: "다이어그램.아이오나 씁니다."})
    _run_check(monkeypatch, tmp_path, ["--only", "testlec", "--check"])
    out = capsys.readouterr().out
    assert "읽기 위험:dotted" in out and "슬라이드 1" in out

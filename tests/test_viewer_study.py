import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from lecture_auto.production.study import (
    GlossaryItem,
    QuizItem,
    Study,
    draft_study,
    load_study,
    save_study,
)
from lecture_auto.production.viewer import build_viewer, viewer_path, write_viewer

SR = 24000
LID = "77_view"
SENTS = ["첫 번째 문장은 시스템 구조를 소개합니다.", "두 번째 문장은 개발 환경을 설명합니다."]


def _tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def _lecture(root: Path, work: Path | None = None, out: Path | None = None) -> tuple[Path, Path]:
    work, out = work or root / "work", out or root / "out"
    audio, scripts = work / LID / "audio", work / LID / "scripts"
    audio.mkdir(parents=True)
    scripts.mkdir(parents=True)
    (out / LID).mkdir(parents=True)
    wav = np.concatenate([_tone(2.0), np.zeros(int(0.2 * SR), dtype=np.float32), _tone(3.0)])
    sf.write(audio / "slide_001.wav", wav, SR)
    script = " ".join(SENTS)
    (scripts / "script_001.json").write_text(json.dumps({"script": script}, ensure_ascii=False), encoding="utf-8")
    qc = {
        "ok": True, "gate_reasons": [], "stt": None,
        "spoken_text_sha256": hashlib.sha256(script.encode()).hexdigest(),
        "segments": [{"index": i, "text": s, "seed": None, "call": None, "fallback": False} for i, s in enumerate(SENTS)],
        "synth_version": "t", "created_at": "2026-11-07T00:00:00Z",
    }
    (audio / "slide_001.wav.qc.json").write_text(json.dumps(qc, ensure_ascii=False), encoding="utf-8")
    sha = hashlib.sha256((audio / "slide_001.wav").read_bytes()).hexdigest()
    timeline = {
        "lecture_id": LID, "mp4": f"{LID}.mp4", "draft": False, "total_seconds": 15.2,
        "entries": [{"slide_number": 1, "start_seconds": 10.0, "duration_seconds": 5.2, "wav": "slide_001.wav",
                     "wav_sha256": sha, "approved": True}],
    }
    (out / LID / f"{LID}.timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    return work, out


def test_viewer_has_sentence_times_on_the_lecture_clock(tmp_path):
    work, out = _lecture(tmp_path)
    v = build_viewer(LID, work, out, [])
    [slide] = v["slides"]
    assert v["mp4"] == f"{LID}.mp4" and slide["start"] == 10.0
    assert [s["text"] for s in slide["sentences"]] == SENTS
    first, second = slide["sentences"]
    assert first["start"] == pytest.approx(10.0) and first["end"] == pytest.approx(12.0, abs=0.01)
    assert second["start"] == pytest.approx(12.2, abs=0.01) and second["box"] is None
    assert slide["cues"] and slide["cues"][0]["start"] == pytest.approx(10.0)
    path = write_viewer(LID, work, out, [])
    assert path == viewer_path(out, LID) and json.loads(path.read_text())["slides"][0]["number"] == 1


class FakeLLM:
    def __init__(self, payload):
        self.payload, self.prompts = payload, []

    def complete_text(self, prompt, temperature=0.3, max_tokens=None):
        self.prompts.append(prompt)
        return "```json\n" + json.dumps(self.payload, ensure_ascii=False) + "\n```"


PAYLOAD = {
    "glossary": [{"term": "스크럼", "definition": "짧은 주기로 일하는 애자일 방식", "slide": 2}, {"term": ""}],
    "quiz": [
        {"question": "스크럼의 반복 주기는?", "choices": ["스프린트", "릴리스", "에픽", "백로그"], "answer": 0,
         "explanation": "스프린트입니다", "slide": 3},
        {"question": "보기 3개", "choices": ["a", "b", "c"], "answer": 0},
        {"question": "정답 범위 밖", "choices": ["a", "b", "c", "d"], "answer": 7},
    ],
}


def test_draft_keeps_only_valid_items_and_nothing_is_public_until_approved(tmp_path):
    llm = FakeLLM(PAYLOAD)
    study = draft_study(llm, LID, {2: {"script": "스크럼 설명"}, 3: {"script": "스프린트"}})
    assert "[슬라이드 2]" in llm.prompts[0] and "스크럼 설명" in llm.prompts[0]
    assert [g.term for g in study.glossary] == ["스크럼"]
    assert [q.question for q in study.quiz] == ["스크럼의 반복 주기는?"]
    assert study.public() == {"glossary": [], "quiz": []}
    study.quiz[0].approved = True
    save_study(tmp_path, study)
    public = load_study(tmp_path, LID).public()
    assert public["glossary"] == [] and public["quiz"][0]["answer"] == 0 and "approved" not in public["quiz"][0]


def test_redraft_keeps_approved_items(tmp_path):
    previous = Study(lecture_id=LID, glossary=[GlossaryItem(term="스크럼", definition="교수 수정본", approved=True)],
                     quiz=[QuizItem(question="old", choices=["a", "b", "c", "d"], answer=1, approved=False)])
    study = draft_study(FakeLLM(PAYLOAD), LID, {1: {"script": "x"}}, previous)
    assert [(g.term, g.definition, g.approved) for g in study.glossary] == [("스크럼", "교수 수정본", True)]
    assert [q.question for q in study.quiz] == ["스크럼의 반복 주기는?"]


def test_missing_study_file_is_empty(tmp_path):
    assert load_study(tmp_path, "none").public() == {"glossary": [], "quiz": []}


def test_batch_study_flag_drafts_and_saves(tmp_path, monkeypatch):
    from lecture_auto.production import batch as bgl

    monkeypatch.chdir(tmp_path)
    scripts = tmp_path / "data" / "work_batch" / LID / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "script_002.json").write_text(json.dumps({"script": "스크럼 설명"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bgl, "LECTURES", [{"id": LID, "name": "n", "subject": "s"}])
    monkeypatch.setattr(bgl, "OpenAILLMClient", lambda: FakeLLM(PAYLOAD))
    bgl.main(["--only", LID, "--study"])
    saved = load_study(tmp_path / "data" / "work_batch", LID)
    assert [g.term for g in saved.glossary] == ["스크럼"] and not saved.glossary[0].approved

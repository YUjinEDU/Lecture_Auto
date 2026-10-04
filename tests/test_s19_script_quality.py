"""S19: batch restyle step (opt-in) + --suggest-pron (mock LLM, tmp_path only)."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import scripts.batch_generate_lectures as bgl
from lecture_auto.pipeline.cache import content_hash, write_cache_hash
from lecture_auto.pipeline.restyle import RestyleResult, compute_metrics
from lecture_auto.schemas.lecture_plan import CarryForward, SectionScriptResult, SectionSlideScript


def _section(scripts: dict[int, str]) -> SectionScriptResult:
    return SectionScriptResult(
        section_summary="s",
        carry_forward=CarryForward(explained=["x"], active_example="e", next_question="q"),
        slides=[SectionSlideScript(slide_number=n, target_seconds=30.0, script=t) for n, t in scripts.items()],
    )


def _client() -> MagicMock:
    c = MagicMock()
    c.text_model, c.vlm_model = "t", "v"
    return c


def _fake_restyle(calls: list, keep: set[int] = frozenset()):
    def fn(client, scripts):
        calls.append(dict(scripts))
        out = {}
        for n, t in scripts.items():
            kept = n in keep
            new = t if kept else t + " 요"
            out[n] = RestyleResult(
                original=t, script=new, kept_original=kept, reasons=["x"] if kept else [],
                metrics_before=compute_metrics(t), metrics_after=compute_metrics(new),
            )
        return out
    return fn


def test_restyle_cache_hit_and_invalidation(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(bgl, "restyle_scripts", _fake_restyle(calls))
    path = tmp_path / "section_001.json"
    client = _client()
    res = _section({1: "가나다", 2: "라마바"})

    out, results = bgl._restyle_section_cached(client, res, path)
    assert len(calls) == 1
    assert [s.script for s in out.slides] == ["가나다 요", "라마바 요"]
    assert out.carry_forward == res.carry_forward
    assert (tmp_path / "section_001.restyled.json").exists()

    out2, _ = bgl._restyle_section_cached(client, res, path)  # same section -> cached
    assert len(calls) == 1
    assert [s.script for s in out2.slides] == ["가나다 요", "라마바 요"]

    bgl._restyle_section_cached(client, _section({1: "다른", 2: "라마바"}), path)  # changed -> re-call
    assert len(calls) == 2


def test_kept_original_slide_stays_original(tmp_path, monkeypatch):
    monkeypatch.setattr(bgl, "restyle_scripts", _fake_restyle([], keep={2}))
    out, _ = bgl._restyle_section_cached(_client(), _section({1: "가", 2: "나"}), tmp_path / "section_001.json")
    assert [s.script for s in out.slides] == ["가 요", "나"]


def test_restyled_scripts_written_as_ours_not_hand_edited(tmp_path, monkeypatch):
    monkeypatch.setattr(bgl, "restyle_scripts", _fake_restyle([]))
    out, _ = bgl._restyle_section_cached(_client(), _section({1: "가"}), tmp_path / "section_001.json")
    scripts: dict = {}
    bgl._write_section_scripts(out, tmp_path, scripts)
    p = tmp_path / "script_001.json"
    assert json.loads(p.read_text(encoding="utf-8"))["script"] == "가 요"
    assert bgl._hand_edited(p) is None  # .hash matches
    assert scripts[1]["script"] == "가 요"


def test_hand_edited_slide_not_overwritten(tmp_path):
    p = tmp_path / "script_001.json"
    gen = json.dumps({"slide_number": 1, "script": "원본"}, ensure_ascii=False)
    p.write_text(gen, encoding="utf-8")
    write_cache_hash(p, content_hash(gen))
    p.write_text(json.dumps({"slide_number": 1, "target_seconds": 5, "script": "손으로 고침"}, ensure_ascii=False),
                 encoding="utf-8")
    scripts: dict = {}
    bgl._write_section_scripts(_section({1: "restyle 결과"}), tmp_path, scripts)
    assert json.loads(p.read_text(encoding="utf-8"))["script"] == "손으로 고침"
    assert scripts[1]["script"] == "손으로 고침"


def test_approved_slide_audio_untouched_when_script_changes(tmp_path):
    wav = tmp_path / "slide_001.wav"
    wav.write_bytes(b"APPROVED")
    tts = MagicMock()
    wavs, failed = bgl._synthesize_all_slides(
        tts, 1, {1: {"script": "restyle로 바뀐 대본", "target_seconds": 5}}, tmp_path, b"",
        (0, 1), None, {1}, verify_stt=False,
    )
    assert wavs == [wav] and failed == []
    assert wav.read_bytes() == b"APPROVED"
    tts.assert_not_called()
    assert not list(tmp_path.glob("*.cand.wav"))


def test_restyle_report_written(tmp_path):
    r = RestyleResult(
        original="합니다 합니다", script="그래서 이제요", kept_original=False, reasons=[],
        metrics_before=compute_metrics("합니다 합니다"), metrics_after=compute_metrics("그래서 이제요"),
    )
    lec = tmp_path / "lec"
    lec.mkdir()
    bgl._write_restyle_report(lec, {1: r})
    rep = json.loads((lec / "restyle_report.json").read_text(encoding="utf-8"))
    assert rep["slides"]["1"]["adopted"] is True
    assert rep["lecture_metrics_before"]["formal_per_1000"] > rep["lecture_metrics_after"]["formal_per_1000"]


def test_lectures_have_no_restyle_key_by_default():
    assert not any("restyle" in lec for lec in bgl.LECTURES)


# ---- --suggest-pron ----

def _setup_lec(tmp_path, texts: dict[int, str]):
    item = {"id": "lec"}
    d = tmp_path / "lec" / "scripts"
    d.mkdir(parents=True)
    for n, t in texts.items():
        (d / f"script_{n:03d}.json").write_text(
            json.dumps({"slide_number": n, "script": t}, ensure_ascii=False), encoding="utf-8")
    return item


def _llm(*replies):
    c = MagicMock()
    c.chat.side_effect = list(replies)
    return c


def test_suggest_pron_normal_and_filters(tmp_path, capsys):
    item = _setup_lec(tmp_path, {1: "이번엔 Kanban 보드를 봅니다. Kanban은 쉽습니다. OK 입니다.", 2: "Kanban 다시."})
    reply = json.dumps({"entries": [
        {"written": "Kanban", "spoken": "칸반", "note": "관례"},
        {"written": "OK", "spoken": "OK 입니다", "note": ""},      # latin left -> dropped
        {"written": "Zzz", "spoken": "쥐쥐쥐", "note": ""},          # not requested -> dropped
    ]}, ensure_ascii=False)
    cfg = Path("config/pronunciation.yaml")
    before = cfg.read_bytes() if cfg.exists() else None
    assert bgl._cli_suggest_pron(item, tmp_path, [], _llm("```json\n" + reply + "\n```")) == 0
    import yaml
    data = yaml.safe_load((tmp_path / "lec" / "pronunciation_suggestions.yaml").read_text(encoding="utf-8"))
    assert data["entries"] == [
        {"written": "Kanban", "spoken": "칸반", "note": "관례", "approved": False, "source": "llm"}
    ]
    out = capsys.readouterr().out
    assert "칸반" in out and "제외" in out
    assert (cfg.read_bytes() if cfg.exists() else None) == before


def test_suggest_pron_retries_bad_json_once(tmp_path):
    item = _setup_lec(tmp_path, {1: "Kanban 보드"})
    ok = json.dumps({"entries": [{"written": "Kanban", "spoken": "칸반", "note": ""}]}, ensure_ascii=False)
    llm = _llm("not json", ok)
    bgl._cli_suggest_pron(item, tmp_path, [], llm)
    assert llm.chat.call_count == 2


def test_suggest_pron_no_tokens_no_llm(tmp_path):
    item = _setup_lec(tmp_path, {1: "영어 없음", 2: "API 는 등록됨"})
    llm = _llm()
    entries = [{"written": "API", "spoken": "에이피아이", "approved": True}]
    assert bgl._cli_suggest_pron(item, tmp_path, entries, llm) == 0
    llm.chat.assert_not_called()
    assert not (tmp_path / "lec" / "pronunciation_suggestions.yaml").exists()


def test_suggest_pron_prompt_has_contexts_capped(tmp_path):
    long = "Kanban " + "가" * 300 + "."
    item = _setup_lec(tmp_path, {1: f"{long} 두번째 Kanban 문장. 세번째 Kanban 문장."})
    llm = _llm(json.dumps({"entries": []}))
    bgl._cli_suggest_pron(item, tmp_path, [], llm)
    user = llm.chat.call_args[0][0][1]["content"]
    line = [ln for ln in user.splitlines() if ln.startswith("- Kanban")][0]
    assert line.count(" / ") == 1  # max 2 sentences
    assert max(len(p) for p in line.split(" / ")) <= 120 + len("- Kanban: ")

"""S17: dynamic slide claim, multi --only, --fix-failed, scripts/produce.py.
All synthesis / subprocess calls are mocked."""
from __future__ import annotations

import fcntl
from unittest.mock import MagicMock, patch

import pytest

import scripts.batch_generate_lectures as bgl
import scripts.produce as produce
from lecture_auto.pipeline.cache import qc_path_for, write_cache_hash

SCRIPTS = {1: {"script": "a" * 10, "target_seconds": 5.0},
           2: {"script": "b" * 50, "target_seconds": 5.0},
           3: {"script": "c" * 30, "target_seconds": 5.0}}


def _claim(tmp_path, run_id="r1", approved=frozenset(), target=None):
    return bgl._synthesize_all_slides(
        object(), 3, SCRIPTS, tmp_path, b"ref", (0, 1), target, set(approved), claim=run_id
    )


def test_claim_same_run_skips_other_run_redoes(tmp_path):
    with patch.object(bgl, "_run_slide_tts", return_value=True) as m:
        _claim(tmp_path)
        assert m.call_count == 3
        _claim(tmp_path)
        assert m.call_count == 3
        _claim(tmp_path, "r2")
        assert m.call_count == 6


def test_claim_skips_locked_slide_without_done(tmp_path):
    (tmp_path / ".claim").mkdir()
    f = (tmp_path / ".claim" / "slide_002.lock").open("w")
    fcntl.flock(f, fcntl.LOCK_EX)
    with patch.object(bgl, "_run_slide_tts", return_value=True) as m:
        _claim(tmp_path)
    assert [c.args[1] for c in m.call_args_list] == [3, 1]
    assert not (tmp_path / ".claim" / "slide_002.done").exists()
    f.close()


def test_claim_order_longest_first_paths_in_slide_order(tmp_path):
    with patch.object(bgl, "_run_slide_tts", return_value=True) as m:
        paths, failed = _claim(tmp_path)
    assert [c.args[1] for c in m.call_args_list] == [2, 3, 1]
    assert paths == [tmp_path / f"slide_{n:03d}.wav" for n in (1, 2, 3)]
    assert failed == []


def test_claim_exception_leaves_no_done_and_propagates(tmp_path):
    with patch.object(bgl, "_run_slide_tts", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            _claim(tmp_path)
    assert not list((tmp_path / ".claim").glob("*.done"))
    with patch.object(bgl, "_run_slide_tts", return_value=True) as m:
        _claim(tmp_path)  # lock released: a restarted worker takes it
    assert m.call_count == 3


def test_claim_failure_recorded_done_and_reported(tmp_path):
    with patch.object(bgl, "_run_slide_tts", side_effect=lambda *a, **k: a[1] != 2):
        _, failed = _claim(tmp_path)
    assert failed == [2]
    assert (tmp_path / ".claim" / "slide_002.done").read_text() == "r1"


def test_claim_approved_not_synthesized(tmp_path):
    with patch.object(bgl, "_run_slide_tts", return_value=True) as m:
        _claim(tmp_path, approved={2})
    assert sorted(c.args[1] for c in m.call_args_list) == [1, 3]


def test_claim_and_shard_conflict(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["b.py", "--claim", "r", "--shard", "0/2"])
    with pytest.raises(SystemExit):
        bgl.main()


LECS = [{"id": f"0{i}_x{'ab'[i % 2]}"} for i in range(1, 10)]


def _err(msg):
    raise ValueError(msg)


def test_select_lectures_multi(monkeypatch):
    monkeypatch.setattr(bgl, "LECTURES", LECS)
    assert [l["id"] for l in bgl._select_lectures("7,8", _err)] == ["07_xb", "08_xa"]
    assert [l["id"] for l in bgl._select_lectures("09,02_x,9", _err)] == ["02_xa", "09_xb"]
    assert len(bgl._select_lectures("08", _err)) == 1
    with pytest.raises(ValueError):
        bgl._select_lectures("7,nomatch", _err)
    with pytest.raises(ValueError):
        bgl._select_lectures("7,99", _err)


def test_multi_only_approval_command_needs_exactly_one(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bgl, "LECTURES", LECS)
    monkeypatch.setattr("sys.argv", ["b.py", "--only", "1,2", "--assemble-only"])
    with pytest.raises(SystemExit):
        bgl.main()


def _fix(audio, approved=frozenset(), claim=None):
    return bgl._fix_failed(audio, 3, SCRIPTS, b"ref", set(approved), claim=claim, ts="T")


def _mk(audio, n, key):
    w = audio / f"slide_{n:03d}.wav"
    w.write_bytes(b"x")
    write_cache_hash(w, key)
    qc_path_for(w).write_text("{}")
    return w


def test_fix_failed_moves_only_invalid_unapproved(tmp_path):
    good = bgl._tts_cache_key(SCRIPTS[1]["script"], b"ref", 5.0, ())
    w1 = _mk(tmp_path, 1, good)
    w2 = _mk(tmp_path, 2, "stale")
    w3 = _mk(tmp_path, 3, "stale")
    assert _fix(tmp_path, approved={3}) == [2]
    assert w1.exists() and w3.exists() and not w2.exists()
    d = tmp_path / "failed_T"
    assert (d / "slide_002.wav").exists() and (d / "slide_002.wav.hash").exists()
    assert qc_path_for(d / "slide_002.wav").exists()
    assert "slide_002.wav" in (d / "MOVED.txt").read_text()
    assert _fix(tmp_path, approved={3}) == []


def test_fix_failed_claim_runs_once_per_run(tmp_path):
    w = _mk(tmp_path, 2, "stale")
    assert _fix(tmp_path, claim="r1") == [2]
    w.write_bytes(b"another worker's fresh failed take")
    assert _fix(tmp_path, claim="r1") == []
    assert w.exists()


# ---- produce.py ----

class FakeProc:
    def __init__(self, codes):
        self.codes = list(codes)

    def poll(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]


def _produce(monkeypatch, tmp_path, argv, popen, state="final"):
    monkeypatch.setattr(produce, "LOG_ROOT", tmp_path)
    monkeypatch.setattr(produce, "ROOT", tmp_path)
    monkeypatch.setattr(produce.time, "sleep", lambda s: None)
    monkeypatch.setattr(bgl, "LECTURES", LECS)
    monkeypatch.setattr(produce, "LECTURES", LECS)
    monkeypatch.setattr(produce, "compute_lecture_status", lambda *a: MagicMock(video_state=state))
    monkeypatch.setattr(produce, "_format_status_line", lambda *a: "line")
    run = MagicMock(return_value=MagicMock(returncode=0))
    with patch.object(produce.subprocess, "Popen", popen), patch.object(produce.subprocess, "run", run):
        rc = produce.main(argv)
    return rc, run


def test_produce_worker_count_and_assemble(monkeypatch, tmp_path):
    popen = MagicMock(side_effect=lambda *a, **k: FakeProc([None, 0]))
    rc, run = _produce(monkeypatch, tmp_path, ["--only", "7,8", "--gpus", "0,1", "--workers-per-gpu", "2"], popen)
    assert popen.call_count == 4
    cmds = [c.args[0] for c in popen.call_args_list]
    assert all("--claim" in c for c in cmds)
    assert {c[c.index("--gpu") + 1] for c in cmds} == {"0", "1"}
    assert len([c for c in run.call_args_list if "--assemble-only" in c.args[0]]) == 2
    assert rc == 0


def test_produce_restart_limited(monkeypatch, tmp_path):
    popen = MagicMock(side_effect=lambda *a, **k: FakeProc([1]))
    rc, _ = _produce(monkeypatch, tmp_path, ["--only", "7", "--gpus", "0", "--max-restarts", "2"], popen)
    assert popen.call_count == 3
    assert rc == 1


def test_produce_draft_exit_1(monkeypatch, tmp_path):
    popen = MagicMock(side_effect=lambda *a, **k: FakeProc([0]))
    rc, _ = _produce(monkeypatch, tmp_path, ["--only", "7", "--gpus", "0"], popen, state="draft")
    assert rc == 1


def test_produce_dry_run_executes_nothing(monkeypatch, tmp_path, capsys):
    popen = MagicMock()
    rc, run = _produce(monkeypatch, tmp_path, ["--only", "7,8", "--gpus", "0,1", "--dry-run"], popen)
    popen.assert_not_called()
    run.assert_not_called()
    out = capsys.readouterr().out
    assert "--claim" in out and "--assemble-only" in out and rc == 0

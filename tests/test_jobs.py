from unittest.mock import patch

import pytest
from pydantic import ValidationError

from lecture_auto.core import worker
from lecture_auto.core.jobs import JobSpec, command, read_spec, write_spec


@pytest.mark.parametrize(("spec", "expected"), [
    (JobSpec(kind="scripts", project_id="07_x"), ("batch", ["--only", "07_x", "--skip-tts"])),
    (JobSpec(kind="regen", project_id="07_x", slides=[3, 1, 3]),
     ("batch", ["--only", "07_x", "--slides", "1,3", "--gpu", "0"])),
    (JobSpec(kind="heal", project_id="07_x"), ("batch", ["--only", "07_x", "--heal", "--gpu", "0"])),
    (JobSpec(kind="assemble", project_id="07_x"), ("batch", ["--only", "07_x", "--assemble-only"])),
    (JobSpec(kind="check", project_id="07_x"), ("batch", ["--only", "07_x", "--check"])),
    (JobSpec(kind="produce", project_id="07_x"), ("produce", ["--only", "07_x", "--gpus", "0", "--fix-failed", "--heal"])),
    (JobSpec(kind="produce", project_id="07_x", workers_per_gpu=1),
     ("produce", ["--only", "07_x", "--gpus", "0", "--fix-failed", "--heal", "--workers-per-gpu", "1"])),
])
def test_command_per_kind(spec, expected):
    assert command(spec) == expected


@pytest.mark.parametrize("bad", [{"kind": "nope"}, {"kind": "regen"}, {"kind": "regen", "slides": [0]}, {"extra": 1}])
def test_invalid_spec_is_rejected(bad):
    with pytest.raises(ValidationError):
        JobSpec.model_validate({"kind": "scripts", "project_id": "07_x", **bad})


def test_worker_runs_the_batch_or_produce_entry_point(tmp_path):
    batch_spec, produce_spec = tmp_path / "b.json", tmp_path / "p.json"
    write_spec(JobSpec(kind="assemble", project_id="07_x"), batch_spec)
    write_spec(JobSpec(kind="produce", project_id="07_x"), produce_spec)
    assert read_spec(batch_spec).kind == "assemble"
    with patch("lecture_auto.production.batch.main") as batch_main:
        assert worker.main([str(batch_spec)]) == 0
    batch_main.assert_called_once_with(["--only", "07_x", "--assemble-only"])
    with patch("scripts.produce.main", return_value=1) as produce_main:
        assert worker.main([str(produce_spec)]) == 1
    produce_main.assert_called_once_with(["--only", "07_x", "--gpus", "0", "--fix-failed", "--heal"])
    assert worker.main([]) == 2

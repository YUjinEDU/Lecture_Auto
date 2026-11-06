import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lecture_auto.core.legacy_lectures import BUILTIN_LECTURES
from lecture_auto.core.migrate import migrate
from lecture_auto.core.project import (
    ProjectConfig,
    delete_project,
    load_projects,
    new_lecture_id,
    save_project,
)

ROOT = Path(__file__).resolve().parent.parent


def _batch_lecture_ids(env: dict[str, str]) -> list[str]:
    code = "import json, lecture_auto.production.batch as b; print(json.dumps([l['id'] for l in b.LECTURES]))"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
        env={**os.environ, **env},
    )
    return json.loads(out.stdout)


def test_save_load_delete_roundtrip(tmp_path):
    p = ProjectConfig(id="12_x", name="x", subject="s", pptx="data/web/uploads/12_x/a.pptx", web=True)
    path = save_project(p, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["pptx"] == "data/web/uploads/12_x/a.pptx"
    assert load_projects(tmp_path) == [p]
    delete_project("12_x", tmp_path)
    assert load_projects(tmp_path) == []
    assert not (tmp_path / "12_x").exists()


def test_projects_load_in_id_order(tmp_path):
    for i in ("10_b", "02_a", "11_c"):
        save_project(ProjectConfig(id=i, name=i, subject="s"), tmp_path)
    assert [p.id for p in load_projects(tmp_path)] == ["02_a", "10_b", "11_c"]


def test_as_item_matches_the_old_lectures_dict_shape():
    item = ProjectConfig(id="05_x", name="n", subject="s", pdf="a.pdf", voice_match=True).as_item()
    assert item == {"id": "05_x", "name": "n", "subject": "s", "pdf": Path("a.pdf"), "voice_match": True}


@pytest.mark.parametrize("bad", [{"id": "../x"}, {"id": "a b"}, {"typo_key": 1}])
def test_invalid_project_is_rejected(bad):
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate({"id": "01_x", "name": "n", "subject": "s", **bad})


def test_new_id_takes_the_next_free_number():
    existing = ["01_a", "11_종합설계_07_시스템구조_30분이상"]
    assert new_lecture_id("06 Product/Backlog", existing) == "12_06_Product_Backlog"
    assert new_lecture_id("x", ["12_x_y", "11_q"]) == "13_x"
    assert new_lecture_id("x", ["13_x", "12_y"]) == "14_x"


def test_migrate_writes_builtins_and_registry_once(tmp_path):
    reg = tmp_path / "lectures.json"
    reg.write_text(json.dumps([{"id": "99_webtest", "name": "w", "subject": "s", "pdf": "a.pdf", "created_at": "t"}]))
    root = tmp_path / "projects"
    written = migrate(root, reg)
    assert written == [lec["id"] for lec in BUILTIN_LECTURES] + ["99_webtest"]
    projects = {p.id: p for p in load_projects(root)}
    assert projects["99_webtest"].web is True
    assert [projects[lec["id"]].as_item() for lec in BUILTIN_LECTURES] == BUILTIN_LECTURES
    assert migrate(root, reg) == []


def test_batch_reads_projects_when_present(tmp_path):
    save_project(ProjectConfig(id="99_only", name="o", subject="s", pdf="a.pdf"), tmp_path)
    assert _batch_lecture_ids({"LECTURE_AUTO_PROJECTS": str(tmp_path)}) == ["99_only"]


def test_batch_has_no_lectures_without_projects(tmp_path):
    assert _batch_lecture_ids({"LECTURE_AUTO_PROJECTS": str(tmp_path / "none")}) == []

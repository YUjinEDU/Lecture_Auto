"""Build a private, reproducible blind comparison in a fresh sandbox.

Run from the critic worktree with the repository Python:
python -m scripts.evaluate_script_quality --source /tmp/gem_root --root /tmp/ab_root
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv

from lecture_auto.core.jobs import JobSpec, write_spec
from lecture_auto.core.project import ProjectConfig, save_project
from lecture_auto.core.worker import main as worker_main
from lecture_auto.llm import get_llm_client
from lecture_auto.pipeline.cache import write_text_atomic
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.style_profile import build_style_profile
from lecture_auto.production.style_profiles import StyleProfiles
from scripts.script_quality_metrics import evaluate

LECTURE = "91_gemini_test"


def main() -> None:
    parser = argparse.ArgumentParser(description="대본 품질 블라인드 비교")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--metrics-only", action="store_true", help="생성된 사본의 최종 평가만 재개")
    args = parser.parse_args()
    code = Path(__file__).resolve().parents[1]
    load_dotenv(code / ".env", override=True)
    root, source = args.root.resolve(), args.source.resolve()
    if args.metrics_only:
        os.chdir(root)
        work = root / "data/work_batch" / LECTURE
        timings = json.loads((root / "timings.json").read_text())
        start = time.monotonic()
        metrics = evaluate(get_llm_client(), root, parse_pdf(next((work / "input").glob("*.pdf"))))
        metrics["wall_times"] = {**timings, "final_evaluation_seconds": time.monotonic() - start}
        write_text_atomic(root / "metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2))
        print("AB_EVALUATION_COMPLETE", flush=True)
        return
    if root == source or root.is_relative_to(source):
        parser.error("평가 폴더는 원본 밖의 새 경로여야 합니다")
    root.mkdir()
    started = time.monotonic()
    work = root / "data/work_batch" / LECTURE
    shutil.copytree(source / "data/work_batch" / LECTURE, work)
    shutil.copytree(source / "data/projects" / LECTURE, root / "data/projects" / LECTURE)
    shutil.copytree(work / "scripts", root / "baseline_scripts")
    for relative in ("config", "data/PDF", "data/audio_ref"):
        target = source / relative
        if target.exists():
            (root / relative).symlink_to(target.resolve(), target_is_directory=True)
    project = ProjectConfig.model_validate_json((root / "data/projects" / LECTURE / "project.json").read_text())
    # Relative project input paths resolve through read-only input links; the work copy is independent.
    os.chdir(root)
    os.environ["LECTURE_AUTO_PROJECTS"] = str(root / "data/projects")
    timings = {"copy_seconds": time.monotonic() - started, "baseline_generation_seconds": None}
    client = get_llm_client()
    start = time.monotonic()
    profile = build_style_profile(client, (code / "data/transcripts/professor_full_lecture_32min.txt").read_text())
    profile_id = StyleProfiles(root, project.owner).save(profile)
    write_text_atomic(root / "style_compact.txt", profile.compact())
    timings["style_profile_seconds"] = time.monotonic() - start
    project = project.model_copy(update={"critic": True, "style_profile": profile_id})
    save_project(project, root / "data/projects")
    for kind in ("intent", "scripts"):
        spec = root / f"{kind}_job.json"
        write_spec(JobSpec(kind=kind, project_id=LECTURE), spec)
        start = time.monotonic()
        worker_main([str(spec)])
        timings[f"{kind}_job_seconds"] = time.monotonic() - start
        write_text_atomic(root / "timings.json", json.dumps(timings, indent=2))
    pdf = next((work / "input").glob("*.pdf"))
    slides = parse_pdf(pdf)
    metrics = evaluate(client, root, slides)
    metrics["wall_times"] = {**timings, "total_seconds": time.monotonic() - started}
    write_text_atomic(root / "metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2))
    print("AB_EVALUATION_COMPLETE", flush=True)


if __name__ == "__main__":
    main()

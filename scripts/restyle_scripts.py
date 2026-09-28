"""S12-b CLI: rewrite a lecture's already-generated slide scripts into the
professor's spoken register, content unchanged (see restyle.py / SPEC.md).

Usage:
    python scripts/restyle_scripts.py --lecture-dir data/work_batch/<id> [--dry-run]

Section grouping comes from ``<lecture-dir>/lecture_plan.json``'s ``sections``
(falls back to 4-slide chunks if the plan is absent). Slides already recorded
in ``approved.json`` are skipped -- their approved audio must not drift out of
sync with the script text.

A real (non-dry-run) run backs up ``scripts/`` to ``scripts_orig_<YYYYMMDD>/``
once (refuses to run again the same day, so a second run can't overwrite the
one backup that still has the pre-restyle text) and then replaces only the
``script`` field of each adopted slide's ``script_NNN.json``, atomically. The
``.hash`` sidecar is deliberately left untouched: batch_generate_lectures.py's
``_hand_edited()`` then sees the content/hash mismatch and treats the slide as
human-edited, keeping the new text and resynthesizing only that slide's audio.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

from lecture_auto.llm import LLMClient, get_llm_client
from lecture_auto.pipeline.approval import load_approvals
from lecture_auto.pipeline.cache import write_text_atomic
from lecture_auto.pipeline.restyle import RestyleResult, compute_metrics, restyle_scripts


def _load_slide_data(scripts_dir: Path) -> dict[int, dict]:
    slide_data: dict[int, dict] = {}
    for path in sorted(scripts_dir.glob("script_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        slide_data[int(data["slide_number"])] = data
    return slide_data


def _load_sections(lecture_dir: Path, slide_numbers: list[int]) -> list[list[int]]:
    """Section groupings from lecture_plan.json's ``sections``, else 4-slide chunks."""
    plan_path = lecture_dir / "lecture_plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        sections = [list(s["slides"]) for s in plan.get("sections", [])]
        covered = {n for section in sections for n in section}
        leftover = [n for n in slide_numbers if n not in covered]
        if leftover:
            sections.append(leftover)
        return sections
    return [slide_numbers[i : i + 4] for i in range(0, len(slide_numbers), 4)]


def _lecture_metrics(slide_data: dict[int, dict], results: dict[int, RestyleResult], after: bool) -> dict[str, float]:
    """SPEC's "강의 전체 지표" -- computed on the whole lecture's text joined
    together (per-1000-char rates, like the SPEC table), not an average of
    per-slide rates (which would let short cover slides dominate).
    """
    parts = []
    for n in sorted(slide_data):
        result = results.get(n)
        parts.append(result.script if (after and result is not None) else slide_data[n]["script"])
    return compute_metrics("".join(parts))


def _print_table(results: dict[int, RestyleResult]) -> None:
    for n in sorted(results):
        r = results[n]
        status = "kept" if r.kept_original else "adopted"
        print(
            f"{n:>4}  {status:8}  "
            f"formal {r.metrics_before['formal_per_1000']:.1f}->{r.metrics_after['formal_per_1000']:.1f}  "
            f"{r.reasons}"
        )


def run(lecture_dir: Path, dry_run: bool, client: LLMClient | None = None) -> dict[int, RestyleResult]:
    lecture_dir = Path(lecture_dir)
    scripts_dir = lecture_dir / "scripts"
    backup_dir = lecture_dir / f"scripts_orig_{dt.date.today():%Y%m%d}"
    if not dry_run and backup_dir.exists():
        raise FileExistsError(f"{backup_dir} already exists -- refusing to overwrite a previous backup")

    slide_data = _load_slide_data(scripts_dir)
    if not slide_data:
        raise FileNotFoundError(f"no script_*.json under {scripts_dir}")

    approved = set(load_approvals(lecture_dir, lecture_dir.name).slides.keys())
    slide_numbers = sorted(n for n in slide_data if n not in approved)
    sections = _load_sections(lecture_dir, slide_numbers)

    client = client or get_llm_client()
    all_results: dict[int, RestyleResult] = {}
    for section_slides in sections:
        section_scripts = {n: slide_data[n]["script"] for n in section_slides if n in slide_data and n not in approved}
        if not section_scripts:
            continue
        all_results.update(restyle_scripts(client, section_scripts))

    if dry_run:
        _print_table(all_results)
        return all_results

    shutil.copytree(scripts_dir, backup_dir)

    for n, result in all_results.items():
        if result.kept_original:
            continue
        data = dict(slide_data[n])
        data["script"] = result.script
        write_text_atomic(scripts_dir / f"script_{n:03d}.json", json.dumps(data, ensure_ascii=False, indent=2))

    report = {
        "lecture_id": lecture_dir.name,
        "slides": {
            str(n): {
                "adopted": not r.kept_original,
                "reasons": r.reasons,
                "metrics_before": r.metrics_before,
                "metrics_after": r.metrics_after,
            }
            for n, r in all_results.items()
        },
        "lecture_metrics_before": _lecture_metrics(slide_data, all_results, after=False),
        "lecture_metrics_after": _lecture_metrics(slide_data, all_results, after=True),
    }
    write_text_atomic(lecture_dir / "restyle_report.json", json.dumps(report, ensure_ascii=False, indent=2))
    return all_results


def main() -> None:
    parser = argparse.ArgumentParser(description="S12: rewrite slide scripts into spoken register (content preserved)")
    parser.add_argument("--lecture-dir", type=Path, required=True, help="e.g. data/work_batch/<id>")
    parser.add_argument("--dry-run", action="store_true", help="Print the result table; write no files")
    args = parser.parse_args()
    run(args.lecture_dir, args.dry_run)


if __name__ == "__main__":
    main()

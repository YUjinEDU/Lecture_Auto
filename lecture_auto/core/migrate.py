"""One-time move of the lecture list into ``project.json`` files.

    python -m lecture_auto.core.migrate [--projects-dir data/projects] [--registry data/web/lectures.json]

Writes every built-in lecture and every web-registered one; an id that already has a
``project.json`` is left alone, so re-running is safe.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lecture_auto.core.legacy_lectures import BUILTIN_LECTURES
from lecture_auto.core.project import (
    ProjectConfig,
    load_projects,
    projects_dir,
    save_project,
)
from lecture_auto.web.registry import load_web_lectures, registry_path


def migrate(root: Path, registry: Path) -> list[str]:
    existing = {p.id for p in load_projects(root)}
    written = []
    for item in [*BUILTIN_LECTURES, *load_web_lectures(registry)]:
        if item["id"] in existing:
            continue
        save_project(ProjectConfig.model_validate(item), root)
        existing.add(item["id"])
        written.append(item["id"])
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write project.json for every known lecture")
    parser.add_argument("--projects-dir", type=Path, default=None)
    parser.add_argument("--registry", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.projects_dir or projects_dir()
    written = migrate(root, args.registry or registry_path())
    print(f"{len(written)} project(s) written to {root}: {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

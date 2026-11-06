"""One-time move of the lecture list into ``project.json`` files.

    python -m lecture_auto.core.migrate [--projects-dir data/projects] [--registry data/web/lectures.json]

Writes every built-in lecture and every web-registered one; an id that already has a
``project.json`` is left alone, so re-running is safe.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lecture_auto.core.legacy_lectures import BUILTIN_LECTURES
from lecture_auto.core.project import (
    ProjectConfig,
    load_projects,
    projects_dir,
    save_project,
)

DEFAULT_REGISTRY = Path("data/web/lectures.json")


def _web_registry(path: Path) -> list[dict]:
    """The web UI's old lecture list (``data/web/lectures.json``), entries marked ``web``."""
    if not path.exists():
        return []
    return [{**entry, "web": True} for entry in json.loads(path.read_text(encoding="utf-8"))]


def migrate(root: Path, registry: Path = DEFAULT_REGISTRY) -> list[str]:
    existing = {p.id for p in load_projects(root)}
    written = []
    for item in [*BUILTIN_LECTURES, *_web_registry(registry)]:
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
    written = migrate(root, args.registry or DEFAULT_REGISTRY)
    print(f"{len(written)} project(s) written to {root}: {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

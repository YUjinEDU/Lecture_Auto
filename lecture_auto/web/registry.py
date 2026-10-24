"""Lectures registered from the web UI.

Built-in lectures stay in ``scripts/batch_generate_lectures.LECTURES``; the ones a
professor adds through the web UI live in a JSON file (default
``data/web/lectures.json``, override with ``LECTURE_AUTO_WEB_REGISTRY``) so that
the batch CLI started by the web job runner sees them too.

Each stored entry is a plain dict with the same keys as a ``LECTURES`` entry;
path-valued keys are stored as strings relative to the repository root and
loaded back as ``Path``. Loaded entries carry ``"web": True``.

No web framework imports here: the batch CLI imports this module.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REGISTRY_ENV = "LECTURE_AUTO_WEB_REGISTRY"
DEFAULT_REGISTRY = Path("data/web/lectures.json")
PATH_KEYS = ("pdf", "pptx", "reference_script", "ref_voice")


def registry_path() -> Path:
    return Path(os.environ.get(REGISTRY_ENV, str(DEFAULT_REGISTRY)))


def load_web_lectures(path: Path | None = None) -> list[dict]:
    path = registry_path() if path is None else path
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for entry in raw:
        item = dict(entry)
        for key in PATH_KEYS:
            if item.get(key) is not None:
                item[key] = Path(item[key])
        item["web"] = True
        out.append(item)
    return out


def save_web_lectures(entries: list[dict], path: Path | None = None) -> None:
    path = registry_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for entry in entries:
        item = {k: v for k, v in entry.items() if k != "web"}
        for key in PATH_KEYS:
            if item.get(key) is not None:
                item[key] = str(item[key])
        serializable.append(item)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


_UNSAFE = re.compile(r"[^0-9A-Za-z가-힣_-]+")


def new_lecture_id(name: str, existing_ids: list[str]) -> str:
    """``NN_<name>`` with the next free number; never a substring of an existing id
    (the CLI's ``--only`` matches by substring) and vice versa."""
    slug = _UNSAFE.sub("_", name).strip("_")[:40] or "lecture"
    numbers = [int(m.group(1)) for i in existing_ids if (m := re.match(r"^(\d+)_", i))]
    n = max(numbers, default=0) + 1
    while True:
        candidate = f"{n:02d}_{slug}"
        if not any(candidate in i or i in candidate for i in existing_ids):
            return candidate
        n += 1

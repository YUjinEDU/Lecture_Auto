"""Read-only views over the batch pipeline's files, plus the one write the web UI
does directly: a professor's script edit (everything else goes through the CLI)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from lecture_auto.core.project import DEFAULT_REF_VOICE, load_projects
from lecture_auto.pipeline.approval import load_approvals
from lecture_auto.pipeline.cache import (
    cache_path_for,
    content_hash,
    qc_path_for,
    write_cache_hash,
    write_text_atomic,
)
from lecture_auto.pipeline.pronunciation import load_pronunciation_entries
from lecture_auto.production import batch as bgl
from lecture_auto.web.settings import Settings

_NUM = re.compile(r"_(\d{3})\.")
OUTPUT_SUFFIXES = {".mp4", ".md", ".json", ".srt", ".vtt"}


class LectureNotFound(KeyError):
    pass


def all_lectures(settings: Settings) -> list[dict]:
    return [p.as_item() for p in load_projects(settings.projects_dir)]


def get_lecture(settings: Settings, lecture_id: str) -> dict:
    for lec in all_lectures(settings):
        if lec["id"] == lecture_id:
            return lec
    raise LectureNotFound(lecture_id)


def ref_voice_path(settings: Settings, item: dict) -> Path:
    return settings.root / Path(item.get("ref_voice") or DEFAULT_REF_VOICE)


def pronunciation_entries(settings: Settings) -> list[dict]:
    return load_pronunciation_entries(settings.root / "config" / "pronunciation.yaml")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_scripts(work: Path) -> dict[int, dict]:
    scripts = {}
    for f in sorted((work / "scripts").glob("script_*.json")):
        data = _read_json(f)
        if data is not None:
            scripts[int(f.stem.rsplit("_", 1)[1])] = data
    return scripts


def _invalid(settings: Settings, item: dict, scripts: dict[int, dict]) -> set[int]:
    audio = settings.work_dir / item["id"] / "audio"
    ref_bytes = bgl._ref_voice_bytes({**item, "ref_voice": ref_voice_path(settings, item)})
    wavs = {n: audio / f"slide_{n:03d}.wav" for n in scripts}
    return set(bgl._invalid_slides(sorted(scripts), wavs, scripts, ref_bytes, pronunciation_entries(settings)))


def output_files(settings: Settings, lecture_id: str) -> list[dict]:
    out = settings.output_dir / lecture_id
    if not out.is_dir():
        return []
    return [
        {"name": p.name, "bytes": p.stat().st_size, "mtime": p.stat().st_mtime}
        for p in sorted(out.iterdir())
        if p.is_file() and p.suffix in OUTPUT_SUFFIXES
    ]


def lecture_summary(settings: Settings, item: dict) -> dict:
    st = bgl.compute_lecture_status(item, settings.work_dir, settings.output_dir)
    work = settings.work_dir / item["id"]
    scripts = _load_scripts(work)
    approved = set(load_approvals(work, item["id"]).slides) if work.exists() else set()
    pending = (_invalid(settings, item, scripts) - approved) if scripts else set()
    # The batch counts a slide with no audio at all among the ones holding a lecture
    # back from being final, which is right for it and wrong for the professor: "listen
    # to it and approve" is impossible before any audio exists.
    missing = sorted(n for n in pending if not (work / "audio" / f"slide_{n:03d}.wav").exists())
    held = sorted(pending - set(missing))
    return {
        "id": item["id"],
        "name": item.get("name", item["id"]),
        "subject": item.get("subject", ""),
        "web": bool(item.get("web")),
        "target_minutes": item.get("target_minutes"),
        "min_minutes": item.get("min_minutes"),
        "slides": st.slides,
        "scripts": st.scripts,
        "audio": st.audio,
        "qc_fail": st.qc_fail,
        "candidates": st.candidates,
        "approved": st.approved,
        "held_back": held,
        "no_audio": missing,
        "video_state": st.video_state,
        "video": st.video_path.name if st.video_path else None,
        "script_chars": sum(len(s.get("script", "")) for s in scripts.values()),
        "files": output_files(settings, item["id"]),
    }


def _qc_view(path: Path) -> dict | None:
    data = _read_json(path)
    if data is None:
        return None
    stt = data.get("stt") or {}
    return {
        "ok": data.get("ok"),
        "gate_reasons": data.get("gate_reasons", []),
        "stt_status": stt.get("status"),
        "cer": stt.get("cer"),
        "transcript": stt.get("transcript"),
        "failing_segments": [
            {"index": s.get("index"), "text": s.get("text"), "cer": s.get("cer"), "stt_status": s.get("stt_status")}
            for s in data.get("segments", [])
            if s.get("fallback") or s.get("stt_status") not in (None, "pass")
        ],
    }


def slide_views(settings: Settings, item: dict) -> list[dict]:
    work = settings.work_dir / item["id"]
    audio = work / "audio"
    scripts = _load_scripts(work)
    pngs = {int(m.group(1)) for p in (work / "rendered").glob("slide_*.png") if (m := _NUM.search(p.name))}
    numbers = sorted(set(scripts) | pngs)
    invalid = _invalid(settings, item, scripts) if scripts else set()
    approvals = load_approvals(work, item["id"]).slides if work.exists() else {}
    views = []
    for n in numbers:
        wav = audio / f"slide_{n:03d}.wav"
        cand = audio / f"slide_{n:03d}.cand.wav"
        cand_info = _read_json(audio / f"slide_{n:03d}.cand.wav.json") if cand.exists() else None
        script_path = work / "scripts" / f"script_{n:03d}.json"
        appr = approvals.get(n)
        has_audio = wav.exists()
        if appr is not None:
            state = "approved"
        elif not has_audio:
            state = "no_audio"
        elif n not in invalid:
            state = "pass"
        else:
            state = "held"
        sc = scripts.get(n, {})
        views.append({
            "number": n,
            "image": n in pngs,
            "script": sc.get("script"),
            "target_seconds": sc.get("target_seconds"),
            "hand_edited": bgl._hand_edited(script_path) is not None,
            "audio": has_audio,
            "candidate": cand_info is not None,
            "candidate_ok": bool(cand_info and cand_info.get("ok")),
            "previous": (audio / f"slide_{n:03d}.prev.wav").exists(),
            "state": state,
            "qc": _qc_view(qc_path_for(wav)) if has_audio else None,
            "candidate_qc": _qc_view(qc_path_for(cand)) if cand_info is not None else None,
            "approval": appr.model_dump(mode="json") if appr is not None else None,
        })
    return views


def save_script(settings: Settings, item: dict, number: int, text: str) -> dict:
    """Write the professor's edit so the pipeline treats it as a hand edit: the
    ``.hash`` sidecar must keep the hash of the *previous* (generated) text, or the
    next script generation overwrites the edit."""
    path = settings.work_dir / item["id"] / "scripts" / f"script_{number:03d}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    previous = path.read_text(encoding="utf-8")
    if not cache_path_for(path).exists():
        write_cache_hash(path, content_hash(previous))
    data = json.loads(previous)
    data["script"] = text
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
    return data

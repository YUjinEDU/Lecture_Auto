"""Intent artifact persistence and deck preparation for the intent job."""
from __future__ import annotations

import fcntl
from pathlib import Path

from lecture_auto.llm import LLMClient
from lecture_auto.pipeline.cache import write_text_atomic
from lecture_auto.pipeline.intent import IntentDraftInput, draft_intent
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.renderer import render_slides
from lecture_auto.schemas.intent import IntentSheet


class EditedIntentError(ValueError):
    def __init__(self):
        super().__init__("수정한 의도 시트가 있습니다. 다시 만들려면 force=true로 확인하세요")


def load_intent(work: Path) -> IntentSheet | None:
    path = work / "intent.json"
    return IntentSheet.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def save_intent(work: Path, sheet: IntentSheet) -> None:
    write_text_atomic(work / "intent.json", sheet.model_dump_json(indent=2))


def generate_intent_job(client: LLMClient, source: IntentDraftInput, work: Path, *, force: bool = False) -> IntentSheet:
    current = load_intent(work)
    if current is not None and current.edited and not force:
        raise EditedIntentError()
    sheet = draft_intent(client, source)
    save_intent(work, sheet)
    return sheet


def prepare_intent_job(item: dict, client: LLMClient, base_work: Path, *, force: bool = False) -> IntentSheet:
    from lecture_auto.production.batch import TARGET_MINUTES, _resolve_pdf_input

    work = base_work / item["id"]
    work.mkdir(parents=True, exist_ok=True)
    with (work / ".prep.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = load_intent(work)
        if current is not None and current.edited and not force:
            raise EditedIntentError()
        (work / "input").mkdir(exist_ok=True)
        pdf = _resolve_pdf_input(item, work / "input", item["id"])
        slides = parse_pdf(pdf)
        render_slides(pdf, work / "rendered", item["id"])
        notes = {
            int(p.stem.rsplit("_", 1)[1]): p.read_text(encoding="utf-8")
            for p in sorted((work / "vlm").glob("*.json"))
            if p.stem.rsplit("_", 1)[-1].isdigit()
        }
        source = IntentDraftInput(
            lecture_id=item["id"], name=item["name"], subject=item["subject"],
            slides=slides, target_minutes=item.get("target_minutes") or TARGET_MINUTES,
            visual_notes=notes,
        )
        return generate_intent_job(client, source, work, force=force)

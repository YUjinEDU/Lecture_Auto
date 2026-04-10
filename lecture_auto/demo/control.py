from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from lecture_auto.demo.state import append_event, update_metadata

_STOP_FLAGS: dict[str, threading.Event] = {}


def _get_stop_flag(job_id: str) -> threading.Event:
    if job_id not in _STOP_FLAGS:
        _STOP_FLAGS[job_id] = threading.Event()
    return _STOP_FLAGS[job_id]


def request_stop(job_id: str) -> None:
    """Signal a running pipeline to stop at the next checkpoint."""
    _get_stop_flag(job_id).set()
    update_metadata(job_id, status="stopping")
    append_event(job_id, "pipeline", "사용자가 중지를 요청했습니다. 현재 단계 완료 후 중지됩니다.")


def _clear_stop_flag(job_id: str) -> None:
    _STOP_FLAGS.pop(job_id, None)


def _check_stop(job_id: str, current_stage: str) -> None:
    """Raise StopIteration if stop was requested for this job."""
    if _get_stop_flag(job_id).is_set():
        raise StopIteration(f"사용자 요청으로 파이프라인이 {current_stage} 단계에서 중지되었습니다.")

"""Demo pipeline package for the presentation-friendly local workflow."""

from .jobs import (
    create_demo_job,
    get_demo_job_paths,
    save_uploaded_pdf,
    save_voice_reference,
    restore_job_from_disk,
    restore_all_jobs_from_disk,
    _resolve_voice_reference,
)
from .control import request_stop
from .orchestration import (
    launch_demo_pipeline,
    launch_rerun,
    update_script_and_rebuild,
    update_glossary,
    rerun_tts_only,
    rerun_video_only,
)

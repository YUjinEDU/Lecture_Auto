from pathlib import Path
import os


class JobPaths:
    SUBDIRS = ("input", "parsed", "rendered", "vlm", "scripts", "audio", "logs", "artifacts")

    def __init__(self, job_id: str, root: Path | None = None):
        self.job_id = job_id
        self.root = root or Path(os.environ.get("JOB_OUTPUT_ROOT", "/data/work"))
        self.job_dir = self.root / job_id

    def ensure_dirs(self) -> "JobPaths":
        for sub in self.SUBDIRS:
            (self.job_dir / sub).mkdir(parents=True, exist_ok=True)
        return self

    @property
    def input_dir(self) -> Path:
        return self.job_dir / "input"

    @property
    def parsed_dir(self) -> Path:
        return self.job_dir / "parsed"

    @property
    def rendered_dir(self) -> Path:
        return self.job_dir / "rendered"

    @property
    def vlm_dir(self) -> Path:
        return self.job_dir / "vlm"

    @property
    def scripts_dir(self) -> Path:
        return self.job_dir / "scripts"

    @property
    def audio_dir(self) -> Path:
        return self.job_dir / "audio"

    @property
    def logs_dir(self) -> Path:
        return self.job_dir / "logs"

    @property
    def artifacts_dir(self) -> Path:
        return self.job_dir / "artifacts"

    @property
    def manifest_path(self) -> Path:
        return self.parsed_dir / "manifest.json"

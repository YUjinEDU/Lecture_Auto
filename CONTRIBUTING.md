# Contributing to Lecture Auto

Thanks for helping! Issues and pull requests are welcome in Korean or English.

## Dev setup

```bash
git clone https://github.com/YUjinEDU/Lecture_Auto.git && cd Lecture_Auto
uv sync --extra dev            # add --all-extras on a CUDA box for Raon TTS
uv run pytest -q               # no GPU, network or API key needed: heavy externals are mocked
uvx ruff check .
```

System tools for real runs: LibreOffice (`soffice`), poppler (`pdftoppm`), `ffmpeg`.

## Ground rules

- **Reproducible**: same input + same settings must give the same artifacts (inputs are keyed by SHA-256).
- **Reviewable**: scripts stay plain text/JSON a professor can edit by hand.
- **Opt-in features keep old outputs byte-identical**: a lecture that does not enable a new
  option must keep the same prompts and cache keys.
- Pydantic v2 at module boundaries; atomic JSON writes (`.tmp` + rename).
- Every behavior change comes with a test next to its module in `tests/`; CI runs ruff + pytest.

## Pull requests

1. Branch from `master`, keep the change focused.
2. `uvx ruff check .` and `uv run pytest -q` must pass.
3. Describe what changed, why, and how you verified it (the PR template asks for this).

By contributing you agree your work is released under the MIT License.

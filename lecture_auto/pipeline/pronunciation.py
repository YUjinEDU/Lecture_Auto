"""Pronunciation dictionary for TTS (S6-d).

Screen text (``written``) can be read wrong by the TTS model (e.g. "API"
sounded out letter-by-letter in English instead of "에이피아이"). Entries are
professor-approved overrides applied only right before synthesis -- the
script text on disk is never rewritten (S6 SPEC: "합성 직전에만
spoken_text = apply_pronunciation(script) 사용").
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_BOUNDARY = r"(?<![A-Za-z0-9])(?:{})(?![A-Za-z0-9])"
# Word-boundary via \b breaks on Hangul: Python's re treats Korean syllables
# as \w, so \bAPI\b fails to match "API를" (no non-word char between "API"
# and the following particle). Anchoring on "not ASCII alnum" instead makes
# the boundary check care only about accidentally matching inside a longer
# ASCII token (e.g. "APIs", "RAPID"), which is the actual risk for terms like
# "API" -- Korean particles glued directly after are exactly the normal case
# and must still match.


def load_pronunciation_entries(path: Path) -> list[dict]:
    """Load ``config/pronunciation.yaml``'s ``entries`` list, or ``[]`` if the
    file doesn't exist."""
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("entries") or []


def apply_pronunciation(text: str, entries: list[dict]) -> str:
    """Replace approved ``written`` terms with their ``spoken`` form.

    Only entries with ``approved: true`` are applied. Matches are on ASCII
    word boundaries (not inside a longer alnum run, e.g. "APIs"/"RAPID" are
    left untouched), and longer ``written`` terms are tried before shorter
    ones that could otherwise shadow them. Pure function: never touches the
    original script text on disk.
    """
    approved = [e for e in entries if e.get("approved") and e.get("written")]
    if not approved:
        return text
    approved.sort(key=lambda e: len(e["written"]), reverse=True)
    spoken_by_written = {e["written"]: e["spoken"] for e in approved}
    pattern = "|".join(re.escape(w) for w in spoken_by_written)
    regex = re.compile(_BOUNDARY.format(pattern))
    return regex.sub(lambda m: spoken_by_written[m.group(0)], text)

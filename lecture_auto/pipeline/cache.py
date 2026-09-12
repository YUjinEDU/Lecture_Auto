"""Content-hash caching for expensive generated artifacts (LLM scripts, TTS audio).

Deciding "is this cached?" by file existence alone means a changed prompt,
reference voice, or model setting silently keeps serving the stale output
forever, and a corrupt/truncated file (e.g. >1KB but still garbage) counts
as valid. Instead, hash the actual inputs that produced the artifact and
compare against a sidecar hash file written alongside it.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def content_hash(*parts: bytes | str) -> str:
    """SHA-256 over all parts in order. Order and part boundaries matter."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8") if isinstance(part, str) else part)
        h.update(b"\x00")
    return h.hexdigest()


def cache_path_for(artifact_path: Path) -> Path:
    return artifact_path.with_name(artifact_path.name + ".hash")


def is_cache_valid(artifact_path: Path, expected_hash: str) -> bool:
    """True if artifact_path exists, is non-empty, and its sidecar hash matches.

    The hash proves the *inputs* are unchanged; it says nothing about whether
    the artifact itself was written completely. Writing the sidecar only after
    the artifact (see ``write_cache_hash``) is what makes a zero-byte or
    half-written artifact fail this check rather than be served as valid.
    """
    hash_path = cache_path_for(artifact_path)
    if not artifact_path.exists() or not hash_path.exists():
        return False
    if artifact_path.stat().st_size == 0:
        return False
    return hash_path.read_text(encoding="utf-8").strip() == expected_hash


def write_cache_hash(artifact_path: Path, hash_value: str) -> None:
    """Write the sidecar hash. Call only AFTER the artifact is fully written."""
    write_text_atomic(cache_path_for(artifact_path), hash_value)


def write_text_atomic(path: Path, text: str) -> None:
    """Write via a .tmp sibling then rename, per the project's artifact rule.

    A plain write that dies midway leaves a truncated file that still exists
    and still has a matching sidecar, which the cache would then accept.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

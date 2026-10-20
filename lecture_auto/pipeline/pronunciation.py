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


_HYPHEN_DIGITS = re.compile(r"^([A-Za-z]+)-(\d+)$")


def normalize_transcript(text: str, entries: list[dict]) -> str:
    """Rewrite Latin terms in an STT transcript to their dictionary spoken form.

    The TTS is asked to say ``spoken`` (e.g. "에이피아이"), but the STT writes
    what it hears in its own orthography ("API", "US11"). Comparing the two
    as-is counts every such term as errors, so a correctly read sentence fails
    the fidelity gate. Entries like "US-11" also match the hyphen-less
    spelling "US11" that STT tends to produce, and single Latin words match in
    either case (STT writes "get" for an entry "GET"). Comparison-only: the
    stored transcript is left as the STT returned it.
    """
    taken = {e.get("written") for e in entries}
    variants = []
    for e in entries:
        written = e.get("written") or ""
        forms = set()
        if m := _HYPHEN_DIGITS.match(written):
            forms.add(m.group(1) + m.group(2))
        if written.isascii() and written.isalpha():
            forms |= {written.lower(), written.upper()}
        variants += [{**e, "written": f} for f in forms if f not in taken]
    return apply_pronunciation(text, list(entries) + variants)


_RISK_PATH = re.compile(r"(?<![A-Za-z0-9가-힣])/[A-Za-z{가-힣][^\s,)]*")
_RISK_DOTTED = re.compile(r"[A-Za-z가-힣]\.[A-Za-z가-힣][A-Za-z0-9가-힣]*")
_RISK_SYMBOL = re.compile(r"[{}]|[A-Za-z]=")
_RISK_QUERY = re.compile(r"/[A-Za-z0-9/_{}\-]*\?[A-Za-z]+=")
_CODE_TOKEN = re.compile(r"[A-Za-z]*[a-z][A-Z][A-Za-z]*|[A-Za-z]+-\d+|/[A-Za-z][A-Za-z0-9/_{}\-]*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
DENSE_SENTENCE_MIN_CHARS = 80
DENSE_SENTENCE_MIN_CODE_TOKENS = 4


def find_speakability_risks(text: str, entries: list[dict]) -> list[tuple[str, str]]:
    """Spots in a script that the TTS/STT pair is known to stumble on.

    Each hit is ``(kind, snippet)``. ``path``/``dotted``/``symbol`` are judged on
    the dictionary-substituted text (a path the dictionary already spells out is
    fine); ``query`` and ``dense`` on the raw text, because a spelled-out query
    string is still rewritten by the STT as English words and a sentence
    stuffed with code tokens (CamelCase names, ``US-11`` codes, paths) made the
    TTS emit near-silence on every seed; plain English term lists are fine.
    Warn-only: callers must not fail a run on these.
    """
    spoken = apply_pronunciation(text, entries)
    risks = [(kind, m.group(0)) for kind, pat in (
        ("path", _RISK_PATH), ("dotted", _RISK_DOTTED), ("symbol", _RISK_SYMBOL),
    ) for m in pat.finditer(spoken)]
    risks += [("query", m.group(0)) for m in _RISK_QUERY.finditer(text)]
    for sentence in _SENTENCE_SPLIT.split(text):
        if (
            len(sentence) >= DENSE_SENTENCE_MIN_CHARS
            and len(_CODE_TOKEN.findall(sentence)) >= DENSE_SENTENCE_MIN_CODE_TOKENS
        ):
            risks.append(("dense", sentence[:40] + "…"))
    return risks


_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")


def find_unlisted_latin_tokens(text: str, entries: list[dict]) -> list[str]:
    """Latin tokens still in *text* after ``apply_pronunciation`` (S13).

    These are the terms the TTS would read with an English/garbled voice:
    not in the dictionary, or only as an unapproved entry. De-duplicated,
    first-seen order. Runs on the substituted text (not the raw one) so
    multi-word keys like "Burndown Chart" cover their parts.
    """
    return list(dict.fromkeys(_LATIN_TOKEN.findall(apply_pronunciation(text, entries))))

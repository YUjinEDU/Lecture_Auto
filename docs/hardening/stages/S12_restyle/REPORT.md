# S12 REPORT — 대본 말투 재작성(내용 보존) 단계

## Branch base

Worktree branch tip was `29275e7`, which predates `docs(s12): restyle stage spec + pilot`
(`961fd5c` on `master`). Cherry-picked that one commit onto this branch as `9444d41` (SPEC.md +
pilot_v2.py + transcript_excerpt.txt, docs only, no code) so the SPEC referenced by this task
existed here. Did **not** pull in `52bbae9` ("drop the per-slide cap on the professor's
expressions") — SPEC line 11 says that fix is uncommitted on the `master` worktree and must not
be included in this branch.

## Files changed

- `lecture_auto/pipeline/restyle.py` (new) — `restyle_scripts(client, scripts)`.
- `lecture_auto/prompts/restyle_instruction.md` (new) — user-prompt template.
- `scripts/restyle_scripts.py` (new) — CLI (S12-b).
- `lecture_auto/pipeline/AGENTS.md` — one line added to the Key Files table for `restyle.py`.
- `tests/test_restyle.py` (new, 8 tests) — pipeline unit tests, LLM mocked.
- `tests/test_restyle_scripts_cli.py` (new, 4 tests) — CLI tests, LLM mocked, `tmp_path` only.

No existing file other than `AGENTS.md` (one line) was modified; `lecture_plan.py`,
`scripts/batch_generate_lectures.py`, and the two existing prompt `.md` files are untouched.

## Test result

`.venv/bin/python -m pytest -q` (cwd = worktree root): **443 passed** — the full suite, including
all 12 new S12 tests.

## Design notes / how S12-c's 7 scenarios map to tests

1. Normal response → adopted: `test_normal_response_is_adopted_and_metrics_recorded`.
2. Latin-token change → only that slide re-asked, second attempt adopted:
   `test_latin_token_change_retries_only_that_slide_then_adopts` — asserts the retry's user
   message contains slide 1 and not slide 2, and that slide 2's first-pass result survives
   unresent.
3. Both attempts out of length range → original kept + reason:
   `test_length_out_of_range_both_attempts_keeps_original`.
4. Digit change → fails validation: `test_digit_change_fails_validation` (direct `_validate` unit
   test).
5. Malformed JSON once → re-ask → success: `test_malformed_json_is_reasked_once_then_succeeds`
   (plus `test_malformed_json_twice_raises` for the give-up path).
6. CLI: approved slide skipped and untouched, backup created, second same-day run aborts before
   calling the LLM, `.hash` sidecar unchanged, `--dry-run` writes nothing (verified by a full
   before/after byte snapshot of every file under the lecture dir, not just the ones a real run
   would touch) — one test each in `test_restyle_scripts_cli.py`.
7. Full `pytest` passes — see above.

## Deviations from SPEC (and why)

- **Prompt structure**: SPEC's wording ("프롬프트 문구는 이것을 그대로 옮기되") is satisfied by
  keeping `pilot_v2.py`'s exact message split — the short system message is hardcoded in
  `restyle.py` (`_SYSTEM_PROMPT`, byte-identical to the pilot's `sysmsg`), and
  `restyle_instruction.md` holds everything the pilot put in the user message (transcript
  excerpt → style stats → per-slide counts → rules → original scripts → output format), in that
  order, with `{{COUNTS}}`/`{{SLIDES}}` filled by `str.replace` (not `.format`/`string.Template`,
  since the output-format line has literal `{"slides": ...}` braces). An earlier draft had put
  the excerpt/stats/rules into the system message and reordered rules before counts; this was
  caught in self-review and reverted to match the pilot's tested layout, since 4.6/1000 (the
  pilot's own measured result) is the only evidence this prompt actually produces the target
  register.
- **`~요 종결` metric**: counts only sentence-final `요` immediately before `.`/`!`/`?`/end-of-text
  (not `죠`, which SPEC's own baseline table and `lecture_plan.py`'s comment track as a separate
  ~5.4/1000 figure for the professor, and not `요` merely followed by whitespace, e.g. "필요
  없다"). This is a reporting-only metric (not one of the 4 gates) and is a regex heuristic, not
  a real sentence parser — flagged in-code with a `ponytail:` comment naming the ceiling.
- **`restyle_report.json`'s lecture-wide figures**: named `lecture_metrics_before`/
  `lecture_metrics_after` rather than an "aggregate" of per-slide rates. They're computed by
  joining every slide's script (kept, approved-and-skipped, or adopted, as appropriate) into one
  string and running `compute_metrics` on it once, so the number is a true per-1000-characters
  rate over the whole lecture — comparable to the SPEC table's 8.2–9.9 — instead of an unweighted
  mean across slides that a couple of short cover slides could skew.
- **Missing-slide-number handling**: if an LLM response omits a requested `slide_number`, that
  slide's `reasons` gets an explicit `"LLM 응답에 이 슬라이드 번호가 없음 -- 원본 유지"` entry (in
  addition to whatever `_validate` finds) rather than only the possibly-confusing "formal
  frequency didn't drop" reason a same-as-original comparison would otherwise produce.

## Known limitations flagged for the supervisor (no code changes made — out of scope / batch
script is off-limits)

- **`_validate`'s formal-frequency gate is a strict `<`.** A slide whose original script already
  has zero 합니다/습니다 endings can never pass (0 is never `<` 0), so it is always kept after one
  wasted retry call. This is what SPEC literally asks for ("빈도가 원본보다 낮음"); flagging in
  case the supervisor wants a `<=`-with-nonzero-original exception instead.
- **Clone-source lectures are not hand-edit-protected.** `scripts/batch_generate_lectures.py`'s
  `clone_from` path (~line 717–753) does `shutil.copy2` of every non-cover-slide `script_NNN.json`
  from the source lecture on every run, with no `_hand_edited()` check (that check only guards
  the section-generation path). If any of 04-2/05/06 is a `clone_from` target of another lecture
  in `LECTURES`, the next batch run for the *clone* will silently overwrite that lecture's
  restyled scripts with the source lecture's (pre- or post-restyle, whichever the source has) —
  independent of anything S12 does. `scripts/batch_generate_lectures.py` is out of bounds for
  this stage (SPEC's 금지 list), so this needs a follow-up stage or a manual note to re-run
  `restyle_scripts.py` on any clone target after a batch run.
- If the LLM returns malformed JSON twice in a row for a section (both the first call and the
  batched retry), `restyle_scripts` raises `json.JSONDecodeError` and `scripts/restyle_scripts.py`
  aborts with nothing written for that lecture (no partial `restyle_report.json`, no script
  changes) — safe, but every other section's LLM calls already made in that run are wasted work.

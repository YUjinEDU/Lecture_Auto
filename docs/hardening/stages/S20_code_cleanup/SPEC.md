# S20 SPEC — 코드 정리(죽은 코드·위험한 스크립트·중복 제거)

기준: master HEAD. 근거: 2026-10-05 읽기 전용 감사(codegraph callers + grep + AST). 원칙: **동작 불변**(합성 결과·캐시 키·qc.json 읽기 호환).

## 작업 항목
### S20-a 폐기된 이어붙이기(tts_continuation) 경로 제거 (`lecture_auto/pipeline/raon_tts.py`)
D-15로 폐기됨. `plan_attempts`(:798)가 항상 `(seed, False)`만 반환 → 아래는 실행 불가능:
- `_synthesize_segment_with_gate`의 `if use_continuation` 분기, `"tts_continuation" if use_continuation` 라벨, `best_fallback_attempt`의 bool
- `continuation_ref` 인자 전달(`_synthesize_segment_with_gate`, `_synthesize_with_splitting`, `synthesize_raon_slide` 루프), `_SplitState` 클래스와 그 `TemporaryDirectory`, 통과 조각마다 쓰는 버리는 WAV(`save_ref`)
- path→index 해석, `metas[..]["continuation_from"]=None`, `boundary_review` 계산(항상 `[]`) → `_write_slide_qc`에 `boundary_review=[]`를 넘기거나 스키마 기본값 사용
- `load_raon_pipeline`과 상한 설정의 `task_params["tts_continuation"]` 쓰기
유지(필수):
- `plan_attempts(has_continuation, seeds)` **시그니처 유지**(테스트 ~15곳). 내부만 단순화 가능.
- `lecture_auto/schemas/production.py`의 `call: Literal["tts","tts_continuation"]`, `continuation_from`, `boundary_review` **스키마 유지** — 06 강의 qc.json 13개에 옛 값이 있고 `annotate_lecture.py`가 검증해 읽는다.
- `TTS_SYNTH_VERSION`·시드·캐시 키 불변(같은 시드, 같은 `pipe.tts` 호출 순서 → 오디오 동일). `torch.manual_seed` 호출 위치·순서 그대로.
- 트레이스 레코드의 `call` 필드는 `"tts"` 고정값으로 계속 기록(분석 스크립트 호환).
테스트: 폐기된 경로만 검증하던 테스트(감사: test_raon_tts.py :421, :879, :913, :1181 부근) 삭제, 위치 인자로 `continuation_ref`를 넘기던 테스트(:477-490, :830-835 부근) 수정.
**추가 테스트(필수)**: mock pipe로 한 슬라이드를 합성할 때 `pipe.tts` 호출 인자·횟수·`torch.manual_seed` 시드 순서가 변경 전과 같음을 고정(변경 전 코드에서 먼저 기록해 두고 비교).
`scripts/batch_generate_lectures.py:381` 부근 낡은 주석 갱신.

### S20-b 위험·낡은 스크립트 삭제
- `scripts/recalibrate_gate.py` 삭제: 캐시 키에 `target_seconds`가 빠져(배치는 포함) `--reconcile`이 유효한 `.hash`를 배치가 거부하는 키로 덮어써 재합성을 유발.
- `scripts/run_mini_test.py`, `scripts/run_mini_test_fluid.py` 삭제: 비어 있는 `data/audio_ref/test_variants/ref_combined.wav`를 참조 → 경고 없이 기본 목소리로 합성. CLAUDE.md의 해당 명령은 `scripts/smoke_e2e.py`/`produce.py --slides`로 교체.
- 이 스크립트들을 import하는 테스트가 있으면 함께 정리.

### S20-c 참조 없는 코드 삭제
- `synthesize_raon_audio`(raon_tts.py), `DEMO_FAST_TTS_SLIDE_LIMIT`(demo/jobs.py), `list_jobs`(demo/state.py), `TTSStatusResponse`(schemas/tts.py) — 각 AGENTS.md 언급도 정리. **삭제 전 각각 repo 전체(portal/ 포함) grep으로 0건 재확인.**
- 테스트에서만 쓰이는 `check_transcription_fidelity`, `slice_raw_audio`/`synthesize_review_speech`(`lecture_auto/review/audio.py` 전체가 비게 되면 파일 삭제) + 해당 테스트. `_passes_quality_gate`는 S9 진단 스크립트가 쓰므로 **유지**.

### S20-d 중복 제거
- `_atomic_write_json`(api/routes/scripts.py, tasks/script_tasks.py) → `cache.write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))`로 교체 — 파일 바이트가 지금과 정확히 같아야 함(배치가 대본 파일 바이트를 해시). 바이트 동일성 테스트 추가.

### S20-e 문서
- `lecture_auto/pipeline/AGENTS.md`의 vLLM 서술, `pipeline/__init__.py` vllm 주석 갱신. `tests/test_token_overlap.py`의 `vllm`/`qwen_vl_utils` 스텁 제거(테스트가 그대로 통과하면).

## 완료 조건
- 전체 pytest 통과(삭제한 테스트 수/추가한 테스트 수 보고), 순 삭제 줄 수 보고.
- `git grep -n "tts_continuation"` 결과가 스키마·트레이스 호환·문서/결정 기록에만 남음(목록 보고).

## 금지
합성 동작·게이트 임계값·시드·캐시 키·`TTS_SYNTH_VERSION` 변경, 스키마 필드 삭제, 실제 GPU/LLM, `data/`·`output/` 쓰기, 새 의존성.

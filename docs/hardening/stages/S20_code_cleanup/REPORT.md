# S20 REPORT — 코드 정리 (감독 기록, 작업자 보고 요약)

- 브랜치 `s20-code-cleanup`(6커밋), 병합 후 전체 pytest 511 통과. 순 **-631줄**(23파일, +238/-869).
- S20-a: 폐기된 tts_continuation 경로 제거(`_SplitState`·임시 WAV 쓰기·continuation_ref 전달·boundary_review 계산·task_params 쓰기). **먼저** 원본 코드에서 `pipe.tts` 호출·`torch.manual_seed` 순서를 고정하는 테스트 2개(재시도 / 전부 실패→fallback→redraw)를 만들어 통과시킨 뒤 제거 → 그대로 통과. 시드·캐시 키·`TTS_SYNTH_VERSION`·스키마 필드 불변(06 qc.json 13개 호환).
- S20-b: `scripts/recalibrate_gate.py`(배치와 다른 캐시 키로 `.hash`를 덮어써 재합성 유발), `run_mini_test.py`·`run_mini_test_fluid.py`(빈 참조 음성 경로 → 기본 목소리로 조용히 합성), `lecture_auto/review/audio.py` 삭제. CLAUDE.md는 `produce.py --slides`로 안내.
- S20-c: 참조 없는 `synthesize_raon_audio`, `check_transcription_fidelity`, `DEMO_FAST_TTS_SLIDE_LIMIT`, `list_jobs`, `TTSStatusResponse` 삭제.
- S20-d: 중복 `_atomic_write_json` 2곳 → `write_text_atomic` (파일 바이트 동일성 테스트 추가).
- S20-e: vLLM 관련 낡은 문서·테스트 스텁 정리.
- 남은 `tts_continuation` 언급: 스키마 Literal(옛 qc.json 호환), 버전 이력 주석, D-15 설명 docstring, 문서/결정 기록, S9 진단 스크립트.

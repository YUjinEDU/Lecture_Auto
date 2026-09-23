# 감독이 직접 확인한 사실 (2026-09-23, HEAD 9a240fb)

## Git
- 로컬 master `9a240fb`는 `origin/master` `b762928`보다 4커밋 앞(플레이어 프로토타입·복습 대본, 미push).
- `api.txt`가 git 추적 중이고 원격 저장소는 공개.

## 테스트 기준선
`.venv/bin/python -m pytest -q --ignore=tests/test_parser.py` → **262 passed, 8 failed**
- `tests/test_parser.py`: `lecture_auto.pipeline.parser` 없음 → collection error
- 실패 8건: `test_jobs_api::test_health_endpoint`, `test_llm::test_env_overrides_models`,
  `test_llm::test_missing_api_key_raises`, `test_scripts_api::TestApproveScripts::test_approve_succeeds_with_all_scripts`,
  `test_video::` 4건(`test_assemble_video_calls_create_and_concat`, `_output_path`, `_skips_missing_wav`,
  `_cleans_up_intermediate_clips`) — 가짜 WAV를 soundfile이 못 읽음

## 코드
- `lecture_auto/pipeline/video.py:219` 누락 WAV는 경고 후 건너뜀. `:236` `merge_audio(slide_pairs[0][1].parent, …)` — 디렉터리를 넘김.
- `lecture_auto/pipeline/tts.py:193` `merge_audio(audio_dir, output_path)` — `slide_*.wav` → `audio_*.wav` → `*.wav` 순 glob.
- `merge_audio` 호출자 4곳: `pipeline/video.py:236`, `tasks/tts_tasks.py:112`, `demo/synthesis.py:327`, `demo/orchestration.py:254`.
- `scripts/batch_generate_lectures.py:397-416` TTS 캐시 키 = `content_hash(script_text, ref_voice_bytes, TTS_MODEL_ID, str(TTS_TEMPERATURE), str(TTS_SEEDS), TTS_SYNTH_VERSION)`. `max_seconds=sc.get("target_seconds")`는 키에 없음. 합성은 `out_wav`에 직접 씀 → 실패 시 기존 파일 덮어씀, 기존 `.hash`는 남음.
- 같은 파일 `:437-447` gate 실패가 있어도 로그만 DRAFT, 같은 `out_mp4` 경로로 조립.
- `lecture_auto/pipeline/raon_tts.py:101` `check_transcription_fidelity` — STT 예외 시 `[]`(=통과), 빈 전사 시 `[]`, 내용 비교 없음. `synthesize_raon_slide(..., verify_stt=False)` 기본.
- `lecture_auto/pipeline/cache.py` — `content_hash`, `is_cache_valid`, `write_cache_hash`, `write_text_atomic` 존재.

## 데이터
- `data/work_batch/01_AI현업_02_디자인씽킹개요`: png 48, wav 48, hash 48 — **현재 캐시 키 유효 4/48**
- `data/work_batch/04_종합설계_02_고객문제이해및정의`: png 29, wav 29, hash 28 — **유효 0/29**
- → 지금 전체 재실행하면 교수님이 들은 음성 73/77이 재생성됨.
- 배치 참조 음성은 `data/audio_ref/reference_v1.wav`(build_voice_reference.py 생성). `scripts/recalibrate_gate.py`, `scripts/smoke_tts_gate.py`는 여전히 `test_variants/ref_phone_norm.wav`.
- `output/종합설계_02_고객문제이해및정의_인트로교체.mp4`(130MB, 29.3분) — 저장소에 제작 스크립트 없음. `LECTURES`의 `output_mp4` 이름과도 다름.
- 영상 길이: 디자인씽킹 26.2분, 고객문제 AI 원본 25.1분.
- 02·03·05 강의는 work_batch 폴더 없음.

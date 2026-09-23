# S1 REPORT (작업자: Sonnet, 2026-09-23)

- 브랜치 `worktree-agent-a50565098e1ae5caf`, 커밋 `a9c7c18` (분기점 `b762928`)
- 변경: `pipeline/tts.py`, `pipeline/video.py`, `scripts/batch_generate_lectures.py`,
  `tests/test_tts.py`, `tests/test_video.py`, `tests/test_batch_generate_lectures.py`(신규)

## 해결 항목
- S1-a `merge_audio`가 디렉터리(기존 glob) 또는 목록(순서 그대로) 수용. `assemble_video`는 목록 전달. 다른 호출자 3곳 불변
- S1-b `assemble_video(strict=True)`: WAV 항목 없음 또는 파일 부재 → `FileNotFoundError`(ffmpeg 전). 배치는 strict
- S1-c `_run_slide_tts`: 기존 WAV 있으면 `slide_NNN.cand.wav` + `.cand.wav.json {ok, cache_key}`만 씀. 기존 WAV·hash 불변
- S1-d `_tts_cache_key(...)`에 `target_seconds` 포함, 합성·검사 공용
- S1-e `_invalid_slides` → 하나라도 무효면 `<stem>_DRAFT.mp4`. `process_lecture`는 실제 경로 반환

## 테스트
- test_tts 3건, test_video 신규 4건 + 기존 실패 4건 수정(구현이 단일 패스 ffmpeg로 바뀐 뒤 갱신 안 된 mock → `subprocess.run` mock으로)
- test_batch_generate_lectures 9건(캐시 키, 후보 보호 성공/실패, 직접 쓰기, 캐시 재사용, 무효 판정, DRAFT 경로, 체인)

## pytest
분기점 256/8 → **277 passed / 4 failed** (남은 4건은 기존 무관 실패)

## 남은 문제(작업자 제기)
- 후보를 매 실행마다 재합성 → 감독이 후속 수정 요청(REVIEW 참조)
- S2 승인 전까지 최종 산출물은 항상 `_DRAFT.mp4` (의도된 동작)
- `failed_slides` 로그 문구 오해 소지

# S1 SPEC — 출력 정합성

참조: `../../PLAN.md` S1 표, `../../00_context/VERIFIED_FACTS.md`, `../../decisions/DECISIONS.md` (D-05, D-06)

## 목표
최종 MP4에 들어가는 음성이 정확히 의도한 파일이어야 하고, 재생성이 기존 음성을 손상시키지 않아야 한다.

## 작업 항목

### S1-a merge_audio는 목록을 병합
- `lecture_auto/pipeline/tts.py:193` `merge_audio`가 `Path`(디렉터리) 또는 `Sequence[Path]`(WAV 목록)를 받게 한다.
  목록이면 그 순서 그대로 병합(glob 안 함). 디렉터리면 기존 동작 유지.
- `lecture_auto/pipeline/video.py:236` → `merge_audio([wav for _, wav in slide_pairs], merged_audio_path)`.
- 나머지 호출자 3곳(`tasks/tts_tasks.py:112`, `demo/synthesis.py:327`, `demo/orchestration.py:254`)은 수정하지 않아도 동작이 같아야 한다.

### S1-b 누락 WAV 엄격 모드
- `assemble_video(..., strict: bool = False)`. `strict=True`면 PNG에 대응하는 WAV가 없을 때 `FileNotFoundError`(슬라이드 번호 포함), 기존 기본값은 경고 후 건너뜀 유지.
- 배치(`scripts/batch_generate_lectures.py`)는 `strict=True`로 호출.

### S1-c 기존 WAV 보호 (D-05)
`scripts/batch_generate_lectures.py:397-416`:
- `out_wav`가 **이미 있고** 캐시 무효(또는 `--slides` 강제)로 합성할 때: `slide_NNN.cand.wav`에 합성. 기존 `slide_NNN.wav`와 `.hash`는 절대 수정하지 않는다(성공·실패 무관). 후보 결과(ok 여부)는 `slide_NNN.cand.wav.json`에 `{"ok": bool, "cache_key": str}`로 atomic write(`write_text_atomic`). 조립에는 기존 `out_wav` 사용.
- `out_wav`가 **없을 때**: 기존처럼 `out_wav`에 합성, ok면 hash 기록, 실패면 hash 없이 남김.
- 로그에 후보 생성 사실과 경로를 남긴다.

### S1-d 캐시 키에 target_seconds
- TTS 캐시 키 `content_hash(...)`에 `str(sc.get("target_seconds"))` 추가.
- 주의: 이로써 기존 해시가 전부 무효가 되지만 S1-c 덕분에 기존 WAV는 보존된다. 이 사실을 커밋 메시지에 적는다.

### S1-e DRAFT 분리
- 조립 직전: 사용하는 각 WAV가 현재 캐시 키로 `is_cache_valid`인지 검사. 하나라도 무효면 출력 경로를 `out_mp4.with_name(out_mp4.stem + "_DRAFT.mp4")`로 바꾸고 무효 슬라이드 번호를 에러 로그로 남긴다. 전부 유효하면 기존 `out_mp4`.
- 반환값은 실제로 쓴 경로.
- 검사 로직은 테스트 가능하도록 작은 함수로 분리(예: `_invalid_slides(...) -> list[int]`). 캐시 키 계산도 한 함수(`_tts_cache_key(script_text, ref_voice_bytes, target_seconds)`)로 모아 합성·검사가 같은 키를 쓰게 한다.

### 부수: 기존 test_video 실패 4건
`tests/test_video.py`의 4건은 가짜 WAV를 soundfile이 못 읽어 실패 중. S1-a가 이 테스트들을 건드리므로 실제 유효 WAV(`soundfile.write`로 짧은 무음)를 만들도록 고쳐도 된다.

## 필수 테스트 (새로 추가, 전부 mock/임시 파일)
1. 디렉터리에 무관한 `slide_999.wav`가 있어도 `assemble_video` 병합 결과 길이 = 선택된 WAV 길이 합.
2. `strict=True`에서 WAV 누락 → 예외, ffmpeg 미호출.
3. 기존 `slide_001.wav`(+유효 hash)가 있고 강제 재생성 → 합성 mock이 `.cand.wav` 경로로 호출, 기존 WAV 바이트·hash 불변. 합성 실패(ok=False)여도 동일.
4. `out_wav`가 없을 때는 `out_wav`에 합성.
5. `target_seconds`만 바꾸면 캐시 키가 달라짐.
6. 무효 WAV 1개 → DRAFT 경로 반환, 전부 유효 → 최종 경로.

배치 스크립트 테스트는 `process_lecture` 전체를 돌리기 어렵다면, TTS 루프를 작은 함수로 추출해 그것을 테스트해도 된다(동작 불변 조건).

## 금지
- `data/`, `output/`의 실제 파일 사용·수정. `api.txt` 열기.
- 새 의존성 추가. AGENTS.md 수정(감독이 병합 후 처리).
- `lecture_auto/pipeline/raon_tts.py` 수정(S4-a 작업자가 병행 수정 중).

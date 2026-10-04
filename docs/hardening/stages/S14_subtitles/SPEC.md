# S14 SPEC — 문장 단위 자막(SRT) + 자막 입힌 영상

기준: master HEAD. 목표: 이미 만든 06~09 강의(재합성 없이)와 앞으로 만들 강의에 문장 단위 자막.
**TTS 코드(`raon_tts.py`)와 배치 스크립트는 수정하지 않는다** — 별도 모듈 + 별도 CLI.

## 감독 사전 측정 (2026-10-05)
- 조각 사이에는 `_PAUSE_MS`(200ms) 길이의 **정확한 0 샘플** 구간이 들어간다(`synthesize_raon_slide`의 `pause`).
  06~09 84개 슬라이드 전부에서 "길이 ≥ 0.8×200ms인 0-샘플 구간 수 == `len(qc['segments']) - 1`" 성립.
  → 조각 시각은 WAV에서 검출로 정확히 얻는다.
- `sha256(apply_pronunciation(현재 script)) == qc['spoken_text_sha256']`: 07·08·09 전부 일치, 06은 23장 중 17장.
- 한글 폰트: `fc-list :lang=ko`에 NanumSquareRound, Noto CJK 있음. ffmpeg `subtitles` 필터(libass) 있음.

## 작업 항목
### S14-a `lecture_auto/pipeline/subtitles.py` (신규)
- `segment_spans(wav: np.ndarray, sr: int, n_segments: int, pause_ms=200) -> tuple[list[tuple[float,float]], str]`
  길이 ≥ 0.8×pause_ms 인 0-샘플 구간을 경계로 (시작초, 끝초) 목록과 방식(`"pause"`) 반환.
  구간 수가 `n_segments-1`과 다르면 **글자 수 비례 분할**로 대체하고 방식 `"proportional"` (글자 수는 호출자가 넘김 → 시그니처에 `seg_chars: list[int]` 포함).
  경계 시각은 0-구간의 중앙이 아니라: 앞 조각 끝 = 0-구간 시작, 다음 조각 시작 = 0-구간 끝.
- `written_segments(script: str, spoken_segments: list[str], entries) -> list[str] | None`
  화면용 원문(영어 용어 원형)을 조각 단위로 복원. `raon_tts._SENTENCE_END_RE`로 원문을 문장 분리 → 문장별 `apply_pronunciation` →
  공백 정규화 후 순서대로 이어 붙여 각 spoken 조각과 정확히 일치하게 묶음. 맞아떨어지지 않으면 `None`(호출자는 spoken 텍스트 사용).
  (긴 문장이 절 단위로 쪼개진 조각 대응 필요 — `_split_long_sentence`를 원문 문장에도 같은 방식으로 적용해보고, 안 되면 None.)
- `split_cue(text, start, end, max_chars=42) -> list[(start,end,text)]`: 한 조각을 ≤2줄(줄당 ~21자, 공백 기준 줄바꿈) 큐 여러 개로 나누고 시간은 글자 수 비례.
- `to_srt(cues) -> str`, `to_vtt(cues) -> str` (stdlib만).

### S14-b `scripts/annotate_lecture.py` (신규 CLI)
- `--only <강의 id 부분 문자열>` 필수(LECTURES 재사용: `from batch_generate_lectures import LECTURES` 또는 동일 매칭 함수 재사용),
  `--burn`(자막 입힌 mp4 생성), `--font` 기본 `NanumSquareRound`.
- 입력: `output/<id>/<stem>.timeline.json`(슬라이드 시작초·wav 파일명), `data/work_batch/<id>/audio/slide_NNN.wav(.qc.json)`, `scripts/script_NNN.json`.
  **timeline이 가리키는 wav의 sha256이 현재 파일과 다르면 그 슬라이드는 건너뛰고 경고**(영상과 어긋난 자막 방지).
- qc.json 없음/segments 비어 있음 → 슬라이드 전체를 큐 하나(원문 script, proportional)로.
- spoken hash 불일치 슬라이드 → `written_segments` 쓰지 않고 qc의 spoken 조각 텍스트 사용, 보고에 표시.
- 출력(같은 `output/<id>/` 폴더, mp4 stem 기준): `<stem>.srt`, `<stem>.vtt`, `<stem>.subtitles.json`(큐 목록 + 슬라이드별 방식/텍스트 출처 통계).
  `--burn`: 원본 mp4는 그대로 두고 `<stem>_subtitled.mp4` 생성(`-c:a copy`, 영상만 재인코딩, `subtitles=...:force_style='FontName=...,FontSize=..,Outline=..'`).
  모든 텍스트/JSON 파일은 atomic write(기존 `write_text_atomic` 재사용).
- 종료 시 요약: 슬라이드 수, pause/proportional 수, written/spoken 수, 건너뛴 슬라이드.

### S14-c 테스트 (합성 numpy wav, tmp_path, ffmpeg는 mock)
1. 조각 3개 + 0-구간 2개 → 경계가 정확(샘플 단위)
2. 0-구간 수 불일치 → proportional, 합계 = 전체 길이
3. 발화 중간의 짧은 0(< 0.8×pause)은 경계로 안 봄
4. `written_segments`: "Product Owner"→"프로덕트 오너" 승인 시 원문 복원 / 맞지 않으면 None
5. `split_cue` 줄 길이·시간 연속성, SRT 시각 포맷(`00:01:02,345`)
6. CLI: wav sha 불일치 슬라이드 건너뜀, spoken hash 불일치 시 spoken 텍스트 사용, `--burn` 시 ffmpeg 명령에 `-c:a copy`·원본 mp4 미변경
7. 전체 pytest 통과

## 보고에 반드시 포함
- (테스트 외) **실데이터 읽기 전용 확인**: 08 강의에 대해 `--burn` 없이 실행하여 `output/` 대신 **스크래치 경로**(`--out-dir` 옵션 추가해 지정)에 SRT 생성, 앞 20개 큐 붙여넣기, 방식/출처 통계.

## 금지
`raon_tts.py`·`batch_generate_lectures.py`·`video.py` 수정, 캐시 키/합성 상수 변경, 실제 GPU/LLM, `data/` 쓰기, 새 의존성.
`output/`에는 쓰지 말 것(실제 생성은 감독 확인 후 사용자 승인으로).

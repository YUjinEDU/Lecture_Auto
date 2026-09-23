# S2 SPEC — 승인 목록 + 타임라인 (웹 UI 데이터 계약)

참조: `../../PLAN.md` S2, `../../00_context/VERIFIED_FACTS.md`, `../../decisions/DECISIONS.md` (D-04, D-05, D-06),
S1 결과(`../S1_output_integrity/REVIEW.md`). 기준 커밋: master `95bf7a4` (S1·S4-a 병합됨).

## 왜 필요한가
S1 이후 기존 해시가 전부 무효라서 모든 영상이 `_DRAFT.mp4`가 되고, 교수님이 이미 들은 음성을 "최종"으로
인정할 방법이 없다. 사람이 승인한 음성은 **합성 설정·캐시 키와 무관하게 고정**되어야 한다.
이 파일 형식은 이후 웹 UI(청취·승인 버튼)가 그대로 읽고 쓴다.

## 1. 스키마 — `lecture_auto/schemas/production.py` (신규)
Pydantic v2. 기존 `schemas/` 관례(파일 구성, `__init__` re-export 여부)를 먼저 확인하고 따른다.

```python
class ApprovedSlide(BaseModel):
    wav: str                 # audio 디렉터리 기준 파일명, 예 "slide_012.wav"
    sha256: str              # 승인 시점 WAV 바이트 해시
    approved_at: datetime    # timezone-aware
    source: Literal["existing", "candidate", "gate_pass"]  # 무엇을 승인했는지
    gate_ok: bool | None     # 승인 시점 자동 검사 결과(알 수 없으면 None)
    note: str = ""

class ApprovalManifest(BaseModel):
    lecture_id: str
    slides: dict[int, ApprovedSlide] = {}

class TimelineEntry(BaseModel):
    slide_number: int
    start_seconds: float
    duration_seconds: float
    wav: str
    wav_sha256: str
    approved: bool

class Timeline(BaseModel):
    lecture_id: str
    mp4: str                 # 파일명
    draft: bool
    total_seconds: float
    entries: list[TimelineEntry]
```
필드 추가·이름 조정은 이유를 보고서에 쓰면 허용. 필드 삭제는 금지.

## 2. 순수 함수 — `lecture_auto/pipeline/approval.py` (신규)
driver-agnostic(나중에 FastAPI도 호출). Redis/DB/로깅 외 부수효과 금지.
- `load_approvals(work_dir, lecture_id) -> ApprovalManifest` (`work_dir/approved.json`, 없으면 빈 manifest)
- `save_approvals(work_dir, manifest)` — `pipeline/cache.py`의 `write_text_atomic` 재사용
- `approve(manifest, audio_dir, n, source, gate_ok, note="") -> ApprovalManifest` — 현재 `slide_NNN.wav`의 sha256 기록, `model_copy`로 새 객체 반환(불변 규칙)
- `verify_approved(manifest, audio_dir) -> list[int]` — 파일 없음 또는 sha 불일치 슬라이드 번호
- `promote_candidate(manifest, audio_dir, n, allow_failed=False, note="") -> ApprovalManifest`
  - `slide_NNN.cand.wav`와 `.cand.wav.json` 필수. json `ok=False`면 `allow_failed=True` 없이는 `ValueError`
  - 기존 `slide_NNN.wav`는 `slide_NNN.prev.wav`로 보관(기존 prev는 덮어씀), `.hash`도 같은 방식
  - `os.replace(cand → slide_NNN.wav)`, 새 `.hash` = cand json의 `cache_key`(ok=True일 때만 기록, 실패본 승격이면 hash 기록 안 함)
  - cand json 삭제, 승인 기록(`source="candidate"`, `gate_ok`=json ok)
- `build_timeline(lecture_id, mp4_name, draft, slide_wavs: list[tuple[int, Path]], approved: set[int]) -> Timeline`
  - 길이는 `soundfile.info(...).duration`. start는 누적합. `assemble_video`의 프레임 길이 계산과 같은 순서·같은 WAV 사용.

## 3. 배치 스크립트 연결 — `scripts/batch_generate_lectures.py`
- TTS 루프: 슬라이드 n이 승인됨 **그리고** `--slides`에 없음 → 합성·후보 생성 모두 건너뜀, 승인 WAV 사용.
  `--slides`에 있으면 S1 후보 흐름(기존 WAV 있음 → `.cand.wav`). 승인은 자동으로 옮겨가지 않음.
- 조립 전: `verify_approved`가 비어 있지 않으면 **조립 중단**(`RuntimeError`, 슬라이드 번호 포함) — 승인본 오염 감지.
- DRAFT 판정(S1-e 확장): 슬라이드 유효 = 승인됨(sha 일치) **또는** 현재 캐시 키로 `is_cache_valid`.
- 조립 후 `<실제 mp4 stem>.timeline.json`을 mp4 옆에 atomic write. DRAFT면 DRAFT 이름 기준.
- 새 CLI (모두 `--only`로 강의 하나 지정 필수, 아니면 `parser.error`):
  - `--approve 1-48` : 현재 `slide_NNN.wav`를 그대로 승인(`source="existing"`, `gate_ok`=현재 캐시 키 유효 여부). 교수님이 이미 들은 음성용
  - `--approve-passing` : 현재 캐시 키로 유효한 슬라이드 전부 승인(`source="gate_pass"`, `gate_ok=True`)
  - `--promote 12,15` (+ `--allow-failed`, `--note "..."`) : 후보 승격
  - `--assemble-only` : 합성 없이 현재 파일로 조립 + timeline. **TTS 모델을 로드하지 않는다**
  - 승인 명령(`--approve*`, `--promote`)은 승인 파일만 수정하고 종료: TTS 모델·LLM 클라이언트 로드, 렌더링, 대본 생성, 합성, 조립 모두 하지 않는다. 대본이 필요하면(`gate_ok` 계산용) 디스크의 `scripts/slide_NNN.json`만 읽는다
  - `--assemble-only`가 LLM 호출을 피할 수 있으면 피한다(대본 캐시가 이미 있으면 기존 캐시 경로로 충분한지 확인). 불가능하면 이유를 보고.
- `_parse_slides_arg` 재사용(범위·쉼표 형식).

## 4. 필수 테스트 (mock·tmp_path만)
1. `approve` → sha 기록, 원본 manifest 불변(새 객체 반환)
2. `save/load` 왕복 동일, 파일은 atomic write 경로 사용
3. `verify_approved`: WAV 바이트 변경 시 해당 번호 반환, 파일 삭제 시 반환
4. `promote_candidate`: 성공 후보 → 메인 교체, prev 보관, hash=cand cache_key, cand json 삭제, 승인 기록
5. 실패 후보 `allow_failed=False` → `ValueError`, 파일 변화 없음 / `True` → 승격되지만 hash 미기록
6. TTS 루프: 승인된 슬라이드는 캐시 키가 무효(합성 버전 변경)여도 `synthesize_raon_slide` 미호출
7. `--slides`에 포함된 승인 슬라이드 → 후보 생성, 메인 WAV·승인 기록 불변
8. DRAFT 판정: 해시 무효지만 승인됨 → 최종 경로 / 승인 sha 불일치 → 조립 중단
9. `build_timeline`: 알려진 길이의 WAV 3개 → start·duration·total 정확
10. CLI: `--approve`에 `--only` 없음 → 에러. 승인 명령 실행 시 `load_raon_pipeline`·`OpenAILLMClient` 미호출(mock으로 확인)

## 금지·주의
- `data/`, `output/` 실데이터 사용 금지(실제 승인 실행은 사용자 확인 후 감독이 한다). `data/audio_ref/**` 금지.
- `raon_tts.py`의 합성·gate 로직 수정 금지. 새 의존성 금지. AGENTS.md 수정 금지(감독 처리).
- `TranscriptionCheck` 이전은 이번 범위 아님.

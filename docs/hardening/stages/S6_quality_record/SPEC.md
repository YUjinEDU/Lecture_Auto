# S6 SPEC — 품질 지표 실제 적용 + F3 + F6 + 발음 사전

참조: 인수인계 F1·F3·F6(`../../00_context/LECTURE_TTS_RESEARCH_HANDOFF.md`), 리뷰 "발음 표현"(`../../00_context/260923_review.md`),
`../../decisions/DECISIONS.md` (D-04, D-08), S1·S2·S3 REVIEW. 기준: master `faf55a3` 이후(S0·S3 병합됨, 전체 pytest 365 passed / 0 failed).

## 왜 필요한가 (감독 확인 사실)
- S4-a로 `evaluate_transcription()`(pass/fail/unavailable + CER)은 생겼지만, 배치는 `synthesize_raon_slide`를
  `verify_stt=False`로 호출하고 `RAON_VERIFY_STT`도 설정하지 않아 **실제 제작에서 한 번도 실행되지 않는다.**
- 켜더라도 결과는 전역 trace 로그(`_trace`)에만 남아 슬라이드 단위로 검수·웹 UI에 쓸 수 없다.
- API 재개 경로(`lecture_auto/tasks/tts_tasks.py:82`)는 WAV 존재만 보고 건너뛰고(F3), 대본 없으면 조용히 건너뛴 뒤
  `merge_audio(디렉터리)` + glob으로 조립한다(S1이 배치에서 고친 문제가 API에 남아 있음).

## S6-a 슬라이드별 품질 기록 (F1 마무리)
- `synthesize_raon_slide(..., qc_path: Path | None = None)` 추가. 주어지면 합성 결과 JSON을 atomic write. 반환값 `(path, ok)` 불변.
  필드(Pydantic 모델 `SlideQC`, `lecture_auto/schemas/production.py`에 추가):
  `ok`, `gate_reasons: list[str]`, `stt: TranscriptionCheck | None`, `spoken_text_sha256`, `segments: list[SegmentQC]`,
  `synth_version`, `created_at`.
  `SegmentQC`: `index`, `text`, `seed`, `call`("tts"|"tts_continuation"), `continuation_from: int | None`(앞 조각 index), `fallback: bool`.
- `TranscriptionCheck`를 `raon_tts.py`에서 `schemas/production.py`로 이동(S4-a 리뷰 후속). `raon_tts.py`는 re-export해서 기존 import 유지.
- 배치: 파일명 `slide_NNN.wav.qc.json` / 후보는 `slide_NNN.cand.wav.qc.json`. `promote_candidate`는 후보 qc를 메인 qc로 함께 이동(prev도 보관).
- 배치에서 STT 검사 **기본 켬**, `--no-stt`로 끔. `pipe`에 `stt`가 없으면 `unavailable`로 기록(현재 로직 유지).
- STT 비교 기준 텍스트는 **발음용 텍스트(S6-d 적용 후)**. CER은 기록만(D-08), 판정 불변.
- `Timeline`/`TimelineEntry`에 선택 필드 `stt_status`, `cer`, `gate_ok` 추가(qc 파일에서 읽음, 없으면 None). 교수님·웹 UI가 "CER 높은 순"으로 청취 가능하게.

## S6-b F3 — API 재개 경로
- `tasks/tts_tasks.py`: 건너뛰기 조건을 "WAV 존재"에서 **현재 대본·참조음성·설정으로 만든 캐시 키의 `is_cache_valid`**로. 합성 성공 후 `write_cache_hash`.
  캐시 키에 넣을 설정은 이 경로의 엔진(`_get_tts()`) 기준으로 판단해 보고.
- 대본 없는 슬라이드는 에러로 실패 처리(조용히 건너뛰지 않음) — 기존 테스트 기대와 충돌하면 보고.
- `merge_audio`는 슬라이드 순서의 명시 목록으로, `assemble_video`는 `strict=True`로.
- `regenerate_slide_tts_task` 등 같은 파일의 다른 경로도 캐시 hash를 갱신하는지 확인.

## S6-c F6 — continuation 경계 기록
- S6-a의 `SegmentQC.continuation_from`으로 기록 자체는 충족. 추가로 `promote_candidate` 또는 `--slides` 재생성 시,
  **같은 슬라이드 안에서** 교체된 조각에 이어받은 조각이 있으면 로그 경고 + qc JSON에 `boundary_review: list[int]`(재청취할 조각 index) 기록.
  (슬라이드 간 continuation은 없음 — batch 주석 확인됨. 자동 재생성 엔진은 만들지 않는다.)

## S6-d 발음 사전
- 파일: `config/pronunciation.yaml`(저장소 추적). 형식:
  ```yaml
  # 화면 표기: TTS 발음. 교수님 확인된 항목만. 문맥에 따라 다르게 읽는 용어는 넣지 말 것.
  entries:
    - written: "API"
      spoken: "에이피아이"
      approved: false   # 교수님 확인 전 = 적용 안 함
  ```
  처음엔 예시 3~5개, 전부 `approved: false`.
- 순수 함수 `apply_pronunciation(text, entries) -> str`(위치: `lecture_auto/pipeline/`의 새 작은 모듈): `approved: true`만 적용,
  영문 단어 경계 기준(부분 문자열 치환 금지: "APIs"/"RAPID" 오치환 방지), 긴 표기 우선.
- 배치: 대본 원문은 그대로 두고, 합성 직전에만 `spoken_text = apply_pronunciation(script)` 사용. **TTS 캐시 키는 spoken_text 기준**
  (사전 변경 시 영향 슬라이드만 무효, 승인 슬라이드는 S2 규칙대로 고정). 원문 대본 JSON에는 쓰지 않는다.
- `pyyaml`은 이미 설치됨(6.0.3). `pyproject.toml`에 명시 의존성이 없으면 추가(uv.lock 동기화 포함).

## 필수 테스트 (mock·tmp_path)
1. `qc_path` 주면 JSON 생성, 필드 채워짐(세그먼트 continuation_from 포함), 안 주면 파일 없음·반환값 동일
2. 배치: STT 기본 켬 → `synthesize_raon_slide`에 `verify_stt=True`와 qc_path 전달 / `--no-stt` → False
3. `promote_candidate`가 qc 파일도 이동·보관
4. timeline에 qc 값 반영, qc 없으면 None
5. F3: 대본이 바뀐 슬라이드는 기존 WAV가 있어도 재합성, 안 바뀐 슬라이드는 건너뜀, 대본 없는 슬라이드 → 실패
6. F3: API 조립이 폴더의 무관한 WAV를 섞지 않음
7. F6: 조각 1 교체 시 조각 2가 continuation_from=1이면 boundary_review=[2]
8. 발음: approved만 적용, 단어 경계(“APIs” 불변), 긴 표기 우선, 원문 대본 JSON 불변, 사전 변경 시 해당 슬라이드 캐시 키만 변경
9. `TranscriptionCheck` 기존 import 경로(`lecture_auto.pipeline.raon_tts`) 유지

## 금지
- 실제 GPU/LLM 실행, `data/`·`output/` 쓰기, `data/audio_ref/**` 수정, AGENTS.md·docs/ 수정.
- 품질 판정 기준(gate 임계값, CER 합격선 도입) 변경 금지.
- 기존 01·04 강의 산출물 재생성 유발 금지: 발음 사전이 전부 `approved: false`면 spoken_text == 원문 → 캐시 키가 S3 시점과 같아야 한다(테스트로 확인).

# S16a SPEC — 강의 간 메모리(연속 강의 이어가기)

기준: master HEAD. 목표: 종합설계 04-1 → 04-2 → 05 → 06처럼 이어지는 강의에서 "지난 시간에 ~" 연결이 실제 지난 강의 내용에 근거하게.

## 원칙 (D-18)
- **명시적 opt-in만**: `LECTURES` 항목에 `"previous": "<이전 강의 id>"`가 있을 때만 동작. 목록 순서로 추론 금지.
- **키가 없으면 모든 프롬프트가 바이트 단위로 기존과 동일** → 기존 07~09 계획/섹션 캐시가 깨지지 않는다(깨지면 대본·음성 연쇄 재생성).
- 기존 `LECTURES` 항목에는 이번 단계에서 `previous`를 **추가하지 않는다**(실제 적용은 사용자 결정).

## 작업 항목
### S16-a `lecture_auto/pipeline/series_memory.py` (신규) + 스키마
- `LectureMemory`(Pydantic, `lecture_auto/schemas/lecture_plan.py` 또는 새 파일): `lecture_id`, `covered_concepts: list[str]`(≤12),
  `running_examples: list[str]`(≤3), `closing_hook: str`(마지막에 예고한 다음 내용, 없으면 ""), `source_sha256`(입력 대본 묶음 해시).
- `summarize_lecture(client, lecture_name, scripts: dict[int,str]) -> LectureMemory`: **이전 강의의 디스크 위 최종 대본**(`scripts/script_NNN.json`의 `script`, 슬라이드 순)을 입력으로 텍스트 LLM 1회. 계획(plan) 말고 대본 — 실제로 말한 내용 기준.
  JSON 파싱은 `strip_markdown_json_fence` 재사용, 잘못된 JSON이면 1회 재요청(`lecture_plan.py` 패턴).
- 캐시: `data/work_batch/<이전 id>/lecture_memory.json` + `.hash`(키 = 시스템 프롬프트 + 입력 대본 + llm config, 기존 `content_hash`/`write_cache_hash`/`is_cache_valid` 재사용).

### S16-b 프롬프트 주입 (`lecture_plan.py`)
- `build_lecture_plan_prompt(..., previous_memory: LectureMemory | None = None)`: None이면 기존과 동일 문자열. 있으면 `[지난 강의 요약]` 블록(다룬 개념, 사례, 예고) + "도입부에서 짧게 연결하되 다시 설명하지 말 것" 지시.
- `build_section_prompt(..., previous_memory=None)`: **첫 섹션에만** 같은 블록 전달(배치에서 첫 섹션일 때만 넘김). 이후 섹션에는 넣지 않는다 — 매 섹션 복습 방지.
- `generate_lecture_plan`/`generate_section_scripts`에 같은 선택 인자 전달.

### S16-c 배치 연결 (`scripts/batch_generate_lectures.py`)
- `process_lecture`: `item.get("previous")`가 있으면 이전 강의 작업 폴더의 대본으로 메모리 로드/생성(대본 없으면 명확한 에러), plan·첫 섹션에 전달.
  캐시 키는 프롬프트 텍스트를 이미 해시하므로 자동 반영(별도 키 추가 불필요 — 확인 후 보고).
- `--memory-preview --only <id>`: 메모리만 생성/로드해서 출력(TTS 모델 로드 없음).

### S16-d 테스트 (mock LLM)
1. **골든 테스트**: `previous_memory=None`일 때 plan/section 프롬프트가 현재 master 출력과 바이트 동일(대표 입력으로 현재 함수 출력을 고정값으로 저장해 비교)
2. memory 있으면 plan 프롬프트와 첫 섹션 프롬프트에만 블록 포함, 두 번째 섹션에는 없음
3. `summarize_lecture` 정상/잘못된 JSON 1회 재요청/2회 실패 시 예외
4. 메모리 캐시: 이전 강의 대본이 바뀌면 재생성, 같으면 LLM 미호출
5. `process_lecture`에서 `previous` 없으면 series_memory 미호출(기존 동작)
6. 전체 pytest 통과

## 금지
기존 LECTURES 항목 수정, `_PLAN_SYSTEM_PROMPT`/professor 시스템 프롬프트 변경, 실제 LLM/GPU, `data/`·`output/` 쓰기, 새 의존성.

# S16a REPORT — 강의 간 메모리 (감독 기록, 작업자 보고 요약)

- 브랜치 `s16-series-memory`: `7ba5a8c`(골든 고정 — 프롬프트 변경 전), `850dcda`(구현). 병합 `881e9d2`.
- 신규: `lecture_auto/pipeline/series_memory.py`, `LectureMemory`(schemas/lecture_plan.py), `tests/test_series_memory.py`, `tests/fixtures/s16_golden/*`(7).
- 변경: `lecture_plan.py`(`previous_memory_block`, 4개 함수에 선택 인자), 배치(`_load_previous_memory`, 계획 + 첫 섹션만 전달, `--memory-preview`).
- **바이트 동일성**: `previous` 없으면 새 인자를 아예 넘기지 않음. 골든 7개(계획/섹션 프롬프트, 캐시 키)가 master 출력과 일치.
- **실데이터 확인(읽기 전용)**: 07·08·09의 계획 캐시 키를 재계산 → 디스크 `lecture_plan.json.hash`와 전부 일치(llm config는 코드 기본값 `text=gpt-5.6-luna;vlm=gpt-5.4-mini`일 때만 일치).
- 주입 블록: `[지난 강의 요약 — 지난 시간에 실제로 다룬 내용]` + 다룬 개념/사례/예고 + "도입부에서 짧게 연결하되 다시 설명하지 말 것".
- 비고: `clone_from` 강의는 계획 생성을 건너뛰므로 `previous` 무효. `--memory-preview`는 실제 LLM 필요(미실행).
- 감독 검토: diff 확인, 전체 pytest 통과. 기존 LECTURES 항목 미수정 — 실제 적용(`previous` 추가)은 새 강의 제작 시.

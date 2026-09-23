# S3 SPEC — 새 강의 입력: PPTX 변환 + 참고 대본 연결

참조: `../../decisions/DECISIONS.md` (D-10, D-11, D-13), S1·S2 REVIEW. 기준: master `fa3bca9` 이후 HEAD.

## 배경
이번 제작 대상은 `data/PDF/종합설계 2026/`의 PPTX 4편이다.

| 강의 | PPTX | 참고 대본 |
|---|---|---|
| 04-1 | `04-1_아이디어를 컨셉으로 만들기.pptx` | `04-1_아이디어를컨셉으로만들기_강의스크립트.md` |
| 04-2 | `04-2_프로토타이핑과 테스트.pptx` | `04-2_프로토타이핑과테스트_강의스크립트.md` |
| 05 | `05_스크럼_활용_애자일_프로세스.pptx` | `05_스크럼_활용_애자일_프로세스_강의스크립트.md` |
| 06 | `06_Product_Backlog.pptx` | `06_Product_Backlog_강의스크립트.md` |

참고 대본 md 형식: 머리말 뒤 `## Part N. ... *(⏱ 시간)*` 섹션, 각 슬라이드는 `**[슬라이드 N] 제목**` 줄로 시작하고
다음 `**[슬라이드` 줄(또는 `## `/`---`) 전까지가 그 슬라이드 설명. `*(연출)*`, `*(⏱ ...)*` 같은 이탤릭 괄호 주석 포함.
**md는 참고 자료다(D-11)**: 사람이 쓴 내용·사례·흐름을 LLM에 제공하되, 대본은 기존 생성기(강의 계획 → 섹션 대본, 교수님 말투 규칙)가 만든다. md를 그대로 TTS에 넣지 않는다.

## 작업 항목
### S3-a PPTX 입력
- `LECTURES` 항목이 `"pptx"` 키를 가질 수 있게 한다(기존 `"pdf"` 항목은 그대로 동작).
- `process_lecture`: `pptx`면 `work_dir/input/<stem>.pdf`로 `lecture_auto/pipeline/renderer.py`의 `pptx_to_pdf()`를 재사용해 변환(이미 있고 PPTX보다 새로우면 재변환 생략), 이후는 기존 PDF 경로와 동일.
- `--assemble-only`/승인 명령은 변환 불필요(이미 rendered/ 사용) — 동작 확인만.

### S3-b 참고 대본 연결
- `LECTURES` 항목의 선택 키 `"reference_script": Path(...)`.
- 새 순수 함수(위치: `lecture_auto/pipeline/lecture_plan.py` 또는 작은 새 모듈, 기존 관례 따라 판단) `parse_reference_script(md_text) -> dict[int, str]`: 슬라이드 번호 → 해당 설명 텍스트. `*(⏱ ...)*`, `*(연출)*` 주석 줄/구문은 제거. 표지 등 마커 없는 부분은 무시.
- `build_lecture_plan_prompt`에 선택 인자 `reference_outline: str | None` — md의 머리말(구성·시간 배분)과 `## Part` 제목 목록만 요약해 전달("참고용 구성, 슬라이드 범위는 실제 슬라이드 기준").
- `build_section_prompt`에 선택 인자 `reference_notes: dict[int, str] | None` — 이번 섹션 슬라이드들의 md 설명만 넣고, 지시문: "아래는 교수님이 준비한 참고 설명이다. 내용·사례·강조점은 반영하되 문장을 그대로 복사하지 말고 기존 규칙(말투·분량)에 맞춰 다시 쓴다." 문구는 조정 가능, 의도는 유지.
- 인자가 None이면 기존 프롬프트와 **바이트 단위로 동일**해야 한다(기존 강의 캐시 보호).
- 캐시 키: 강의 계획/섹션 캐시 키(`_generate_lecture_plan_cached`, `_generate_section_scripts_cached`)가 프롬프트 텍스트를 해시하므로 참고 대본 변경 시 자동 무효화되는지 확인하고, 아니면 포함.
- 슬라이드 수 검증: md의 최대 슬라이드 번호가 실제 슬라이드 수와 다르면 경고 로그(중단하지 않음). md에 없는 슬라이드는 참고 없이 생성.

### S3-c 4편 등록
- `LECTURES`에 위 4편 추가. id는 기존 규칙 따라 `06_종합설계_04-1_아이디어를컨셉으로만들기`처럼 순번+과목+번호+제목(공백 없이). `subject="종합설계"`, `output_mp4=output/<id>.mp4`.
- `--only` 인덱스로도 선택 가능해야 함(6~9).

## 필수 테스트 (mock·tmp_path, 실제 soffice/LLM 금지)
1. `parse_reference_script`: 작은 md 샘플 → 슬라이드별 텍스트, 주석 제거, 마커 없는 머리말 무시
2. 실제 4개 md 파일을 **읽기만** 해서 파싱 → 슬라이드 수가 0이 아니고 번호가 1부터 증가(데이터 형식 회귀 방지). `data/PDF/`가 없으면 skip 허용
3. `build_section_prompt(..., reference_notes=None)` 출력이 기존과 동일(현재 구현으로 만든 기대값과 비교)
4. `reference_notes` 제공 시 해당 섹션 슬라이드 설명만 포함, 다른 섹션 설명 미포함
5. pptx 항목 → `pptx_to_pdf` mock 호출, 변환본이 최신이면 미호출
6. 참고 대본이 바뀌면 섹션 캐시 키가 바뀜
7. `LECTURES` 4편 경로가 실제 파일을 가리킴(`data/PDF/` 없으면 skip)

## 금지
- 실제 제작 실행(GPU/LLM) 금지 — 사용자 확인 후 S5에서.
- `tests/test_parser.py`, `tests/test_jobs_api.py`, `tests/test_llm.py`, `tests/test_scripts_api.py`, `scripts/recalibrate_gate.py`, `scripts/smoke_tts_gate.py` 수정 금지(S0 작업자 병행).
- `raon_tts.py` 합성 로직, 교수님 말투 빈도 규칙(`build_section_prompt`의 기존 문구) 변경 금지.
- `data/` 쓰기, AGENTS.md·docs/ 수정, 새 의존성 금지.

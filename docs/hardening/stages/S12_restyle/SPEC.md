# S12 SPEC — 대본 말투 재작성(내용 보존) 단계

기준: master HEAD. 사용자 결정(2026-09-28): 04-2·05·06 대본에 **B안(어미 + 연결어)** 적용. 04-1은 제외(전부 승인됨).

## 배경 (감독 측정, 1,000자당)
| | 교수님 실강 | 현재 대본(4편) | 파일럿 B안 |
|---|---|---|---|
| 합니다/습니다 | 2.9 | 8.2–9.9 | 4.6 |
| 그래서+이제 | 11.8 | 1.2–2.0 | 5.1 |
| ~요 종결 | 3.3 | 0.2–0.8 | 1.3 |
- 생성 프롬프트의 모순(시스템 프롬프트가 표현을 슬라이드당 0~2회로 제한)은 감독이 이미 고침(미커밋, 같은 브랜치에 포함하지 말 것 — master 작업트리에 있음).
- 그것만으로는 합니다/습니다 7.8→7.3 수준. 내용 생성과 말투를 한 번에 시키면 모델이 문어체로 돌아간다 → **내용이 확정된 대본을 말투만 다시 쓰는 별도 단계**가 필요.
- 파일럿 코드: `pilot_v2.py`(같은 폴더). 프롬프트 문구는 이것을 그대로 옮기되 아래 "의미 보호" 규칙을 추가.

## 작업 항목
### S12-a `lecture_auto/pipeline/restyle.py` (신규)
- `restyle_scripts(client: LLMClient, scripts: dict[int, str]) -> dict[int, RestyleResult]` — 한 섹션(여러 슬라이드)을 LLM 1회 호출로 재작성. 텍스트만(이미지 없음), `temperature=0.5`.
- 프롬프트: `lecture_auto/prompts/restyle_instruction.md`(신규)에 파일럿 v2의 지시문 + 교수님 발췌(`transcript_excerpt.txt` 내용을 그대로 파일에 포함 — 런타임에 data/ 읽지 않기). 슬라이드별 필수 횟수 줄은 코드에서 생성(파일럿과 같은 식: 연결어 `max(2, round(len*0.009))`, `자,` 전환 `len>400`이면 1, 합니다/습니다 최대 `max(1, round(len*0.003))`).
- 의미 보호 규칙 추가: "연결어는 앞뒤 문장이 실제로 결과·순서·조건 관계일 때만. '이제'를 '지금'의 뜻으로 끼워 넣지 않는다. '그 다음에 마지막'처럼 중복되는 연결을 만들지 않는다."
- 슬라이드별 검증(모두 통과해야 채택):
  1. 글자 수 비율 0.95–1.10
  2. 라틴 토큰 집합(`[A-Za-z][A-Za-z0-9'\-]*`) 원본과 동일 — 발음 사전 승인 범위를 벗어나지 않게
  3. 합니다/습니다 1,000자당 빈도가 원본보다 낮음
  4. 숫자 토큰(`\d+`) 집합 동일
- 불통과 슬라이드만 모아 1회 재요청. 그래도 불통과면 **원본 유지**(`RestyleResult.kept_original=True`, 사유 기록).
- JSON 파싱은 `strip_markdown_json_fence` 재사용, 잘못된 JSON이면 1회 재요청(`lecture_plan.py` 패턴과 동일).
- `RestyleResult`: `original`, `script`, `kept_original`, `reasons: list[str]`, `metrics_before/after: dict`(합습니다·그래서+이제·~요 종결 1,000자당).

### S12-b `scripts/restyle_scripts.py` (신규 CLI)
- `--lecture-dir data/work_batch/<id>` 필수, `--dry-run`(파일 안 씀, 결과를 표로 출력).
- 섹션 묶음은 `lecture_plan.json`의 sections 사용(없으면 4장씩).
- `approved.json`에 있는 슬라이드는 건너뜀(승인 음성과 대본이 어긋나지 않도록).
- 실행 시: `scripts/` 전체를 `scripts_orig_<YYYYMMDD>/`로 복사(이미 있으면 중단 — 두 번 덮지 않기). 그 다음 `script_NNN.json`의 `script` 필드만 원자적으로 교체(`.tmp`→rename). **`.hash` 사이드카는 건드리지 않는다** → 배치가 "사람이 고친 대본"으로 보고 보존하며 그 슬라이드 음성만 다시 만든다(`_hand_edited`, `scripts/batch_generate_lectures.py:596`).
- `restyle_report.json`(작업 폴더) 기록: 슬라이드별 채택 여부·사유·지표 전후, 강의 전체 지표 전후.

### S12-c 테스트 (mock LLM만)
1. 정상 응답 → 채택, 지표 기록
2. 라틴 토큰이 바뀐 응답 → 해당 슬라이드만 재요청, 두 번째 정상이면 채택
3. 두 번 다 길이 벗어남 → 원본 유지 + 사유
4. 숫자 바뀜 → 불통과
5. 잘못된 JSON 1회 → 재요청 후 성공
6. CLI: 승인 슬라이드 건너뜀, 백업 폴더 생성, 백업 폴더가 이미 있으면 중단, `.hash` 파일 불변, `--dry-run`은 아무 파일도 안 씀 (tmp_path에 가짜 작업 폴더)
7. 전체 pytest 통과

## 금지
- 실제 LLM/GPU 호출, `data/`·`output/` 쓰기, `data/audio_ref/**`.
- `lecture_plan.py`·배치 스크립트·프롬프트 기존 파일 수정(신규 파일만). AGENTS.md는 `lecture_auto/pipeline/AGENTS.md`에 restyle.py 한 줄 추가만 허용.
- 새 의존성.

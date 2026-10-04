# S19 REPORT — 대본 생성 최적화 (감독 기록, 작업자 보고 요약)

- 브랜치 `s19-script-quality` `4588186`, 병합 후 전체 pytest 505 통과(S16 골든 불변).
- S19-a: `LECTURES` 항목 `"restyle": True`일 때만 섹션 결과 직후 `restyle_scripts`(섹션당 LLM 1회) → `sections/section_NNN.restyled.json`(+.hash, 키 = 섹션 결과 + restyle 지시문 + 시스템 프롬프트 + llm config) → 기존 쓰기 루프(`_write_section_scripts`로 그대로 추출)가 `script_NNN.json`+`.hash` 기록 → restyle 결과는 "우리 대본", 사람 수정본은 계속 보존. `restyle_report.json`은 S12 CLI와 같은 형식.
  키가 없으면 호출 0, 파일 0, 캐시 키 불변(테스트: LECTURES에 `restyle` 키 없음 단언).
- S19-b: `--suggest-pron --only <하나>` — 미등록 토큰 + 등장 문장 2개를 LLM 1회(temperature 0.2) → `written`이 요청 토큰이 아니거나 `spoken`에 라틴 문자가 남으면 제외 → `data/work_batch/<id>/pronunciation_suggestions.yaml`(`approved: false`, `source: llm`) + 표준출력. `config/pronunciation.yaml` 불변(바이트 비교 테스트).
- **감독 실데이터 확인(2026-10-05)**: `--check --only 01_` → 미등록 28개, exit 1. `--suggest-pron --only 01_`(실제 LLM) → 후보 생성 정상(MRI→엠알아이, HMW→에이치엠더블유, UX→유엑스 …).
  한계: "How Might We"·"Yes, but"처럼 여러 단어 구문이 단어별로 제안됨 → 승인 시 구문 키로 묶어 등록하는 게 낫다(사전은 다단어 키 지원).

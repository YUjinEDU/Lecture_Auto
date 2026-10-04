# S17 REPORT — 오케스트레이션 (감독 기록, 작업자 보고 요약)

- 브랜치 `s17-orchestration` `383e737`, 병합 후 전체 pytest 494 통과.
- `--claim RUN_ID`(`--shard`와 배타): 기존 스킵 규칙 먼저 → 글자 수 내림차순 → `audio/.claim/slide_NNN.lock` non-blocking flock → 같은 run의 `.done`이면 건너뜀 → `_run_slide_tts` → 성공/게이트 실패 모두 `.done` 기록, 예외면 미기록(재시작 워커가 가져감). 한 바퀴만, 다른 워커가 쥔 슬라이드를 기다리지 않음(barrier 제거). claim 워커는 조립 안 함.
- `--only 7,8,9`(인덱스/부분문자열 혼합, 0매칭 에러, 승인 명령은 1개만).
- `scripts/produce.py`: GPU×workers 워커(20초 간격, `logs/produce_<run_id>/`), 비정상 종료 재시작(최대 `--max-restarts`), 종료 후 강의별 `--assemble-only`, 상태표, DRAFT/실패 시 exit 1, `--dry-run`.
- `--fix-failed`: 승인 안 됨 + 현재 키로 캐시 무효인 WAV(+.hash/.qc.json)를 `audio/failed_<ts>/`로 **이동**(삭제 없음) + `MOVED.txt`. 강의별 `fix.lock` + run별 마커로 1회만.
  주의: 규칙상 `TTS_SYNTH_VERSION` 변경 등으로 키가 바뀌면 미승인 슬라이드 전부가 대상이 된다(=DRAFT 규칙과 동일). 08·09처럼 승인 0건인 강의에 쓰기 전에 `--status`로 확인할 것.
- SPEC과 다른 점: 워커를 `python -m scripts.batch_generate_lectures`(cwd=repo)로 실행, 최종 상태를 프로세스 내에서 계산, `--fix-failed` 이동은 prep lock 대신 별도 `fix.lock`(prep lock은 5단계 전에 풀리므로).
- 불변: 정적 `--shard`, 승인 규칙, 후보(`.cand.wav`) 규칙, 캐시 키·합성 로직.

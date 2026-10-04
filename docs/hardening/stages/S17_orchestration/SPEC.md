# S17 SPEC — 제작 오케스트레이션: 동적 슬라이드 분배 + 크래시 복구 + 단일 명령

기준: master HEAD(S13 병합 후). 근거: `00_context/SPEED_RESEARCH_20260928.md` §3-A/A2, §4-2/3/4, §5 2~4위.
실측 낭비: GPU 대기 ≈179.5 GPU-분(정적 홀짝 샤딩 불균형+강의 경계 barrier), 샤드 크래시 시 GPU 2시간 13분 방치,
`run_fix.sh`류 수작업(mv → 재합성 → 재조립)을 매번 스크래치패드에 새로 작성.

## 작업 항목
### S17-a 동적 claim (`scripts/batch_generate_lectures.py`)
- 새 옵션 `--claim <run_id>`(`--shard`와 동시 사용 금지). 이 모드에서 `_synthesize_all_slides`는 홀짝 배정 대신:
  - 후보 = 이 실행에서 처리할 슬라이드(승인·`--slides` 규칙 등 기존 스킵 조건은 **그대로 먼저** 적용).
  - 순서 = 대본 글자 수 내림차순(긴 것 먼저 → 꼬리 불균형 최소화). 순서는 처리 순서일 뿐 결과·캐시 키에 영향 없음.
  - 각 슬라이드: `audio/.claim/slide_NNN.lock`에 `fcntl.flock(LOCK_EX|LOCK_NB)`. 실패(다른 워커가 처리 중) → 다음 슬라이드.
    성공 → `audio/.claim/slide_NNN.done` 파일 내용이 같은 `run_id`면 건너뜀(이미 이 run에서 처리됨), 아니면 기존 `_run_slide_tts` 호출 →
    **성공/실패와 무관하게** done 파일에 run_id 기록(atomic) → 락 해제. (크래시 시 done이 안 써지고 커널이 락을 풀어 다른/재시작 워커가 가져감.)
  - 한 바퀴 돌고 claim 가능한 것이 없으면 그 강의는 이 워커 몫 종료(다른 워커가 쥔 슬라이드를 기다리지 않음 → 다음 강의로 바로 이동, barrier 제거).
  - 반환 `wav_paths`는 지금처럼 슬라이드 순서 전체, `failed_slides`는 이 워커가 처리한 것 중 실패만.
- `--claim` 모드도 `shard_count>1`처럼 **조립하지 않는다**(조립은 S17-c가 모든 워커 종료 후 1회).
- 기존 `--shard` 동작은 그대로 유지(호환).

### S17-b `--only` 여러 강의
- `--only 7,8,9` 또는 `--only 08,09`: 콤마로 나눠 각 토큰에 기존 매칭(숫자 인덱스 / id 부분 문자열) 적용, LECTURES 순서 유지, 중복 제거.
  토큰 하나가 0개 매칭이면 에러. 승인 계열 명령은 여전히 정확히 1개만 허용(기존 검사 유지).

### S17-c `scripts/produce.py` (신규, 단일 명령)
- `python scripts/produce.py --only 7,8,9 --gpus 0,1 [--workers-per-gpu 1] [--slides ...] [--no-stt] [--max-restarts 2] [--fix-failed]`
- run_id = 타임스탬프. GPU×workers-per-gpu 개의 워커를 `batch_generate_lectures.py --only ... --claim <run_id> --gpu g`로 띄움(20초 간격, 로그는 `logs/produce_<run_id>/worker_<g>_<k>.log`).
- 워커가 0이 아닌 코드로 끝나면 같은 인자로 재시작(최대 `--max-restarts`), 초과 시 경고만 하고 계속.
- 모든 워커 종료 후 강의별로 `--assemble-only` 실행(서브프로세스), 마지막에 `--status` 표 출력. 종료 코드: 하나라도 DRAFT/실패면 1.
- `--dry-run`: 실행할 명령만 출력.
- 표준 라이브러리(`subprocess`, `time`)만. 셸 스크립트 대신 이 파일 하나.

### S17-d `--fix-failed` (`batch_generate_lectures.py`, produce.py는 그대로 전달)
- 리서치 §4-2 규칙: 슬라이드 n이 `approved` 아님 **그리고** `not is_cache_valid(out_wav, 현재 cache_key)`이면 대상.
  대상의 기존 `slide_NNN.wav`(+`.hash`, `.qc.json` 있으면)를 `audio/failed_<YYYYMMDD_HHMMSS>/`로 **이동**(삭제 금지) 후,
  메인 경로로 바로 재합성되게 한다(=`out_wav`가 없으므로 기존 S1-c 규칙상 메인에 씀). 승인 슬라이드는 절대 이동하지 않음.
- `--claim`과 함께 쓸 때 이동은 강의별 prep lock 안에서 한 번만(두 워커가 동시에 옮기지 않게; 이미 옮겨졌으면 no-op).
- 이동 목록을 로그와 `audio/failed_<ts>/MOVED.txt`에 기록.

### S17-e 테스트 (tmp_path, `_run_slide_tts`/합성 mock, 실제 프로세스 대신 함수 호출)
1. claim: 같은 run_id로 두 번 호출 → 두 번째는 합성 0회. 다른 run_id → 다시 합성(캐시 규칙대로).
2. claim: 락이 잡혀 있는 슬라이드(테스트에서 직접 flock) → 건너뛰고 나머지 처리, done 미기록.
3. claim: 처리 순서가 글자 수 내림차순, 결과 wav_paths는 슬라이드 순서.
4. claim: 합성 중 예외 → done 미기록(재시작 워커가 가져갈 수 있음) — 예외는 그대로 전파.
5. 승인 슬라이드는 claim 모드에서도 합성 안 함. `--claim`+`--shard` 동시 → parser 에러.
6. `--only 7,8` 파싱(인덱스/부분문자열 혼합, 0매칭 에러, 승인 명령은 1개만).
7. `--fix-failed`: 무효·미승인만 이동, 승인·유효는 그대로, MOVED.txt 내용, 두 번 호출 시 no-op.
8. produce.py: `subprocess.Popen`/`run` mock — 워커 수 = gpus×workers, 비정상 종료 시 재시작 횟수 제한, 모든 워커 후 강의별 assemble 호출, `--dry-run`은 실행 안 함.
9. 전체 pytest 통과.

## 금지
합성 로직·게이트 임계값·캐시 키·`TTS_SYNTH_VERSION` 변경, 실제 GPU/LLM 실행, `data/`·`output/` 쓰기, 새 의존성.
문서: `scripts/AGENTS.md`(있으면) / 루트 CLAUDE.md "Production batch workflow"에 produce.py 사용법 3~5줄 추가.

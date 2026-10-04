# S18 REPORT — TTS 생성 상한 (감독 기록, 작업자 보고 요약)

- 브랜치 `s18-tts-speed` `0abe6c8`, 병합 `b40f6e2`.
- `_TOKEN_CAP_RATIO = _MAX_DURATION_RATIO + 0.05`(1.40)로 `max_new_tokens` 계산(기존 1.5). attempt 트레이스에 `expected_seconds`.
- `scripts/bench_tts_throughput.py`: 고정 12문장×시드 17, `--procs-per-gpu 1|2`, 대상 GPU에 다른 프로세스가 있으면 exit 2(`--force`로만 무시). GPU가 비면 실행해 1→2 프로세스 처리량 비교(§3-E 미측정 항목).
- **캐시 키·합성 버전 유지 근거**: `modeling_raon.py:7982` 디코드 루프는 `max_new_tokens`로만 경계, 고정 시드라 상한 아래에서 끝나는 생성은 토큰 단위로 동일. 상한에 걸리던 생성은 1.35배를 넘으므로 원래도 불합격.
- **주의(작업자 발견)**: `modeling_raon.py:7963`의 정적 KV 캐시 길이가 `max_new_tokens`에 비례(8토큰 단위). 마스킹으로 수학적으로는 동일하나 bf16 SDPA 축약 길이가 달라 드물게 샘플이 바뀔 수 있음 — 기존에도 텍스트 길이마다 캐시 길이가 달랐으므로 새로운 비결정성은 아님. 기존 음성은 재합성 대상이 아니라 영향 없음.
- 기대 이득: long 실패 시도(실패 시간의 5~12%)의 생성 길이 1.47→≤1.40배 → TTS 단계 약 1% 내외. 큰 레버는 처리량(벤치 대기)과 S17 claim.

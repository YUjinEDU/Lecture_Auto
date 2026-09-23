# S9 REVIEW (감독)

- 판정: ✅ 병합. 작업자 커밋 f6d7fba·2ecb060·eec18a9·eb4a8c9, master에서 전체 pytest 417 passed / 0 failed.
- diff 확인: 조각 판정 = 싼 검사(long/voiced/silence, 길이 하한 없음) → STT pass & CER ≤ 0.25. STT 불가 시 기존 판정 그대로. `plan_attempts`는 plain 4개만. 속도 상수 7.0 두 곳 동기. `--slides`만 `TTS_RESEED_SEEDS`. 버전 v12.
- 의도된 기대값 변경: 섹션 프롬프트 baseline("5.7자"→"7.0자"), 발음 테스트 골든 캐시 키(버전 변경), 예산 테스트.
- 작업자가 남긴 위험(실측으로 확인할 것): 영어 용어 밀집 조각의 STT 오인식 → CER 0.25 초과 과잉 불합격 / 과길이 상한이 cps < 5.2로 좁아짐(실험 정상 조각 최저 5.51) / 조각 STT 시간.
- 04-1 처리: 기존 audio(구 대본·구 gate)는 `audio_old_20260923_s8/`로 옮기고(삭제 아님) 새로 제작.

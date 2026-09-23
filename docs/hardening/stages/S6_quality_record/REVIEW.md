# S6 REVIEW (감독: Opus, 2026-09-23)

**판정: ✅ 병합 완료 (`ad24f1c`)**

| 항목 | 결과 |
|---|---|
| pytest(병합 후, 감독 재실행) | **394 passed, 0 failed** |
| STT 판정 반영 | 확인: `verify_stt=True`면 STT reasons가 gate `reasons`에 합류 → 반복·길이 이상은 **불합격 처리**. 판정 규칙 자체(S4-a)는 불변이고 켜진 것뿐. 불합격이어도 기존 WAV 보호(후보/DRAFT)라 데이터 손실 없음 |
| CER 기준 텍스트 | 합성·STT 모두 `spoken_text` 사용 확인 |
| 발음 사전 | 미승인 4건(API, GPU, SQL, CI/CD) — 적용 안 됨, 캐시 키 불변 테스트 있음 |
| 기존 동작 보호 | `synthesize_raon_slide` 자체 기본값 `verify_stt=False` 유지 → 배치 외 호출자 영향 없음 |
| F3 API 대본 누락 실패 | 포털 approve 엔드포인트가 전 슬라이드 대본 존재를 먼저 검사(test_scripts_api) → 정상 흐름에선 발생 안 함 |
| 실데이터 사본 스모크 | 04번 사본에서 `--only 4 --approve 1-3` 정상, approved.json 기록 확인, 원본 불변 |
| 로직 제거 시 실패 | #2·#5·#7·#8 작업자 확인 |

## S5 전 확인할 것
- 첫 실제 합성에서 STT 추가 시간 측정, STT 오탐으로 불합격이 과도한지 qc.json으로 확인

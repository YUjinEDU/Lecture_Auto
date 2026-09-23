# S0 REVIEW (감독: Opus, 2026-09-23)

**판정: ✅ 병합 완료 (`ce8b40a`)** — 작업자 커밋 `7aa7b40`

| 항목 | 원인 | 수정 | 감독 확인 |
|---|---|---|---|
| S0-a | `parser.py → parser_pptx.py` 단순 rename 후 테스트 import 미갱신 | import 경로 수정(29건 복구, 중복 아님) | 수집 오류 0 |
| S0-b | 버전 문자열이 `main.py`에 2곳 중복, 0.4.0 올릴 때 /health 누락 | /health가 `app.version` 사용 | **앱 동작 변경**: /health 0.3.0 → 0.4.0 |
| S0-c | 루트 `.env`가 `load_dotenv()`로 테스트에 유입 → **테스트가 실제 FactChat API를 호출**하고 있었음 | autouse fixture로 `dotenv.load_dotenv` stub + 키 제거 | `load_dotenv`가 함수 내부 import라 stub 유효, 해당 테스트 0.02s(네트워크 없음) |
| S0-d | approve가 Celery 기본 AMQP 브로커(127.0.0.1:5672)에 실제 연결 시도 | 같은 파일의 기존 패턴대로 task mock | 통과 |
| S0-e | gate/smoke 스크립트가 예전 참조 음성 | `reference_v1.wav`로(상수 복제 — scripts/ 네임스페이스 import가 다른 체크아웃으로 샐 수 있음을 작업자가 실측) | 타당 |

- pytest(ignore 없이): **352 passed, 0 failed, 0 errors** (worktree·병합 후 둘 다 감독 재실행)
- 남은 것: REF_VOICE 상수 3곳 중복(주석으로 동기화 안내)

# S7 REVIEW (감독: Opus, 2026-09-23)

**판정: ✅ 병합 완료 (`6a5793f`)** — 작업자 커밋 `f191d67`

- 발견 경위: S5 준비 점검 중 감독이 실제 PPTX 변환 시도 → `soffice` exit 1, 에러 메시지 공백
- 원인: `pptx_to_pdf()`가 `--env:UserInstallation`(대시 2개) 사용. LibreOffice 24.2는 `-env:`만 허용, 오류는 stdout으로 출력
- 수정: `-env:UserInstallation={Path.as_uri()}`(공백·한글 경로 URL 인코딩), 실패 시 stderr+stdout 포함
- 다른 사용처: `parser_pdf.py:328`은 이미 `-env:` → 영향 없음
- 확인: pytest **395 passed / 0 failed**(감독 재실행), 실제 변환 — 작업자 04-1, 감독 06(공백 포함 job_id) 성공
- 글꼴(감독 확인): 맑은 고딕 미설치 → Noto Sans CJK KR 대체. 4편 샘플 슬라이드에서 한글 깨짐·레이아웃 붕괴 없음, 글꼴 모양만 원본과 다름

# S6 REPORT (작업자: Sonnet, 2026-09-23)

- 커밋 `9b384e4`, 기준 `c61a75a`
- 변경: `schemas/production.py`(`TranscriptionCheck` 이전, `SegmentQC`, `SlideQC`, Timeline 필드), `pipeline/raon_tts.py`(qc_path, F6),
  `pipeline/cache.py`(`qc_path_for`), `pipeline/approval.py`(qc 이동·timeline 반영), `pipeline/pronunciation.py`(신규),
  `config/pronunciation.yaml`(신규, 4건 전부 미승인), `tasks/tts_tasks.py`(F3), `scripts/batch_generate_lectures.py`, `pyproject.toml`/`uv.lock`(pyyaml)
- 테스트 +29 (365 → **394 passed**)

## 요약
- S6-a: 슬라이드마다 `slide_NNN.wav.qc.json`(후보는 `.cand.wav.qc.json`). 배치 STT 기본 켬(`--no-stt`). STT 비교 기준은 발음용 텍스트. timeline에 `stt_status`/`cer`/`gate_ok`
- S6-b(F3): API 재개 = 캐시 키 기준, 대본 없으면 즉시 실패, 명시 목록 병합 + strict 조립
- S6-c(F6): `continuation_from` 기록. 2차 패스(슬라이드 전체 에너지 기준 재추첨)가 이미 참조된 조각을 교체하는 **실제 도달 가능한 경로**가 있어 `boundary_review` 기록(재현 테스트 포함)
- S6-d: `apply_pronunciation` — 승인 항목만, ASCII 단어 경계("API를"은 적용, "APIs"/"RAPID"는 미적용), 긴 표기 우선. 미승인뿐이면 캐시 키 불변(골든 해시 테스트)

## 앱 동작 변경
- 배치: STT 반복/길이 이상 사유가 품질 판정에 반영됨(이전엔 꺼져 있었음). 슬라이드당 ASR 1회 추가 — GPU 시간 실측 없음
- API: 첫 재개 시 hash 없는 기존 WAV는 1회 재합성. 대본 없는 슬라이드가 있으면 작업 전체 실패

## 남은 것
- STT GPU 시간 실측 필요(S5 첫 실행 때), `TTSEngine._model_path` private 속성 의존

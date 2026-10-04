# S14 REPORT — 문장 단위 자막

(작업자 보고를 감독이 기록 — 작업자의 파일 쓰기가 하네스에서 거부됨)

- 브랜치 `s14-subtitles`, 커밋 `68f08aa`(작업자) + 감독 수정 커밋(자막 분할 개선).
- 신규: `lecture_auto/pipeline/subtitles.py`(`segment_spans`, `written_segments`, `split_cue`, `to_srt`, `to_vtt`),
  `scripts/annotate_lecture.py`(`--only --burn --font --work-dir --output-dir --out-dir --pronunciation`), `tests/test_subtitles.py`.
  `raon_tts.py`·`batch_generate_lectures.py`·`video.py` 미수정(import만).
- pytest: 455 passed (기준 444 + S14 11).

## SPEC과 다른 점
- `segment_spans(wav, sr, n_segments, seg_chars=None, pause_ms=200)` — 파일 양끝에 닿은 0-구간은 경계로 안 셈.
- CLI가 저장소 루트를 `sys.path[0]`에 넣음(편집 설치된 venv가 다른 체크아웃을 import하는 문제 회피).
- timeline은 `<id>.timeline.json`, 없으면 `<id>_DRAFT.timeline.json`.
- 절 중간에서 쪼개진 TTS 조각은 원문 복원 불가 → 그 슬라이드는 spoken 텍스트(06 slide 4, 09 slide 18).
- `--only 06_`은 `09_종합설계_06_`도 매칭 — 06은 `--only 06_종합설계`.

## 실데이터(읽기 전용, 스크래치 출력)
| 강의 | 슬라이드 | pause | proportional | 원문 | spoken | 건너뜀 | spoken hash 불일치 |
|---|---|---|---|---|---|---|---|
| 06 | 23 | 23 | 0 | 16 | 7 | 없음 | 8,14,20,21,22,23 |
| 07 | 19 | 19 | 0 | 19 | 0 | 없음 | 없음 |
| 08 | 24 | 24 | 0 | 24 | 0 | 없음 | 없음 |
| 09 | 18 | 18 | 0 | 17 | 1 | 없음 | 없음 |

## 감독 수정 (리뷰 중 발견)
작업자 버전 `split_cue`는 42자 탐욕 채우기라 "…살펴보겠습니다. 그래서"처럼 문장 경계를 넘거나 0.5초짜리 "거고요." 단독 자막이 생김.
→ 문장 경계 우선, 긴 문장은 균등 분할(쉼표 선호), 8자 미만 꼬리는 앞 자막에 병합. 08 결과: 634 큐, 최단 1.9s, 중앙 3.95s, 1.2s 미만 0개, 줄 최대 26자.

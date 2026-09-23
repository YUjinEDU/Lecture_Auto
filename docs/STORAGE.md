# 저장 구조 — 무엇이 어디에 있나

원칙: **`output/`은 사람이 보는 결과물만, `data/`는 입력과 작업 파일.** 강의 하나 = 폴더 하나(양쪽 모두 같은 `<lecture_id>`).
`<lecture_id>` 예: `06_종합설계_04-1_아이디어를컨셉으로만들기` (순번_과목_차시_제목). 두 폴더 모두 git 추적 안 함.

## 1. 결과물 — `output/<lecture_id>/`

| 파일 | 뜻 |
|---|---|
| `<id>.mp4` | 최종본. 모든 슬라이드가 검사 통과 또는 교수님 승인 |
| `<id>_DRAFT.mp4` | 검증 안 된 슬라이드가 있는 영상. 최종본이 생기면 자동 삭제 |
| `<mp4 이름>.report.md` | **검수 보고서** — "먼저 들어볼 슬라이드"(검사 실패·받아쓰기 불일치·후보 대기)와 영상 내 시각 |
| `<mp4 이름>.timeline.json` | 슬라이드별 시작 시각·길이·승인·검사 결과 (웹 UI가 읽는 형식) |

기존 결과물: `01_…`, `04_…` 폴더로 이전. 04의 교수님 전달본은 `종합설계_02_고객문제이해및정의_인트로교체.mp4`(인트로 수동 교체, D-13).
`output/_archive/`: 테스트 영상(mini 3slides), AI 원본 백업.

## 2. 작업 폴더 — `data/work_batch/<lecture_id>/`

| 경로 | 내용 | 사람이 손대도 되나 |
|---|---|---|
| `input/` | PPTX에서 변환한 PDF | ✕ (재생성) |
| `rendered/slide_NNN.png` | 슬라이드 이미지 | ✕ |
| `lecture_plan.json`, `sections/` | LLM 강의 계획·섹션 대본 캐시 | ✕ |
| `scripts/script_NNN.json` | **슬라이드별 대본** (`script` 필드). 고치면 그 슬라이드만 재합성 | ○ (검수 편집) |
| `audio/slide_NNN.wav` | 현재 음성 | ✕ |
| `audio/slide_NNN.wav.qc.json` | 품질 기록: 검사 통과 여부, 받아쓰기 결과·CER, 조각별 seed | ✕ (읽기) |
| `audio/slide_NNN.cand.wav` (+`.json`, `.qc.json`) | 다시 만든 **후보** 음성. 들어보고 `--promote N` | ✕ |
| `audio/slide_NNN.prev.wav` | 승격 전 이전 음성(되돌리기용) | ✕ |
| `audio/*.hash` | 캐시 키. 대본·참조음성·설정이 같으면 재합성 생략 | ✕ |
| `approved.json` | **교수님 승인 목록** (sha256 고정). 승인 음성은 `--slides`로 지정하지 않는 한 재생성 안 됨 | CLI로만 |
| `video/` | ffmpeg 중간 파일 | ✕ |

## 3. 입력·참조 — `data/`

| 경로 | 내용 |
|---|---|
| `PDF/종합설계 2026/*.pptx`, `*_강의스크립트.md` | 제작 대상 PPTX + 교수님 참고 대본(내용 참고용, D-11) |
| `PDF/종합설계 2026/1차/`, `PDF/AI현업문제해결/` | 이전 차수 PDF |
| `audio_ref/reference_v1.wav` | **현재 참조 음성**(D-12). 수정·덮어쓰기 금지 |
| `transcripts/professor_full_lecture_32min.txt` | 교수님 실강 전사 — 말투 분석 기준 |
| `voice_professor/` | 원본 녹음 |
| `backup_20260923_audio/` | S1 이전 01·04 음성 백업(읽기 전용) |
| `work/<job_id>/` | API(FastAPI+Celery) 경로의 작업 폴더 — 배치와 별개 |
| `work_mini_test*/`, `smoke*/` | 스모크 테스트 스크립트 작업 폴더(`scripts/run_mini_test*.py`, `smoke_*.py`) |

## 4. 자주 쓰는 명령

```bash
python scripts/batch_generate_lectures.py --status             # 전체 강의 진행 상황 한 표
python scripts/batch_generate_lectures.py --only 6 --gpu 1     # 04-1 제작(대본→음성→영상)
python scripts/batch_generate_lectures.py --only 6 --slides 12,15   # 일부 슬라이드 재생성(후보로)
python scripts/batch_generate_lectures.py --only 6 --promote 12     # 후보 채택
python scripts/batch_generate_lectures.py --only 6 --approve 1-46   # 현재 음성 승인
python scripts/batch_generate_lectures.py --only 6 --assemble-only  # 모델 없이 재조립
```
강의 번호(`--only`): 1–3 AI현업, 4–5 종합설계 1차, 6 04-1, 7 04-2, 8 05, 9 06.

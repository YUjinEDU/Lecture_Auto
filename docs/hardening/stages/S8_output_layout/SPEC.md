# S8 SPEC — 결과물 폴더 구조 + 한눈에 보는 상태

참조: `../../../STORAGE.md`(목표 구조, 감독 작성), S2·S6 REVIEW. 기준: master HEAD.

## 왜
- `output/`에 강의 영상·DRAFT·timeline·테스트 영상·백업이 한 폴더에 섞여 있고 이름 규칙이 제각각.
- 강의 하나가 어디까지 됐는지(대본 몇 장, 음성 몇 장, 검사 실패, 후보 대기, 승인) 보려면 폴더를 뒤져야 함.

## 목표 구조 (배치 경로 `scripts/batch_generate_lectures.py`)
```
output/<lecture_id>/                 ← 교수님·사람이 보는 결과물만
  <lecture_id>.mp4                   최종본 (모든 슬라이드 유효 또는 승인)
  <lecture_id>_DRAFT.mp4             검증 안 된 슬라이드가 있을 때
  <mp4 stem>.timeline.json           (기존 S2 형식 그대로)
  <mp4 stem>.report.md               ← 신규: 사람이 읽는 검수 보고서
data/work_batch/<lecture_id>/        ← 작업 폴더(기존 그대로, 이름·하위 구조 변경 금지)
```

## 작업 항목
### S8-a 강의별 출력 폴더
- `LECTURES`의 `output_mp4`를 `output/<id>/<id>.mp4`로 바꾼다(항목마다 하드코딩하지 말고 id에서 계산해도 됨 — 기존 관례에 맞게 판단).
- 최종본을 쓸 때 같은 폴더의 오래된 `<id>_DRAFT.mp4`와 그 `.timeline.json`/`.report.md`는 삭제(재생성 가능한 산출물이라 안전; 로그로 남김). DRAFT를 쓸 때 기존 최종본은 **건드리지 않는다**(S1-e 규칙 유지).
- `--assemble-only`·일반 실행 모두 적용.

### S8-b 검수 보고서 `report.md`
조립 직후 timeline과 같은 위치에 atomic write. 순수 함수로(`lecture_auto/pipeline/approval.py` 또는 작은 새 모듈): 입력은 `Timeline` + audio 디렉터리(qc·cand 파일 읽기), 출력은 markdown 문자열.
내용(한국어):
1. 머리: 강의 id, 최종/DRAFT, 총 길이(분:초), 슬라이드 수, 승인 n / 검사 통과 n / 실패 n / 후보 대기 n.
2. **"먼저 들어볼 슬라이드"** 표: gate 실패, STT fail/unavailable, `boundary_review` 비어있지 않음, 후보(`.cand.wav`) 대기 중인 슬라이드만. 열: 슬라이드, 영상 내 시작 시각(mm:ss), 길이, 문제(gate_reasons·STT 상태·CER), 조치 힌트(예: `--promote 12` / `--slides 12`).
   CER 높은 순 정렬. 문제 없으면 "없음".
3. 전체 슬라이드 표: 번호, 시작 시각, 길이, 승인, gate, STT, CER.
판정 기준은 기존 값만 쓴다(새 임계값·CER 합격선 도입 금지 — D-08).

### S8-c `--status` 명령
- `python scripts/batch_generate_lectures.py --status` (선택적으로 `--only`) → 강의별 한 줄 표를 stdout에 출력하고 종료.
  열: 번호, id, 슬라이드(png), 대본, 음성(wav), 검사 실패, 후보 대기, 승인, 영상(최종/DRAFT/없음 + 경로).
- 디스크만 읽는다: TTS 모델·LLM 클라이언트 로드 금지, 파일 쓰기 금지. 기존 승인 명령 상호배타 그룹에 넣는다.
- 계산은 순수 함수(웹 UI 재사용 대비)로 분리, 출력 포맷팅만 CLI에.
- "검사 실패"는 qc.json `ok=false` 기준, qc가 없으면 세지 않고 별도 표시(예: `qc없음 12`).

## 필수 테스트 (mock·tmp_path)
1. 조립 결과 경로가 `output/<id>/<id>.mp4` / DRAFT면 `<id>_DRAFT.mp4`, timeline·report가 같은 폴더
2. 최종본 조립 시 오래된 DRAFT 3종 삭제, DRAFT 조립 시 기존 최종본 불변
3. report: 실패·STT fail·boundary_review·후보 대기 슬라이드만 "먼저 들어볼" 표에 나오고 CER 내림차순, 문제 없으면 "없음"
4. `--status`: 알려진 tmp 폴더 구성 → 카운트 정확, `load_raon_pipeline`·`OpenAILLMClient` 미호출, 파일 생성 없음
5. 기존 테스트 전부 통과(경로 기대값 바뀌는 테스트는 새 구조로 갱신, 이유를 보고)

## 금지
- `data/`·`output/` 실데이터 이동·쓰기(기존 파일 이전은 감독이 한다), `data/audio_ref/**`.
- `data/work_batch/<id>/` 내부 구조·파일명 변경, 캐시 키 입력 변경(재합성 유발 금지).
- 품질 판정 로직 변경, AGENTS.md·docs/ 수정, 새 의존성.
- `lecture_auto/prompts/` 수정(감독이 병행 수정 중).

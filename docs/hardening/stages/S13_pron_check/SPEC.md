# S13 SPEC — 발음 사전 사전 점검(`--check`)

기준: master HEAD. 근거: `00_context/SPEED_RESEARCH_20260928.md` §4-1, §5 1위.
배경: 08/09 제작에서 사전에 없는 영어 용어가 합성 **후에** 발견돼 두 번 다시 만듦(최소 340 GPU-분 낭비).

## 작업 항목
### S13-a `lecture_auto/pipeline/pronunciation.py`
- `find_unlisted_latin_tokens(text: str, entries: list[dict]) -> list[str]` 추가.
  `apply_pronunciation(text, entries)` 결과에서 `[A-Za-z][A-Za-z0-9\-]*` 토큰을 찾아 **중복 제거·첫 등장 순서**로 반환.
  (원문에 직접 정규식을 돌리지 않는다 — "Burndown Chart" 같은 다단어 키를 놓치지 않기 위해 기존 치환을 재사용.)
- 미승인(`approved: false`) 항목은 치환되지 않으므로 결과에 남는 게 맞다(=아직 승인 필요).

### S13-b `scripts/batch_generate_lectures.py`
- `--check` (`--only` 필수, `--approve` 계열과 같은 "모델·LLM 로드 없음" 경로): `scripts/script_NNN.json`의 `script`를 읽어
  토큰별로 `토큰  등장 슬라이드 번호들  (사전에 미승인 항목으로 있으면 표시)` 표를 출력. 대본이 없으면 명확한 에러.
  미등록 토큰이 있으면 종료코드 1, 없으면 0(셸 스크립트에서 게이트로 쓰게).
- 일반 실행의 `[5/6]` 시작 직전, 같은 스캔 결과를 **경고 로그로만** 출력(동작 변경 없음, 중단하지 않음). 커밋 메시지에 명시.

### S13-c 테스트 (tmp_path만)
1. 다단어 키("Burndown Chart") 승인 시 "Burndown"/"Chart"가 결과에 없음
2. 미승인 항목 토큰은 결과에 남음, 승인 항목은 사라짐
3. 한글 조사 붙은 경우("API를") 처리, 중복 제거·순서
4. CLI `--check`: 가짜 작업 폴더에서 미등록 있으면 exit 1 + 슬라이드 번호 출력, 없으면 exit 0, `--only` 없으면 에러
5. 전체 pytest 통과

## 금지
실제 LLM/GPU, `data/`·`output/`·`config/pronunciation.yaml` 쓰기, 새 의존성, 캐시 키·합성 상수 변경.

# S19 SPEC — 대본 생성 최적화: 말투 재작성 통합 + 발음 사전 후보 자동 제안

기준: master HEAD(S13·S16a·S17 병합 후).
배경:
- S12 restyle은 별도 CLI라 새 강의마다 사람이 따로 돌려야 하고, 결과가 "손으로 고친 대본"(`.hash` 불일치)으로 남아 이후 재생성 흐름과 섞인다(D-18: 07~09 "수정됨" 61건이 사실 restyle).
- S13 `--check`가 미등록 영어 토큰을 찾아도, 한글 발음을 사람이 처음부터 써야 한다(08/09에서 105개를 손으로 작성).

## 작업 항목
### S19-a 배치 안 restyle 단계 (opt-in, `scripts/batch_generate_lectures.py`)
- `LECTURES` 항목에 `"restyle": True`일 때만. **키가 없으면 동작·캐시 키·파일 전부 기존과 동일**(기존 항목은 수정하지 않음).
- 섹션 결과(`result`)를 얻은 직후, 대본 파일 쓰기 루프 전에 `_restyle_section_cached(llm_client, result, section_result_path)`:
  - `lecture_auto.pipeline.restyle.restyle_scripts(client, {n: script})` 재사용(한 섹션 = LLM 1회, 기존 검증·재요청·원본 유지 규칙 그대로).
  - 캐시: `sections/section_NNN.restyled.json` + `.hash`, 키 = `content_hash(섹션 결과 JSON, restyle 지시문 템플릿 원문, restyle 시스템 프롬프트, llm config)`.
  - 반환: 각 슬라이드 `script`를 `RestyleResult.script`로 바꾼 `SectionScriptResult`(`model_copy`), carry_forward 불변.
  - 강의 단위 지표(전/후 합니다·습니다, 연결어, ~요 1,000자당)를 로그 + `restyle_report.json`(S12 CLI와 같은 형식)으로.
- 그 뒤 기존 쓰기 루프가 그대로 `script_NNN.json` + `.hash`를 쓴다 → restyle 결과는 "우리가 쓴 대본"이고, 사람이 고친 대본(`_hand_edited`)은 계속 보존.
- 승인된 슬라이드: 기존과 같다(대본이 바뀌면 오디오 캐시가 무효가 되지만 승인 규칙상 재합성 안 함) — 이 상호작용을 테스트로 고정.

### S19-b `--suggest-pron` (발음 후보 제안, TTS 모델 로드 없음)
- `--suggest-pron --only <하나>`: `_scan_unlisted`로 미등록 토큰과 등장 문장(토큰 포함 문장 최대 2개, 각 120자 이내)을 모아 텍스트 LLM 1회:
  "각 영어 토큰을 한국 대학 강의에서 교수가 실제로 읽는 한글 발음으로. 약어는 관례대로(예: PO→피오 또는 풀어 읽기 중 강의 문맥상 자연스러운 것). 출력 JSON `{"entries":[{"written":..,"spoken":..,"note":..}]}`".
  잘못된 JSON 1회 재요청(`strip_markdown_json_fence` 재사용).
- 검증: `spoken`에 라틴 문자가 남으면 제외(사유 출력). `written`이 요청 토큰 집합에 없으면 제외.
- 출력: `data/work_batch/<id>/pronunciation_suggestions.yaml`(atomic) — `config/pronunciation.yaml`과 같은 항목 형식 + `approved: false` + `source: llm`. 그리고 붙여넣기용 YAML 조각을 표준출력. **`config/pronunciation.yaml`은 절대 수정하지 않는다**(승인은 사람).
- 미등록 토큰이 없으면 LLM 호출 없이 종료(exit 0).

### S19-c 테스트 (mock LLM, tmp_path)
1. `restyle` 키 없음 → `restyle_scripts` 미호출, 기존 테스트·골든(S16) 전부 그대로 통과
2. `restyle: True` → 섹션마다 1회 호출, 쓴 `script_NNN.json`이 restyle 결과 + `.hash` 일치(=hand-edited 아님)
3. restyle 캐시: 같은 섹션 결과면 재호출 없음, 섹션 결과가 바뀌면 재호출
4. hand-edited 슬라이드는 restyle 결과로 덮어쓰지 않음
5. `kept_original` 슬라이드는 원본 유지
6. `--suggest-pron`: 정상 / 라틴 남은 spoken 제외 / 요청 외 written 제외 / 토큰 없으면 LLM 미호출 / config 파일 바이트 불변
7. 전체 pytest 통과

## 금지
기존 LECTURES 항목 수정, restyle 프롬프트·검증 규칙 변경, `config/pronunciation.yaml` 쓰기, 실제 LLM/GPU, `data/`·`output/` 쓰기(테스트), 새 의존성.

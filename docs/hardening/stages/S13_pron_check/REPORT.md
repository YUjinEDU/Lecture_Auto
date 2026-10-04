# S13 REPORT — 발음 사전 사전 점검 (`--check`)

- 브랜치: `s13-pron-check` (master c3c0229 기준)
- 변경 파일: `lecture_auto/pipeline/pronunciation.py` (`find_unlisted_latin_tokens`),
  `scripts/batch_generate_lectures.py` (`--check`, `_scan_unlisted`, `_cli_check`, [5/6] 직전 경고),
  `tests/test_pron_check.py` (신규)
- 해결 항목: S13-a, S13-b, S13-c
- 동작 변경: 일반 실행도 `[5/6]` 직전에 미등록 영어 토큰을 **경고 로그**로 출력(중단 없음). `--check`는
  `approval_group`(상호 배타)에 속하며 `--only` 필수, 미등록 있으면 exit 1.
- 추가 테스트 7건(다단어 키, 미승인/승인, 조사·중복·순서, --check exit 1/0, --only 없음, 대본 없음).
  신규 테스트는 기반 코드에서 ImportError로 실패 확인 후 구현.
- pytest: 451 passed (기준선 444 + 7). 실패 0.
- 실데이터 읽기 전용 확인(메인 repo cwd, 워크트리 스크립트 사용):
```
--only 08: [08_종합설계_05_스크럼_활용_애자일_프로세스] unlisted tokens: 0   (exit 0)
--only 09: [09_종합설계_06_Product_Backlog] unlisted tokens: 0   (exit 0)
```
(현재 사전이 08/09의 영어 용어를 모두 포함 — 이전에 두 번 재제작한 원인이 해소된 상태.)

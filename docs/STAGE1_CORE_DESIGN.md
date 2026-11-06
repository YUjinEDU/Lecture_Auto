# 1단계 설계: 코어 라이브러리화 + 강의별 설정

작성: 2026-11-07 · 브랜치: `feat/product` · 상위 문서: [`PRODUCT_PLAN.md`](PRODUCT_PLAN.md)

## 1. 지금 구조의 문제 (코드 근거)

| 문제 | 위치 |
|---|---|
| 강의 목록이 코드 안 상수. 웹 등록분은 import 시점에 `LECTURES.extend(load_web_lectures())`로 덧붙임 | `scripts/batch_generate_lectures.py:137-230`, `lecture_auto/web/registry.py` |
| 제작 로직 1,814줄이 CLI 스크립트 안에 있음(`process_lecture`, `_heal_lecture`, 승인·조립·점검) | `scripts/batch_generate_lectures.py` |
| 강의별 설정이 **프로세스 환경변수**로 전달됨: 참조 음성(`LECTURE_AUTO_REF_VOICE` → 모듈 상수 `REF_VOICE`), 마스터링(`LECTURE_AUTO_MASTER_AUDIO`), 음색 보정(`LECTURE_AUTO_VOICE_MATCH`를 `os.environ`에 넣었다 뺌) | `batch_generate_lectures.py:135,264`, `pipeline/video.py:226`, `pipeline/voice_match.py:33`, `web/runner.py:42-55` |
| 웹 ↔ 제작 계약이 CLI 인자 문자열(`--only <id>`, 부분 문자열 매칭) | `web/runner.py:job_argv`, `registry.new_lecture_id` |
| `produce.py`가 강의를 **목록 순번**(`LECTURES.index(lec)+1`)으로 지정 | `scripts/produce.py:95,100` |
| 승인·후보 채택 같은 몇 초짜리 파일 작업도 웹이 subprocess로 실행 | `web/app.py` → `batch_generate_lectures --approve ...` |

## 2. 유지할 것

- **GPU·LLM 작업은 계속 별도 프로세스로 돈다.** 작업 중단 시 프로세스 그룹 전체 종료, GPU 메모리 회수, 웹 재시작 후에도 작업 생존(pid 인계)이 이 구조에 기대고 있다. 바꾸는 건 "프로세스에 무엇을 넘기느냐"(CLI 인자 + 환경변수 → 작업 명세 파일)다.
- 파일이 진실의 원천. `data/work_batch/<id>/`, `output/<id>/` 경로와 파일 형식은 바꾸지 않는다.
- **TTS 캐시 키 불변.** `_tts_cache_key`는 참조 음성 *바이트*·모델·온도·시드·버전·목표 길이로 만든다(경로 아님). 같은 음성 파일을 가리키는 한 리팩터 후에도 기존 음성이 전부 유효해야 한다. 어긋나면 수십 시간 분량을 다시 합성하게 된다.
- `produce.py`의 슬라이드 단위 claim(flock) 병렬 구조.

## 3. 목표 구조

```
lecture_auto/
  core/
    project.py     # ProjectConfig(pydantic) + 저장소: data/projects/<id>/project.json
    paths.py       # 작업·출력 경로 계산 (지금 process_lecture 안의 디렉터리 규칙)
    jobs.py        # JobSpec(pydantic): kind, project_id, slides, gpu ...
    worker.py      # python -m lecture_auto.core.worker <job.json>  (GPU/LLM 작업 진입점)
  production/      # batch_generate_lectures.py에서 옮겨 온 제작 로직
    scripts.py     # 계획·섹션 대본 생성·말투 재작성·손으로 고친 대본 보존
    synth.py       # 슬라이드 합성, 캐시 키, 실패 슬라이드 정리
    heal.py
    assemble.py    # 승인 반영 조립, DRAFT/최종 경로
    review.py      # approve / promote / unapprove / restore_prev / check / status
scripts/
  batch_generate_lectures.py   # argparse만 남김 → core/production 호출 (기존 인자 그대로 동작)
  produce.py                   # 강의를 순번 대신 id로 지정
```

### ProjectConfig (강의별 설정)

지금 `LECTURES` 항목의 키를 그대로 옮기고, 환경변수로 전달되던 값을 필드로 만든다.

| 필드 | 지금 |
|---|---|
| `id`, `name`, `subject` | 동일 |
| `source` (`pdf` 또는 `pptx` 경로), `reference_script`, `clone_from`, `previous` | 동일 |
| `target_minutes`, `min_minutes` | 동일 (없으면 `TARGET_MINUTES`) |
| `ref_voice` | 환경변수 `LECTURE_AUTO_REF_VOICE` → **필드** (기본 `reference_v1.wav`) |
| `master_audio` | 환경변수 → **필드** |
| `voice_match` | `os.environ` 토글 → **필드** |
| `tts_engine` | 신규, 기본 `"raon"` (2단계에서 사용) |

저장: `data/projects/<id>/project.json`(원자적 쓰기). 강의 목록 = 이 폴더 목록. 2단계 이후 사용자별 분리는 `data/users/<uid>/projects/`로 루트만 바꾼다.

### 설정 전달 방식

- `REF_VOICE` 모듈 상수, `LECTURE_AUTO_MASTER_AUDIO`/`VOICE_MATCH` 환경변수 읽기를 없애고, `ProjectConfig`를 인자로 받는다(`process_lecture(project, ...)`, `assemble_video(..., master_audio=project.master_audio)`, `synthesize_raon_slide(..., voice_match=project.voice_match)`).
- CLI에서 손으로 export하던 환경변수가 필요 없어진다(지금 `docs/WEB_UI.md` 3절의 주의사항이 사라짐).

### 웹 연결

- 승인·후보 채택·승인 취소·되돌리기·상태 조회: 웹이 `production.review`를 **같은 프로세스에서 직접 호출**한다(작업 중인 강의 잠금은 지금처럼 409).
- 대본 생성·음성/영상 제작·재생성·복구·조립·점검: `JobSpec`을 `data/web/jobs/<job>.json`에 쓰고 `python -m lecture_auto.core.worker <job.json>`을 실행한다. `job_env`는 `CUDA_VISIBLE_DEVICES` 등 프로세스 수준 값만 남는다.
- `registry.py`, `--only` 부분 문자열 매칭, `new_lecture_id`의 부분 문자열 회피 규칙은 제거한다(id 완전 일치만).

## 4. 작업 순서 (각 단계가 커밋 하나 이상, 매번 전체 테스트 통과)

| # | 작업 | 확인 |
|---|---|---|
| 0 | **기준선 저장**: 현재 코드로 모든 강의의 슬라이드별 TTS 캐시 키, `--status` 출력, 강의별 출력 경로를 JSON으로 저장하는 점검 스크립트 | 스크립트가 지금 저장소에서 돌고 결과가 커밋됨 |
| 1 | `ProjectConfig` + 저장소 + 이전 스크립트(`LECTURES` + `data/web/lectures.json` → `project.json`). 이 단계에선 `LECTURES`를 `project.json`에서 읽어 만들어 기존 코드가 그대로 돈다 | 전체 테스트, 기준선과 동일 |
| 2 | 환경변수 → 필드 전환(`ref_voice`, `master_audio`, `voice_match`). 웹 `job_env`에서 해당 값 제거 | 기준선 캐시 키 동일, 테스트 |
| 3 | 제작 로직을 `lecture_auto/production/`으로 이동(동작 변경 없는 순수 이동). CLI는 얇은 argparse | 테스트, 기준선 동일, `--status` 동일 |
| 4 | `JobSpec` + `core.worker`; 웹 runner가 이를 사용; 승인류는 직접 호출. `produce.py`는 id로 지정 | 웹 테스트, 웹에서 실제 강의 하나로 대본 생성 → 승인 → 조립 수동 확인 |
| 5 | `registry.py`·`LECTURES` 상수·부분 문자열 매칭 제거, 문서(`WEB_UI.md`, `AGENTS.md`) 갱신 | 테스트, 기준선 동일 |

0번의 기준선 비교가 이 리팩터의 안전장치다. 캐시 키가 하나라도 달라지면 그 단계는 멈추고 원인을 찾는다.

## 5. 이 단계에서 하지 않는 것

- TTS 공급자 추상화(2단계), 계정·DB(3단계), 화면 변경.
- 발견했지만 손대지 않는 것: `LECTURE_AUTO_TTS_TEMPERATURE`로 온도를 바꿔도 캐시 키는 상수 `TTS_TEMPERATURE`를 쓴다(`raon_tts.py:108` vs `_tts_cache_key`). 온도를 바꾸면 결과는 달라지는데 캐시는 유효하다고 판단한다. 2단계에서 온도를 강의 설정으로 옮길 때 같이 고친다.

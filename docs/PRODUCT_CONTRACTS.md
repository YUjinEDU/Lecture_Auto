# 제품화 단계 간 약속 (2~6단계 공통)

여러 작업이 동시에 진행되므로, 서로 기대는 부분을 여기 한 곳에 고정한다. 바꾸려면 이 문서부터 고친다.

## 강의 설정 (`lecture_auto/core/project.py`, `data/projects/<id>/project.json`)

| 필드 | 뜻 | 누가 쓰나 |
|---|---|---|
| `owner` | 강의 주인 사용자 id. `None`이면 관리자 소유(계정 도입 전 강의) | 3단계(계정) |
| `tts_engine` | `"raon"`(로컬 GPU, 업로드 음성 복제) 또는 `"gemini"`(BAZE API, 기본 음성 30종) | 2단계(TTS) |
| `tts_voice` | `gemini`일 때 음성 이름(예: `Charon`). `raon`이면 무시 | 2단계 |
| `tts_instructions` | `gemini`일 때 말투 지시(예: "대학 강의처럼 차분하게") | 2단계 |
| `ref_voice` | `raon`일 때 복제할 참조 음성 경로(사용자가 올린 음성이면 `data/voices/<user>/<voice>.wav`) | 2·3단계 |

`as_item()`은 기본값과 같은 필드를 뺀 dict를 돌려준다. 제작 코드는 `item.get("tts_engine", "raon")`처럼 기본값을 직접 적는다.

## API 키가 작업 프로세스에 전달되는 방식

- 사용자는 BAZE API 키 하나를 등록한다(대본 생성 LLM과 Gemini TTS가 같은 게이트웨이 `https://factchat-cloud.mindlogic.ai/v1/gateway`를 쓴다).
- 웹의 작업 러너는 강의 `owner`의 키를 복호화해 작업 환경변수로 넘긴다:
  - `BAZE_API_KEY` = 사용자 키 (Gemini TTS)
  - `FACTCHAT_API_KEY` = 같은 키, `FACTCHAT_BASE_URL` = 위 게이트웨이 (대본 생성)
- `owner`가 없거나 키를 등록하지 않은 관리자 강의는 서버 `.env`의 값을 그대로 쓴다.
- 키 원문은 작업 기록(`data/web/jobs/*.json`의 `env`)·로그·명세 파일에 남기지 않는다.

## 저장 위치

| 경로 | 내용 | 단계 |
|---|---|---|
| `data/web/app.db` (SQLite) | 사용자, 암호화된 API 키, 음성 동의 기록, 공유 링크, 신고 | 3·4·6단계 |
| `data/voices/<user>/<voice>.wav` (+ `.json` 동의 기록) | 사용자가 올린 참조 음성 | 3단계 |
| `data/work_batch/<id>/study.json` | 용어·퀴즈와 교수자 승인 여부 | 5단계 |

강의 id는 전체에서 유일하므로 작업 폴더(`data/work_batch/<id>`, `output/<id>`)는 사용자별로 나누지 않는다. 접근 권한은 `owner`로 확인한다.

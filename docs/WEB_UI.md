# Lecture Auto 스튜디오 — 웹 화면 사용·운영 안내

교수님이 명령어 없이 강의 제작 전 과정을 진행하는 웹 화면. 제작 엔진은 그대로
`scripts/batch_generate_lectures.py`·`scripts/produce.py`이고, 웹은 그 명령을 버튼으로
실행하고 `data/work_batch/<id>/`·`output/<id>/` 파일을 보여 줄 뿐이다
(파일이 진실의 원천 — CLI로 한 작업도 웹에 그대로 보인다).

## 1. 서버 켜기 (GPU 서버에서)

```bash
cd ~/workspace/Lecture_Auto
LECTURE_WEB_PASSWORD='<교수님께 드릴 비밀번호>' .venv/bin/python -m lecture_auto.web --host 0.0.0.0 --port 8800
```

- 사용자 정보는 시작할 때 생성하는 SQLite `data/web/app.db`에 저장한다. 비밀번호는 사용자마다 다른 salt와 scrypt로 해시한다. DB에 사용자가 없고 `LECTURE_WEB_PASSWORD`가 있으면 `admin@local` 관리자를 만든다. 이후에는 이 환경변수를 바꿔도 기존 계정 비밀번호가 바뀌지 않는다. 이메일은 `LECTURE_WEB_ADMIN_EMAIL`로 처음 생성할 때 지정할 수 있다.
- 로그인은 이메일과 비밀번호를 사용한다. 계정이 만들어진 뒤에는 비밀번호 환경변수가 없어도 시작한다. 신규 설치에서는 공개 가입을 열기 전에 초기 관리자 계정을 만들어 둔다.
- 로그인 쿠키 서명 키는 처음 실행 때 `data/web/secret.key`(권한 600)에 만들어진다. 쿠키는 사용자 id와 만료 시간을 서명하며 HttpOnly·SameSite=strict를 사용한다. 이 키는 API 키 암호화에도 사용하므로 **로그아웃을 위해 삭제하거나 교체하면 안 된다**. DB와 함께 안전하게 백업한다. 분실하면 저장된 API 키를 복구할 수 없다. 계정을 비활성화하면 기존 쿠키도 즉시 거부한다.
- 오래 켜 둘 때는 tmux 등에서 실행. 서버를 껐다 켜도 **실행 중이던 제작 작업은 계속 돌고**, 다시 켠 서버가 그 작업을 이어서 추적한다. 다만 그 작업의 종료 코드는 알 수 없으므로 끝나면 "중단됨"으로 표시된다 — 실제 결과는 강의 화면의 영상 상태·확인 필요 목록으로 판단한다.
- 외부(연구실 홈페이지)에서 쓰려면 홈페이지 서버가 이 주소로 프록시한다. 화면은 상대 경로만 쓰므로 `/lecture/` 같은 하위 경로 아래에 붙여도 된다. GPU 서버 포트를 인터넷에 직접 열지 말 것.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `LECTURE_WEB_PASSWORD` | 없음 | 최초 사용자만 관리자 계정으로 생성할 때 사용할 비밀번호 |
| `LECTURE_WEB_ADMIN_EMAIL` | `admin@local` | 최초 관리자 이메일 |
| `LECTURE_WEB_SIGNUP` | `closed` | `closed`: 가입 차단, `open`: 공개 가입, `invite`: 일회용 초대 코드 필요 |
| `LECTURE_WEB_GPU` | `0` | 제작에 쓸 GPU 번호(nvidia-smi 기준). **GPU1은 다른 사람 학습용 — 쓰지 말 것** |
| `LECTURE_WEB_SECRET` | `data/web/secret.key` | 쿠키 서명 키를 직접 지정 |
| `LECTURE_WEB_ROOT` | 저장소 루트 | `data/`·`output/`·`config/`가 있는 폴더(테스트용 사본을 가리킬 때) |
| `LECTURE_WEB_MAX_LECTURES` | `30` | 계정당 등록 강의 수 |
| `LECTURE_WEB_MAX_UPLOAD_MB` | `300` | PPTX/PDF 파일 크기 한도 |
| `LECTURE_WEB_MAX_VOICES` | `10` | 계정당 음성 수 |
| `LECTURE_WEB_MAX_VOICE_UPLOAD_MB` | `50` | 음성 업로드 파일 크기 한도 |
| `LECTURE_WEB_STORAGE_LIMIT_MB` | `5120` | 계정당 업로드 원본·음성·동의 파일 합계 한도 |

설정 화면에서 자신의 BAZE API 키 하나를 등록한다. 저장 전 게이트웨이의 `GET /models/`로 검증하며,
DB에는 서버 서명 키에서 유도한 Fernet 키로 암호화한 값과 끝 4자리만 저장한다. 화면과 API는 끝 4자리만 돌려준다.
키 삭제도 설정 화면에서 할 수 있다. 일반 사용자는 키가 없으면 작업을 등록할 수 없다.
관리자 또는 이전 강의(`owner=null`)는 등록 키가 없으면 서버 환경변수를 사용한다.

가입 화면은 이메일·10자 이상 비밀번호·이름·필수 약관 동의를 받는다. 초대 모드의 코드는 관리 화면에서 발급하며 한 번만 사용할 수 있다.
약관은 로그인 없이 `/terms`에서 읽을 수 있다. 일반 사용자는 자기 강의와 음성·작업만 볼 수 있고 다른 사용자의 리소스에는 404를 받는다.
관리자는 모든 강의와 작업을 볼 수 있으며 `owner=null`인 이전 강의도 관리자 소유로 취급한다.

## 2. 교수님 사용 순서

1. **새 강의 등록** — PPTX/PDF, 제목, 과목, 목표 길이(분), 필요하면 최소 길이. 음성 엔진은 Raon 또는 Gemini를 선택한다. Raon은 내 음성 또는 서버 기본 음성을, Gemini는 기본 음성 30종과 선택적인 말투 지시를 사용한다. 등록한 뒤에도 강의의 **음성 설정**에서 수정할 수 있다.
2. **1. 대본 생성** — 슬라이드를 읽고 대본을 만든다(GPU 안 씀, 수 분).
3. **대본 검토·수정** — 슬라이드별 대본을 고치고 "대본 저장". 고친 대본은 "대본 직접 수정됨"으로 표시되고, 대본을 다시 생성해도 덮어쓰지 않는다.
4. **2. 음성·영상 제작** — 전체 음성 + 영상(GPU, 강의 길이의 약 5배 시간). 끝나면 실패한 슬라이드를 한 번 자동 복구한다.
5. **확인 필요 탭** — 검사에 걸린 슬라이드를 듣고:
   - 괜찮으면 **현재 음성 승인**
   - 새로 만든 후보가 있으면 들어보고 **후보 채택**
   - 대본을 고친 뒤 "다시 만들기 선택" 체크 → **선택 슬라이드 다시 만들기**
   - 잘못 승인했으면 **승인 취소**, 후보를 잘못 채택했으면 **이전 음성으로 되돌리기**
   - 음성이 아직 없는 슬라이드는 "확인 필요"가 아니라 "아직 음성이 없는 슬라이드"로 따로 표시된다(4단계를 실행하면 만들어짐).
6. **영상 다시 조립** → "결과물 내려받기"에서 mp4·검수 보고서를 받는다.
   모든 슬라이드가 통과/승인이면 `<id>.mp4`(최종), 아니면 `<id>_DRAFT.mp4`.

작업은 한 번에 하나만 실행되고 나머지는 대기한다. 웹이 켜져 있는 동안에는 같은 강의나 GPU 0을 쓰는 명령줄 작업(`produce`, `batch_generate_lectures`)을 손으로 돌리지 말 것 — 웹은 명령줄에서 시작한 작업을 볼 수 없어서 서로 잠그지 못한다.

로그인 실패는 1초 지연되며 이메일당 1분에 10회, 전체 50회에서 제한한다(해당 제한에 도달하면 맞는 비밀번호도 거부).
세션 쿠키는 HTTPS(또는 프록시의 `X-Forwarded-Proto: https`)로 접속했을 때만 `Secure`가 붙는다.
외부에 열 때는 프록시에서 HTTPS를 종료하고 외부의 전달 헤더를 덮어쓰며 요청 횟수와 본문 크기를 제한한다.
작업 중인 강의는 대본 수정·설정 변경·승인이 잠긴다(409).
"작업 중단"은 프로세스 그룹 전체를 종료하며, 이미 만들어진 음성은 남는다.

음성·영상 제작은 일부 슬라이드가 검사에 걸려 DRAFT로 끝나도 종료 코드가 실패라서, 웹은 작업이 끝난 순간의
디스크 상태로 결과를 표시한다: 모든 슬라이드에 음성이 있고 일부만 보류면 **"확인 필요 N장"**(5단계로 진행),
음성이 없는 슬라이드가 남았거나 다른 작업이 실패했으면 **"실패"**(작업 기록의 로그 끝부분 확인).

저장하지 않은 대본 수정이 있는 채로 다른 화면으로 가면 확인 창이 뜬다.

## 3. 버튼과 실제 명령

작업 버튼은 `data/web/jobs/specs/<job>.json`(작업 명세: 종류·강의 id·슬라이드)을 쓰고
`python -m lecture_auto.core.worker <명세>`를 실행한다. worker가 명세를 아래 명령으로 바꾼다(`lecture_auto/core/jobs.py`).
승인·후보 채택·승인 취소·되돌리기는 작업이 아니라 웹 프로세스 안에서 바로 처리한다.

| 버튼 | 실행 명령 (`--only <id>`) |
|---|---|
| 대본 생성 | `batch_generate_lectures --skip-tts` |
| 음성·영상 제작 | `produce --gpus 0 --fix-failed --heal` |
| 선택 슬라이드 다시 만들기 | `batch_generate_lectures --slides N,M --gpu 0` (후보로 저장) |
| 보류 슬라이드 자동 복구 | `batch_generate_lectures --heal --gpu 0` |
| 영상 다시 조립 | `batch_generate_lectures --assemble-only` |
| 발음 점검 | `batch_generate_lectures --check` |
| 현재 음성 승인 / 후보 채택 | CLI의 `--approve N` / `--promote N [--allow-failed]`와 같은 동작 (즉시) |
| 승인 취소 / 이전 음성으로 되돌리기 | CLI의 `--unapprove N` / `--restore-prev N`와 같은 동작 (즉시) |

작업 프로세스에는 `CUDA_VISIBLE_DEVICES=<LECTURE_WEB_GPU>`와 `LECTURE_AUTO_PROJECTS=<root>/data/projects`를 넣는다.
소유자의 키를 실행 직전에 복호화하여 `BAZE_API_KEY`와 `FACTCHAT_API_KEY`로 넣고,
`FACTCHAT_BASE_URL=https://factchat-cloud.mindlogic.ai/v1/gateway`를 지정한다.
평문 키는 작업 기록의 `env`나 명세에 넣지 않는다. 작업 프로세스 앞의 `web.job_worker`가 출력의 API 키를
디스크에 쓰기 전에 가린다. 이 프로세스도 작업 그룹에 속하므로 웹 재시작 후 살아 있고 취소 시 함께 종료된다.
참조 음성(`ref_voice`), 음색 보정(`voice_match`), 마스터링(`master_audio`)은 강의의 `project.json`에 있고,
웹에서 등록한 Raon 강의는 내 기본 음성(없으면 `reference_v2.wav`) + 음색 보정 + 마스터링으로 만들어진다. CLI로 직접 돌려도 같은 설정을 쓴다
(환경변수를 손으로 지정할 필요 없음).

## 4. 파일 위치

| 경로 | 내용 |
|---|---|
| `data/projects/<id>/project.json` | 강의 하나의 설정(입력 파일, 목표 길이, 참조 음성 등). 웹과 CLI가 모두 여기서 강의 목록을 읽는다(`LECTURE_AUTO_PROJECTS`로 변경) |
| `data/web/uploads/<id>/` | 올린 PPTX/PDF |
| `data/web/jobs/<job>.json`, `.log` | 작업 기록과 전체 로그("작업 기록" 화면) |
| `data/web/jobs/specs/<job>.json` | worker에 넘긴 작업 명세 |
| `data/web/secret.key` | 로그인 쿠키 서명 키 |
| `data/web/app.db` | 계정·암호화 API 키·음성 메타데이터·초대·신고·비활성화·업로드 소유권 |
| `data/voices/<user>/<voice>.wav` | 계정 전용 참조 음성 |
| `data/voices/<user>/<voice>.json` | 업로드 원본 SHA-256, 동의 문구·시각·사용자 id |

`data/`는 git에 올리지 않는다. 웹에서 강의를 "목록에서 삭제"하면 `project.json`만 지우고 파일은 남긴다.
그래서 같은 제목으로 다시 올리면 남은 폴더와 겹치지 않는 새 번호를 받는다(옛 승인·대본·영상을 물려받지 않음).
삭제한 강의의 업로드도 계정 저장 공간 계산에 포함된다. 완전 삭제는 운영자에게 요청한다.
작업이 대기·실행 중인 강의는 삭제가 거부된다(409). 다른 강의의 작업은 상관없다: 모든 명령이 강의를 id로 가리킨다.

### 처음 한 번: 강의 목록 이전

`project.json`이 생기기 전의 저장소(강의 목록이 코드 상수 + `data/web/lectures.json`)에서 올라온 경우, 서버를 켜기 전에 한 번 실행한다.
이미 `project.json`이 있는 강의는 건드리지 않으므로 다시 실행해도 안전하다.

```bash
.venv/bin/python -m lecture_auto.core.migrate   # data/projects/<id>/project.json 생성
```

이걸 하지 않으면 강의 목록이 비어 보인다.

### 내 음성과 신고 관리

**내 음성**에서 WAV·MP3·M4A를 업로드하고
“이 목소리의 주인이 본인이거나, 주인에게 AI 음성 복제 사용 동의를 받았습니다”에 동의해야 한다.
확장자와 매직 바이트를 검사하며 필요한 경우 ffmpeg로 24kHz 모노 PCM WAV로 변환한다.
이름 변경·미리 듣기·기본 음성 지정·삭제를 지원한다. 내 음성은 다른 계정이 조회하거나 강의에 지정할 수 없다.
Raon은 비상업적 학교 내부용이며 공개 서비스에서는 Gemini를 사용한다.

강의와 음성 화면에서 로그인한 사용자가 신고할 수 있다. **관리** 화면은 신고 목록·사용자 목록·초대 코드 발급을 제공한다.
관리자는 신고 대상 음성이나 강의를 비활성화/복구하고 사용자 계정도 비활성화/복구할 수 있다.
비활성화된 음성·강의는 새 작업 제출과 실행 직전에 거부하며, 사용자 비활성화는 기존 세션도 무효화한다.
이미 실행 중인 작업은 관리자가 작업 기록에서 따로 취소한다.

주요 API: `/api/signup`, `/api/login`, `/api/logout`, `/api/me`,
`/api/settings/key`, `/api/voices`, `/api/lectures/<id>/settings`, `/api/reports`,
`/api/admin/reports`, `/api/admin/users`, `/api/admin/invites`,
`PUT /api/admin/voices/<id>`, `PUT /api/admin/lectures/<id>`, `PUT /api/admin/users/<id>`.

## 5. 개발

- 코드: `lecture_auto/web/` (`app.py` 라우트, `store.py` 파일 조회·대본 저장, `runner.py` 작업 큐, `static/` 화면 — 빌드 없는 HTML/JS/CSS).
  강의 설정·작업 명세·worker는 `lecture_auto/core/`, 제작 로직은 `lecture_auto/production/batch.py`.
- 테스트: `tests/test_web_app.py`, `tests/accounts/`, `tests/test_project.py`, `tests/test_jobs.py` — 임시 폴더 사본과 가짜 실행 파일로 계정 격리·암호화·음성 동의·할당량·실제 작업 큐·취소·승인을 검증한다. 모든 외부 API와 ffmpeg는 모의 처리한다.

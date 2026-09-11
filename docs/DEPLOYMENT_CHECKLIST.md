# 배포 전 체크리스트 (운영) — Lecture Auto

> 코드 밖에서 손봐야 하는 운영/보안 작업 모음. 공개(외부 접근) 전에 **위에서 아래로** 순서대로.
> 토폴로지: `브라우저 → 공개 홈페이지(NAS, Node Next.js) → /api/gpu 프록시 → 내부 GPU 서버(FastAPI)`.
> cloudflared(`sdlab_tunnel`)가 홈페이지 앞단에서 외부 트래픽 수신. GPU 서버는 LAN에만 존재.

---

## 0. 한눈에 보기 (우선순위)

| # | 항목 | 위험도 | 차단성 |
|---|------|:---:|:---:|
| 1 | `api.txt` OpenAI 키 제거 + 회전 + 히스토리 스크럽 | 🔴 치명 | 공개 전 필수 |
| 2 | 홈페이지 auth 미들웨어가 `/api/gpu/*` 보호 | 🔴 치명 | 공개 전 필수 |
| 3 | GPU 드라이버 NVML mismatch 수정 | 🟠 높음 | 로컬 GPU 동작 전 필수 |
| 4 | `GPU_API_URL` 등 env 설정 (홈페이지 + GPU 서버) | 🟠 높음 | 동작 전 필수 |
| 5 | sdlab_web 컨테이너 → GPU LAN 도달성 확인 | 🟠 높음 | 동작 전 필수 |
| 6 | 백엔드 프로세스 관리(systemd/docker) | 🟡 중간 | 안정성 |
| 7 | Rate limiting | 🟡 중간 | 공개 권장 |
| 8 | 스모크 테스트 | 🟢 검증 | 공개 직전 |

---

## 1. 🔴 `api.txt` 유출 키 제거 + 회전

`api.txt`(레포 루트, git 추적 중)에 살아있는 OpenAI 키가 있고 `demo/ai.py`가 읽는다. **공개 전 1순위.**

```bash
# (1) OpenAI 대시보드에서 해당 키 즉시 폐기(revoke) 후 새 키 발급
#     https://platform.openai.com/api-keys

# (2) 코드에서 키를 env로만 읽도록 정리됐는지 확인 (LLMClient 통일 작업 후엔 OPENAI_API_KEY env)
# (3) 파일 제거 + gitignore
git rm api.txt
echo "api.txt" >> .gitignore
echo ".env" >> .gitignore        # 혹시 누락됐으면
git commit -m "chore(security): remove leaked OpenAI key file"

# (4) git 히스토리에서 완전 제거 (이미 푸시됐다면 필수)
#     git-filter-repo 권장 (설치: pipx install git-filter-repo)
git filter-repo --path api.txt --invert-paths --force
#     또는 BFG: java -jar bfg.jar --delete-files api.txt
git push --force --all     # 협업자에게 재클론 공지
```

- [ ] 키 폐기 + 신규 발급
- [ ] `api.txt` 삭제 + `.gitignore` 등록
- [ ] 히스토리 스크럽 + force-push
- [ ] 새 키는 GPU 서버 `.env`의 `OPENAI_API_KEY`로만 보관

---

## 2. 🔴 홈페이지 auth 미들웨어가 `/api/gpu/*` 보호

`/api/gpu/[...path]` 프록시는 **GPU API 전체로 가는 통로**다. 홈페이지가 공개라서, 이 경로가 인증으로 막히지 않으면 누구나 GPU 백엔드를 호출하는 **오픈 릴레이**가 된다.

Next.js 미들웨어 matcher는 흔히 `/api`를 제외하므로 반드시 포함시킬 것.

```ts
// 홈페이지 레포의 middleware.ts (sdlab_web)
export const config = {
  // /api/gpu 를 반드시 포함
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

// 미들웨어 본문에서 /api/gpu/* 요청에 대해 세션/JWT 검증 후 통과/거부
// (교수 role 또는 SERVER_SECRET 헤더 등 — 기존 인증 체계에 맞춤)
```

- [ ] `/api/gpu/*`가 matcher에 포함됨
- [ ] 미인증 요청이 401/403으로 거부되는지 테스트
- [ ] (선택) 프록시 라우트에서 `SERVER_SECRET` 헤더를 추가로 검증해 GPU FastAPI까지 이중 게이팅

---

## 3. 🟠 GPU 드라이버 NVML mismatch 수정

```
Failed to initialize NVML: Driver/library version mismatch (535.309)
```
드라이버 커널 모듈과 유저스페이스 라이브러리 버전 불일치. 로컬 Qwen3-TTS/VLM 돌기 전 해결.

```bash
nvidia-smi                      # 현재 에러 재확인
# 가장 간단: 재부팅
sudo reboot
# 또는 모듈 재로드 (GPU 미사용 상태에서)
sudo rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia 2>/dev/null
sudo modprobe nvidia
# 패키지 버전 정렬이 필요하면 드라이버 재설치
nvidia-smi                      # name/메모리 정상 출력되면 OK
```

- [ ] `nvidia-smi` 정상 출력
- [ ] `python -c "import torch; print(torch.cuda.is_available())"` → True

---

## 4. 🟠 환경변수 설정

### 4-1. 홈페이지(NAS, sdlab_web 컨테이너)
```bash
# 홈페이지 .env.local / docker-compose environment
GPU_API_URL=http://<GPU_LAN_IP>:8000     # 서버 전용! NEXT_PUBLIC_ 아님
```
> `portal/.env.local.example` 참고. 브라우저엔 노출 안 됨.

### 4-2. GPU 서버 (FastAPI)
```bash
# /home/dbsdosdb/workspace/Lecture_Auto/.env  (.env.example 참고)
OPENAI_API_KEY=<신규 키>                 # 1번에서 발급
REDIS_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
REDIS_PROGRESS_DB=2
JOB_OUTPUT_ROOT=/data/work
SOFFICE_BIN=soffice
RENDER_DPI=150
LOG_LEVEL=INFO
# (LLM 통일 후) LLM_VLM_MODEL / LLM_SCRIPT_MODEL
# (TTSEngine 후)  TTS_ENGINE=qwen
SERVER_SECRET=<홈페이지와 공유할 비밀>     # 프록시→FastAPI 인증용(선택)
```

- [ ] 홈페이지에 `GPU_API_URL`
- [ ] GPU 서버 `.env` 채움 (특히 `OPENAI_API_KEY`)
- [ ] `SERVER_SECRET` 양쪽 일치(이중 게이팅 쓸 경우)

---

## 5. 🟠 컨테이너 → GPU LAN 도달성

sdlab_web 컨테이너가 GPU 서버 LAN IP로 outbound 가능한지 확인. (기본 docker bridge면 보통 호스트 경유로 됨)

```bash
# NAS에서
sudo docker exec -it sdlab_web sh
#  컨테이너 안에서:
wget -qO- http://<GPU_LAN_IP>:8000/health   # 또는 curl
#  → {"status":"ok"} 나오면 도달 OK
```
막히면: compose 네트워크 설정(예: `network_mode: host` 또는 적절한 라우팅) 조정.

- [ ] 컨테이너 안에서 `/health` 응답 확인

---

## 6. 🟡 백엔드 프로세스 관리 (dev 터미널 금지)

GPU 서버에서 uvicorn·Celery·Redis를 재부팅에도 살아남게 서비스로.

```bash
# 권장: docker-compose 또는 systemd
# 예) systemd 유닛 3개: lecture-api(uvicorn), lecture-worker(celery), redis(또는 docker)
#  - uvicorn --workers 1  (GPU 비공유)
#  - celery -A lecture_auto.tasks.celery_app worker --concurrency 1
sudo systemctl enable --now lecture-api lecture-worker redis
```
> Celery `--concurrency 1` 고정 (GPU OOM 방지, CLAUDE.md 규칙).

- [ ] API/worker/redis가 서비스로 등록 + 재부팅 생존
- [ ] cloudflared(`sdlab_tunnel`)도 named tunnel 서비스로 상시 기동

---

## 7. 🟡 Rate limiting

공개 엔드포인트 남용/비용 폭주 방지.

- [ ] 홈페이지 미들웨어 또는 FastAPI(slowapi 등)에 분당 요청 제한
- [ ] 특히 비용 발생 경로(스크립트 생성=OpenAI, 재생성, TTS) 보호

---

## 8. 🟢 공개 직전 스모크 테스트

```bash
# (A) GET (슬라이드 PNG) — 200 + image/png
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" \
  https://홈페이지/api/gpu/jobs/<id>/slides/1/png

# (B) PUT (스크립트 저장) — 200 + JSON
curl -s -X PUT https://홈페이지/api/gpu/jobs/<id>/scripts/1 \
  -H 'content-type: application/json' -d '{"script":"테스트"}'

# (C) SSE (진행률) — 이벤트가 "찔끔찔끔" 와야 정상(버퍼링 X)
curl -N https://홈페이지/api/gpu/jobs/<id>/scripts/progress

# (D) 미인증 요청이 막히는지 (2번 검증)
curl -s -o /dev/null -w "%{http_code}\n" https://홈페이지/api/gpu/jobs/x/scripts   # 401/403 기대
```

- [ ] A/B/C 정상, C는 점진적 수신
- [ ] D는 거부됨

---

## 참고: 이제 불필요해진 것

- **FastAPI CORS / `ALLOWED_ORIGINS`** — 프록시 도입으로 브라우저는 same-origin만 호출(서버↔서버 통신)하므로 더 이상 필요 없음. 정리 가능.

---

_최종 수정: 2026-06-13_

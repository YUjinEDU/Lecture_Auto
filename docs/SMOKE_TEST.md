# 로컬 E2E 스모크 테스트

단위 테스트는 모든 모델을 mock합니다. 이 스모크는 **실제 모델로** 파이프라인이 끝까지 도는지 확인합니다 — LLMClient(OpenAI)·TTSEngine(로컬 Qwen) 리팩터링이 실제로 맞물리는지 배포 전 검증용.

스크립트: `scripts/smoke_e2e.py` · 입력: PDF(권장) 또는 PPTX · 출력: `data/smoke/<stem>/`

## 사전 점검 (pre-flight)

| 필요 | 확인 | 어느 단계부터 |
|---|---|---|
| poppler (`pdftoppm`) | `which pdftoppm` | render~ |
| `OPENAI_API_KEY` | `echo $OPENAI_API_KEY` | vlm~ |
| GPU + `qwen-tts` + 드라이버 정상 | `nvidia-smi`, `python -c "import qwen_tts"` | tts |
| ffmpeg (영상까지 갈 때) | `which ffmpeg` | (영상은 스모크 범위 밖) |

## 단계별 실행 (싼 것부터)

```bash
# 0) 의존성 (uv 사용 시 자동) — 또는: pip install -e .
# 1) 렌더만 (API·GPU 불필요) — poppler/파싱 확인  ✅ 이미 통과 확인됨
uv run python scripts/smoke_e2e.py "PPTX/04-SQL 1.pdf" --stage render --max-slides 2

# 2) ① 검증 — OpenAI VLM만 (가장 싼 API 확인). GPU 불필요
export OPENAI_API_KEY=sk-...        # 새로 회전한 키
uv run python scripts/smoke_e2e.py "PPTX/04-SQL 1.pdf" --stage vlm --max-slides 2

# 3) ① 전체 — OpenAI VLM + 스크립트 (기본 단계). GPU 불필요
uv run python scripts/smoke_e2e.py "PPTX/04-SQL 1.pdf" --stage script --max-slides 2

# 4) ② 포함 전체 — 로컬 Qwen3-TTS (GPU 필요, 드라이버 mismatch 먼저 수정)
uv run python scripts/smoke_e2e.py "PPTX/04-SQL 1.pdf" --stage tts --max-slides 2 --voice 박유진음성.wav
```

> 비용: `--max-slides N`이 OpenAI 호출 수를 제한합니다 (슬라이드당 vision 1 + text 1). 렌더는 PDF 전체를 PNG로 만들지만(무료) 유료 API는 N장만 처리합니다. 처음엔 2로.

## 단계 의미

- `render` 통과 → 파싱·poppler·manifest OK (코드 구조 검증).
- `vlm`/`script` 통과 → **① OpenAI 통합이 실제로 동작** (가장 위험했던 신규 연동).
- `tts` 통과 → **② 로컬 Qwen3-TTS가 음성 생성** → 전체 흐름 완성.

## 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `pdftoppm` not found | `sudo apt install poppler-utils` |
| `OPENAI_API_KEY is not set` | export 후 재실행 |
| OpenAI 401/insufficient_quota | 키 회전/결제 확인 |
| `nvidia-smi` mismatch | 재부팅 (DEPLOYMENT_CHECKLIST §3) |
| `No module named qwen_tts` | `pip install qwen-tts` (GPU 환경) |
| TTS만 실패, ①은 성공 | ②(TTS)만 문제 — 모델/GPU 확인. ①은 정상이라는 신호 |

## 현재 검증 상태 (2026-06-13)

- ✅ `--stage render` — 실제 `PPTX/04-SQL 1.pdf`로 통과 (parse 2 slides + PNG 렌더).
- ⏳ `vlm`/`script` — `OPENAI_API_KEY` 설정 후 실행 필요 (스크립트 경로는 import까지 검증됨).
- ⏳ `tts` — GPU 드라이버 수정 + qwen-tts 설치 후 실행 필요.

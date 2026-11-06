# Gemini TTS 조사 (2026-10-09/10)

출처: ai.google.dev/gemini-api/docs/{pricing,speech-generation}, mixed-news.com (3.8 voice cloning), eesel.ai.
HANDOFF.md의 "복제 미검증" 가정을 대체한다 -- 최신 3.8 모델은 음성 복제를 지원한다.

## 모델/요금 (USD / 1M tokens, 출력=오디오 25 tok/s)
| ID | 복제 | 입력 | 출력 |
|---|---|---|---|
| gemini-3.8-flash-tts | O | 0.50 -> 2027-01-01부터 1.00 | 9 -> 18 |
| gemini-3.8-flash-lite-tts | O | 0.50 -> 1.00 | 6 -> 12 |
| gemini-3.1-flash-tts-preview | X | 1.00 | 20 |
| gemini-2.5-pro-preview-tts | X | 1.00 | 20 |
무료 티어(3.8), 배치 약 50% 할인. 강의 1편(20~25분, 3~3.75만 tok) 3.8-flash 기준 약 $0.35 -> 2027-01부터 약 $0.70.

## 음성 복제
- `POST /v1beta/voices`, `type="replicated"`, `store`(기본 True, 1년 TTL, 프로젝트당 200개) -> `voice_...` / stateless `voicekey_...`(7일).
- 참조 음성 + **동의 음성(consent audio, 화자 본인 녹음)** 필요. 참조 약 30초(보도 기준, 공식 복제 문서 미확인).
- AI Studio 차단 지역: 일리노이/텍사스/EEA/영국/스위스/인도. 한국은 목록에 없음(공식 확인 안 함).
- SynthID 워터마크 + C2PA. 복제 음성은 Google 서버에 저장됨 -> 교수님 동의 필요.
- 스타일: `speech_metadata.style`, `<short pause>` 태그, 대문자 강조. 한국어 지원.

## 리스크
- 재현성: 모델 업데이트 시 출력 변동 -> 모델 ID 고정 + WAV 보관.
- 품질 수치는 대부분 Google 자체 발표. 한국어 강의 품질은 직접 청취 검증 필요(미실시).
- 가격은 Google 결정(2027-01 2배).

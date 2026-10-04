# S15 SPEC — 말하는 문장에 맞춘 슬라이드 하이라이트(형광펜/밑줄)

기준: **S14 브랜치(또는 S14 병합 후 master)**. S14의 `segment_spans`/`written_segments`/CLI를 재사용.
목표: 지금 말하는 문장이 가리키는 슬라이드 텍스트 블록에 형광펜+밑줄을 표시해 "슬라이드쇼"를 "강의"처럼.
선행연구: AutoLectures(2505.02966)가 같은 아이디어(Levenshtein/LLM 정렬) — `00_context/PRIOR_ART_20261005.md`. 우리 기여는 새로움이 아니라 실사용 품질.

## 원칙 (D-19)
- 결과는 **별도 파일** `<stem>_annotated.mp4`. 원본 mp4·timeline·DRAFT/승인 로직은 건드리지 않는다.
- 재합성 없음: 기존 WAV를 그대로 쓰고(`-c:a copy` 또는 timeline 순 WAV 병합 재사용) 영상만 새로 만든다.
- 결정적(재현성): 매핑은 어휘 기반, LLM 없음.

## 작업 항목
### S15-a `lecture_auto/pipeline/highlight.py` (신규)
- 블록 좌표: `data/work_batch/<id>/input/`의 PDF를 `parse_pdf`로 다시 파싱(0.1초 수준) → `ShapeRecord`(EMU) 중 `has_text`인 것.
  픽셀 변환: `scale = PNG 폭(px) / 페이지 폭(pt)`, EMU→pt는 `/12700`. 페이지 폭은 PyMuPDF로(의존성 이미 있음).
- `map_segment_to_block(seg_text: str, blocks) -> int | None`: 조각(원문 written 텍스트 우선, 없으면 spoken)과 블록 텍스트의 어휘 겹침 점수.
  토큰 = 한글 2자 이상 어절의 앞 2~3글자 바이그램 + 라틴 토큰 소문자(단순·결정적 방식이면 세부는 작업자 재량, 근거를 보고).
  임계값 미만이면 None(하이라이트 없음). 제목 블록(`text_role=="title"`)은 매칭 대상에서 제외 또는 감점(항상 제목이 걸리는 것 방지).
  같은 블록이 연속 조각에서 이어지면 유지.
- `draw_highlight(png, bbox_px) -> PIL.Image`: 반투명 노란 형광펜(알파 ~0.30) + 블록 아래 2~3px 밑줄. 원본 PNG 불변, 새 이미지 반환.

### S15-b CLI 확장 (`scripts/annotate_lecture.py --highlight`)
- 슬라이드마다 조각 구간별로 프레임 PNG(하이라이트 없으면 원본 그대로)를 스크래치/`video/annotate_tmp/`에 쓰고,
  ffmpeg concat 매니페스트(`file`/`duration`)를 **조각 단위**로 만들어 기존 `assemble_video`와 같은 인코딩 옵션으로 영상 생성.
  오디오는 timeline 순서의 WAV(이미 있는 `merge_audio` 재사용). `--burn`과 함께 주면 S14 자막도 입힘.
- 출력: `<stem>_annotated.mp4` + `<stem>.highlight.json`(슬라이드·조각별 매핑 블록 id·점수, 커버리지 통계).
- `--slides 3-5` 옵션: 일부 슬라이드만 짧은 미리보기 영상으로(사용자 검토용).

### S15-c 테스트 (tmp_path, ffmpeg mock, 합성 PNG)
1. 좌표 변환: 알려진 EMU 박스 → 기대 픽셀 박스
2. 매핑: 블록 텍스트 단어가 많이 겹치는 조각 → 해당 블록, 무관 조각 → None, 제목만 겹치면 제목 선택 안 함
3. draw_highlight: 박스 안 픽셀 색 변화, 박스 밖 불변, 원본 파일 불변
4. 매니페스트: 조각 duration 합 == 슬라이드 WAV 길이(허용 1ms), 슬라이드 순서
5. 원본 mp4/timeline 바이트 불변
6. 전체 pytest 통과

## 보고에 반드시 포함
- 08 강의 실데이터 **읽기 전용** 커버리지: 조각 중 하이라이트가 붙은 비율, 슬라이드별 분포, 잘못 붙은 것으로 보이는 예 5개(조각 텍스트 vs 블록 텍스트).
- 08 슬라이드 3~5의 미리보기 mp4를 **스크래치 경로**에 생성(`--out-dir`) — ffmpeg만 쓰므로 GPU 불필요. 경로를 보고.

## 금지
`raon_tts.py`·`batch_generate_lectures.py`·`video.py` 수정(재사용은 import로), `output/`·`data/` 쓰기(작업 폴더의 `video/annotate_tmp/` 포함 — 테스트는 tmp_path, 실데이터 확인은 `--out-dir` 스크래치), 새 의존성, LLM 호출.

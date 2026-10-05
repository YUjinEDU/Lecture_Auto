# 선행연구·오픈소스 지형 조사: 강의 녹음 + 슬라이드 -> 슬라이드별 노트 / 코스 위키 / 내레이션 영상 (2026-10-05)

도구: Exa(web_search_exa / web_fetch_exa) 정상 동작. GitHub 스타/라이선스/최근 푸시는 `gh api`로 직접 확인(2026-10-05 기준).
표기: [검증] = 1차 출처(arXiv/ICCV/WACV 페이지, 공식 README, 공식 제품 페이지, gh api)에서 확인. [2차] = 블로그/리뷰 등 2차 출처. [미검증] = 확인 못함.

## 1. 요약 (10줄)

1. 슬라이드-음성 정렬 연구는 존재하나 영어/유튜브 위주. 한국어 + 슬라이드 + 전사 정렬을 다룬 공개 벤치마크는 못 찾음 [미검증: 부재 단정은 아님].
2. 영어 정렬 벤치마크로 쓸 만한 것은 CMU LPM(ICCV 2023; 334영상/187시간/9,031슬라이드, 슬라이드 전환 구간 수작업 주석 `segments.txt`). 다만 영상 본체는 YouTube ID+스크립트만 배포, GitHub 라이선스 NOASSERTION.
3. AVLectures(WACV 2023; 86강좌/2,350강의/2,200시간, MIT OCW, 코드 CC0)는 주제 분할용(15강좌 350강의에 경계 정답)이라 "슬라이드 단위 정렬" 정답은 아님.
4. 요약/노트 생성 연구는 VT-SSum(125K 쌍, 슬라이드 텍스트를 약지도 정답으로 사용, 추출 요약) 등 구형이 대부분. LLM 시대에는 "슬라이드+전사로 노트" 논문이 흩어져 있고, 충실성(faithfulness)·교수 말투 보존을 정면으로 평가한 표준은 없음.
5. 제품: NotebookLM(2026-07부터 "Gemini Notebook"으로 개명 [검증: notebooklm.google/plus])은 오디오 파일/PDF/슬라이드를 소스로 받아 스터디가이드·오디오/비디오 오버뷰·마인드맵·퀴즈·플래시카드를 만든다. 그러나 "슬라이드 한 장당 교수가 실제로 한 말" 정렬은 제공하지 않음(제품 설명에 해당 기능 언급 없음 [2차]).
6. 한국어 제품(클로바노트, 다글로, 릴리스, 에이닷노트)은 전사+요약+화자분리 중심. 슬라이드 정렬/코스 위키는 없음 [2차, 공식 기능표 미확인].
7. 오픈소스는 최근 3~5개월 사이 급증했으나 전부 소규모(대부분 스타 0~12). 가장 근접: drpwchen/lecture-to-notes(106 stars, MIT, 2026-09 활동). 한국어 우선/TTS 영상/위키 링크를 한 번에 하는 것은 없음.
8. ASR은 Whisper large-v3-turbo 계열이 비용/속도 최선. 한국어 파인튜닝(batisay-ko 등)은 실사용 장문에서 CER 15~19%대(자동 전사 기준 상대치) [검증: HF 카드]. 전문용어는 슬라이드 텍스트로 initial_prompt/후교정 필요.
9. 논문: "ASR 용어 오류를 슬라이드 OCR/텍스트로 교정하면서 교수 발화 근거를 문장 단위로 인용하는 노트" + 한국어 소규모 평가셋이 가장 현실적인 한 가지 주장. KCC 수준이면 가능, 상위 학회는 어려움.
10. 리스크 1순위는 법/동의: 강의 녹음 허락, 교수 음성 클로닝(TTS), 슬라이드 저작권. OSS 배포물에는 강의 자료·클론 음성을 절대 포함하지 말 것.

## 2. 정렬 연구·데이터셋

| 데이터셋/연구 | 규모 | 언어 | 라벨 | 라이선스/배포 | 영어 벤치마크 적합성 |
|---|---|---|---|---|---|
| LPM (Lee et al., ICCV 2023; arXiv 2208.08080) [검증] | 334영상, 187시간, 9,031슬라이드, 8,598 figure, 1.6M 단어, 강연자 10명 | 영어 | 슬라이드 전환 구간(수작업 `segments.txt`), figure bbox, Google ASR 전사(WER 약 17% 수기검증), OCR(Tesseract, WER 약 38%), 마우스 궤적 | YouTube ID+스크립트만 배포(원본 영상 비공개). GitHub 라이선스 NOASSERTION (56 stars, 마지막 푸시 2023-10) | 가장 적합. 슬라이드 단위 구간+전사가 있어 "슬라이드별 발화 정렬" 평가 가능. 단 영상 재다운로드 필요, 강연자 10명으로 작음 |
| AVLectures (Singh et al., WACV 2023; arXiv 2210.16644) [검증] | 86강좌, 2,350강의, 2,200시간, 평균 55분, 코퍼스 7.1M 단어 | 영어(MIT OCW, STEM) | 15강좌(350강의)만 주제 경계 정답(목차 스크래핑 또는 사전 분할 영상 재조립). 나머지는 자막/OCR/슬라이드(선택) | 저장소 CC0-1.0 [검증: gh]. 콘텐츠는 MIT OCW 자체 라이선스(별도 확인 필요) [미검증] | 슬라이드-전환 정답이 아님(주제 분할). 칠판 강의 혼재. 정렬 평가에는 간접적 |
| VT-SSum (arXiv 2106.05606) [검증] | 9,616영상, 125K 전사-요약 쌍 | 영어 | 슬라이드 페이지별 전사 구간(VideoLectures.NET 타임라인) + 슬라이드 텍스트를 약지도 "정답 요약"(ROUGE 최대 문장 추출) | GitHub 라이선스 없음(none), 23 stars | 정렬 정답은 플랫폼 타임라인이라 정확하나 "요약 정답"은 추출식 약지도라 노트 품질 평가용으로는 부적합 |
| LecSumm (2025) [2차: exa 요약] | 학생 200명이 10개 ML 토픽 강의노트를 요약, 2,000 요약 | 영어 | 사람 요약(길이/깊이/톤/형식 선호) | 미확인 | "사람 선호 포착" 연구. 입력이 노트라 전사 구어 재구성과는 다름 |
| AI Hub 한국어 대학 강의 데이터 [검증: aihub 페이지] | 4,800시간 음성, 라벨 2.1M 문장 | 한국어 | 전사 + 전문용어(entity) 라벨, 강의 요약 필드(선택) | AI Hub 이용약관(신청/승인 필요) [미검증: 상세 조건] | ASR/전문용어 평가용으로 유용. 슬라이드 정렬 정답은 없음 |
| 기타 언급: LectureBank, LectureVideoDB, VLEngagement [2차: LPM 논문 표1] | - | - | - | - | 정렬용 아님 |

핵심 관찰
- LPM 논문 자체가 결론에서 "슬라이드-음성의 약한 교차모달 정렬(한 figure가 발화 일부와만 대응)", "전문 용어", "장거리 시퀀스"를 현 모델의 약점으로 보고함 [검증]. 우리 문제와 정확히 겹침.
- 한국어 강의 + 슬라이드 + 슬라이드 전환 타임스탬프를 함께 가진 공개 데이터는 찾지 못함 [미검증]. 따라서 한국어 평가셋은 직접 구축(우리 강의 3~5개 수작업 전환점 라벨)이 필요.
- 정렬 방법 계열(문헌 및 OSS 공통): (a) 영상 프레임 슬라이드 전환 검출(pHash/SSIM/PySceneDetect), (b) 슬라이드 텍스트와 전사 임베딩 유사도 + 시간 단조성(DTW류), (c) 녹음만 있을 때는 (b)만 가능. 우리 경우 오디오 단독이 흔하므로 (b)가 핵심 난제이자 차별점 후보.

## 3. 강의 요약/재구성 연구·평가법

| 연구 | 내용 | 평가 방식 | 시사점 |
|---|---|---|---|
| VT-SSum | 구어 전사 요약, 슬라이드=약지도 | 추출 요약 Top-k F1 | 구어체 도메인 불일치(뉴스로 학습한 모델이 구어 감탄사/조사에서 불리) 확인 [검증] |
| OpenULTD/UniSum (Politecnico di Torino 석사논문) [2차] | MIT/Yale 1,583 전사-요약 쌍, 필기 여부 멀티모달 변형 | ROUGE, BERTScore | 구형(BART). 참고만 |
| AIDEN (RANLP 2025) [검증: ACL 프로시딩 본문] | 슬라이드 텍스트(앞뒤 슬라이드 포함)+RAG로 LLM이 스피커 노트 생성, 슬라이드 검색 | BERTScore(GPT-4 0.84, +RAG 0.85), Recall@k | 발화가 아니라 슬라이드에서 "가상 스피커 노트"를 만드는 방향. 우리의 "실제 발화 기반"과 반대 방향이라 대비 포인트 |
| Dinh et al. 2026 NSLP "From Slides to Chatbots" [검증] | 슬라이드 vs 전사를 RAG 소스로 비교 | SciEx 시험 문제 LLM 채점 | 흥미로운 결과: 원 전사/LLM 정제 전사는 슬라이드 대비 RAG 성능 향상이 없거나 오히려 저하. 슬라이드 이미지 입력이 텍스트보다 우수. 즉 "구어 전사를 그대로 쓰면 도움 안 됨" -> 재구성(구조화)의 필요성 근거 |
| 교실 AI 신뢰성 서베이(IJISAE, 100편 스코핑) [2차, 저널 신뢰도 낮음] | 정렬을 핵심으로 한 증거 연결 IR, 주장 단위 충실성, 인용 정밀도, 커버리지, abstention 제안 | WES(증거 품질 가중 지지 점수) 등 제안 | 평가 프레임 아이디어 참고용. 인용 시 저널 신뢰도 주의 |
| Asthana et al. NeurIPS-GAIED 2023 [검증: 포스터] | GPT로 강의 "moment" 분할, 개념, 문항 생성 | 2인 평가자 루브릭(관련성 92%, 오답지 그럴듯함 65% 등) | 전사만으로는 "슬라이드 참조 발화"를 못 잡는다고 스스로 한계 명시 -> 슬라이드 결합 동기 |
| 슬라이드 기반 문항 생성(arXiv 2407.20578) [검증] | 46명 학생이 246문항을 5축 평가(명확성/관련성/난이도/슬라이드 관련/QA 정합) | 학생 리커트 | 학생 평가 프로토콜 템플릿 |
| Study texts from slides (WESAAC 2026) [2차: 초록] | 슬라이드 -> 자기완결 학습문서, 담화 재구성 | 4개 MLLM 비교 | 방향 유사, 발화 미사용 |

평가 축 정리(우리 논문/릴리스에 쓸 수 있는 것)
- 충실성: 노트의 각 주장 -> 근거 전사 구간/슬라이드 요소 연결률(인용 정밀도). 자동 검사기로는 SummaC/MiniCheck/NLI류가 후보 [서베이 인용, 개별 미검증]. 한국어 NLI 성능은 별도 검증 필요.
- 커버리지: 슬라이드 요소(OCR 블록/figure) 중 노트에 반영된 비율. SlideNote(OSS)가 element_id 기반 coverage 체크를 이미 구현 [검증: README].
- 환각: 발화에 없는 내용 추가율. 교수 발화에 없는 "교과서식 보충"을 금지/분리 표기하는 설계가 차별점.
- 교수 말투/예시 보존: 자동 지표 정립 안 됨. 대리 지표(발화 인용 비율, 교수 고유 예시 포함률)+소규모 사람 평가.
- 이해도: 퀴즈 기반(노트만 읽고 문항 풀이, 강의 원본 시청군과 비교)은 연구 설계 상 가장 강력하나 학생 모집 비용이 큼. 소규모(n=10~20) 파일럿은 KCC 수준에서 가능.

## 4. 제품 비교표

| 제품 | 입력 | 출력 | 한국어 | 슬라이드 정렬 | 교수 말투 | 코스 위키/주차 연결 | 비고 |
|---|---|---|---|---|---|---|---|
| Google NotebookLM (= Gemini Notebook, 2026-07 개명) [검증: notebooklm.google/plus; 세부 기능은 2차 리뷰 2026-04~09] | PDF, 슬라이드(Google Slides), 오디오 파일(MP3/WAV/M4A), YouTube, 웹, docx 등. 노트북당 소스 50(무료) | 스터디가이드/FAQ/브리핑, 오디오 오버뷰(2인 팟캐스트), 비디오 오버뷰(슬라이드 내레이션형 + 2026-03 시네마틱), 마인드맵, 슬라이드 덱(PPTX/PDF 내보내기), 인포그래픽, 퀴즈/플래시카드, 인터랙티브 러닝 오버뷰(2026-09 롤아웃 중) | 지원(품질 세부 미검증) | 없음(소스 단위 인용만, 슬라이드 한 장-발화 구간 매핑 UI 언급 없음) | 없음(새 2인 호스트 목소리/문체) | 노트북 내 여러 소스 교차 질의는 가능, 위키 페이지 생성은 아님 | 개명 시점 이후 URL/명칭 변동. 무료 한도: 오디오/비디오 오버뷰 하루 3회 [2차] |
| 네이버 클로바노트 [2차: 블로그 다수] | 녹음/업로드 | 전사, 화자분리, AI 요약(주제/소제목/할 일), 구간 재생 | 매우 강함(국내 표준) | 없음 | 없음 | 없음 | 슬라이드 입력 개념 없음. 공식 기능표/현행 요금 미확인 |
| 다글로 (Daglo) [2차] | 녹음, PDF 등 | 전사, 요약, 퀴즈 생성 | 강함 | 없음 | 없음 | 없음 | PDF+녹음을 같이 넣으면 요약 [2차 블로그 주장, 미검증] |
| 릴리스 (Lilys AI) [2차] | YouTube/영상/PDF/음성 | 타임스탬프 요약, 블로그/보고서 변환 | 지원 | 없음 | 없음 | 없음 | 유튜브 요약 강점, 강의 슬라이드 정렬 목적 아님 |
| 에이닷노트, 티로 [2차: velopers.kr 비교] | 녹음 | 전사+요약 | 강함 | 없음 | 없음 | 없음 | 에이닷노트/클로바노트가 강의 인식 강하다는 사용 후기 |
| Otter, Notta [미검증] | 녹음/회의 | 전사/요약 | 한국어 품질 미검증 | 추정 없음 | 없음 | 없음 | 이번 조사에서 1차 출처 확인 못함. 비교표에서 제외 가능 |

제품들이 공통으로 안 하는 것(확인 가능한 범위)
- 슬라이드 한 장 단위로 "교수가 이 장에서 실제로 한 말"을 근거 타임스탬프와 함께 정렬 제시 [미검증이나 제품 설명에서 해당 기능 언급 없음].
- 교수 본인의 어투/예시를 보존한 재구성(제품은 중립 요약 또는 새 호스트 목소리).
- 주차 간 개념 페이지 링크(코스 위키). NotebookLM은 노트북 내 질의로 대체. 위키형 영속 산출물은 아님.
- 사용자 소유 로컬/오프라인 처리와 Obsidian 호환 파일 산출.
- 주의: NotebookLM은 변화가 빠르다. "슬라이드 정렬을 안 한다"는 주장은 논문/README에 쓰기 전에 직접 재현 테스트(슬라이드 PDF + 녹음 업로드 후 질의)로 확인하고 날짜를 박을 것.

## 5. 오픈소스 비교표 (gh api 2026-10-05 확인)

| 저장소 | 스타 | 라이선스 | 마지막 푸시 | 하는 일 | 우리 대비 |
|---|---|---|---|---|---|
| drpwchen/lecture-to-notes | 106 | MIT | 2026-09-01 | 영상/오디오/PDF/사진 혼합 폴더 -> faster-whisper, 슬라이드 추출/OCR(Surya)/로컬 VLM, 캡처시간 기반 정렬(+전사 교차상관 검증), 동기화 HTML 뷰어(영상-전사-요약 양방향 하이라이트), Obsidian vault 출력, Claude Code 스킬. Stage F(합성)는 프롬프트 스펙뿐 스크립트 없음 | 가장 근접. 중국어/영어 위주(--lang zh/en/bilingual), 한국어/TTS 영상/개념 위키 없음. 슬라이드 주어진 PDF 모드 지원(build_slides_from_pdf) |
| Cat-blizzard/SlideNote | 19 | AGPL-3.0 | 2026-09-28 | PPT/PDF -> 충실성/커버리지 가드 있는 노트, source_map, coverage.json | 슬라이드만(발화 미사용). 커버리지/충실성 가드 설계는 참고할 만함 |
| Stefan0219/video-to-notes (구 llm-course-wiki) | 35 | GPL-3.0 | 2026-07-08 | 전사+슬라이드+기존 요약 -> Obsidian 코스 위키(lecture note, concepts/*.md, pending_links) | 구조가 우리 (b)와 가장 비슷. Codex 스킬 형태, 슬라이드-발화 정렬/TTS 없음 |
| tuan3w/obsidian-vault-agent | 39 | MIT | 2026-03-30 | Claude Code 플러그인: /course /lecture /youtube, mlx-whisper, 슬라이드 프레임, Feynman식 노트 | 영어 개인 vault 중심, 정렬은 프레임 시간 기반 |
| GD4AI/obsidian-llm-wiki | 680 | Apache-2.0 | 2026-10-04 | Karpathy LLM Wiki 아이디어의 Obsidian 플러그인(엔티티/개념 페이지, PPR 그래프 검색, 11개 언어 출력) | 강의 특화 아님이나 위키 링크 UX 레퍼런스로 인기 최고. 소스 페이지에 verbatim 인용 |
| hqhq1025/ai-course-notes | 174 | NOASSERTION | 2026-08-18 | CS336류 강의를 슬라이드+자막으로 장문 노트(교수 목소리 장부 "teacher-voice ledger", 커버리지 매트릭스, QA 게이트) | 교수 말투 보존 발상이 우리 (a)와 유사. LaTeX/PDF 중심, 자막 의존 |
| sugarfolds/lecture-notes-pipeline | 0 | MIT | 2026-05-14 | Canvas 자료/녹화 다운로드 + mlx-whisper 중국어 + PPT 정렬 + 노트 규칙 스킬 | 소규모, 중국어 |
| shyenx/slidoc | 2 | MIT | 2026-05-15 | ffmpeg + whisper.cpp, 프레임-SRT 시간창 조인, 품질 게이트(고유 라인 비율 80%) | 소규모, 아이디어(환각 반복 게이트) 참고 |
| skoropysAlex/lecture-notes | 2 | MIT | 2026-04-21 | faster-whisper + PySceneDetect -> Google Docs | 소규모 |
| RexTSLO/video-slide-notes | 3 | MIT | 2026-06-07 | 슬라이드 변화 검출 + Whisper -> 슬라이드/전사 병렬 PDF, NotebookLM 투입용 | 소규모 |
| travisseng/svla-toolkit | 12 | AGPL-3.0 | 2025-11-04 | 장면 검출, 이중 OCR, Whisper, SBERT 전사-OCR 정렬, Gemini 챕터 | 연구형 툴킷, AGPL |
| Floucs/notebooklm-obsidian-pipeline | 4 | none | 2026-05-13 | PDF+전사를 NotebookLM에 올려 4개 질문 -> Obsidian 노트 | NotebookLM 의존(비공식 CLI) |
| dataflowr/transcripts | 0 | Apache-2.0 | 2026-03-07 | 35개 강의 전사 -> 318개 Obsidian 개념 노트(교수 인용 + 타임스탬프) | "교수 발화 인용+타임스탬프" 개념 페이지의 좋은 형태 예시 |
| Dod-o/VT-SSum, dondongwon/LPMDataset, Darshansingh11/AVLectures | 23 / 56 / 14 | none / NOASSERTION / CC0 | 2021 / 2023 / 2025 | 데이터셋 저장소 | 5장 참조 |

공백(gap) 평가
- 위 저장소 중 아래 4가지를 동시에 만족하는 것은 확인하지 못함: (1) 슬라이드 PDF/PPTX 기준 슬라이드별 발화 정렬(오디오 단독 포함), (2) 한국어 우선 처리(전문용어 교정), (3) 주차 간 개념 페이지 링크, (4) 같은 근거로 내레이션 슬라이드 영상 생성. 개별 요소는 각각 존재한다. 따라서 "빈 공간"은 개별 기능이 아니라 통합과 한국어, 그리고 근거 인용 수준에 있다. 경쟁 저장소가 최근 5개월에 폭증했으므로 선점 이점은 짧다고 가정할 것.
- 눈에 띄는 OSS 릴리스 요건(제안): (a) 3분짜리 데모 영상/GIF + 샘플 산출물(저작권 free 강의, 예: CC 라이선스 영어/한국어 강의), (b) `pip install` 후 한 줄 CLI(`lecture-wiki run slides.pdf audio.m4a`), (c) 한국어 용어 교정 사이클(슬라이드 텍스트 -> initial_prompt + 후보정 플래그, 원문 전사는 변조하지 않고 플래그만; lecture-to-notes의 원칙 참고), (d) Obsidian 호환 vault(YAML frontmatter, `[[wikilink]]`, 타임스탬프 딥링크), (e) 로컬 ASR 기본 + 클라우드 선택, (f) 모든 문장에 근거 전사 구간 ID(감사 가능), (g) 평가 스크립트와 작은 한국어 골드셋 동봉.

## 6. ASR 선택지 (한국어 90분 강의 기준)

| 후보 | 한국어 근거 | 타임스탬프 | 비용/속도 | 비고 |
|---|---|---|---|---|
| Whisper large-v3-turbo (faster-whisper) | 단일화자 12강의 10.2시간 영어 코퍼스에서 turbo가 WER 8.9%로 large-v3(14.2%, 한 강의에서 디코더 락업 29.7%)보다 우수, RTFx 약 65x [검증: asr-bench README, 영어]. 한국어 직접 수치는 아래 | 세그먼트 + 단어(WhisperX 정렬) | 로컬 GPU 90분 약 1~2분(5090 기준 RTFx 65 외삽 [추정]). Groq 호스팅 약 $0.0007/분 [2차: opentranscription.io] | 기본 후보. 긴 오디오 환각 반복 방지(VAD, 반복 게이트) 필수 |
| 한국어 파인튜닝 Whisper (batisay-ko-turbo/large 등, HF 커뮤니티) | KsponSpeech clean 6.99~6.83%, 회의 7~9%, 실사용 장문 통화 CER 14.9~19.4%(자동 전사 기준 상대치) [검증: HF 모델 카드, 자기보고] | 세그먼트 | 로컬 | turbo는 "Community v2(상업 협의)", base는 Apache-2.0 [검증: 카드]. 라이선스 확인 필수. 강의 도메인 독립 검증 없음 |
| OpenAI gpt-4o-transcribe / mini | 벤치 AA-WER 4.0% (GPT Transcribe 3.3%), 가격 $0.006/분(4o) [2차: artificialanalysis, opentranscription] | 단어 타임스탬프 제한(모델별 상이) [미검증] | 90분 약 $0.54(4o), 약 $0.27(mini $0.003/분) | 정렬용 정밀 타임스탬프는 Whisper 계열이 안전. 25MB 청크 제한 등 운영 이슈 |
| WhisperX | 단어 정렬(wav2vec2 forced alignment) + pyannote 화자분리 | 단어 수준 | 로컬 | 한국어 정렬 모델 가용 여부는 [미검증]. 정렬 정밀도는 슬라이드 전환 매칭에 유용 |
| Clova Speech/Note | 국내 강의 성능 호평 [2차] | 있음 | 유료 API 가격 [미검증] | 로컬/오프라인 요건과 충돌, 재현성 낮음 |
| AI Hub 대학 강의 4,800h | 학습/평가용 데이터. 공개 베이스라인 CER 10% 이하(Conformer) [검증: 데이터 페이지] | - | - | ASR 평가셋 후보 |

결정 가이드
- 화자분리: 강의는 대부분 교수 1인. 질의응답 구간만 문제. 우선순위 낮음(옵션). 필요하면 WhisperX/pyannote. 동의 없는 학생 음성이 섞이므로 질문 구간 익명 처리 옵션이 필요.
- 슬라이드 텍스트로 용어 교정: initial_prompt(최대 약 224 토큰 제한) 또는 후처리 사전. 교정은 "플래그" 우선, 자동 치환은 위험(lecture-to-notes가 자동 교정 2종을 만들었다가 측정 후 폐기한 사례 [검증: README]).
- 한국어 WER은 띄어쓰기 변동이 커서 CER 병행 필수.
- 반복 환각(긴 오디오) 게이트: 고유 라인 비율, VAD(slidoc/asr-bench 사례).

## 7. 결론

### 7-a. 논문 가능성 (방어 가능한 novelty)
- 현실적 단일 주장(권장): "슬라이드-앵커드, 근거 인용형 구어 강의 재구성: ASR 오류가 있는 오디오 단독 입력에서, 주어진 슬라이드 텍스트/구조를 앵커로 (1) 발화를 슬라이드 단위로 정렬하고 (2) 전문용어를 슬라이드 근거로 교정 플래그하며 (3) 교수 발화 인용 단위로 근거를 단 재구성 노트를 생성했을 때, 슬라이드 전용 생성/무정렬 전사 요약 대비 충실성(인용 정밀도)과 커버리지가 향상된다." 한국어 강의 소규모 골드셋(전환점 수작업) + LPM(영어)에서 정렬 정확도 보고.
- 근거: LPM 논문이 약한 정렬과 전문용어를 미해결 난제로 명시 [검증]. Dinh 2026은 원 전사가 슬라이드 대비 이득이 없다고 보고 [검증] -> 재구성의 필요성. AIDEN은 반대로 슬라이드에서 가상 노트 생성 [검증] -> "실제 발화 기반" 차별화.
- 약점: 개별 구성요소(Whisper, 전환 검출, LLM 요약)는 새롭지 않음. OSS 다수가 이미 유사 파이프라인 구현. novelty는 평가 설계(한국어 + 오디오 단독 정렬 + 인용 충실성 지표)와 데이터에 있음. 상위 학회 가능성 낮음, KCC/워크숍 수준 현실적. 교수 말투 보존은 자동 지표가 없어 사람 평가 소규모로만 주장 가능.
- 비용 대비: 골드셋 라벨링(강의 3~5개, 슬라이드 전환점) + 비교 3 조건 + 학생 퀴즈 파일럿(선택)이면 수 주 분량. "싸게" 하려면 퀴즈 연구는 제외하고 정렬+충실성만 보고.

### 7-b. OSS 포지셔닝 문장 (초안)
"이미 가진 강의 슬라이드(PDF/PPTX)와 수업 녹음만 넣으면, 교수가 각 슬라이드에서 실제로 한 말을 근거 타임스탬프와 함께 정렬하고, 그 발화를 교수의 예시와 어투를 살려 읽기 좋은 설명으로 재구성하며, 주차 간 개념 페이지가 연결된 Obsidian 호환 코스 위키를 로컬에서 생성한다(선택: 같은 근거로 내레이션 슬라이드 영상). 새 슬라이드를 만들거나 교수 대신 말하지 않고, 모든 문장은 원 발화 구간으로 역추적된다. 한국어 우선, 영어 지원."

### 7-c. 상위 5대 리스크
1. 법/동의(녹음·음성 클로닝): 수업 녹음은 교수/학교 정책과 동의가 필요하고, 교수 음성 클론 TTS는 본인 서면 동의 + 용도 제한 필요(내레이션 영상은 합성 음성 고지). 데모/샘플에 실제 교수 음성/강의를 넣지 말 것. 학생 질문 음성은 개인정보. 국내 개인정보보호법/학교 내규 해석은 [미검증, 별도 확인 필요].
2. 슬라이드 저작권: 교수 자작 슬라이드는 허락 후 사용 가능하나, 슬라이드 내 외부 도판/교재 도표는 제3자 저작권. 생성 노트/영상에 슬라이드 이미지를 포함하는 배포는 제한. OSS에는 코드와 CC 라이선스 샘플만 포함. 데이터셋(LPM/AVLectures) 재배포 조건도 확인(원 콘텐츠 라이선스 별도).
3. 한국어 전문용어 ASR 품질: 영어 혼용(코드스위칭), 약어, 수식 낭독에서 오류 큼. 한국어 장문 CER이 15~19%대 사례 [검증: HF, 자동 전사 기준]. 잘못된 전사에서 파생된 노트가 "충실한 척" 오답을 만들 위험. 대응: 플래그 우선, 근거 인용 의무, 저신뢰 구간 abstain.
4. 충실성/환각과 교수 말투 보존 간의 긴장: 재구성(LLM)이 발화에 없는 설명을 보충하면 "교수가 한 말"이 아니게 됨. 발화 근거 문장과 모델 보충 문장을 시각적으로 구분하고 기본값은 보충 최소화. 말투 모사는 오히려 교수 사칭 오해 소지(교수 동의, 라벨 표기).
5. 경쟁 및 변동성: 최근 5개월에 유사 OSS 폭증(lecture-to-notes 106 stars 등) + NotebookLM이 빠르게 기능 추가(2026-09 인터랙티브 러닝 오버뷰). 차별화가 "통합"뿐이면 단기 모방 가능. 대응: 한국어 골드셋/평가 스크립트/재현성 같은 해자 + 논문. 추가로 의존 모델 라이선스(batisay-ko-turbo 상업 협의 등) 및 OpenAI 의존(현 구현은 OpenAI 기반이므로 로컬/오프라인 요건 충돌).

### 우리 저장소와의 관계 (참고, 코드 미변경)
- CLAUDE.md 상 기존 파이프라인은 "슬라이드 -> VLM -> LLM 스크립트 -> TTS -> 영상" 방향이고, 계획 도구는 "슬라이드 + 실제 발화 -> 정렬/재구성 -> 위키"로 방향이 반대. TTS/자막/하이라이트 동기 영상(c)은 기존 자산 재사용 가능. 기존 PRIOR_ART_20261005.md와의 중복/차이는 이 문서에서 검토하지 않음.

## 8. 출처

1차(검증)
- LPM: https://openaccess.thecvf.com/content/ICCV2023/html/Lee_Lecture_Presentations_Multimodal_Dataset_Towards_Understanding_Multimodality_in_Educational_Videos_ICCV_2023_paper.html , arXiv https://export.arxiv.org/pdf/2208.08080v1.pdf , https://github.com/dondongwon/LPMDataset
- AVLectures: https://openaccess.thecvf.com/content/WACV2023/html/S._Unsupervised_Audio-Visual_Lecture_Segmentation_WACV_2023_paper.html , arXiv 2210.16644 (https://ar5iv.labs.arxiv.org/html/2210.16644), https://github.com/Darshansingh11/AVLectures
- VT-SSum: https://arxiv.org/abs/2106.05606 , https://github.com/Dod-o/VT-SSum
- AIDEN (RANLP 2025): https://acl-bg.org/proceedings/2025/RANLP%202025/pdf/2025.ranlp-1.150.pdf
- From Slides to Chatbots (NSLP 2026): https://aclanthology.org/2026.nslp-1.16.pdf
- 슬라이드 기반 문항 생성: https://arxiv.org/pdf/2407.20578
- Asthana et al., GAIED NeurIPS 2023 포스터: https://gaied.org/neurips2023/files/31/31_poster.pdf
- NotebookLM/Gemini Notebook 공식 페이지: https://notebooklm.google/plus
- AI Hub 한국어 대학 강의 데이터: https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=115&dataSetSn=71627&topMenu=100
- OSS README: https://github.com/drpwchen/lecture-to-notes , https://github.com/Cat-blizzard/SlideNote , https://github.com/Stefan0219/llm-course-wiki (현재 video-to-notes), https://github.com/tuan3w/obsidian-vault-agent , https://github.com/green-dalii/obsidian-llm-wiki , https://github.com/hqhq1025/ai-course-notes , https://github.com/dataflowr/transcripts , https://github.com/shyenx/slidoc , https://github.com/sugarfolds/lecture-notes-pipeline , https://github.com/skoropysAlex/lecture-notes , https://github.com/RexTSLO/video-slide-notes , https://github.com/travisseng/svla-toolkit , https://github.com/Floucs/notebooklm-obsidian-pipeline
- ASR 벤치: https://github.com/Ryfter/asr-bench/blob/main/README.md , HF 카드 https://huggingface.co/batiai/batisay-ko-turbo , https://huggingface.co/batiai/batisay-ko-large-GGUF
- 스타/라이선스/푸시 일자: `gh api repos/<repo>` 직접 조회(2026-10-05)

2차/미검증 (인용 전 재확인)
- NotebookLM 기능 세부/한도: https://aiunpacking.com/review/notebooklm/ , https://teachaitools.blog/blog/notebooklm-complete-guide-2026 , https://www.xda-developers.com/tested-notebooklms-new-interactive-learning-overviews-fixed-biggest-problem/ , https://www.xda-developers.com/notebooklm-cinematic-video-overviews-feature/
- 한국 제품 비교 블로그: https://markppark.tistory.com/131 , https://velopers.kr/post/5370 , https://kateko.kr/google-notebooklm-vs-lilys-ai-comparison-guide/ , https://codecampai.com/clovanote-summarization-use-cases/
- ASR 벤더 비교/가격: https://opentranscription.io/en/ranker , https://artificialanalysis.ai/speech-to-text/models/gpt-4o-audio
- 교실 AI 서베이(저널 신뢰도 낮음): https://ijisae.org/index.php/IJISAE/article/download/8165/7164/13740
- LecSumm: https://exa.ai/library/publication/p4m62tp9gr2
- Otter/Notta, Clova/Daglo 공식 기능·요금: 이번 조사에서 1차 출처 미확인
- LPM/AVLectures 원 콘텐츠 재배포 라이선스, 개인정보보호법 적용, 한국어 WhisperX 정렬 모델 가용성: 미확인

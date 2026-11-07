# 시놀로지 NAS에 올리기 (GPU 없음, API 음성 전용)

연구실 홈페이지 서브도메인(예: `lecture.연구실도메인`)으로 여는 방법. NAS는 x86 + Container Manager(Docker)가 되면 된다.

## 이 모드에서 되는 것 / 안 되는 것

| 된다 | 안 된다 |
|---|---|
| 슬라이드 업로드, 대본 생성(BAZE LLM), Gemini 음성 30종 + 말투 지시, 영상 조립, 자막·하이라이트, 학생 공유 페이지, 용어·퀴즈, 계정·한도 | Raon 목소리 복제, 음성 파일 업로드 (GPU 필요) |

`LECTURE_WEB_RAON=off`(이미지 기본값)이면 새 강의는 Gemini가 기본이고, Raon 선택지와 "내 음성" 메뉴가 사라진다.
Raon으로 설정된 옛 강의는 보기·내려받기는 되고, 제작하려면 음성 설정에서 Gemini를 고르라는 안내가 나온다.

## 1. 이미지 만들기 (둘 중 하나)

**A. GPU 서버에서 빌드해서 옮기기 (NAS가 느려도 빠름)**

```bash
cd Lecture_Auto
docker build -t lecture-auto:latest .
docker save lecture-auto:latest | gzip > lecture-auto.tar.gz     # 약 500MB
```

`lecture-auto.tar.gz`를 NAS에 올린 뒤 Container Manager → 이미지 → 추가 → 파일에서 추가.

**B. NAS에서 직접 빌드**: 저장소를 NAS 폴더에 두고 Container Manager → 프로젝트 → 생성 → 그 폴더의 `docker-compose.nas.yml`을
고르고, `image:` 줄 아래에 `build: .`을 추가한다. (LibreOffice 설치 때문에 빌드에 수십 분 걸릴 수 있다.)

## 2. 실행

1. File Station에서 `/volume1/docker/lecture-auto` 폴더를 만든다. 강의·계정 DB·영상이 전부 여기에 쌓인다(백업 대상).
2. Container Manager → 프로젝트 → 생성 → 소스: `docker-compose.nas.yml`. 환경변수 `LECTURE_WEB_PASSWORD`에 첫 관리자 비밀번호를 넣는다.
3. 처음 켜면 설정 파일과 기본 참조 음성이 볼륨에 채워지고, 관리자 계정 `admin@local`이 만들어진다.

## 3. 서브도메인 + HTTPS (DSM 기본 기능)

1. 연구실 도메인 DNS에 `lecture` A 레코드(NAS 공인 IP) 또는 CNAME(시놀로지 DDNS 주소)을 만든다.
2. 제어판 → 보안 → 인증서 → 추가 → Let's Encrypt로 `lecture.연구실도메인` 인증서를 받는다.
3. 제어판 → 로그인 포털 → 고급 → 역방향 프록시 → 생성
   - 소스: HTTPS, 호스트 `lecture.연구실도메인`, 포트 443
   - 대상: HTTP, `localhost`, 포트 8800
   - 사용자 지정 머리글: `X-Forwarded-Proto` = `https` (로그인 쿠키에 Secure가 붙는다)
4. 공유기는 443만 NAS로 넘긴다. 8800은 넘기지 않는다.
5. 큰 PPTX(최대 300MB)를 올려 보고 413 오류가 나면 역방향 프록시의 업로드 크기 제한을 늘린다(DSM 버전마다 위치가 다름 — 직접 확인 필요).

연구실 홈페이지(Next.js)에서는 이 주소로 가는 링크 버튼만 두면 된다. 홈페이지 서버를 거쳐 프록시하면 업로드 크기·시간 제한에 걸린다.

## 4. 운영

- 업데이트: 새 이미지를 받아 같은 이름으로 바꾸고 프로젝트를 다시 시작. 데이터는 볼륨에 남는다.
- 백업: Hyper Backup으로 `/volume1/docker/lecture-auto`를 매일 백업.
- 대본 생성·Gemini 음성 비용은 각 사용자가 설정에 등록한 BAZE 키로 나간다. 서버 키는 없어도 된다.
- 작업은 한 번에 하나씩 돈다. 실측(GPU 서버 CPU, 39분 강의): 영상 조립 약 35초. NAS CPU는 이보다 몇 배 느릴 수 있다.

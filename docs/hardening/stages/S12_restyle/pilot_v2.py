"""Pilot: content-preserving spoken-register rewrite of existing slide scripts. Writes only to scratchpad."""
import json,re,sys,glob
from pathlib import Path
from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.lecture_plan import strip_markdown_json_fence
SP=Path(sys.argv[1]); lec=glob.glob(f"data/work_batch/{sys.argv[2]}_*")[0]; nums=[int(x) for x in sys.argv[3].split(",")]
raw=open("data/transcripts/professor_full_lecture_32min.txt").read()
lines=[re.sub(r"\[\d+s - \d+s\]\s*","",l) for l in raw.splitlines() if l.strip()]
clean=lambda s: re.sub(r"(^|\s)(어|음|그)(?=\s)","",s)
sample="\n".join(clean(l) for l in lines[38:47])
LAT=re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
scripts={n:json.load(open(f"{lec}/scripts/script_{n:03d}.json"))["script"] for n in nums}
sysmsg=("당신은 김영국 교수님 본인입니다. 이미 내용이 확정된 강의 대본을 교수님이 실제 강의실에서 말하는 말투로만 바꿔 씁니다. "
"내용·순서·사실·예시는 그대로 두고 말투만 바꿉니다.")
counts="\n".join(f"- 슬라이드 {n}: '그래서'·'이제'·'그 다음에'·'그러면'으로 문장 잇기 합쳐 최소 {max(2,round(len(s)*0.009))}회, '자,' 화제 전환 {1 if len(s)>400 else 0}회 이상, '합니다/습니다' 종결 최대 {max(1,round(len(s)*0.003))}회" for n,s in scripts.items())
user=f"""[교수님 실제 강의 전사 발췌 — 말투 참고용. STT라 문장부호가 없고 '어/음' 같은 군말은 제거했습니다]
{sample}

[이 발췌에서 보이는 말투 특징 (1000자당 빈도, 교수님 / 현재 대본)]
- '합니다/습니다' 종결: 2.9 / 9  → 확 줄일 것. 대신 '~거죠', '~겁니다', '~거고요', '~되겠죠', '~해야 됩니다', '~하는 거예요', '~고요' 로 끝낸다.
- '그래서': 6.0 / 0.8, '이제': 5.9 / 0.7 → 문장과 문장을 이 말로 잇는다.
- '자,'로 화제 전환: 2.7 / 0.4
- '한번 ~해 봅시다', '그렇죠?', '아까 얘기했듯이', '예를 들면' 같은 말을 자연스럽게 섞는다.

[슬라이드별 필수 횟수 — 글자 수에 비례]
{counts}

[규칙]
1. 내용 추가·삭제 금지. 슬라이드에 없는 사실을 만들지 않는다.
2. 영어 단어는 철자 그대로 유지하고 새 영어 단어를 추가하지 않는다.
3. 슬라이드별 글자 수는 원래의 95~108% 안에서 유지한다.
4. '어', '음', '그니까' 같은 군말은 넣지 않는다. 음성 합성용이라 문장은 30~90자로, 문장부호를 제대로 찍는다.
5. 같은 표현을 기계적으로 반복하지 않는다(예: 모든 문장을 '그래서'로 시작하지 말 것).

[원래 대본]
{json.dumps([{"slide_number":n,"script":s} for n,s in scripts.items()],ensure_ascii=False,indent=1)}

[출력] JSON만: {{"slides":[{{"slide_number":N,"script":"..."}}]}}"""
out=json.loads(strip_markdown_json_fence(OpenAILLMClient().chat([{"role":"system","content":sysmsg},{"role":"user","content":user}],temperature=0.5)))
res={}
for s in out["slides"]:
    n=s["slide_number"]; o=scripts[n]; r=s["script"]
    res[n]={"orig":o,"new":r,"len_ratio":round(len(r)/len(o),3),"latin_same":sorted(set(LAT.findall(o)))==sorted(set(LAT.findall(r))),"latin_added":sorted(set(LAT.findall(r))-set(LAT.findall(o)))}
(SP/f"restyle_{sys.argv[2]}_v2.json").write_text(json.dumps(res,ensure_ascii=False,indent=1))
for n,v in res.items(): print(n,v["len_ratio"],v["latin_same"],v["latin_added"])

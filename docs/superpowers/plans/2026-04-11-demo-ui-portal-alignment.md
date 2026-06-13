# Demo UI Portal Alignment Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demo 프론트엔드의 글꼴·톤·분위기를 `homepage/page.tsx`(lab 포털)과 동일하게 맞춘다.

**Architecture:** styles.css 토큰과 컴포넌트 스타일만 수정. index.html 폰트 import 정리. app.js는 변경 없음. 두-뷰 라우팅 기능 구조 그대로 유지.

**Tech Stack:** Vanilla HTML/CSS, Pretendard (메인 한글 폰트, CDN), JetBrains Mono (코드 전용)

**폰트 결정:** Pretendard — 현대적이고 가독성 최고인 한국 웹 표준 폰트. 어르신 사용을 위해 base 18px.
**구조 유지:** 홈 그리드 → 상세 워크스페이스 두-뷰 라우팅 구조는 변경하지 않음.

---

## Reference: homepage/page.tsx 디자인 언어

```
배경:      흰 페이지 (white / gray-50)
카드:      bg-white rounded-xl border border-gray-200 p-6
제목:      text-gray-900, font-bold/semibold, text-2xl/text-lg
본문:      text-gray-500/gray-400, text-sm
포인트:    bg-emerald-700 hover:bg-emerald-800, text-white
입력창:    border-gray-300, focus:ring-2 focus:ring-emerald-600
폰트:      sans-serif (Noto Sans KR) — serif 없음
```

## File Map

| 파일 | 역할 | 변경 여부 |
|------|------|-----------|
| `lecture_auto/demo_static/index.html` | HTML 구조 + 폰트 import | 수정 — Noto Serif KR 제거 |
| `lecture_auto/demo_static/styles.css` | 전체 스타일 | 수정 — 토큰·컴포넌트 정렬 |
| `lecture_auto/demo_static/app.js` | 라우팅·데이터 로직 | **변경 없음** |

---

## Task 1: 폰트 교체 — Pretendard + base 18px

**Files:**
- Modify: `lecture_auto/demo_static/index.html`
- Modify: `lecture_auto/demo_static/styles.css`

### 변경 이유
Pretendard는 한국 웹에서 가장 가독성 좋은 현대 폰트. 어르신 접근성을 위해 base 18px 적용.
Noto Serif KR은 완전 제거, Noto Sans KR도 Pretendard로 교체.

- [ ] **Step 1: index.html 폰트 import 전체 교체**

`index.html` `<head>`의 `<link>` 폰트 블록 전체를 아래로 교체:

```html
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

- [ ] **Step 2: styles.css — serif 변수 제거, Pretendard로 교체**

`:root`의 폰트 변수를:

```css
--font-sans:  'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif;
--font-mono:  'JetBrains Mono', 'Menlo', monospace;
```

`--font-serif` 변수 줄은 완전 삭제.

- [ ] **Step 3: styles.css 내 `var(--font-serif)` 전체 치환**

파일 전체에서 `var(--font-serif)` → `var(--font-sans)` 로 replace_all.

```bash
grep -c "font-serif" lecture_auto/demo_static/styles.css
```
Expected: `0`

- [ ] **Step 4: base font-size 18px으로 변경**

```css
html { font-size: 18px; -webkit-font-smoothing: antialiased; }
```

- [ ] **Step 5: 커밋**

```bash
git add lecture_auto/demo_static/index.html lecture_auto/demo_static/styles.css
git commit -m "style(demo): switch to Pretendard 18px base, remove Noto Serif KR"
```

---

## Task 2: 색상 토큰 → Tailwind Gray 팔레트 정확히 맞추기

**Files:**
- Modify: `lecture_auto/demo_static/styles.css` (`:root` 블록)

### 변경 이유
현재 토큰이 #e5e7eb 등 Tailwind 근사치이지만, 일부 값이 미세하게 다름. 포털 정확한 값으로 통일.

> ⚠️ **전제조건:** Task 1 Step 3의 `var(--font-serif)` 전체 치환이 반드시 먼저 완료되어야 함. 이 `:root` 블록에서 `--font-serif`가 삭제되므로, 잔류 참조가 있으면 렌더링 폴백 발생.

- [ ] **Step 1: `:root` 토큰 블록을 아래로 교체**

```css
:root {
  /* ── Background & Surface ── */
  --bg:         #f9fafb;   /* gray-50  */
  --surface:    #ffffff;   /* white    */
  --surface-2:  #f9fafb;   /* gray-50  */
  --surface-3:  #f3f4f6;   /* gray-100 */

  /* ── Border ── */
  --border:     #e5e7eb;   /* gray-200 */
  --border-2:   #d1d5db;   /* gray-300 */

  /* ── Emerald accent (emerald-700/800) ── */
  --accent:     #047857;
  --accent-hover: #065f46;
  --accent-dim: rgba(4, 120, 87, 0.08);
  --accent-glow:rgba(4, 120, 87, 0.15);

  /* ── Text ── */
  --text:       #111827;   /* gray-900 */
  --muted:      #6b7280;   /* gray-500 */
  --faint:      #9ca3af;   /* gray-400 */

  /* ── Status colors ── */
  --green:  #10b981;   /* emerald-500 */
  --red:    #ef4444;   /* red-500     */
  --yellow: #f59e0b;   /* amber-500   */
  --blue:   #3b82f6;   /* blue-500    */

  /* ── Typography ── */
  --font-sans:  'Noto Sans KR', -apple-system, sans-serif;
  --font-mono:  'JetBrains Mono', 'Menlo', monospace;

  /* ── Shape & Shadow ── */
  --radius:    8px;
  --radius-sm: 6px;
  --radius-lg: 12px;   /* rounded-xl equivalent */
  --shadow:    0 1px 3px rgba(0,0,0,.08), 0 4px 16px rgba(0,0,0,.06);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.05);

  --topbar-h: 58px;
  --tabbar-h: 50px;
}
```

- [ ] **Step 2: btn-cta, btn-primary hover 색상 연결**

아래 두 곳에 hover 색상 추가:
```css
.btn-cta:hover  { background: var(--accent-hover); opacity: 1; transform: translateY(-1px); }
.btn-primary:hover { background: var(--accent-hover); opacity: 1; }
```

- [ ] **Step 3: 커밋**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): align color tokens to Tailwind gray palette + emerald-700"
```

---

## Task 3: 카드 스타일 → portal card 패턴 (rounded-xl border p-6)

**Files:**
- Modify: `lecture_auto/demo_static/styles.css`

### 변경 이유
포털 카드는 `bg-white rounded-xl border border-gray-200 p-6 shadow-none`. 현재 demo 카드는 shadow가 강하고 padding이 다름.

- [ ] **Step 1: `.lecture-card` 패딩·그림자 수정**

```css
.lecture-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);   /* 12px = rounded-xl */
  padding: 20px 20px 16px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: relative;
  overflow: hidden;
}
.lecture-card:hover {
  border-color: var(--border-2);
  box-shadow: var(--shadow);
}
```

(transform 제거 — 포털은 hover lift 없음)

- [ ] **Step 2: `.detail-card` 스타일 같은 패턴으로 통일**

```css
.detail-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
}
```

- [ ] **Step 3: `.control-card` 스타일 통일**

같은 패턴: `border: 1px solid var(--border)`, `border-radius: var(--radius-lg)`, `padding: 24px`.

- [ ] **Step 4: 커밋**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): align card styles to portal rounded-xl border p-6 pattern"
```

---

## Task 4: 헤더 · 브랜드 → 포털 헤더 무게감으로 조정

**Files:**
- Modify: `lecture_auto/demo_static/styles.css`

### 변경 이유
포털 헤더는 `text-2xl font-bold text-gray-900`, 서브텍스트는 `text-sm text-gray-500`. 현재 demo는 serif + 큰 brand-mark로 과장된 느낌.

- [ ] **Step 1: `.brand-name` 타이포 수정**

```css
.brand-name {
  font-family: var(--font-sans);
  font-size: 1.35rem;       /* text-2xl 근사 */
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text);
  line-height: 1.2;
}
```

- [ ] **Step 2: `.brand-sub` 수정**

```css
.brand-sub {
  font-size: 0.82rem;
  color: var(--muted);
  margin-top: 2px;
  font-family: var(--font-sans);  /* mono 제거 */
}
```

- [ ] **Step 3: `.brand-mark` 크기 줄이기**

```css
.brand-mark {
  width: 38px;
  height: 38px;
  background: var(--accent);
  color: #fff;
  font-family: var(--font-sans);
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
```

- [ ] **Step 4: `.toolbar-label` serif 제거**

```css
.toolbar-label {
  font-family: var(--font-sans);
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text);
}
```

- [ ] **Step 5: 커밋**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): align header/brand typography to portal weight and sans-serif"
```

---

## Task 5: 탭바 · 상태 pill → 포털 스타일

**Files:**
- Modify: `lecture_auto/demo_static/styles.css`

### 변경 이유
포털은 탭/버튼에 ring-based focus, 심플한 border-bottom 기반 active 탭 스타일 사용.

- [ ] **Step 1: 현재 `.tab`, `.tab.active` 스타일 확인**

```bash
grep -n "\.tab " lecture_auto/demo_static/styles.css | head -20
```

- [ ] **Step 2: `.tab` 스타일 심플하게 교체**

```css
.tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  font-family: var(--font-sans);
  font-size: 0.9rem;
  font-weight: 500;
  padding: 14px 18px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.tab:hover  { color: var(--text); }
.tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
```

- [ ] **Step 3: `.status-pill` 스타일 정리**

```css
.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 100px;
  font-size: 0.75rem;
  font-weight: 500;
  font-family: var(--font-sans);
  border: 1px solid var(--border);
  background: var(--surface-3);
  color: var(--muted);
}
.status-pill[data-status="running"],
.status-pill[data-status="queued"]    { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
.status-pill[data-status="completed"],
.status-pill[data-status="done"]      { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
.status-pill[data-status="failed"],
.status-pill[data-status="error"]     { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
.status-pill[data-status="stopped"]   { background: var(--surface-3); color: var(--muted); }
.status-pill[data-status="stopping"]  { background: #fffbeb; color: #b45309; border-color: #fde68a; }
```

- [ ] **Step 4: 커밋**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): simplify tab active indicator and status pill to portal style"
```

---

## Task 6: 입력 필드 → 포털 input 스타일

**Files:**
- Modify: `lecture_auto/demo_static/styles.css`

### 변경 이유
포털은 `border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-600`. Demo input이 다크 배경용 스타일로 남아있을 수 있음.

- [ ] **Step 1: `.field-input`, `input`, `textarea`, `select` 스타일 확인 및 교체**

```css
input[type="text"],
input[type="number"],
input[type="email"],
textarea,
select,
.field-input {
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 8px 12px;
  font-size: 0.9rem;
  font-family: var(--font-sans);
  width: 100%;
  transition: border-color 0.15s, box-shadow 0.15s;
  outline: none;
}
input:focus,
textarea:focus,
select:focus,
.field-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
}
```

- [ ] **Step 2: 커밋**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): align form inputs to portal border/focus-ring pattern"
```

---

## Task 7: 모달 스타일 → 포털 카드 패턴

**Files:**
- Modify: `lecture_auto/demo_static/styles.css`

- [ ] **Step 1: `.modal-box` 스타일 확인**

```bash
grep -n "modal-box" lecture_auto/demo_static/styles.css | head -10
```

- [ ] **Step 2: `.modal-box` 교체**

```css
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.3);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 100;
}

.modal-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 20px 60px rgba(0,0,0,.12);
  width: 100%;
  max-width: 520px;
  max-height: 90dvh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border);
}

.modal-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text);
}
```

- [ ] **Step 3: 커밋**

```bash
git add lecture_auto/demo_static/styles.css
git commit -m "style(demo): align modal to portal card style (white, border, soft shadow)"
```

---

## Task 8: 최종 시각 검증

- [ ] **Step 1: 서버 실행 후 브라우저에서 확인**

```bash
# 서버가 이미 실행 중이면 /demo 열기
# 확인 항목:
# - 홈 화면: 흰 배경, gray 카드, 에메랄드 버튼
# - serif 폰트가 아무 곳에도 안 보임
# - 카드 hover: lift 없이 border-color만 변경
# - 탭 active: 에메랄드 underline
# - 모달: 흰 카드, 부드러운 그림자
```

- [ ] **Step 2: serif 폰트 잔재 최종 검사**

```bash
grep -n "serif" lecture_auto/demo_static/styles.css
grep -n "Noto Serif" lecture_auto/demo_static/index.html
```
Expected: 모두 0건

- [ ] **Step 3: 최종 커밋**

```bash
git add lecture_auto/demo_static/
git commit -m "style(demo): complete portal alignment — light theme, emerald, sans-serif"
```

# 식품 이커머스 그로스 대시보드

데이터 분석에 익숙하지 않은 실무자가 자연어로 질문하면 AI가 데이터를 조회·시각화·해석하고,
발견한 문제를 Growth Lab에서 가설 → 전략 → 실험 설계로 이어가는 AI 기반 그로스 의사결정 지원 서비스입니다.

기본은 DB 없이 폴더 안의 CSV(`ecommerce_generation_blueprint/data/generated/v2`)로 동작합니다.
이 데이터는 실제 이커머스 데이터의 특성을 반영해 만든 가상 식품 이커머스(A마켓)의 2026-04-01 ~ 2026-09-30 데이터입니다.

## 실행

**방법 1 (가장 쉬움)** — `dashboard` 폴더의 `run.bat` 을 더블클릭합니다.
`dashboard_test` 폴더에 이미 만들어 둔 가상환경(.venv)을 그대로 사용합니다.

**방법 2 (터미널)**

```
cd C:\Users\kelly\Desktop\BAAI경영시뮬레이션\dashboard
..\dashboard_test\.venv\Scripts\python.exe -m streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다. 처음 열 때 데이터 계산에 10~20초 정도 걸리고, 이후에는 바로 뜹니다.

## 화면 구성

| 화면 | 핵심 질문 |
|---|---|
| AI 분석가 (모든 화면 오른쪽 패널) | 궁금한 것을 물으면 데이터를 찾아 숫자·차트·해석으로 답한다 |
| 통합 현황 | 지금 무엇이 달라졌고, 무엇부터 확인해야 하는가? |
| 상품·큐레이션 | 어떤 상품과 테마가 누구에게 잘 작동하는가? |
| 고객 여정·전환 | 고객이 어디에서 구매를 포기하는가? |
| 고객·리텐션 | 어떤 고객이 돌아오고, 어떤 고객이 떠나는가? |
| Growth Lab | 어떤 문제를 해결하고, 어떻게 검증할 것인가? |

AI 분석가는 별도 메뉴가 아니라 모든 화면 오른쪽에 붙은 채팅 패널입니다. 사이드바의 **AI 분석가 열기**로 열고 닫으며,
화면을 옮겨도 대화가 이어집니다. 왼쪽 사이드바의 기간·비교 조건은 모든 화면이 공유합니다. AI 분석가 답변의 분석 결과와 분석 화면(통합 현황, 상품·큐레이션,
고객 여정, 리텐션)의 **Growth Lab에 저장** 버튼으로 문제 후보를 모으고, Growth Lab에서 문제 정의 → 가설 → 전략(ICE) → 실험 설계(표본·기간 계산)
→ 결과 검토로 이어갑니다. 저장 위치는 아래 [DB 연결과 팀 공유](#db-연결과-팀-공유)를 참고하세요.

## AI 분석가와 Growth Lab AI 초안

### 작동 방식
- 질문 → AI가 알맞은 분석 도구(`core/tools.py`, 14개)와 기간·고객 조건을 고름 → 도구 실행 → AI가 결과를 근거로 2~5문장으로 설명
- **숫자는 AI가 만들지 않습니다.** 모든 숫자는 대시보드와 같은 계산 함수(`core/metrics.py`)에서 나옵니다.
  답변에 도구 결과에 없는 숫자가 있으면 화면에 경고를 띄웁니다.
- AI에는 원본 데이터가 아니라 도구가 계산한 요약 결과만 전달됩니다.
- 데이터로 확인된 사실과 원인·대책(가설)을 구분해 답하고, 데이터에 없는 질문(광고비·ROAS, 결제 페이지 진입, 체류 시간 등)은
  없다고 밝힌 뒤 대체 지표를 제안합니다.
- "요즘"처럼 기간이 애매한 질문은 먼저 기간을 되묻습니다. 기간 기준: 오늘 = 2026-09-30, 이번 달 = 9월, 지난달 = 8월.
- 고객 조건(성별, 연령대, 지역, 가입 경로, 등급, 첫 구매/기존 구매, 신규 가입)을 걸어 물을 수 있습니다.
- Growth Lab의 **AI 초안 만들기**는 저장된 문제에 대해 도구로 근거를 다시 확인한 뒤 가설·전략(ICE)·실험 설계 초안을 씁니다.
  근거에서 찾지 못한 숫자에는 '⚠️ 확인 필요'를 붙입니다. 초안은 실무자가 검토한 뒤 반영합니다.
- AI 분석가 답변의 분석 결과마다 **Growth Lab에 저장** 버튼이 있습니다. 문제 제목과 문제라고 본 이유를 적어 저장하면
  질문·근거 사실·AI 설명이 함께 넘어가고, Growth Lab의 AI 초안도 이 근거를 받아 씁니다.

### 연결 방법
`.streamlit/secrets.toml`(PC) 또는 Streamlit Cloud의 Secrets에 키를 넣습니다.

```toml
OPENAI_API_KEY = "sk-..."        # GPT 사용 (우선)
# GEMINI_API_KEY = "..."         # OPENAI 키가 없을 때 Gemini 사용
# OPENAI_MODEL = "gpt-5-nano"    # 모델 고정이 필요할 때만 (없으면 가장 가벼운 모델 자동 선택)
```

키가 없으면 AI 분석가는 **예시 질문** 버튼만 정해진 분석으로 답하고, Growth Lab AI 초안은 쓸 수 없습니다.

## AI 분석가 평가 (`eval/`)

| 평가 | 내용 | 실행 |
|---|---|---|
| 기본 평가셋 | 실무자 질문 30개 + 데이터로 답할 수 없는 질문 8개(X1~X8). 지시문·도구를 고치는 데 사용 | `eval_llm.bat` |
| 홀드아웃 1차 | 처음 보는 질문 28개(표현 바꾸기, 다른 기간, 미지원 질문). 수정에 쓰지 않음, 3회 반복 | `eval_holdout.bat` |
| 홀드아웃 2차 | 30개(표현 바꾸기, 고객 조건 조합, KPI 정의, 모르는 것 인정). 수정에 쓰지 않음, 3회 반복 | `eval_holdout2.bat` |
| 도구-정답 일치 | 올바른 도구·기간이면 정답과 같은 숫자가 나오는지 (AI 호출 없음) | `python eval/check_tools.py` |
| 데이터 변경 | 데이터 일부를 바꾸면 답도 바뀌고, 건드리지 않은 곳은 그대로인지 | `python eval/data_change.py` |

- 정답은 데이터에서 직접 계산합니다: `python eval/make_answers.py` → `eval/answers.json`, `eval/answers.md` (데이터가 바뀌면 다시 실행)
- 기본 평가셋은 보면서 고쳐 왔으므로 그 점수만으로 일반화 성능을 말하지 않습니다. 홀드아웃 문항이 틀려도 그 문항에 맞춘 규칙을 넣지 않습니다.
- 결과: `eval/llm_results*.md`(사람이 보는 표), `.json`

## 계산 기준

KPI 정의서 공식 v2를 따릅니다.

- 완료 매출 = COMPLETED 주문의 `total_amount` 합 (배송비 포함, 회계 순매출 아님)
- 전환율은 모두 DISTINCT 세션 기준, 구간 전환율의 분모는 직전 단계 도달 세션
- 주문 → 큐레이션/일반 탐색 귀속은 purchase 이벤트로 1:1 (테마 경유 매출 ≠ 테마의 증분 효과)
- 신규 방문 / 신규 가입 / 첫 구매는 서로 다른 개념
- 데이터에 없는 것: 결제 진입 단계, 비로그인 방문, 세션 유입 채널, 실험 결과

## 폴더 구조

```
dashboard/
├─ app.py              # 진입점, 메뉴, 화면 + AI 분석가 패널 배치
├─ run.bat             # 더블클릭 실행
├─ check_db.bat        # DB 점검
├─ eval_*.bat          # AI 분석가 평가 실행 (기본·홀드아웃 1차·2차)
├─ core/
│  ├─ data.py          # 데이터 읽기 + 세션·주문 마트 (CSV ↔ DB 교체 지점)
│  ├─ metrics.py       # 공통 계산 엔진 (KPI, 퍼널, 테마, 변화 탐지, 표본 계산)
│  ├─ chat.py          # AI 분석가 채팅 패널 (모든 화면 오른쪽)
│  ├─ tools.py         # AI가 부르는 분석 도구 14개 (metrics.py 결과를 사실·차트·표로 정리)
│  ├─ llm.py           # AI 분석가·Growth Lab 초안 (지시문, 도구 호출, 근거 없는 숫자 확인, Gemini)
│  ├─ llm_openai.py    # OpenAI(GPT) 호출
│  ├─ db.py            # DB 연결 (.env / Streamlit Secrets)
│  ├─ store.py         # Growth Lab 저장소 (DB 또는 JSON)
│  └─ ui.py            # 기간 선택, 숫자 표시, 공통 컴포넌트
├─ views/              # 화면 5개 (분석 4개 + Growth Lab)
└─ eval/               # AI 분석가 평가셋·정답·채점
```

## DB 연결과 팀 공유

### Growth Lab 저장 위치
- DB 접속 정보(`dashboard/.env` 또는 `dashboard_test/.env`)가 있으면 Growth Lab은 **Supabase의 `growth_lab_problems` 테이블**에 저장됩니다.
  팀원 모두가 같은 문제·가설·실험안을 보고 고칠 수 있고, 사이드바의 **내 이름**이 작성자·수정자로 남습니다.
- 접속 정보가 없으면 이 PC의 `growth_lab/store.json` 에 저장됩니다.

### 1단계: DB 점검 (내 PC)
`check_db.bat` 을 더블클릭합니다. 13개 테이블의 행 수·컬럼이 CSV와 같은지, DB 데이터로 계산한 완료 매출이
KPI 정의서 기준값(526,717,597원)과 같은지 확인하고, Growth Lab 저장 테이블을 만듭니다.
마지막 줄이 "모두 정상입니다"이면 다음 단계로 갑니다.

내 PC 대시보드도 DB에서 읽게 하려면 `dashboard/.env` 에 `DATA_BACKEND=db` 를 적습니다(없으면 CSV를 읽음).

### 2단계: GitHub에 올리기
1. github.com 에서 새 저장소(Repository)를 만듭니다. **Private**를 권장합니다.
2. 저장소 화면의 "uploading an existing file"을 눌러 `dashboard` 폴더 **안의 내용 전체**를 끌어다 놓습니다
   (`app.py`, `requirements.txt`, `core`, `views`, `.streamlit` 등이 저장소 맨 위에 오도록).
3. `.env` 와 `growth_lab` 폴더는 올리지 않습니다. 비밀번호가 들어 있습니다.

### 3단계: Streamlit Community Cloud에 배포
1. share.streamlit.io 에 GitHub 계정으로 로그인 → **Create app** → 방금 만든 저장소 선택, Main file path = `app.py`.
2. **Advanced settings → Secrets** 에 `.streamlit/secrets.toml.example` 내용을 붙여넣고 값을 채웁니다.
   AI 분석가를 쓰려면 `OPENAI_API_KEY` 줄의 주석(`#`)을 지우고 키를 넣습니다.
   - Supabase 화면 상단 **Connect → Session pooler** 의 Host·User·Port를 씁니다.
     Streamlit Cloud는 IPv4만 되는데, Supabase의 Direct connection 주소는 IPv6 전용이라 연결되지 않을 수 있습니다.
3. **Deploy** 를 누르면 몇 분 뒤 `https://<이름>.streamlit.app` 주소가 생깁니다.
4. 앱 설정의 **Sharing** 에서 공개 범위를 정합니다. 팀원만 보게 하려면 비공개로 두고 팀원 이메일을 초대합니다.

### 운영 메모
- 배포된 앱은 처음 열 때 DB에서 데이터를 읽느라 수십 초 걸릴 수 있고, 이후에는 빠릅니다.
  한동안 아무도 안 쓰면 잠들었다가 다시 깨어나는 데 시간이 걸립니다.
- 같은 문제를 두 사람이 동시에 고치면 나중에 저장한 내용이 남습니다. 작업할 문제를 나눠 맡는 것을 권장합니다.
- 코드를 고치면 GitHub 파일만 바꾸면 앱이 자동으로 다시 배포됩니다.

## 아직 하지 않은 것

- **아직 도구가 없는 분석**: 요일×시간대 주문, 함께 사는 상품 조합, 결제수단별 분석, 여러 연령대·성별을 한 표로 비교
- **실험 결과**: 실제 실험 데이터가 없어 Growth Lab 결과 검토는 모의 결과 입력으로만 확인합니다('모의 결과' 표시).

# 식품 이커머스 그로스 대시보드

DB 없이 폴더 안의 CSV(`ecommerce_generation_blueprint/data/generated/v2`)로 동작합니다.

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

| 메뉴 | 핵심 질문 |
|---|---|
| 통합 현황 | 지금 무엇이 달라졌고, 무엇부터 확인해야 하는가? |
| 상품·큐레이션 | 어떤 상품과 테마가 누구에게 잘 작동하는가? |
| 고객 여정·전환 | 고객이 어디에서 구매를 포기하는가? |
| 고객·리텐션 | 어떤 고객이 돌아오고, 어떤 고객이 떠나는가? |
| Growth Lab | 어떤 문제를 해결하고, 어떻게 검증할 것인가? |

왼쪽 사이드바의 기간·비교 조건은 모든 화면이 공유합니다. 각 화면의 **Growth Lab에 저장** 버튼으로 문제 후보를 모으고,
Growth Lab에서 문제 정의 → 가설 → 전략(ICE) → 실험 설계(표본·기간 계산) → 결과 검토로 이어갑니다.
Growth Lab 내용은 `dashboard/growth_lab/store.json` 에 저장됩니다.

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
├─ app.py              # 진입점, 메뉴
├─ run.bat             # 더블클릭 실행
├─ check_db.bat        # DB 점검
├─ core/
│  ├─ data.py          # 데이터 읽기 + 세션·주문 마트 (CSV ↔ DB 교체 지점)
│  ├─ metrics.py       # 공통 계산 엔진 (KPI, 퍼널, 테마, 변화 탐지, 표본 계산)
│  ├─ db.py            # DB 연결 (.env / Streamlit Secrets)
│  ├─ store.py         # Growth Lab 저장소 (DB 또는 JSON)
│  └─ ui.py            # 기간 선택, 숫자 표시, 공통 컴포넌트
└─ views/              # 화면 5개
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
   - Supabase 화면 상단 **Connect → Session pooler** 의 Host·User·Port를 씁니다.
     Streamlit Cloud는 IPv4만 되는데, Supabase의 Direct connection 주소는 IPv6 전용이라 연결되지 않을 수 있습니다.
3. **Deploy** 를 누르면 몇 분 뒤 `https://<이름>.streamlit.app` 주소가 생깁니다.
4. 앱 설정의 **Sharing** 에서 공개 범위를 정합니다. 팀원만 보게 하려면 비공개로 두고 팀원 이메일을 초대합니다.

### 운영 메모
- 배포된 앱은 처음 열 때 DB에서 데이터를 읽느라 수십 초 걸릴 수 있고, 이후에는 빠릅니다.
  한동안 아무도 안 쓰면 잠들었다가 다시 깨어나는 데 시간이 걸립니다.
- 같은 문제를 두 사람이 동시에 고치면 나중에 저장한 내용이 남습니다. 작업할 문제를 나눠 맡는 것을 권장합니다.
- 코드를 고치면 GitHub 파일만 바꾸면 앱이 자동으로 다시 배포됩니다.

## 아직 연결하지 않은 것

- **AI 챗봇**: LLM API 키가 필요합니다. 연결하면 각 화면의 기간·필터를 넘겨받아 `core/metrics.py`(또는
  `ecommerce_generation_blueprint/src/kpi`)의 계산 결과로 답하고, Growth Lab의 가설 'AI 초안' 칸을 채우는 구조로 붙일 수 있습니다.

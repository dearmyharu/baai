# Growth Lab 인계 문서 (ver.2)

작성: 2026-11-21. Growth Lab 화면 개편은 팀원 담당입니다. 이 문서는 어디서부터 시작하면 되는지, 다른 화면과 무엇을 주고받는지를 정리합니다.
전체 설계는 프로젝트 문서 `claude/재설계_2026-11-21.md`를 따릅니다.

## 0. 현재 상태 (2026-11-21 갱신)

- **임시 Growth Lab이 동작합니다.** 화면 구성과 UX/UI는 팀원이 바꾸면 됩니다.
- 계산은 `engine/growth.py`에 있고 이미 동작합니다. 화면(`views/growth_lab.py`)은 이 함수들을 불러 표시만 합니다.
  - `breakeven(m, target, lever, today)`: 본전 주문 증가율(최근 28일 기준, simulation 재계산)
  - `profit_probability(be, m, target, today, low, mode, high, days)`: 주문 반응 가정 범위(삼각분포) + 일별 흔들림으로 이익이 날 확률
  - `detect_days(m, target, today, effect)`: 브리핑 판정과 같은 지표(대상 매출 비중)로 효과 확인에 필요한 일수. 대부분 '확인 어려움'으로 나옴(작은 쇼핑몰 특성)
  - `plan_row(...)`·`save_plan(row)`: 실행 계획 → promotion 한 행(로컬 CSV 또는 DB)
  - `result_series(m, promo)`: 결과 차트 데이터. 판정은 `briefing.promo_status`
- 임시 화면의 세 가지 모드: `lab_request` 없음 → 등록된 프로모션 목록 / `type=plan` → 수단 조정·본전·이익 확률·확인 기간·실행 계획 등록 / `type=lab` → 프로모션 결과
- 확인: 세 모드 모두 화면 오류 없음(테스트 도구). '실행 계획 등록' 버튼은 데이터 파일을 바꾸므로 시험하지 않았습니다.
- 바꿀 파일: `views/growth_lab.py`(화면). 계산을 바꿔야 하면 `engine/growth.py`를 고치되 함수 이름·반환 형식은 유지해 주세요.
- 챗봇 연결(예정): Growth Lab 화면이 현재 값을 `st.session_state["growth_context"]`에 넣으면 오른쪽 챗봇이 참고해 답합니다. 챗봇이 제안한 수단·값은 `st.session_state["lab_suggestion"]`에 남고, 이를 입력칸에 반영하는 버튼은 화면 구성이 정해진 뒤에 만듭니다.

## 1. Growth Lab의 역할

ver.2는 세 화면이 역할을 나눕니다.

| 화면 | 답하는 질문 | 담당 |
|---|---|---|
| 아침 브리핑 | 전일 실적은 어떤가, 무엇이 달라졌나, 지난 프로모션은 어떻게 됐나 | 완료 |
| AI 분석가(챗봇) | 왜 그런가, 어디를(대상) 무엇으로(수단) 밀어야 하나 | 완료(2026-11-21) |
| **Growth Lab** | **해도 되는가(손익), 효과를 확인할 수 있는가(기간), 어떻게 실행하는가(계획)** | **팀원** |

Growth Lab은 챗봇이 찾은 대상·수단을 받아 다음 네 가지를 보여 주고, 사용자가 실행 계획을 등록하는 곳입니다.

1. 본전에 필요한 추가 주문: 할인으로 줄어든 이익을 메우려면 주문이 몇 건(몇 %) 더 늘어야 하는지. 확정 계산입니다.
2. 이익이 날 확률: 주문 반응을 범위로 가정하고(예: −5% ~ +30%) 몬테카를로로 계산합니다. 가정 범위를 화면에 반드시 표시합니다.
3. 효과 확인에 필요한 기간: 현재 주문 규모로 효과를 구분하려면 며칠이 필요한지. 작은 쇼핑몰은 확인이 어려울 수 있으므로 "이 규모로는 N일 필요 / 확인 어려움"을 말해 주는 것이 핵심입니다.
4. 실행 계획 한 장: 대상, 수단, 기간, 주 지표, 짝 지표, 중단 기준.

## 2. 이미 정해진 것 (바꾸려면 상의)

- AI로 주문 반응을 예측하지 않습니다. 주문 반응은 사용자가 정하는 가정값이고, 화면에 가정임을 표시합니다.
- 이익 = 결제 금액(쿠폰 차감 후 상품금액 + 고객 배송비) − 상품원가 − 배송 원가(주문당 3,000원 가정). 결제 수수료는 넣지 않고 화면에 "기타 비용 제외"를 표시합니다. 브리핑(`engine/briefing.py`의 `SHIP_COST`, `ledger`)과 같은 식을 씁니다.
- 화면 문구는 업무 보고체(~입니다)입니다. 구어체(~어요)는 쓰지 않습니다.
- 실행 후 판정(효과 있음 / 불분명 / 중단 검토)은 아침 브리핑이 매일 계산합니다(`engine/briefing.py`의 `promo_status`). Growth Lab은 같은 판정을 다시 만들지 말고 이 함수를 불러 쓰면 됩니다.

## 3. Growth Lab이 받는 것 (입력)

다른 화면은 `st.session_state["lab_request"]`에 요청을 넣고 Growth Lab 화면으로 이동합니다. Growth Lab은 이 값을 읽어 화면을 채웁니다. 지금 임시 화면(`views/growth_lab.py`)은 받은 값을 그대로 출력만 합니다.

### 3-1. 아침 브리핑에서: 프로모션 결과 보기 (지금 동작함)
```python
{"type": "lab", "label": "Growth Lab 결과 보기", "promotion_id": "PR003"}
```
→ 해당 프로모션의 계획 대비 결과를 보여 줍니다. 계산은 `briefing.promo_status(m, day)`에서 같은 ID를 찾아 쓰면 됩니다(기준일은 `st.session_state["today"]` − 1일).

### 3-2. 챗봇에서: 새 계획 만들기 (2026-11-21 구현, 지금 동작함)
AI 분석가 오른쪽 '분석 진행'에서 다섯 조건이 모두 채워지면 'Growth Lab에서 계획 세우기' 버튼이 생기고, 아래 형식으로 보냅니다. 만드는 코드: `engine/case.py`의 `lab_request`.
```python
{
  "type": "plan",
  "question": "최근 7일 정육 카테고리에서 매출이 줄어든 상품은? ...",   # 출발 질문
  "diagnosis": {                                   # 진단(계산 엔진, case.diagnose)
      "metric": "정육 카테고리 일평균 매출",
      "value": 277640, "base": 280111, "change": -0.009,        # 최근 7일 일평균 vs 직전 4주 일평균
      "period": ["2026-10-15", "2026-10-21"],
      "sales3": 570000, "base3": 950000, "change3": -0.39,      # 최근 3일 합계 vs 지난 4주 같은 요일 3일 평균
      "period3": ["2026-10-19", "2026-10-21"]},
  "target": {"type": "category", "value": "정육"},              # category | product(값 = 상품명)
  "lever": {"policy": "price", "value": -5},                     # simulation.POLICIES 키. price는 가격 변화율(내리면 음수, %)
                                                                 # discount = 정률 %, bundle = 추가 할인 %, shipping = 무료배송 기준 원
  "hypothesis": "정육 카테고리에 판매가 할인 5%를 적용하면 ... 일평균 매출이 늘고 이익률은 중단 기준 안에 머문다",
  "cause_hypothesis": "...",                                     # 대화에서 나온 원인 가설(확인 전, 빈 문자열일 수 있음)
  "primary_metric": "정육 카테고리 일평균 매출",
  "guard_metric": "정육 카테고리 이익률",
  "stop_rule": "정육 카테고리 이익률이 시작 전보다 8%p 넘게 떨어지면 중단",
  "evidence": ["..."],                                           # 챗봇 답변의 근거 문장(계산 엔진 숫자)
}
```
- 빈 칸이 있는 요청은 오지 않습니다(조건 확인은 코드가 함).
- 수단 값은 사용자가 고른 기본 선택지(판매가 5·10%, 쿠폰 5%, 묶음 5%, 무료배송 3만 원)이거나 대화 중 손익 계산에 쓴 값입니다. Growth Lab에서 바꿀 수 있게 하는 것을 권합니다.
- 시험 방법: AI 분석가에서 아침 브리핑의 '원인 분석' 버튼으로 시작 → 오른쪽에서 수단 선택 → 'Growth Lab에서 계획 세우기'.

## 4. Growth Lab이 남기는 것 (출력)

실행 계획을 등록하면 `promotion` 테이블에 한 행을 추가합니다. 아침 브리핑은 이 테이블을 읽어 다음 날부터 "프로모션 점검"에 자동으로 보여 줍니다.

| 열 | 예 | 비고 |
|---|---|---|
| promotion_id | PR004 | 기존 최대 번호 + 1 |
| promotion_name | 정육 5% 할인 | |
| category | 정육 | 지금 판정 로직은 카테고리 단위만 지원 |
| lever | price | simulation.POLICIES 키 |
| discount_pct | 5 | |
| start_date / end_date | 2026-11-02 / 2026-11-15 | end_date 포함 |
| primary_metric / guard_metric | 정육 일평균 매출 / 정육 이익률 | |
| stop_rule | 정육 이익률이 시작 전보다 8%p 넘게 떨어지면 중단 | 숫자 + "%p"를 넣으면 판정에 그대로 쓰임 |
| status | PLANNED 또는 RUNNING | |
| is_simulated | FALSE | 사용자가 등록한 계획은 FALSE (10월 3건만 TRUE) |

저장 위치: 지금은 `data/promotion.csv`에 행을 덧붙이고, 저장 뒤 `ui.get_mart.clear()`로 캐시를 비우면 브리핑에 반영됩니다. Supabase로 옮긴 뒤에는 같은 이름의 `promotion` 테이블에 INSERT 합니다(`db/schema.sql`).

상품 단위 계획이 필요하면 `promotion`에 `target_type`, `target_value` 열을 추가하고 `promo_status`도 함께 고쳐야 합니다. 이 경우 미리 상의해 주세요(브리핑과 같이 바뀜).

## 5. 쓸 수 있는 코드

| 파일 | 내용 | 그대로 쓰기 |
|---|---|---|
| `engine/simulation.py` | 정책 재계산(가격·쿠폰·배송·혜택·묶음·노출). `prepare(m, start, end, scope, costs)` → `simulate(prepared, config)` → `comparison(result)`. 주문 반응은 `order_change_pct` 하나 | 가능. 몬테카를로는 `order_change_pct`를 범위에서 뽑아 `simulate`를 여러 번 돌리거나, 결과가 선형이면 식으로 바로 계산 |
| `engine/briefing.py` | `ledger(m)`: 이익 장부(주문·주문 상품), `promo_status(m, day)`: 프로모션 판정 | 가능 |
| `engine/data.py` | `build_all()`: 원본 표 + 세션·주문·주문 상품 마트. `m["raw"]["promotion"]` | 가능 |
| `engine/ui.py` | `get_mart()`(캐시), `won()`, 색 | 가능 |
| `engine/data.py` `as_of(m, today)` | 기준일(오늘) 이전 데이터만 남긴 마트. AI 분석가가 미래 데이터를 보지 않게 쓰는 것과 같은 함수 | 권장. Growth Lab 계산도 기준일 이전 데이터로 |

새로 만들어야 하는 것: 본전 계산, 이익 확률(몬테카를로), 확인 기간 계산. `engine/growth.py` 같은 새 파일에 계산을 두고, `views/growth_lab.py`는 표시만 하는 구조를 권합니다(브리핑과 같은 구조).

확인 기간 계산 참고: 브리핑의 판정은 "대상 카테고리 일 매출 비중"을 일 단위로 비교합니다. 같은 지표의 일별 흔들림(표준편차)으로 필요한 일수를 계산하면 판정 방식과 맞습니다.

## 6. 시작 순서 (제안)

1. `run.bat`으로 앱을 띄우고, 아침 브리핑에서 기준일 10/22 → 금일 확인 사항의 "Growth Lab 결과 보기"를 눌러 요청이 넘어오는 것을 확인합니다.
2. 3-1(프로모션 결과 보기)부터 만듭니다. 계산은 `promo_status`가 이미 하므로 화면만 만들면 됩니다.
3. `engine/growth.py`에 본전·이익 확률·확인 기간 계산을 만들고 테스트합니다.
4. 3-2(챗봇에서 오는 계획) 화면을 만듭니다. 챗봇에서 실제 요청을 보내 시험할 수 있습니다.
5. 실행 계획 등록 → `data/promotion.csv` 저장 → 브리핑 반영을 확인합니다.

## 7. 파일 담당

- Growth Lab 담당: `views/growth_lab.py`, `engine/growth.py`(새 파일)
- 같이 쓰는 파일(고칠 때 알려 주기): `engine/briefing.py`, `engine/data.py`, `data/*.csv`, `db/schema.sql`, `app.py`
- 챗봇 담당: `views/chat.py`, 챗봇 관련 `engine/` 파일

## 8. 실행·데이터 정보

- 실행: `dashboard_v2/run.bat` (dashboard_test/.venv 사용)
- 데이터: `dashboard_v2/data/` 4/1~10/31 가상 데이터. 10월은 이어 붙인 데이터이고 10월 프로모션 3건(PR001~003)은 모의입니다. 자세한 내용은 `dashboard_v2/README.md`.

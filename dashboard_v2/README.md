# ver.2 (2026-11-21 시작)

설계 결정은 프로젝트 문서 `claude/재설계_2026-11-21.md`를 따릅니다.

## 폴더
- `data/` : 앱이 읽는 CSV 14개. 파일 이름 = DB 테이블 이름. 4~9월은 원본(`ecommerce_generation_blueprint/data/generated/v2`)과 행 단위로 같고, 10월이 이어 붙어 있습니다.
- `pipeline/extend_october.py` : 10월 데이터를 만드는 스크립트
- `db/schema.sql`, `db/upload_to_supabase.py` : Supabase로 옮길 때 사용

## 10월 데이터 다시 만들기
```
cd BAAI경영시뮬레이션
python dashboard_v2/pipeline/extend_october.py --gen ecommerce_generation_blueprint --src ecommerce_generation_blueprint/data/generated/v2 --out dashboard_v2/data
```
필요 패키지: numpy, pandas, scipy, pyyaml

## 10월 데이터에 대해 알아 둘 것
- 9/30 상태(등급, 월별 구매액, 마지막 방문, 탈퇴)를 원본 CSV에서 이어받고, 10월은 별도 난수로 시뮬레이션했습니다.
- 10월 신규 가입자는 없습니다(기존 고객 10,000명만 활동).
- `promotion.csv`의 프로모션 3건은 **모의**입니다. 효과는 데이터에 심은 것이며 실제 효과의 근거가 아닙니다.
- 원본에서 바뀐 칸: 고객 현재 등급·상태(10/31 기준), 등급 이력·가격 이력의 열린 구간 종료일, 상시 쿠폰 4개 종료일(11/1), 테마 종료일(10/31)

## Supabase로 옮기기
1. Supabase 새 프로젝트 → Database 연결 문자열(URI) 복사
2. `set DATABASE_URL=<연결 문자열>` (Windows) 후 `python dashboard_v2/db/upload_to_supabase.py`

## 화면 구성 (2026-11-21)
- 기준일: 2026-10-26(월) 아침 고정, 데이터는 10/25까지(`engine/data.py` TODAY)
- 왼쪽 메뉴: 아침 브리핑 / 분석 4화면(ver.1에서 가져옴: 통합 현황, 상품·큐레이션, 고객 여정·전환, 고객·리텐션) / Growth Lab(임시본, 팀원이 개편)
- 오른쪽: AI 분석가 패널(`engine/chat_panel.py`). 답변의 분석은 왼쪽에 질문 대시보드로 띄움(`engine/popup.py`). 지금 보는 화면의 요약을 함께 받아 답함

## 실행
- PC: `run.bat` 더블클릭 (dashboard_test/.venv 사용). AI 키는 `.streamlit/secrets.toml`의 OPENAI_API_KEY
- 데이터: 기본은 `data/` 폴더의 CSV. 저장소에는 올리지 않습니다(공개 저장소).

## Streamlit Cloud 배포
- Main file path: `dashboard_v2/app.py` (requirements는 `dashboard_v2/requirements.txt`를 씀)
- Secrets: `OPENAI_API_KEY`, `DATA_BACKEND = "db"`, DB 접속 정보(`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` 또는 `DATABASE_URL`)
- DB에 10월 데이터와 `promotion` 테이블이 있어야 10월 화면이 나옵니다(`db/sync_to_db.py`). `promotion` 테이블이 없으면 프로모션 점검만 비어 보입니다.


## Growth Lab 개편 (2026-11-22)

- 앱 경로: `dashboard_v2/app.py` → 왼쪽 **실행 → Growth Lab**
- **새 프로모션 분석**: 카테고리 1개 + ① 판매가 할인율(%) ② 쿠폰 할인율(%) 또는 주문당 할인액(원) ③ 무료배송 기준금액(원) 중 1개를 직접 입력합니다. 추가혜택·묶음 할인은 이 화면에서 제외했습니다.
- **무료배송 정책**: 주문 전체가 아니라 **선택한 카테고리의 쿠폰 차감 후 상품금액**만 변경된 기준금액과 비교합니다. 예: 정육 15,000원 + 과일 5,000원은 정육 기준 20,000원을 충족하지 않습니다. 기존에 무료배송이었던 주문은 그대로 유지합니다.
- **쿠폰 정책**: 선택 카테고리 상품금액에 주문당 한 번 적용하며, 기존 해당 카테고리 쿠폰 할인은 교체해 중복 적용하지 않습니다. 정액 할인은 대상 상품금액이 상한입니다. 다른 카테고리의 기존 할인은 유지합니다.
- **판매가 할인**: 선택 카테고리 상품의 판매가격에만 적용하며 기존 해당 카테고리 쿠폰 할인과 중복되지 않습니다.
- **시뮬레이션**: 주문 반응 기본 삼각분포(−5%, 가장 가능성 높은 값 +10%, +30%), 최근 56일 일별 매출·이익의 짝지은 재표본화, 20,000회. 예상 매출·이익률 중앙값(10~90백분위수 범위), 효과 확인 기간, 28일 기준 본전 주문 증가율, 이익 증가 확률을 표시합니다.
- **매출 KPI 범위**: **선택한 카테고리가 포함된 완료 주문 전체의 결제매출(다른 카테고리 상품 포함)**입니다. 판매 정책만 선택 카테고리 상품에 적용합니다. 이익률도 같은 주문 전체 범위입니다.
- 주문 반응은 AI 예측이 아닙니다. 매출·이익률은 이 가정의 **조건부 시나리오**이지 미래 확정 예측이 아닙니다. 이익은 주문당 배송 원가 3,000원을 반영하고 기타 비용은 제외합니다.
- **등록된 프로모션**: 아침 브리핑에서 `{"type":"lab","promotion_id":"PR003"}`를 전달하면 해당 결과로 이동합니다. 이전에 저장한 계획 또는 시작 전인 계획도 목록에서 확인 가능합니다.
- 실행 계획 등록은 `promotion` 행 추가이며, 실제 쇼핑몰에 할인/쿠폰을 발행하지 않습니다. 앱의 기준일은 **2026-10-26 아침으로 고정**되어 있으므로 시작일이 그 이후인 계획은 *등록 목록*에 표시되지만, 이후 실적을 확보하거나 기준일을 이동시키기 전에는 브리핑 실적 판정에 나타나지 않습니다.
- 이번 개편은 **챗봇 → Growth Lab 자동 이동을 다루지 않습니다**. Growth Lab 자체 분석 및 아침 브리핑 → 등록 프로모션 결과 흐름만 대상으로 했습니다.

### Supabase 데이터베이스 사용 시 필수 스키마 갱신

기존에 `promotion` 테이블을 만든 DB에서는 **`db/schema.sql` 하단의 `ALTER TABLE promotion ADD COLUMN IF NOT EXISTS ...` 6개 문장**을 SQL Editor에서 한 번 실행해 주세요. 정액 쿠폰 금액/할인 방식/배송 기준금액/주문 반응 가정을 보존하기 위한 신규 열입니다. DB에 쓰기 권한이 없는 `dashboard_reader` 계정으로는 등록이 실패하므로, 별도의 INSERT 권한이 있는 운영 계정이 필요합니다. 연결된 DB를 자동 변경하지 않습니다.

로컬 CSV 모드에서는 `data/promotion.csv`에 열을 자동으로 추가하지만, Streamlit Cloud의 로컬 파일은 재배포·재시작 시 보존되지 않을 수 있습니다. **계획을 지속 저장하려면 DB 모드**를 사용하세요.

### 검증

```bash
cd dashboard_v2
python -m unittest discover -s tests -p 'test_growth_policy.py'
streamlit run app.py
```

테스트 파일 `tests/test_growth_policy.py`는 혼합 장바구니의 카테고리 단독 무료배송 판정, 주문당 정액 쿠폰, 카테고리 정률 쿠폰, 기존 쿠폰 중복 방지, 본전 계산을 확인합니다.

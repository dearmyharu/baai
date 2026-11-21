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

## 실행
- PC: `run.bat` 더블클릭 (dashboard_test/.venv 사용). AI 키는 `.streamlit/secrets.toml`의 OPENAI_API_KEY
- 데이터: 기본은 `data/` 폴더의 CSV. 저장소에는 올리지 않습니다(공개 저장소).

## Streamlit Cloud 배포
- Main file path: `dashboard_v2/app.py` (requirements는 `dashboard_v2/requirements.txt`를 씀)
- Secrets: `OPENAI_API_KEY`, `DATA_BACKEND = "db"`, DB 접속 정보(`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` 또는 `DATABASE_URL`)
- DB에 10월 데이터와 `promotion` 테이블이 있어야 10월 화면이 나옵니다(`db/sync_to_db.py`). `promotion` 테이블이 없으면 프로모션 점검만 비어 보입니다.

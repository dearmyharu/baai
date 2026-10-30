"""DB 점검: 대시보드가 쓰는 13개 테이블이 DB에 제대로 있는지 확인한다.

실행 (dashboard 폴더에서):
    ..\\dashboard_test\\.venv\\Scripts\\python.exe check_db.py
또는 check_db.bat 더블클릭
"""
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.data import DEFAULT_DATA_DIR, TABLES  # noqa: E402
from core.db import get_engine, has_db_config  # noqa: E402

OK, NG = "[OK]", "[확인 필요]"


def main():
    if not has_db_config():
        print(f"{NG} DB 접속 정보가 없습니다. dashboard/.env 또는 dashboard_test/.env 를 확인하세요.")
        return 1
    eng = get_engine()
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        print(f"{OK} DB 연결 성공")
    except Exception as e:
        print(f"{NG} DB 연결 실패: {e}")
        return 1

    insp = inspect(eng)
    schema = "public" if eng.dialect.name == "postgresql" else None
    existing = set(insp.get_table_names(schema=schema))
    data_dir = Path(os.getenv("DATA_DIR") or DEFAULT_DATA_DIR)
    problems = 0
    print("\n테이블                          DB 행 수    CSV 행 수   컬럼")
    for t in TABLES:
        csv = data_dir / f"{t}.csv"
        csv_cols = list(pd.read_csv(csv, nrows=0, encoding="utf-8-sig").columns) if csv.exists() else None
        csv_n = sum(1 for _ in open(csv, encoding="utf-8-sig")) - 1 if csv.exists() else None
        if t not in existing:
            print(f"{NG} {t:<28} 테이블 없음")
            problems += 1
            continue
        with eng.connect() as c:
            n = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        db_cols = [col["name"] for col in insp.get_columns(t, schema=schema)]
        missing = [x for x in (csv_cols or []) if x not in db_cols]
        same_n = csv_n is None or n == csv_n
        mark = OK if (same_n and not missing) else NG
        problems += mark == NG
        col_msg = "일치" if not missing else f"없는 컬럼: {', '.join(missing)}"
        print(f"{mark} {t:<28} {n:>10,}  {('-' if csv_n is None else f'{csv_n:,}'):>10}   {col_msg}")

    print("\n대시보드 계산 점검 (DB 데이터로 실제 계산)")
    os.environ["DATA_BACKEND"] = "db"
    from core.data import build_all
    m = build_all()
    comp = m["orders"][m["orders"]["order_status"].eq("COMPLETED")]
    rev, cnt = int(comp["total_amount"].sum()), len(comp)
    print(f"{OK if cnt == 18529 else NG} 완료 주문 {cnt:,}건 (KPI 정의서 기준 18,529)")
    print(f"{OK if rev == 526717597 else NG} 완료 매출 {rev:,}원 (KPI 정의서 기준 526,717,597)")
    problems += (cnt != 18529) + (rev != 526717597)

    try:
        with eng.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS growth_lab_problems (id TEXT PRIMARY KEY, title TEXT, status TEXT, "
                           "data TEXT, created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT)"))
        print(f"{OK} Growth Lab 저장 테이블(growth_lab_problems) 준비 완료")
    except Exception as e:
        print(f"{NG} Growth Lab 테이블을 만들 수 없습니다 (권한 확인 필요): {e}")
        problems += 1

    print("\n결과:", "모두 정상입니다. 배포해도 됩니다." if not problems else f"확인이 필요한 항목 {problems}개")
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())

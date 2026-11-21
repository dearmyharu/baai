"""data/*.csv 를 Supabase(PostgreSQL)에 올린다.

준비: 환경변수 DATABASE_URL (Supabase > Project Settings > Database > Connection string, URI)
실행: python db/upload_to_supabase.py            # 테이블 만들고 비어 있으면 올림
      python db/upload_to_supabase.py --replace  # 기존 행을 지우고 다시 올림
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["customer", "customer_initial_snapshot", "customer_prior_monthly_sales", "customer_grade_history",
         "product", "product_price_history", "curation_theme", "curation_product", "coupon",
         "orders", "order_items", "order_coupon", "event_log", "promotion"]
BOOL_COLS = {"customer": ["marketing_consent"], "promotion": ["is_simulated"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    url = os.environ["DATABASE_URL"]
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text((ROOT / "db/schema.sql").read_text(encoding="utf-8")))
        if a.replace:
            for t in reversed(ORDER):
                c.execute(text(f"DELETE FROM {t}"))
    for t in ORDER:
        with eng.connect() as c:
            n = c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        if n:
            print(f"{t}: 이미 {n}행 있음 → 건너뜀 (--replace로 다시 올리기)")
            continue
        df = pd.read_csv(ROOT / "data" / f"{t}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False)
        df = df.replace("", None)
        for col in BOOL_COLS.get(t, []):
            df[col] = df[col].map({"TRUE": True, "FALSE": False})
        df.to_sql(t, eng, if_exists="append", index=False, chunksize=5000, method="multi")
        print(f"{t}: {len(df)}행 업로드")


if __name__ == "__main__":
    main()

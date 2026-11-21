"""DB에 이미 있는 4~9월 데이터는 두고, data/*.csv와 다른 부분만 맞춘다(10월 추가용).

- 없는 행: 넣는다 (10월 주문·이벤트·등급 이력·가격 이력 등)
- 바뀐 칸: 고친다 (고객 현재 등급·상태, 열린 구간 종료일, 쿠폰·테마 종료일)
- promotion 테이블: 없으면 만들고 행을 맞춘다
- 지우는 것은 없다.

실행: python db/sync_to_db.py            # 무엇을 바꿀지 보여 주기만 함
      python db/sync_to_db.py --apply    # 실제 반영
      python db/sync_to_db.py --export db/to_upload   # 넣을 행 CSV + 고칠 SQL 파일만 만듦(DB는 그대로)
접속: dashboard_v2/.env 의 DATABASE_URL
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parents[1]
KEYS = {
    "customer": ["customer_id"], "customer_initial_snapshot": ["customer_id"],
    "customer_prior_monthly_sales": ["customer_id", "sales_month"], "customer_grade_history": ["grade_history_id"],
    "product": ["product_id"], "product_price_history": ["price_history_id"], "curation_theme": ["theme_id"],
    "curation_product": ["theme_id", "product_id"], "coupon": ["coupon_id"], "orders": ["order_id"],
    "order_items": ["order_item_id"], "order_coupon": ["order_coupon_id"], "event_log": ["event_id"],
    "promotion": ["promotion_id"],
}
UPDATE_COLS = {
    "customer": ["membership_grade", "account_status"],
    "customer_grade_history": ["effective_to"],
    "product_price_history": ["effective_to"],
    "coupon": ["end_date"],
    "curation_theme": ["end_date"],
    "promotion": ["promotion_name", "category", "lever", "discount_pct", "start_date", "end_date",
                  "primary_metric", "guard_metric", "stop_rule", "status", "is_simulated"],
}
PROMOTION_DDL = """CREATE TABLE IF NOT EXISTS public.promotion (
    promotion_id text PRIMARY KEY, promotion_name text, category text, lever text, discount_pct numeric,
    start_date date, end_date date, primary_metric text, guard_metric text, stop_rule text, status text,
    is_simulated boolean)"""


def db_url() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(".env에 DATABASE_URL이 없습니다.")


def conv(v: str, typ: str):
    """CSV 글자 → DB 열 형식에 맞는 값. 빈 칸은 NULL."""
    if v == "":
        return None
    if typ in ("integer", "smallint", "bigint"):
        return int(float(v))
    if typ in ("numeric", "double precision", "real"):
        return float(v)
    if typ == "boolean":
        return v.upper() in ("TRUE", "1", "T")
    return v


def norm(v) -> str:
    """DB 값과 CSV 글자를 같은 모양으로 비교하기 위한 문자열."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "hour") else v.strftime("%Y-%m-%d")
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v)
    return s[:-2] if s.endswith(".0") else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--export", default=None, help="넣을 행 CSV와 고칠 SQL을 이 폴더에 저장")
    a = ap.parse_args()
    exp = Path(a.export) if a.export else None
    sql_lines = []
    if exp:
        exp.mkdir(parents=True, exist_ok=True)
    con = psycopg2.connect(db_url(), connect_timeout=15)
    cur = con.cursor()
    if a.apply:
        cur.execute(PROMOTION_DDL)
    for t, key in KEYS.items():
        df = pd.read_csv(ROOT / "data" / f"{t}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False)
        cur.execute("select column_name, data_type from information_schema.columns "
                    "where table_schema='public' and table_name=%s order by ordinal_position", (t,))
        types = dict(cur.fetchall())
        if not types:
            if t == "promotion" and not a.apply:
                print(f"{t}: 테이블 없음 → 만들고 {len(df)}행 넣을 예정")
                if exp:
                    sql_lines.append(PROMOTION_DDL + ";")
                    for _, r in df.iterrows():
                        vals = ", ".join(_lit(r[c]) for c in df.columns)
                        sql_lines.append(f"insert into public.promotion ({', '.join(df.columns)}) values ({vals});")
                    sql_lines.append('alter table public.promotion enable row level security;')
                    sql_lines.append('create policy "dashboard_reader can read" on public.promotion for select to dashboard_reader using (true);')
                    sql_lines.append('grant select on public.promotion to dashboard_reader;')
                continue
            raise SystemExit(f"DB에 {t} 테이블이 없습니다.")
        cols = [c for c in df.columns if c in types]
        upd = [c for c in UPDATE_COLS.get(t, []) if c in cols]
        cur.execute(f"select {', '.join(key + upd)} from public.{t}")
        have = {tuple(norm(v) for v in r[:len(key)]): [norm(v) for v in r[len(key):]] for r in cur.fetchall()}
        k = df[key].astype(str).agg(tuple, axis=1) if len(key) > 1 else df[key[0]].map(lambda x: (x,))
        if t == "customer_prior_monthly_sales":
            k = k.map(lambda x: (x[0], x[1][:10]))
        new = df[~k.isin(have.keys())]
        old = df[k.isin(have.keys())]
        changed = []
        if upd:
            for kk, (_, r) in zip(k[k.isin(have.keys())], old.iterrows()):
                cur_vals = have[kk]
                csv_vals = [norm(r[c]) for c in upd]
                if cur_vals != csv_vals:
                    changed.append(r)
        print(f"{t}: DB {len(have):,}행 · CSV {len(df):,}행 → 넣기 {len(new):,} · 고치기 {len(changed):,}")
        if exp:
            if len(new):
                new[cols].to_csv(exp / f"{t}.csv", index=False, encoding="utf-8")
            for r in changed:
                sets = ", ".join(f"{c} = {_lit(r[c])}" for c in upd)
                where = " and ".join(f"{c} = {_lit(r[c])}" for c in key)
                sql_lines.append(f"update public.{t} set {sets} where {where};")
        if not a.apply:
            continue
        if len(new):
            rows = [tuple(conv(r[c], types[c]) for c in cols) for _, r in new.iterrows()]
            execute_values(cur, f"insert into public.{t} ({', '.join(cols)}) values %s", rows, page_size=2000)
        for r in changed:
            sets = ", ".join(f"{c} = %s" for c in upd)
            where = " and ".join(f"{c} = %s" for c in key)
            cur.execute(f"update public.{t} set {sets} where {where}",
                        [conv(r[c], types[c]) for c in upd] + [conv(r[c], types[c]) for c in key])
        con.commit()
    if a.apply:
        print("반영 완료")
    if exp:
        (exp / "2_update.sql").write_text("begin;\n" + "\n".join(sql_lines) + "\ncommit;\n", encoding="utf-8")
        print(f"저장: {exp}")
    con.close()


def _lit(v: str) -> str:
    return "null" if v == "" else "'" + str(v).replace("'", "''") + "'"


if __name__ == "__main__":
    main()

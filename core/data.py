"""데이터 계층.

지금은 폴더 안의 CSV(ecommerce_generation_blueprint/data/generated/v2)를 읽는다.
나중에 DB(Supabase)를 붙일 때는 .env 에 DATA_BACKEND=db 만 넣으면
같은 테이블 이름으로 DB에서 읽고, 나머지 화면 코드는 바꿀 필요가 없다.

계산 규칙은 KPI 정의서 공식 v2 를 따른다.
- 퍼널·전환율: DISTINCT session 기준
- 주문 금액: orders 헤더 기준 (order_items 조인 후 합산 금지)
- 주문 → 경로·테마: purchase 이벤트 1:1 귀속
- 신규 방문 / 신규 가입 / 첫 구매는 서로 다른 개념
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]          # BAAI경영시뮬레이션 폴더
DEFAULT_DATA_DIR = ROOT / "ecommerce_generation_blueprint" / "data" / "generated" / "v2"

PERIOD_START = pd.Timestamp("2026-04-01")
PERIOD_END = pd.Timestamp("2026-10-01")             # 미포함
AS_OF = pd.Timestamp("2026-09-30 23:59:59")

TABLES = [
    "customer", "customer_initial_snapshot", "customer_prior_monthly_sales",
    "customer_grade_history", "product", "product_price_history",
    "curation_theme", "curation_product", "coupon",
    "orders", "order_items", "order_coupon", "event_log",
]

DATETIME_COLS = {
    "orders": ["order_time"],
    "event_log": ["event_time"],
    "customer_grade_history": ["effective_from", "effective_to"],
    "customer": ["signup_date"],
    "customer_initial_snapshot": ["first_purchase_date", "last_purchase_date", "last_visit_date"],
}

ENTRY_LABEL = {"CURATION": "큐레이션 경유", "BROWSE": "일반 탐색"}
VISITOR_LABEL = {"NEW": "신규 방문", "RETURNING": "재방문", "UNKNOWN": "판정 불가"}


def _load_env():
    from .db import load_env
    load_env()


def backend_name() -> str:
    _load_env()
    return os.getenv("DATA_BACKEND", "csv").lower()


def _read_csv_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for t in TABLES:
        out[t] = pd.read_csv(data_dir / f"{t}.csv", encoding="utf-8-sig", low_memory=False)
    return out


def _read_db_tables() -> dict[str, pd.DataFrame]:
    from .db import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        return {t: pd.read_sql(f"SELECT * FROM {t}", conn) for t in TABLES}


def load_raw(data_dir: str | os.PathLike | None = None) -> dict[str, pd.DataFrame]:
    if backend_name() == "db":
        raw = _read_db_tables()
    else:
        _load_env()
        d = Path(data_dir or os.getenv("DATA_DIR") or DEFAULT_DATA_DIR)
        raw = _read_csv_tables(d)
    for t, cols in DATETIME_COLS.items():
        for c in cols:
            col = pd.to_datetime(raw[t][c], errors="coerce")
            if getattr(col.dt, "tz", None) is not None:      # DB의 timestamptz → 한국시간 기준 naive
                col = col.dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
            raw[t][c] = col
    for t, df in raw.items():                                  # DB numeric(Decimal) → float
        for c in df.columns:
            if df[c].dtype == object:
                first = df[c].dropna().head(1)
                if len(first) and isinstance(first.iloc[0], Decimal):
                    df[c] = pd.to_numeric(df[c], errors="coerce")
    return raw


# ---------------------------------------------------------------------------
# 마트 만들기
# ---------------------------------------------------------------------------
def _daypart(h: pd.Series) -> pd.Series:
    bins = [-1, 5, 10, 13, 17, 21, 23]
    labels = ["심야(0-5시)", "아침(6-10시)", "점심(11-13시)", "오후(14-17시)", "저녁(18-21시)", "밤(22-23시)"]
    return pd.cut(h, bins=bins, labels=labels).astype(str)


def build_sessions(raw: dict) -> pd.DataFrame:
    e = raw["event_log"].sort_values(["event_time", "event_id"])
    g = e.groupby("session_id", sort=False)
    s = g.agg(customer_id=("customer_id", "first"), start=("event_time", "min"),
              end=("event_time", "max"), entry=("event_type", "first"),
              theme_id=("theme_id", "first"), n_events=("event_id", "size"))
    cnt = pd.crosstab(e["session_id"], e["event_type"])
    for col in ["theme_impression", "theme_click", "product_click", "add_to_cart", "purchase", "search", "category_view"]:
        s[f"n_{col}"] = cnt[col].reindex(s.index).fillna(0).astype(int) if col in cnt else 0
    s["path"] = np.select([s["entry"].eq("theme_impression"), s["entry"].isin(["search", "category_view"])],
                          ["CURATION", "BROWSE"], "INVALID")
    s["has_theme_click"] = s["n_theme_click"] > 0
    s["has_product_click"] = s["n_product_click"] > 0
    s["has_cart"] = s["n_add_to_cart"] > 0
    s["has_purchase"] = s["n_purchase"] > 0

    pur = e[e["event_type"].eq("purchase")].drop_duplicates("session_id").set_index("session_id")["order_id"]
    s["order_id"] = pur.reindex(s.index)
    first_click = e[e["event_type"].eq("product_click")].drop_duplicates("session_id").set_index("session_id")["product_id"]
    s["first_product_id"] = first_click.reindex(s.index)
    cat = raw["product"].set_index("product_id")["category"]
    s["first_category"] = s["first_product_id"].map(cat)

    orders = raw["orders"].set_index("order_id")
    s["order_status"] = s["order_id"].map(orders["order_status"])
    s["order_total"] = s["order_id"].map(orders["total_amount"])
    s["has_completed"] = s["order_status"].eq("COMPLETED")

    # 신규 방문 / 재방문 (세션 단위, KPI 정의서 §6.2)
    cust = raw["customer"].set_index("customer_id")
    snap = raw["customer_initial_snapshot"].set_index("customer_id")
    s = s.reset_index().sort_values(["customer_id", "start", "session_id"])
    signup = s["customer_id"].map(cust["signup_date"])
    prior_visit = s["customer_id"].map(snap["prior_visit_count"])
    prior_visit = prior_visit.where(signup < PERIOD_START, 0)      # 4/1 이후 가입자는 0
    obs_prev = s.groupby("customer_id").cumcount()
    visit_index = prior_visit + obs_prev
    s["visitor_type"] = np.where(visit_index.isna(), "UNKNOWN", np.where(visit_index.eq(0), "NEW", "RETURNING"))
    s["is_new_signup"] = (signup >= PERIOD_START).values

    s["date"] = s["start"].dt.normalize()
    s["week"] = s["start"].dt.to_period("W-SUN").dt.start_time
    s["month"] = s["start"].dt.to_period("M").dt.start_time
    s["hour"] = s["start"].dt.hour
    s["daypart"] = _daypart(s["hour"])
    s["is_weekend"] = s["start"].dt.dayofweek >= 5
    s["day_type"] = np.where(s["is_weekend"], "주말", "평일")
    themes = raw["curation_theme"].set_index("theme_id")["theme_name"]
    s["theme_name"] = s["theme_id"].map(themes)
    return s.sort_values("start").reset_index(drop=True)


def build_orders(raw: dict, sessions: pd.DataFrame) -> pd.DataFrame:
    o = raw["orders"].copy()
    link = sessions.dropna(subset=["order_id"]).set_index("order_id")
    o["session_id"] = o["order_id"].map(link["session_id"])
    o["path"] = o["order_id"].map(link["path"])
    o["attributed_theme_id"] = o["order_id"].map(link["theme_id"])
    o["visitor_type"] = o["order_id"].map(link["visitor_type"])
    themes = raw["curation_theme"].set_index("theme_id")["theme_name"]
    o["theme_name"] = o["attributed_theme_id"].map(themes)

    oc = raw["order_coupon"].drop_duplicates("order_id").set_index("order_id")["coupon_id"]
    o["coupon_id"] = o["order_id"].map(oc).fillna("NO_COUPON")
    o["has_coupon"] = o["coupon_id"].ne("NO_COUPON")

    # 주문 당시 등급 (as-of join)
    gh = raw["customer_grade_history"].sort_values("effective_from")
    o = o.sort_values("order_time")
    o = pd.merge_asof(o, gh[["customer_id", "effective_from", "effective_to", "membership_grade"]],
                      left_on="order_time", right_on="effective_from", by="customer_id", direction="backward")
    valid = o["effective_to"].isna() | (o["order_time"] < o["effective_to"])
    o["grade_at_order"] = o["membership_grade"].where(valid)
    o = o.drop(columns=["effective_from", "effective_to", "membership_grade"])

    # 첫 구매 판정 (KPI 정의서 §5.5)
    cust = raw["customer"].set_index("customer_id")
    snap = raw["customer_initial_snapshot"].set_index("customer_id")
    signup = o["customer_id"].map(cust["signup_date"])
    prior = o["customer_id"].map(snap["prior_order_count"])
    prior = prior.where(signup < PERIOD_START, 0)
    o["is_new_signup"] = signup >= PERIOD_START
    comp = o["order_status"].eq("COMPLETED")
    o["completed_seq"] = np.nan
    o.loc[comp, "completed_seq"] = o[comp].groupby("customer_id").cumcount() + 1
    o["is_first_purchase"] = np.where(prior.isna(), np.nan,
                                      (comp & prior.eq(0) & o["completed_seq"].eq(1)).astype(float))
    o["customer_type"] = np.where(prior.fillna(1).gt(0) | o["completed_seq"].gt(1), "기존 구매 고객", "첫 구매 고객")
    o.loc[~comp, "customer_type"] = np.nan

    o["date"] = o["order_time"].dt.normalize()
    o["week"] = o["order_time"].dt.to_period("W-SUN").dt.start_time
    o["month"] = o["order_time"].dt.to_period("M").dt.start_time
    return o.reset_index(drop=True)


def build_items(raw: dict, orders: pd.DataFrame) -> pd.DataFrame:
    it = raw["order_items"].merge(raw["product"][["product_id", "product_name", "brand", "category", "cost_price"]],
                                  on="product_id", how="left")
    cols = ["order_id", "customer_id", "order_time", "order_status", "path", "attributed_theme_id",
            "theme_name", "visitor_type", "customer_type", "date", "week", "month"]
    it = it.merge(orders[cols], on="order_id", how="left")
    it["net_sales"] = it["sales_amount"] - it["allocated_coupon_discount"]
    it["contribution"] = it["net_sales"] - it["quantity"] * it["cost_price"]
    return it


def build_all(data_dir=None) -> dict:
    raw = load_raw(data_dir)
    sessions = build_sessions(raw)
    orders = build_orders(raw, sessions)
    items = build_items(raw, orders)
    return {"raw": raw, "sessions": sessions, "orders": orders, "items": items}

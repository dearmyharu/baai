"""공통 계산 엔진. 화면과 (나중에) AI 챗봇이 같은 함수로 숫자를 만든다."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .data import PERIOD_START

MIN_SAMPLE = 30


# ---------------------------------------------------------------------------
# 기간
# ---------------------------------------------------------------------------
def in_period(df: pd.DataFrame, col: str, start, end) -> pd.DataFrame:
    return df[(df[col] >= start) & (df[col] < end)]


def previous_period(start: pd.Timestamp, end: pd.Timestamp):
    """같은 길이의 직전 기간. 상세 데이터(4/1) 이전이면 None."""
    length = end - start
    p_start, p_end = start - length, start
    if p_start < PERIOD_START:
        return None
    return p_start, p_end


# ---------------------------------------------------------------------------
# 통계 도우미
# ---------------------------------------------------------------------------
def safe_div(a, b):
    return np.nan if not b else a / b


def pct_change(cur, prev):
    if prev is None or prev == 0 or pd.isna(prev) or pd.isna(cur):
        return np.nan
    return (cur - prev) / prev


def two_prop_test(x1, n1, x2, n2):
    """두 비율 차이의 양측 z-검정 p값 (scipy 없이)."""
    if min(n1, n2) == 0:
        return np.nan, np.nan
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def sample_size_per_group(p0: float, mde_rel: float, alpha=0.05, power=0.8) -> float:
    """두 비율 비교 A/B 테스트의 그룹당 필요 표본 (정규근사)."""
    p1 = p0 * (1 + mde_rel)
    if not (0 < p0 < 1 and 0 < p1 < 1) or p0 == p1:
        return np.nan
    z_a = _norm_ppf(1 - alpha / 2)
    z_b = _norm_ppf(power)
    pbar = (p0 + p1) / 2
    n = (z_a * math.sqrt(2 * pbar * (1 - pbar)) + z_b * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / (p1 - p0) ** 2
    return math.ceil(n)


def _norm_ppf(q: float) -> float:
    # Acklam 근사
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    if q < plow:
        r = math.sqrt(-2 * math.log(q))
        return (((((c[0]*r+c[1])*r+c[2])*r+c[3])*r+c[4])*r+c[5]) / ((((d[0]*r+d[1])*r+d[2])*r+d[3])*r+1)
    if q > 1 - plow:
        return -_norm_ppf(1 - q)
    r = q - 0.5
    t = r * r
    return (((((a[0]*t+a[1])*t+a[2])*t+a[3])*t+a[4])*t+a[5])*r / (((((b[0]*t+b[1])*t+b[2])*t+b[3])*t+b[4])*t+1)


# ---------------------------------------------------------------------------
# 핵심 KPI
# ---------------------------------------------------------------------------
def kpis(m: dict, start, end) -> dict:
    o = in_period(m["orders"], "order_time", start, end)
    s = in_period(m["sessions"], "start", start, end)
    comp = o[o["order_status"].eq("COMPLETED")]
    per_buyer = comp.groupby("customer_id").size()
    revenue = comp["total_amount"].sum()
    n_orders = comp["order_id"].nunique()
    buyers = comp["customer_id"].nunique()
    n_sessions = len(s)
    n_purchase = int(s["has_purchase"].sum())
    return {
        "revenue": revenue,
        "orders": n_orders,
        "buyers": buyers,
        "aov": safe_div(revenue, n_orders),
        "sessions": n_sessions,
        "purchase_sessions": n_purchase,
        "cvr": safe_div(n_purchase, n_sessions),
        "repeat_buyers": int((per_buyer >= 2).sum()),
        "repeat_rate": safe_div((per_buyer >= 2).sum(), buyers),
        "first_purchases": int(comp["is_first_purchase"].eq(1).sum()),
        "first_buyers_share": safe_div(comp.loc[comp["is_first_purchase"].eq(1), "customer_id"].nunique(), buyers),
        "cancel_refund_rate": safe_div(o["order_status"].ne("COMPLETED").sum(), len(o)),
        "coupon_order_share": safe_div(comp["has_coupon"].sum(), n_orders),
    }


# ---------------------------------------------------------------------------
# 퍼널
# ---------------------------------------------------------------------------
FUNNEL_STEPS = {
    "ALL": [("방문 세션", None), ("상품 클릭", "has_product_click"), ("장바구니", "has_cart"),
            ("구매", "has_purchase"), ("구매 완료", "has_completed")],
    "CURATION": [("테마 노출", None), ("테마 클릭", "has_theme_click"), ("상품 클릭", "has_product_click"),
                 ("장바구니", "has_cart"), ("구매", "has_purchase"), ("구매 완료", "has_completed")],
    "BROWSE": [("탐색 진입", None), ("상품 클릭", "has_product_click"), ("장바구니", "has_cart"),
               ("구매", "has_purchase"), ("구매 완료", "has_completed")],
}


def path_filter(s: pd.DataFrame, path: str) -> pd.DataFrame:
    return s if path == "ALL" else s[s["path"].eq(path)]


def step_masks(s: pd.DataFrame, path: str) -> list[tuple[str, pd.Series]]:
    """단계별 '직전 단계까지 모두 도달한' 세션 마스크."""
    out, mask = [], pd.Series(True, index=s.index)
    for label, flag in FUNNEL_STEPS[path]:
        if flag is not None:
            mask = mask & s[flag]
        out.append((label, mask.copy()))
    return out


def funnel(s: pd.DataFrame, path: str) -> pd.DataFrame:
    s = path_filter(s, path)
    rows, top, prev = [], None, None
    for label, mask in step_masks(s, path):
        n = int(mask.sum())
        top = n if top is None else top
        rows.append({"단계": label, "세션 수": n,
                     "직전 단계 대비 전환율": safe_div(n, prev) if prev is not None else np.nan,
                     "첫 단계 대비": safe_div(n, top)})
        prev = n
    return pd.DataFrame(rows)


def step_rate(s: pd.DataFrame, path: str, step_idx: int, by=None):
    """step_idx-1 → step_idx 전환율. by 가 있으면 그룹별 (분자, 분모, 비율)."""
    s = path_filter(s, path)
    masks = step_masks(s, path)
    den_mask, num_mask = masks[step_idx - 1][1], masks[step_idx][1]
    df = pd.DataFrame({"den": den_mask.astype(int), "num": num_mask.astype(int)})
    if by is None:
        d, n = int(df["den"].sum()), int(df["num"].sum())
        return n, d, safe_div(n, d)
    df["grp"] = s[by].astype(str).values
    g = df.groupby("grp")[["num", "den"]].sum()
    g["rate"] = g["num"] / g["den"].replace(0, np.nan)
    return g


# ---------------------------------------------------------------------------
# 테마
# ---------------------------------------------------------------------------
def theme_table(m: dict, start, end) -> pd.DataFrame:
    s = in_period(m["sessions"], "start", start, end)
    s = s[s["path"].eq("CURATION")]
    o = in_period(m["orders"], "order_time", start, end)
    comp = o[o["order_status"].eq("COMPLETED") & o["path"].eq("CURATION")]
    g = s.groupby("theme_id").agg(
        노출세션=("session_id", "size"), 클릭세션=("has_theme_click", "sum"),
        상품클릭세션=("has_product_click", "sum"), 장바구니세션=("has_cart", "sum"),
        구매세션=("has_purchase", "sum"))
    r = comp.groupby("attributed_theme_id").agg(완료주문=("order_id", "nunique"), 경유매출=("total_amount", "sum"))
    g = g.join(r).fillna({"완료주문": 0, "경유매출": 0})
    g["클릭률"] = g["클릭세션"] / g["노출세션"]
    g["상품클릭률"] = g["상품클릭세션"] / g["클릭세션"].replace(0, np.nan)
    g["장바구니율"] = g["장바구니세션"] / g["상품클릭세션"].replace(0, np.nan)
    g["장바구니→구매"] = g["구매세션"] / g["장바구니세션"].replace(0, np.nan)
    g["구매전환율"] = g["구매세션"] / g["노출세션"]
    g["객단가"] = g["경유매출"] / g["완료주문"].replace(0, np.nan)
    themes = m["raw"]["curation_theme"].set_index("theme_id")
    g.insert(0, "테마", themes["theme_name"].reindex(g.index))
    g["노출 영역"] = themes["placement"].reindex(g.index)
    return g.reset_index().rename(columns={"theme_id": "theme_id"})


# ---------------------------------------------------------------------------
# 확인할 변화 (문제 후보) 자동 탐지
# ---------------------------------------------------------------------------
def _cand(kind, title, metric, segment, cur, prev, unit, n_cur, n_prev, p, page, definition, extra=None):
    delta = cur - prev
    return {"kind": kind, "title": title, "metric": metric, "segment": segment,
            "current": cur, "previous": prev, "delta": delta, "unit": unit,
            "n_current": int(n_cur), "n_previous": int(n_prev), "p_value": p,
            "direction": "하락" if delta < 0 else "상승", "page": page,
            "definition": definition, **(extra or {})}


def detect_changes(m: dict, cur: tuple, prev: tuple, min_n: int = 100, alpha: float = 0.05,
                   min_pp: float = 0.01, min_pct: float = 0.10) -> list[dict]:
    """현재 vs 비교 기간에서 크게 달라진 지표를 찾는다. 결과는 '확정된 문제'가 아니라 확인할 후보."""
    s_c = in_period(m["sessions"], "start", *cur)
    s_p = in_period(m["sessions"], "start", *prev)
    out = []

    def rate_check(kind, title, metric, segment, nc, dc, np_, dp, page, definition, extra=None):
        if min(dc, dp) < min_n:
            return
        z, p = two_prop_test(nc, dc, np_, dp)
        rc, rp = nc / dc, np_ / dp
        if p < alpha and abs(rc - rp) >= min_pp:
            out.append(_cand(kind, title, metric, segment, rc, rp, "rate", dc, dp, p, page, definition,
                             {"z": abs(z), **(extra or {})}))

    # 1) 전체 및 경로별 퍼널 단계
    for path, path_label in [("ALL", "전체 세션"), ("CURATION", "큐레이션 경유"), ("BROWSE", "일반 탐색")]:
        steps = FUNNEL_STEPS[path]
        for i in range(1, len(steps)):
            if steps[i][0] == "구매 완료":
                continue
            nc, dc, _ = step_rate(s_c, path, i)
            np_, dp, _ = step_rate(s_p, path, i)
            name = f"{steps[i-1][0]} → {steps[i][0]}"
            rate_check("funnel", f"{path_label} {name} 전환율", name, path_label, nc, dc, np_, dp, "journey",
                       f"DISTINCT 세션 기준. {steps[i-1][0]}에 도달한 세션 중 {steps[i][0]}까지 간 비율",
                       {"path": path, "step_idx": i})

    # 2) 방문 유형 · 신규 가입 고객별 세션 구매 전환율
    for col, labels in [("visitor_type", {"NEW": "신규 방문", "RETURNING": "재방문"}),
                        ("is_new_signup", {True: "신규 가입 고객(4/1 이후)", False: "기존 가입 고객"})]:
        for val, lab in labels.items():
            a, b = s_c[s_c[col].eq(val)], s_p[s_p[col].eq(val)]
            rate_check("segment", f"{lab}의 세션 구매 전환율", "세션 구매 전환율", lab,
                       a["has_purchase"].sum(), len(a), b["has_purchase"].sum(), len(b), "journey",
                       "구매 세션 / 전체 세션 (큐레이션+일반 탐색)", {"segment_col": col, "segment_val": str(val)})

    # 3) 테마별 클릭률 · 장바구니→구매 · 구매전환율
    tc = theme_table(m, *cur).set_index("theme_id")
    tp = theme_table(m, *prev).set_index("theme_id")
    for tid in tc.index.intersection(tp.index):
        a, b, name = tc.loc[tid], tp.loc[tid], tc.loc[tid, "테마"]
        rate_check("theme", f"'{name}' 테마 클릭률", "테마 클릭률", name,
                   a["클릭세션"], a["노출세션"], b["클릭세션"], b["노출세션"], "curation",
                   "테마 클릭 세션 / 테마 노출 세션", {"theme_id": tid})
        rate_check("theme", f"'{name}' 테마 장바구니→구매 전환율", "장바구니→구매", name,
                   a["구매세션"], a["장바구니세션"], b["구매세션"], b["장바구니세션"], "curation",
                   "구매 세션 / 장바구니 세션 (해당 테마 큐레이션 세션)", {"theme_id": tid})
        rate_check("theme", f"'{name}' 테마 구매 전환율", "테마 구매 전환율", name,
                   a["구매세션"], a["노출세션"], b["구매세션"], b["노출세션"], "curation",
                   "구매 세션 / 테마 노출 세션", {"theme_id": tid})

    # 4) 카테고리 매출 (상품금액, 쿠폰 후)
    it_c = in_period(m["items"], "order_time", *cur)
    it_p = in_period(m["items"], "order_time", *prev)
    cc = it_c[it_c["order_status"].eq("COMPLETED")].groupby("category")["net_sales"].sum()
    cp = it_p[it_p["order_status"].eq("COMPLETED")].groupby("category")["net_sales"].sum()
    days_c = (cur[1] - cur[0]).days
    days_p = (prev[1] - prev[0]).days
    total = cc.sum()
    for cat in cc.index.intersection(cp.index):
        n_c = len(it_c[it_c["category"].eq(cat)])
        n_p = len(it_p[it_p["category"].eq(cat)])
        if (total and cc[cat] / total < 0.05) or min(n_c, n_p) < min_n:
            continue
        a, b = cc[cat] / days_c, cp[cat] / days_p
        ch = pct_change(a, b)
        if abs(ch) >= max(min_pct, 0.15):
            out.append(_cand("category", f"'{cat}' 카테고리 일평균 매출", "카테고리 일평균 상품매출", cat,
                             a, b, "won", n_c, n_p,
                             np.nan, "curation", "완료 주문의 쿠폰 차감 후 상품금액 ÷ 기간 일수 (배송비 제외)",
                             {"z": abs(ch) * 5, "pct": ch, "category": cat}))

    # 5) 매출 · 객단가 (일평균)
    k_c, k_p = kpis(m, *cur), kpis(m, *prev)
    for key, label, unit in [("revenue", "일평균 완료 매출", "won"), ("aov", "객단가", "won")]:
        a, b = k_c[key], k_p[key]
        if key == "revenue":
            a, b = a / days_c, b / days_p
        ch = pct_change(a, b)
        if not pd.isna(ch) and abs(ch) >= min_pct:
            out.append(_cand("kpi", label, label, "전체", a, b, unit, k_c["orders"], k_p["orders"], np.nan,
                             "overview", "COMPLETED 주문 total_amount 기준 (배송비 포함)",
                             {"z": abs(ch) * 5, "pct": ch}))

    # 통계 검정을 거친 비율 지표를 먼저, 금액 지표는 그 뒤에 변화율 순으로
    out.sort(key=lambda c: (pd.notna(c.get("p_value")), c.get("z", 0)), reverse=True)
    return out


# ---------------------------------------------------------------------------
# 쿠폰 효율 (ROAS 대신 쓰는 프로모션 효율 지표)
# ---------------------------------------------------------------------------
def coupon_efficiency(m: dict, start, end) -> dict:
    """쿠폰 효율 = 쿠폰 사용 완료 주문의 완료 매출 ÷ 쿠폰 할인액.

    '쿠폰 때문에 생긴 매출'이 아니라 '쿠폰을 쓴 주문의 매출'이다(쿠폰 없이도 샀을 고객 포함).
    반환: {"total": {...}, "by_coupon": DataFrame}
    """
    o = in_period(m["orders"], "order_time", start, end)
    comp = o[o["order_status"].eq("COMPLETED")]
    cp = comp[comp["has_coupon"]]
    nc = comp[~comp["has_coupon"]]
    discount = cp["coupon_discount_amount"].sum()
    sales = cp["total_amount"].sum()
    total = {
        "coupon_orders": int(cp["order_id"].nunique()),
        "coupon_order_share": safe_div(cp["order_id"].nunique(), comp["order_id"].nunique()),
        "discount": discount,
        "coupon_sales": sales,
        "efficiency": safe_div(sales, discount),
        "aov_coupon": safe_div(sales, cp["order_id"].nunique()),
        "aov_no_coupon": safe_div(nc["total_amount"].sum(), nc["order_id"].nunique()),
    }
    names = m["raw"]["coupon"].set_index("coupon_id")
    by = (cp.groupby("coupon_id")
          .agg(주문수=("order_id", "nunique"), 할인액=("coupon_discount_amount", "sum"),
               쿠폰주문매출=("total_amount", "sum"), 고객수=("customer_id", "nunique"))
          .reset_index())
    by["쿠폰"] = by["coupon_id"].map(names["coupon_name"]).fillna(by["coupon_id"])
    by["할인 방식"] = by["coupon_id"].map(names["discount_type"])
    by["효율"] = by["쿠폰주문매출"] / by["할인액"].where(by["할인액"] > 0)
    by["주문당 할인액"] = by["할인액"] / by["주문수"]
    by = by.sort_values("효율", ascending=False).reset_index(drop=True)
    return {"total": total, "by_coupon": by}


# ===========================================================================
# 화면 계산 함수 (화면과 AI 챗봇이 함께 쓰는 계산. 화면 표시용 라벨 변환은 views 에서)
# ===========================================================================
def completed_items(m: dict, start, end) -> pd.DataFrame:
    """기간 안 완료 주문의 주문상품 행."""
    it = in_period(m["items"], "order_time", start, end)
    return it[it["order_status"].eq("COMPLETED")]


def completed_orders(m: dict, start=None, end=None) -> pd.DataFrame:
    """완료 주문 (기간을 주지 않으면 전체 관측 기간), 주문 시각 순."""
    o = m["orders"] if start is None else in_period(m["orders"], "order_time", start, end)
    return o[o["order_status"].eq("COMPLETED")].sort_values("order_time")


# ---------------------------------------------------------------------------
# 매출·상품
# ---------------------------------------------------------------------------
def revenue_decomposition(m: dict, cur: tuple, prev: tuple, k: dict | None = None, kp: dict | None = None) -> dict | None:
    """완료 매출 변화 = 주문 수 변화 효과 + 객단가 변화 효과. 비교할 주문이 없으면 None."""
    k = k or kpis(m, *cur)
    kp = kp or kpis(m, *prev)
    if not (kp["orders"] and k["orders"]):
        return None
    return {"revenue_change": k["revenue"] - kp["revenue"],
            "order_effect": (k["orders"] - kp["orders"]) * kp["aov"],
            "aov_effect": (k["aov"] - kp["aov"]) * k["orders"]}


def new_signups(m: dict, start, end) -> int:
    """기간 안 신규 가입 고객 수 (Acquisition 대체 지표)."""
    c = m["raw"]["customer"]
    return len(c[(c["signup_date"] >= start) & (c["signup_date"] < end)])


def sales_trend(m: dict, start, end, grain: str = "date") -> pd.DataFrame:
    """완료 매출·주문 수 시계열. grain = date | week | month."""
    o = completed_orders(m, start, end)
    return o.groupby(grain).agg(매출=("total_amount", "sum"), 주문수=("order_id", "nunique")).reset_index()


def category_sales(m: dict, start, end) -> pd.DataFrame:
    """카테고리별 상품매출(쿠폰 후, 배송비 제외)과 비중, 매출 순."""
    cat = completed_items(m, start, end).groupby("category")["net_sales"].sum().sort_values(ascending=False).reset_index()
    cat["비중"] = cat["net_sales"] / cat["net_sales"].sum()
    return cat


def top_products(m: dict, start, end, n: int = 5) -> pd.DataFrame:
    """상품매출 상위 n개 상품."""
    it = completed_items(m, start, end)
    return (it.groupby(["product_name", "category"])
            .agg(상품매출=("net_sales", "sum"), 구매고객=("customer_id", "nunique"), 수량=("quantity", "sum"))
            .sort_values("상품매출", ascending=False).head(n).reset_index())


def category_performance(m: dict, start, end) -> pd.DataFrame:
    """카테고리별 상품매출·주문·고객·공헌이익과 비중 (index = category, 정렬 전)."""
    it = completed_items(m, start, end)
    cat = it.groupby("category").agg(상품매출=("net_sales", "sum"), 주문수=("order_id", "nunique"),
                                     구매고객=("customer_id", "nunique"), 공헌이익=("contribution", "sum"))
    cat["매출 비중"] = cat["상품매출"] / cat["상품매출"].sum()
    cat["큐레이션 경유 비중"] = it[it["path"].eq("CURATION")].groupby("category")["net_sales"].sum() / cat["상품매출"]
    cat["공헌이익률"] = cat["공헌이익"] / cat["상품매출"]
    return cat


def product_performance(m: dict, start, end, category: str | None = None) -> pd.DataFrame:
    """상품별 상품매출·수량·고객·재구매 고객 비중·큐레이션 경유 비중·공헌이익률, 매출 순."""
    it = completed_items(m, start, end)
    sub = it if category in (None, "전체") else it[it["category"].eq(category)]
    per_cust = sub.groupby(["product_id", "customer_id"])["order_id"].nunique()
    rep = (per_cust >= 2).groupby("product_id").sum()
    pr = sub.groupby(["product_id", "product_name", "category"]).agg(
        상품매출=("net_sales", "sum"), 판매수량=("quantity", "sum"), 구매고객=("customer_id", "nunique"),
        공헌이익=("contribution", "sum")).reset_index()
    pr["재구매 고객 비중"] = pr["product_id"].map(rep) / pr["구매고객"]
    cur_share = sub[sub["path"].eq("CURATION")].groupby("product_id")["net_sales"].sum()
    pr["큐레이션 경유 비중"] = pr["product_id"].map(cur_share).fillna(0) / pr["상품매출"]
    pr["공헌이익률"] = pr["공헌이익"] / pr["상품매출"]
    return pr.sort_values("상품매출", ascending=False)


def segment_category_mix(m: dict, start, end, by: str = "customer_type") -> pd.DataFrame:
    """고객 구분(by)별 카테고리 상품매출 비중. by = customer_type | grade_at_order | visitor_type."""
    it = completed_items(m, start, end).copy()
    if by == "grade_at_order":
        it = it.merge(m["orders"][["order_id", "grade_at_order"]], on="order_id", how="left")
    mix = it.groupby([by, "category"])["net_sales"].sum().reset_index()
    mix["비중"] = mix["net_sales"] / mix.groupby(by)["net_sales"].transform("sum")
    return mix


# ---------------------------------------------------------------------------
# 큐레이션 테마
# ---------------------------------------------------------------------------
QUADRANT_HINT = {
    "관심↑ 구매↓": "관심은 있지만 구매로 이어지지 않음 → 상품 구성·가격·상세 정보 검토",
    "관심↓ 구매↑": "클릭한 고객은 잘 구매함 → 노출 확대나 배너 메시지 개선 검토",
}


def theme_quadrant(m: dict, start, end) -> tuple[pd.DataFrame, float, float]:
    """테마별 관심(클릭률) vs 구매(클릭 후 구매율) 사분면. (테마 표, 클릭률 중앙값, 클릭 후 구매율 중앙값)."""
    tt = theme_table(m, start, end)
    tt["클릭후구매율"] = tt["구매세션"] / tt["클릭세션"].replace(0, np.nan)
    mx, my = tt["클릭률"].median(), tt["클릭후구매율"].median()

    def quadrant(r):
        hi_i, hi_b = r["클릭률"] >= mx, r["클릭후구매율"] >= my
        if hi_i and not hi_b:
            return "관심↑ 구매↓"
        if not hi_i and hi_b:
            return "관심↓ 구매↑"
        return "관심↑ 구매↑" if hi_i else "관심↓ 구매↓"

    tt["구분"] = tt.apply(quadrant, axis=1)
    return tt, mx, my


def theme_weekly(m: dict, theme_id: str) -> pd.DataFrame:
    """테마 하나의 주별 노출·클릭·장바구니·구매 세션과 전환율 (전체 관측 기간)."""
    ts = m["sessions"][m["sessions"]["theme_id"].eq(theme_id)]
    w = ts.groupby("week").agg(노출=("session_id", "size"), 클릭=("has_theme_click", "sum"),
                               장바구니=("has_cart", "sum"), 구매=("has_purchase", "sum")).reset_index()
    w["클릭률"] = w["클릭"] / w["노출"]
    w["장바구니→구매"] = w["구매"] / w["장바구니"].replace(0, np.nan)
    w["구매 전환율"] = w["구매"] / w["노출"]
    return w


def theme_segments(m: dict, theme_id: str, start, end, by: str = "visitor_type") -> pd.DataFrame:
    """테마 하나를 고객·시간 구분(by)별로 나눈 클릭률·전환율.
    by = visitor_type | is_new_signup | day_type | daypart."""
    ts = in_period(m["sessions"], "start", start, end)
    ts = ts[ts["theme_id"].eq(theme_id)]
    grp = ts.groupby(by).agg(노출세션=("session_id", "size"), 클릭세션=("has_theme_click", "sum"),
                             장바구니세션=("has_cart", "sum"), 구매세션=("has_purchase", "sum")).reset_index()
    grp["클릭률"] = grp["클릭세션"] / grp["노출세션"]
    grp["장바구니→구매"] = grp["구매세션"] / grp["장바구니세션"].replace(0, np.nan)
    grp["구매 전환율"] = grp["구매세션"] / grp["노출세션"]
    return grp


def theme_lineup(m: dict, theme_id: str, start, end) -> tuple[pd.DataFrame, float]:
    """테마 편성 상품별 클릭·장바구니 세션과 경유 매출. (상품 표, 편성 외 상품 경유 매출)."""
    ev = in_period(m["raw"]["event_log"], "event_time", start, end)
    ev = ev[ev["theme_id"].eq(theme_id)]
    clicks = ev[ev["event_type"].eq("product_click")].groupby("product_id")["session_id"].nunique()
    carts = ev[ev["event_type"].eq("add_to_cart")].groupby("product_id")["session_id"].nunique()
    it = completed_items(m, start, end)
    it = it[it["attributed_theme_id"].eq(theme_id)]
    sales = it.groupby("product_id").agg(경유상품매출=("net_sales", "sum"), 판매수량=("quantity", "sum"))
    lineup = m["raw"]["curation_product"]
    lineup = lineup[lineup["theme_id"].eq(theme_id)].merge(
        m["raw"]["product"][["product_id", "product_name", "category"]], on="product_id")
    lineup["상품 클릭 세션"] = lineup["product_id"].map(clicks).fillna(0).astype(int)
    lineup["장바구니 세션"] = lineup["product_id"].map(carts).fillna(0).astype(int)
    lineup["클릭→장바구니"] = lineup["장바구니 세션"] / lineup["상품 클릭 세션"].replace(0, np.nan)
    lineup = lineup.join(sales, on="product_id").fillna({"경유상품매출": 0, "판매수량": 0})
    lineup["매출 비중"] = lineup["경유상품매출"] / max(lineup["경유상품매출"].sum(), 1)
    extra = it[~it["product_id"].isin(lineup["product_id"])]["net_sales"].sum()
    return lineup, extra


# ---------------------------------------------------------------------------
# 고객 여정
# ---------------------------------------------------------------------------
def step_breakdown(s_cur: pd.DataFrame, s_prev: pd.DataFrame | None, path: str, step_idx: int, by: str) -> pd.DataFrame:
    """한 퍼널 구간을 by 기준으로 나눈 전환율. 비교 세션이 있으면 변화·p값·전체 변화 기여(%p)도.
    index = 그룹 값(문자열), 열 = num, den, 분석 기간 [, num_p, den_p, 비교 기간, 변화(%p), p값, 전체 변화 기여(%p)]."""
    gc = step_rate(s_cur, path, step_idx, by=by).rename(columns={"rate": "분석 기간"})
    if s_prev is not None:
        gp = step_rate(s_prev, path, step_idx, by=by)
        gc = gc.join(gp.rename(columns={"num": "num_p", "den": "den_p", "rate": "비교 기간"}), how="left")
        gc["변화(%p)"] = (gc["분석 기간"] - gc["비교 기간"]) * 100
        gc["p값"] = [two_prop_test(r.num, r.den, r.num_p, r.den_p)[1] if pd.notna(r.den_p) and r.den_p > 0 else np.nan
                    for r in gc.itertuples()]
        # 전체 변화에 대한 기여: 그룹 분모 비중 × 그룹 전환율 변화
        gc["전체 변화 기여(%p)"] = (gc["den"] / gc["den"].sum()) * gc["변화(%p)"]
    return gc


def funnel_weekly(m: dict, path: str) -> pd.DataFrame:
    """경로별 퍼널 구간 전환율의 주별 추이 (전체 관측 기간, '구매 완료' 구간 제외). 열 = week, 구간, 전환율."""
    order = [lab for lab, _ in FUNNEL_STEPS[path]]
    ss = path_filter(m["sessions"], path)
    weeks = []
    for wk, g in ss.groupby("week"):
        row = {"week": wk}
        for i in range(1, len(order)):
            if order[i] == "구매 완료":
                continue
            n, dd, r = step_rate(g, path, i)
            row[f"{order[i-1]}→{order[i]}"] = r
        weeks.append(row)
    return pd.DataFrame(weeks).melt(id_vars="week", var_name="구간", value_name="전환율")


# ---------------------------------------------------------------------------
# 고객·리텐션
# ---------------------------------------------------------------------------
def observation_end() -> pd.Timestamp:
    """관측 종료 다음 날 (2026-10-01)."""
    from .data import AS_OF
    return AS_OF.normalize() + pd.Timedelta(days=1)


def customer_mix(m: dict, start, end) -> pd.DataFrame:
    """첫 구매 고객 vs 기존 구매 고객의 고객 수·매출·주문 수·매출 비중 (index = 구분)."""
    cc = completed_orders(m, start, end)
    mix = cc.groupby("customer_type").agg(고객수=("customer_id", "nunique"), 매출=("total_amount", "sum"),
                                          주문수=("order_id", "nunique")).reindex(["첫 구매 고객", "기존 구매 고객"])
    mix["매출 비중"] = mix["매출"] / mix["매출"].sum()
    return mix


def cohort_retention(m: dict, basis: str = "lifetime") -> tuple[pd.DataFrame, pd.Series]:
    """월별 코호트의 1~5개월 후 재구매(유지)율. 관찰할 수 없는 칸은 빠진다.
    basis = lifetime (생애 첫 구매 고객) | observed (관측 기간 첫 주문 고객, 기존 고객 포함).
    (칸별 표, 코호트 크기)."""
    comp = completed_orders(m)
    obs_end = observation_end()
    if basis == "lifetime":
        first = comp[comp["is_first_purchase"].eq(1)].groupby("customer_id")["month"].min()
    else:
        first = comp.groupby("customer_id")["month"].min()
    act = comp[["customer_id", "month"]].drop_duplicates()
    act = act[act["customer_id"].isin(first.index)]
    act["cohort"] = act["customer_id"].map(first)
    act["k"] = ((act["month"].dt.year - act["cohort"].dt.year) * 12 + act["month"].dt.month - act["cohort"].dt.month)
    size = first.value_counts().sort_index()
    ret = act[act["k"] >= 1].groupby(["cohort", "k"])["customer_id"].nunique().reset_index(name="고객")
    grid = pd.MultiIndex.from_product([size.index, range(1, 6)], names=["cohort", "k"]).to_frame(index=False)
    grid = grid[grid["cohort"].dt.year * 12 + grid["cohort"].dt.month + grid["k"] <= obs_end.year * 12 + obs_end.month - 1]
    ret = grid.merge(ret, how="left").fillna({"고객": 0})
    ret["유지율"] = ret["고객"] / ret["cohort"].map(size)
    ret["코호트"] = ret["cohort"].dt.strftime("%Y-%m") + " (n=" + ret["cohort"].map(size).astype(str) + ")"
    ret["경과"] = ret["k"].astype(str) + "개월 후"
    return ret, size


def _order_sequence(m: dict) -> pd.DataFrame:
    comp = completed_orders(m)
    seq = comp[["customer_id", "order_time", "is_first_purchase"]].copy()
    seq["next_time"] = seq.groupby("customer_id")["order_time"].shift(-1)
    seq["gap_days"] = (seq["next_time"] - seq["order_time"]).dt.total_seconds() / 86400
    return seq


def repeat_rates(m: dict, windows=(7, 30, 60)) -> pd.DataFrame:
    """관측 기간 첫 완료 주문 후 N일 안 재구매율, 첫 주문 월 × 고객 구분별.
    N일이 관측 기간 안에 끝나는 고객만 대상. 열 = 첫 주문 월, 구분, 기준, 대상 고객, 재구매율."""
    obs_end = observation_end()
    firsts = _order_sequence(m).groupby("customer_id").head(1).copy()
    firsts["month"] = firsts["order_time"].dt.to_period("M").dt.start_time
    firsts["구분"] = np.where(firsts["is_first_purchase"].eq(1), "생애 첫 구매 고객", "기존 구매 고객")
    rows = []
    for win in windows:
        elig = firsts[firsts["order_time"] + pd.Timedelta(days=win) <= obs_end]
        for (mon, grp_), g in elig.groupby(["month", "구분"]):
            rows.append({"첫 주문 월": mon.strftime("%Y-%m"), "구분": grp_, "기준": f"{win}일 재구매율",
                         "대상 고객": len(g), "재구매율": (g["gap_days"] <= win).mean()})
    return pd.DataFrame(rows)


GAP_BINS = [0, 3, 7, 14, 21, 30, 45, 60, 90, 200]
GAP_LABELS = ["0-3일", "4-7일", "8-14일", "15-21일", "22-30일", "31-45일", "46-60일", "61-90일", "91일+"]


def repeat_gaps(m: dict) -> dict:
    """연속된 두 완료 주문 사이 간격 분포 (전체 관측 기간).
    {"dist": 간격·건수·비중 표, "median_days": 중앙값, "orders_per_buyer": 구매 고객당 완료 주문}."""
    gaps = _order_sequence(m)["gap_days"].dropna()
    gd = pd.cut(gaps, bins=GAP_BINS, labels=GAP_LABELS, include_lowest=True).value_counts().reindex(GAP_LABELS).reset_index()
    gd.columns = ["간격", "건수"]
    gd["비중"] = gd["건수"] / gd["건수"].sum()
    return {"dist": gd, "median_days": gaps.median() if len(gaps) else np.nan,
            "orders_per_buyer": completed_orders(m).groupby("customer_id").size().mean()}


RFM_RULES = pd.DataFrame([
    ("신규 구매", "생애 첫 구매가 최근 30일 안이고 관측 기간 완료 주문 1건 이하", "첫 구매 경험 강화, 두 번째 구매 유도"),
    ("핵심", "마지막 구매 30일 이내 · 관측 기간 주문 4건 이상", "이탈 방지, 혜택 유지"),
    ("충성", "마지막 구매 60일 이내 · 주문 2건 이상", "구매 빈도 높이기, 교차 판매"),
    ("성장 가능", "마지막 구매 30일 이내 · 주문 1건 이하", "재구매 유도"),
    ("관심 필요", "마지막 구매 31~60일 · 주문 1건 이하", "리마인드"),
    ("이탈 우려", "마지막 구매 60일 초과 · 주문 2건 이상", "복귀 유도"),
    ("휴면 추정", "마지막 구매 60일 초과 · 주문 1건 이하 (4/1 이전 마지막 구매 포함)", "저비용 재활성화 시도"),
], columns=["고객군", "분류 기준", "활용 방향 (가설)"])
RFM_ORDER = list(RFM_RULES["고객군"])


def rfm_segments(m: dict, ref) -> pd.DataFrame:
    """기준일(ref, 미포함) 시점 고객별 R·F·M과 규칙 기반 고객군 (index = customer_id).
    F·M은 관측 기간(4/1~) 기준, R은 4/1 이전 마지막 구매일도 반영. 이탈 확률이 아니다."""
    comp = completed_orders(m)
    hist = comp[comp["order_time"] < ref]
    g = hist.groupby("customer_id").agg(last=("order_time", "max"), F=("order_id", "nunique"), M=("total_amount", "sum"))
    snap = m["raw"]["customer_initial_snapshot"].set_index("customer_id")
    prior_last = snap["last_purchase_date"].dropna()
    allc = g.index.union(prior_last.index)
    r = pd.DataFrame(index=allc)
    r["last"] = g["last"].reindex(allc).fillna(prior_last.reindex(allc))
    r["F"] = g["F"].reindex(allc).fillna(0).astype(int)
    r["M"] = g["M"].reindex(allc).fillna(0)
    r["recency"] = (ref - r["last"]).dt.days
    first_new = comp[comp["is_first_purchase"].eq(1)].groupby("customer_id")["order_time"].min()
    r["first_purchase"] = first_new.reindex(allc)

    def seg(x):
        if pd.notna(x.first_purchase) and x.first_purchase < ref and (ref - x.first_purchase).days <= 30 and x.F <= 1:
            return "신규 구매"
        if x.recency <= 30 and x.F >= 4:
            return "핵심"
        if x.recency <= 60 and x.F >= 2:
            return "충성"
        if x.recency <= 30:
            return "성장 가능"
        if x.recency <= 60:
            return "관심 필요"
        if x.F >= 2:
            return "이탈 우려"
        return "휴면 추정"

    r["고객군"] = r.apply(seg, axis=1)
    return r


def rfm_summary(m: dict, start, end, r: pd.DataFrame | None = None) -> pd.DataFrame:
    """고객군별 고객 수·평균 주문·경과일 중앙값·분석 기간 매출과 비중. 기준일 = 분석 기간 종료일."""
    r = rfm_segments(m, end) if r is None else r
    cur_orders = completed_orders(m, start, end)
    summ = r.groupby("고객군").agg(고객수=("F", "size"), 평균주문=("F", "mean"), 경과일중앙값=("recency", "median"))
    cur_rev = cur_orders.assign(seg=cur_orders["customer_id"].map(r["고객군"])).groupby("seg")["total_amount"].sum()
    summ["분석 기간 매출"] = cur_rev.reindex(summ.index).fillna(0)
    summ["매출 비중"] = summ["분석 기간 매출"] / max(summ["분석 기간 매출"].sum(), 1)
    summ["고객 비중"] = summ["고객수"] / summ["고객수"].sum()
    return summ.reindex(RFM_ORDER).dropna(how="all").reset_index()


def rfm_preference(m: dict, start, end, dim: str = "category", r: pd.DataFrame | None = None) -> pd.DataFrame:
    """RFM 고객군별 카테고리(또는 theme_name) 상품매출 비중. 테마는 큐레이션 경유 주문만."""
    r = rfm_segments(m, end) if r is None else r
    it = completed_items(m, start, end).assign(고객군=lambda x: x["customer_id"].map(r["고객군"]))
    if dim == "theme_name":
        it = it.dropna(subset=["theme_name"])
    pv = it.groupby(["고객군", dim])["net_sales"].sum().reset_index()
    pv["비중"] = pv["net_sales"] / pv.groupby("고객군")["net_sales"].transform("sum")
    return pv

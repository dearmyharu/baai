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

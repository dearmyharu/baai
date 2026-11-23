"""일일 브리핑: 실무자가 업무 시작 시 처음 보는 화면의 계산.

구성
1. 전일 실적 (평소 = 최근 4주 동일 요일)
2. 월간 누적 실적 (전월 동기와 비교)
3. 전일 상품별 판매 동향
4. 금일 확인 사항 (규칙 6가지)

원칙
- 주문 데이터만 쓴다 (주문·주문 상품·원가·쿠폰·주문 상태). 방문 로그는 쓰지 않는다.
- 이익 = 고객이 낸 돈(쿠폰 차감 후 상품금액 + 고객 배송비) − 상품원가 − 배송 원가(주문당 SHIP_COST).
  결제 수수료 등 기타 비용은 넣지 않는다. Growth Lab(simulation.py)과 같은 식이 되도록 배송 원가만 넘긴다.
- 화면 문장은 이 파일이 숫자를 넣어 만든다(AI가 쓰지 않는다). 문체는 업무 보고체.
"""
from __future__ import annotations

import pandas as pd

SHIP_COST = 3000          # 판매자 배송 원가(주문당, 가정값)
WEEKS = 4                 # '평소' = 최근 4주 같은 요일

# 할 일 규칙 기준값. 2026-11-20 실제 9월 데이터로 맞춤(eval/briefing_tune.py): 하루 평균 2.8건, 0건인 날 없음.
# ④ 쿠폰 의존은 이 데이터에서 +10%p로 낮춰도 한 번도 걸리지 않음(쿠폰 사용 비중이 안정적).
TH = {
    "drop_pct": 0.35,        # ① 3일 매출이 평소보다 35% 이상 낮음
    "rise_x": 1.3,           # ② 3일 판매량이 평소의 1.3배 이상
    "min_base_qty3": 10,     # ①② 상품: 평소 3일 판매량이 이보다 적으면 판단하지 않음
    "min_impact": 0.01,      # 하루 영향 금액이 하루 평균 매출의 1% 미만이면 제외
    "spike_x": 2.5,          # ⑥ 전일 주문 건수가 평소의 2.5배 이상 (수량이 아니라 주문 건수: 한 주문에 여러 개는 급변이 아님)
    "spike_min_qty": 5,      # ⑥ 그리고 주문 5건 이상
    "spike_impact": 0.02,    # ⑥ 늘어난 매출이 하루 평균 매출의 2% 이상
    "zero_base_qty": 10,     # ⑥ 평소 하루 10개 이상 팔리던 상품이 어제 0개
    "margin_max": 0.15,      # ③ 이익률 15% 미만
    "top_share": 0.20,       # ③ 판매 상위 20% 상품만
    "min_orders7": 10,       # ③ 최근 7일 주문 10건 이상
    "coupon_pp": 0.20,       # ④ 쿠폰 사용 주문 비중 +20%p 이상
    "cancel_min": 3,         # ⑤ 어제 취소·환불 3건 이상
    "max_items": 4,          # 화면에 보여 줄 최대 개수
}
DOW = "월화수목금토일"


def _d(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.month}/{ts.day}"


def _won(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.2f}억원"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.0f}만원"
    return f"{v:,.0f}원"


# ---------------------------------------------------------------------------
# 이익 장부 (완료 주문)
# ---------------------------------------------------------------------------
def ledger(m: dict, ship_cost: float = SHIP_COST) -> tuple[pd.DataFrame, pd.DataFrame]:
    """완료 주문 단위 장부와, 배송 부담을 상품금액 비율로 나눠 넣은 주문 상품 장부."""
    it = m["items"]
    it = it[it["order_status"].eq("COMPLETED")].copy()
    it["cost"] = it["quantity"] * it["cost_price"]
    o = m["orders"]
    o = o[o["order_status"].eq("COMPLETED")].copy()
    agg = it.groupby("order_id").agg(gross=("sales_amount", "sum"), discount=("allocated_coupon_discount", "sum"),
                                     net=("net_sales", "sum"), cost=("cost", "sum"))
    o = o.join(agg, on="order_id")
    o[["gross", "discount", "net", "cost"]] = o[["gross", "discount", "net", "cost"]].fillna(0)
    o["shipping_income"] = (o["total_amount"] - o["net"]).clip(lower=0)
    o["ship_burden"] = ship_cost - o["shipping_income"]
    o["profit"] = o["total_amount"] - o["cost"] - ship_cost
    o["date"] = o["order_time"].dt.normalize()
    share = it["net_sales"] / it["order_id"].map(o.set_index("order_id")["net"]).replace(0, pd.NA)
    it["ship_burden"] = share.fillna(0).astype(float) * it["order_id"].map(o.set_index("order_id")["ship_burden"])
    it["profit"] = it["net_sales"] - it["cost"] - it["ship_burden"]
    it["date"] = it["order_time"].dt.normalize()
    return o, it


def _same_weekdays(day: pd.Timestamp, weeks: int = WEEKS) -> list[pd.Timestamp]:
    return [day - pd.Timedelta(days=7 * k) for k in range(1, weeks + 1)]


def _level(value, base: list) -> str:
    if not base:
        return "비교 불가"
    if value < min(base):
        return "평소 대비 낮음"
    if value > max(base):
        return "평소 대비 높음"
    return "평소 수준"


# ---------------------------------------------------------------------------
# 1. 어제 장사
# ---------------------------------------------------------------------------
def daily(o: pd.DataFrame) -> pd.DataFrame:
    g = o.groupby("date").agg(revenue=("total_amount", "sum"), orders=("order_id", "nunique"),
                              profit=("profit", "sum"), discount=("discount", "sum"), gross=("gross", "sum"))
    idx = pd.date_range(g.index.min(), g.index.max(), freq="D") if len(g) else g.index
    g = g.reindex(idx, fill_value=0)
    g["aov"] = g["revenue"] / g["orders"].where(g["orders"] > 0)
    return g


def yesterday(o: pd.DataFrame, day: pd.Timestamp) -> dict:
    g = daily(o)
    base_days = [d for d in _same_weekdays(day) if d in g.index]
    row = g.loc[day] if day in g.index else pd.Series(0, index=g.columns)
    out = {"day": day, "dow": DOW[day.dayofweek], "base_days": base_days}
    for k in ("revenue", "orders", "profit", "aov"):
        base = g.loc[base_days, k].dropna().tolist()
        mean = sum(base) / len(base) if base else None
        out[k] = float(row[k]) if pd.notna(row[k]) else None
        out[f"{k}_base"] = mean
        out[f"{k}_chg"] = (out[k] / mean - 1) if mean and out[k] is not None else None
        out[f"{k}_min"], out[f"{k}_max"] = (min(base), max(base)) if base else (None, None)
    out["level"] = _level(out["revenue"], g.loc[base_days, "revenue"].tolist())
    return out


def trend(o: pd.DataFrame, day: pd.Timestamp, days: int = 14) -> pd.DataFrame:
    g = daily(o)
    idx = pd.date_range(day - pd.Timedelta(days=days - 1), day, freq="D")
    t = g.reindex(idx, fill_value=0)[["revenue", "profit", "orders"]].reset_index(names="date")
    t["요일"] = t["date"].dt.dayofweek.map(lambda i: DOW[i])
    t["어제"] = t["date"].eq(day)
    return t


# ---------------------------------------------------------------------------
# 2. 이번 달 진행
# ---------------------------------------------------------------------------
def month_pace(o: pd.DataFrame, day: pd.Timestamp) -> dict:
    g = daily(o)
    start = day.replace(day=1)
    cum = g.loc[start:day, "revenue"].sum()
    pstart = (start - pd.Timedelta(days=1)).replace(day=1)
    plen = (start - pstart).days
    pend = pstart + pd.Timedelta(days=min(day.day, plen) - 1)
    pcum = g.loc[pstart:pend, "revenue"].sum() if pstart >= g.index.min() else None
    pfull = g.loc[pstart:start - pd.Timedelta(days=1), "revenue"].sum() if pcum is not None else None
    mlen = pd.Period(day, "M").days_in_month
    return {"cum": float(cum), "prev_cum": pcum, "prev_full": pfull, "chg": (cum / pcum - 1) if pcum else None,
            "projection": float(cum / day.day * mlen), "progress": day.day / mlen, "day": day.day, "month": day.month}


# ---------------------------------------------------------------------------
# 3. 어제 상품
# ---------------------------------------------------------------------------
def _qty_table(it: pd.DataFrame, key: str, value: str, day: pd.Timestamp, back: int = 40) -> pd.DataFrame:
    lo = day - pd.Timedelta(days=back)
    x = it[(it["date"] >= lo) & (it["date"] <= day)]
    t = x.pivot_table(index=key, columns="date", values=value, aggfunc="sum", fill_value=0)
    return t.reindex(columns=pd.date_range(lo, day, freq="D"), fill_value=0)


def movers(it: pd.DataFrame, day: pd.Timestamp, n: int = 3) -> dict:
    q = _qty_table(it, "product_name", "quantity", day)
    base_cols = [d for d in _same_weekdays(day) if d in q.columns]
    df = pd.DataFrame({"상품": q.index, "어제": q[day].values, "평소": q[base_cols].mean(axis=1).values})
    df = df[(df["평소"] >= 2) | (df["어제"] >= 5)]
    df["차이"] = df["어제"] - df["평소"]
    up = df[df["어제"] >= df["평소"] * 1.5].nlargest(n, "차이")
    down = df[df["어제"] <= df["평소"] * 0.67].nsmallest(n, "차이")
    return {"up": up.reset_index(drop=True), "down": down.reset_index(drop=True)}


# ---------------------------------------------------------------------------
# 4. 오늘 할 일
# ---------------------------------------------------------------------------
def _windows(day: pd.Timestamp, length: int) -> tuple[list, list[list]]:
    cur = list(pd.date_range(day - pd.Timedelta(days=length - 1), day, freq="D"))
    base = [[d - pd.Timedelta(days=7 * k) for d in cur] for k in range(1, WEEKS + 1)]
    return cur, base


def _win_sum(t: pd.DataFrame, days: list) -> pd.Series:
    cols = [d for d in days if d in t.columns]
    return t[cols].sum(axis=1)


def _base_mean(t: pd.DataFrame, bases: list[list]) -> pd.Series:
    return pd.concat([_win_sum(t, b) for b in bases], axis=1).mean(axis=1)


def _spike_profile(o_all: pd.DataFrame, it: pd.DataFrame, m: dict, product: str, day: pd.Timestamp) -> dict:
    x = it[(it["date"] == day) & (it["product_name"] == product)]
    oid = x["order_id"].unique()
    od = o_all[o_all["order_id"].isin(oid)]
    n_orders, n_cust = len(oid), x["customer_id"].nunique()
    first = int(od["is_first_purchase"].fillna(0).astype(float).sum()) if "is_first_purchase" in od else 0
    coupon = float(od["has_coupon"].mean()) if "has_coupon" in od and len(od) else 0.0
    qc = x.groupby("customer_id")["quantity"].sum()
    top_share = float(qc.max() / qc.sum()) if qc.sum() else 0.0
    hours = x["order_time"].dt.hour
    best, best_h, best_to = 0.0, None, None
    for h in range(0, 22):
        inside = hours[hours.between(h, h + 2)]
        s = len(inside) / len(hours) if len(hours) else 0.0
        if s > best:
            best, best_h, best_to = s, int(inside.min()), int(inside.max()) + 1
    chan = None
    cust = m.get("raw", {}).get("customer")
    if cust is not None and "signup_channel" in cust and first:
        fc = od.loc[od["is_first_purchase"].fillna(0).astype(float).eq(1), "customer_id"]
        c = fc.map(cust.set_index("customer_id")["signup_channel"]).value_counts()
        chan = c.index[0] if len(c) else None
    if top_share >= 0.5 and n_cust <= 2:
        guess = "대량 주문"
    elif n_orders >= 3 and first / max(n_cust, 1) >= 0.5:
        guess = "바이럴·외부 유입"
    elif coupon >= 0.7:
        guess = "쿠폰 영향"
    elif best >= 0.6 and n_orders >= 3:
        guess = "특정 시간대 집중(방송·게시물 여부 확인 필요)"
    else:
        guess = "특이 패턴 없음"
    return {"orders": n_orders, "customers": n_cust, "first": first, "coupon_share": coupon,
            "top_customer_share": top_share, "hour_from": best_h, "hour_to": best_to, "hour_share": best,
            "channel": chan, "guess": guess}


def todos(m: dict, day: pd.Timestamp, th: dict | None = None, ship_cost: float = SHIP_COST) -> list[dict]:
    """오늘 할 일 후보 (돈 영향 순, 최대 th['max_items']개). 각 항목: kind, key, title, reasons, impact, tone, actions."""
    th = TH | (th or {})
    day = pd.Timestamp(day).normalize()
    o, it = ledger(m, ship_cost)
    g = daily(o)
    hist = g.loc[day - pd.Timedelta(days=27):day, "revenue"]
    avg_day = float(hist.mean()) if len(hist) else 0.0                 # 최근 4주 하루 평균 매출
    min_day = th["min_impact"] * avg_day                                 # 하루 기준 최소 영향 금액
    cur3, base3 = _windows(day, 3)
    span3 = f"{_d(cur3[0])}~{_d(cur3[-1])}"
    out: list[dict] = []

    # ⑥ 어제 갑자기 튄 상품 (하루 단위, 기준을 더 엄격하게)
    q = _qty_table(it, "product_name", "quantity", day)
    s = _qty_table(it, "product_name", "net_sales", day)
    n = _qty_table(it.assign(n=1).drop_duplicates(["order_id", "product_name"]), "product_name", "n", day)
    bcols = [d for d in _same_weekdays(day) if d in q.columns]
    qmean, qmax, qy = q[bcols].mean(axis=1), q[bcols].max(axis=1), q[day]
    nmean, nmax, ny_ = n[bcols].mean(axis=1), n[bcols].max(axis=1), n[day]
    smean = s[bcols].mean(axis=1)
    unit = (s.sum(axis=1) / q.sum(axis=1).replace(0, pd.NA)).astype(float).fillna(0)
    spiked = set()
    for p in q.index:
        if (ny_[p] >= max(th["spike_min_qty"], th["spike_x"] * nmean[p]) and ny_[p] > nmax[p]
                and s[day][p] - smean[p] >= th["spike_impact"] * avg_day):
            prof = _spike_profile(m["orders"], it, m, p, day)
            reasons = [f"주문 {ny_[p]:.0f}건 ({qy[p]:.0f}개) · 평소 {nmean[p]:.1f}건 (같은 요일 최대 {nmax[p]:.0f}건)",
                       f"주문 {prof['orders']}건 · 구매 고객 {prof['customers']}명(첫 구매 {prof['first']}명) · "
                       f"쿠폰 사용 {prof['coupon_share']:.0%}" +
                       (f" · {prof['hour_from']}~{prof['hour_to']}시에 {prof['hour_share']:.0%}"
                        if prof["hour_from"] is not None else ""),
                       f"주문 패턴 추정: {prof['guess']}"]
            out.append({"kind": "spike", "key": f"product:{p}", "tone": "opportunity", "priority": 0,
                        "title": f"{p} 전일 주문 급증(평소 대비 {ny_[p] / max(nmean[p], 0.5):.1f}배) 원인 확인",
                        "reasons": reasons, "impact": float(s[day][p] - smean[p]), "profile": prof,
                        "actions": [{"type": "ask", "label": "구매 고객 분석",
                                     "q": f"{_d(day)} {p} 구매 고객의 구성(첫 구매/기존, 가입 경로, 연령대)을 분석해 주세요"}]})
            spiked.add(p)
        elif qmean[p] >= th["zero_base_qty"] and qy[p] == 0:
            out.append({"kind": "spike", "key": f"product:{p}", "tone": "problem", "priority": 0,
                        "title": f"{p} 전일 판매 없음 · 품절·상품 페이지 점검",
                        "reasons": [f"최근 4주 동일 요일 평균 {qmean[p]:.1f}개"], "impact": float(qmean[p] * unit[p]),
                        "actions": []})
            spiked.add(p)

    # ① 덜 팔리는 카테고리·상품, ② 잘 팔리는 상품 (3일)
    cs = _qty_table(it, "category", "net_sales", day)
    c3, cb3 = _win_sum(cs, cur3), _base_mean(cs, base3)
    flagged_cat = set()
    for c in cs.index:
        b, v = cb3[c], c3[c]
        if b > 0 and (b - v) / b >= th["drop_pct"] and (b - v) / 3 >= min_day:
            ps = it[it["category"].eq(c)]
            pt = _qty_table(ps, "product_name", "net_sales", day)
            pdiff = (_base_mean(pt, base3) - _win_sum(pt, cur3)).sort_values(ascending=False)
            top = pdiff.index[0] if len(pdiff) and pdiff.iloc[0] > 0 else None
            out.append({"kind": "drop", "key": f"category:{c}", "tone": "problem", "priority": 1,
                        "title": f"{c} 카테고리 매출 감소 원인 확인",
                        "reasons": [f"{span3} 매출 {_won(v)} · 평소 {_won(b)} ({(v / b - 1):+.0%})"] +
                                   ([f"감소 폭 최대 상품: {top} (−{_won(pdiff.iloc[0])})"] if top else []),
                        "impact": float((b - v) / 3),
                        "actions": [{"type": "ask", "label": "AI 분석가 원인 분석",
                                     "q": f"{span3} {c} 카테고리 매출이 직전 4주 동일 요일 대비 감소한 원인을 상품·고객층별로 분석해 주세요"}]})
            flagged_cat.add(c)
    q3, qb3 = _win_sum(q, cur3), _base_mean(q, base3)
    s3, sb3 = _win_sum(s, cur3), _base_mean(s, base3)
    cat_of = it.drop_duplicates("product_name").set_index("product_name")["category"]
    for p in q.index:
        if p in spiked or qb3[p] < th["min_base_qty3"]:
            continue
        if (cat_of.get(p) not in flagged_cat and sb3[p] > 0 and (sb3[p] - s3[p]) / sb3[p] >= th["drop_pct"]
                and (sb3[p] - s3[p]) / 3 >= min_day):
            out.append({"kind": "drop", "key": f"product:{p}", "tone": "problem", "priority": 1,
                        "title": f"{p} 판매 감소 원인 확인",
                        "reasons": [f"{span3} {q3[p]:.0f}개 · 평소 {qb3[p]:.1f}개 ({(q3[p] / qb3[p] - 1):+.0%})"],
                        "impact": float((sb3[p] - s3[p]) / 3),
                        "actions": [{"type": "ask", "label": "AI 분석가 원인 분석",
                                     "q": f"{span3} {p} 판매가 직전 4주 동일 요일 대비 감소한 원인을 분석해 주세요"}]})
        elif q3[p] >= th["rise_x"] * qb3[p] and (s3[p] - sb3[p]) / 3 >= min_day:
            out.append({"kind": "rise", "key": f"product:{p}", "tone": "opportunity", "priority": 1,
                        "title": f"{p} 판매 증가 · 노출 확대 검토",
                        "reasons": [f"{span3} {q3[p]:.0f}개 · 평소 {qb3[p]:.1f}개 ({q3[p] / qb3[p]:.1f}배)"],
                        "impact": float((s3[p] - sb3[p]) / 3),
                        "actions": [{"type": "ask", "label": "구매 고객 분석",
                                     "q": f"{span3} {p} 구매 고객의 구성을 분석하고 평소와 달라진 점을 알려 주세요"}]})

    # ③ 남는 게 적은 인기 상품 (최근 7일)
    lo7 = day - pd.Timedelta(days=6)
    w7 = it[(it["date"] >= lo7) & (it["date"] <= day)]
    pp = w7.groupby("product_name").agg(net=("net_sales", "sum"), profit=("profit", "sum"),
                                        discount=("allocated_coupon_discount", "sum"), orders=("order_id", "nunique"),
                                        pid=("product_id", "first"))
    if len(pp):
        cut = pp["net"].quantile(1 - th["top_share"])
        low = pp[(pp["net"] >= cut) & (pp["orders"] >= th["min_orders7"]) &
                 (pp["profit"] / pp["net"] < th["margin_max"])]
        for p, r in low.iterrows():
            out.append({"kind": "margin", "key": f"product:{p}", "tone": "problem", "priority": 2,
                        "title": f"{p} 저마진 · 쿠폰·가격 조정 검토",
                        "reasons": [f"최근 7일 매출 상위 상품, 이익률 {r.profit / r.net:.0%} "
                                    f"(쿠폰 할인 {_won(r.discount)}, 배송 원가 반영)"],
                        "impact": float(r.discount / 7),
                        "actions": [{"type": "lab", "label": "Growth Lab 손익 비교",
                                     "scope": {"product_ids": [str(r.pid)]}}]})

    # ④ 쿠폰 의존이 커진 카테고리 (최근 7일 vs 이전 28일)
    lo35 = day - pd.Timedelta(days=34)
    w35 = it[(it["date"] >= lo35) & (it["date"] <= day)].copy()
    w35["cpn"] = w35["allocated_coupon_discount"] > 0
    w35["recent"] = w35["date"] >= lo7
    co = (w35.groupby(["category", "recent", "order_id"])
             .agg(cpn=("cpn", "max"), disc=("allocated_coupon_discount", "sum"), gross=("sales_amount", "sum"))
             .groupby(["category", "recent"]).agg(share=("cpn", "mean"), disc=("disc", "sum"), gross=("gross", "sum"),
                                                   n=("cpn", "size")))
    for c in co.index.get_level_values(0).unique():
        if (c, True) not in co.index or (c, False) not in co.index:
            continue
        r, b = co.loc[(c, True)], co.loc[(c, False)]
        extra = r.disc - (b.disc / b.gross if b.gross else 0) * r.gross
        if r.n >= 10 and r.share - b.share >= th["coupon_pp"] and extra / 7 >= min_day:
            out.append({"kind": "coupon", "key": f"category:{c}", "tone": "problem", "priority": 2,
                        "title": f"{c} 카테고리 쿠폰 운영 지속 여부 검토",
                        "reasons": [f"최근 7일 쿠폰 사용 주문 {r.share:.0%} · 이전 4주 {b.share:.0%}",
                                    f"평소 대비 추가 할인액 약 {_won(extra)}"],
                        "impact": float(extra / 7),
                        "actions": [{"type": "lab", "label": "Growth Lab 손익 비교",
                                     "scope": {"categories": [c]}}]})

    # ⑤ 취소·환불 (어제)
    allo = m["orders"].copy()
    allo["date"] = allo["order_time"].dt.normalize()
    bad = allo[~allo["order_status"].eq("COMPLETED")]
    by_day = bad.groupby("date").agg(n=("order_id", "nunique"), amt=("total_amount", "sum"))
    ny = int(by_day["n"].get(day, 0))
    bmax = max([int(by_day["n"].get(d, 0)) for d in _same_weekdays(day)] or [0])
    if ny >= th["cancel_min"] and ny > bmax:
        out.append({"kind": "cancel", "key": "cancel", "tone": "check", "priority": 2,
                    "title": "취소·환불 주문 확인",
                    "reasons": [f"전일 {ny}건 ({_won(by_day['amt'].get(day, 0))}) · 최근 4주 동일 요일 최대 {bmax}건"],
                    "impact": float(by_day["amt"].get(day, 0)),
                    "actions": [{"type": "ask", "label": "AI 분석가 조회",
                                 "q": f"{_d(day)} 취소·환불 주문을 상태별로 조회해 주세요"}]})

    return rank(merge(out), th["max_items"])


def merge(items: list[dict]) -> list[dict]:
    """같은 상품·카테고리에 걸린 할 일은 하나로 합친다(이유와 버튼을 모은다)."""
    by: dict[str, dict] = {}
    for x in sorted(items, key=lambda z: z["priority"]):
        k = x["key"]
        if k not in by:
            by[k] = {**x, "kinds": [x["kind"]]}
            continue
        y = by[k]
        y["kinds"].append(x["kind"])
        y["reasons"] = y["reasons"] + x["reasons"]
        y["impact"] = max(y["impact"], x["impact"])
        labels = {a["label"] for a in y["actions"]}
        y["actions"] = y["actions"] + [a for a in x["actions"] if a["label"] not in labels]
        if x["tone"] == "problem":
            y["tone"] = "problem"
    return list(by.values())


def rank(items: list[dict], k: int) -> list[dict]:
    """하루 급변을 먼저, 그다음 돈 영향 순. 기회(잘 팔리는 것)가 있으면 최소 1개는 남긴다."""
    srt = sorted(items, key=lambda x: (x["priority"] != 0, -x["impact"]))
    top = srt[:k]
    if not any(x["tone"] == "opportunity" for x in top):
        opp = next((x for x in srt[k:] if x["tone"] == "opportunity"), None)
        if opp and top:
            top = top[:-1] + [opp]
    return top


# ---------------------------------------------------------------------------
# 맨 위 요약 문장
# ---------------------------------------------------------------------------
def summary(y: dict, pace: dict, items: list[dict]) -> str:
    parts = []
    lvl = {"평소 대비 낮음": "평소 대비 낮은 수준입니다", "평소 대비 높음": "평소 대비 높은 수준입니다",
           "평소 수준": "평소 수준입니다"}.get(y["level"], "")
    parts.append(f"전일({y['dow']}) 매출은 {_won(y['revenue'])}으로 {lvl}." if lvl
                 else f"전일({y['dow']}) 매출은 {_won(y['revenue'])}입니다.")
    parts.append(f"금일 확인 사항은 {len(items)}건입니다." if items else "금일 특이 사항은 없습니다.")
    if pace.get("chg") is not None:
        word = "높습니다" if pace["chg"] >= 0 else "낮습니다"
        parts.append(f"이번 달 누적 매출은 전월 동기 대비 {abs(pace['chg']):.1%} {word}.")
    return " ".join(parts)


def streaks(m: dict, day: pd.Timestamp, items: list[dict], th: dict | None = None,
            ship_cost: float = SHIP_COST, back: int = 6) -> None:
    """같은 확인 사항이 며칠째 이어지는지 표시한다(최대 back+1일). 새 항목과 반복 항목을 구분하기 위함."""
    keys = {x["key"] for x in items}
    alive = set(keys)
    for x in items:
        x["streak"] = 1
    for k in range(1, back + 1):
        if not alive:
            break
        prev = {x["key"] for x in todos(m, day - pd.Timedelta(days=k), (th or {}) | {"max_items": 99}, ship_cost)}
        alive &= prev
        for x in items:
            if x["key"] in alive:
                x["streak"] = k + 1


def brief(m: dict, day, th: dict | None = None, ship_cost: float = SHIP_COST) -> dict:
    """화면 한 장에 필요한 계산 전부. day = 어제(브리핑 대상 날짜)."""
    day = pd.Timestamp(day).normalize()
    o, it = ledger(m, ship_cost)
    y = yesterday(o, day)
    pace = month_pace(o, day)
    items = todos(m, day, th, ship_cost)
    streaks(m, day, items, th, ship_cost)
    return {"day": day, "yesterday": y, "trend": trend(o, day), "pace": pace, "movers": movers(it, day),
            "todos": items, "summary": summary(y, pace, items), "ship_cost": ship_cost}

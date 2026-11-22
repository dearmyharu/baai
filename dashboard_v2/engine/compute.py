"""계산 함수 8개 (의도 하나 = 함수 하나). 입력은 query.Query, 출력은 query.Result.

- 기준(비교·기간·장부)은 basis.py만 쓴다. 이 파일에 기준 숫자를 다시 적지 않는다.
- 받을 수 없는 입력은 ValueError로 거절한다(조용히 버리거나 쇼핑몰 전체로 바꾸지 않는다).
- 이유·가설·추천 문장은 만들지 않는다. 사실 문장(facts)은 숫자를 넣은 정해진 문장뿐이다.
- 화면 코드(streamlit)를 쓰지 않는다.
"""
from __future__ import annotations

import pandas as pd

from . import basis as S
from . import briefing as B
from . import fmt as F
from . import metrics as M
from .data import _daypart
from .query import AXES, INTENTS, ITEM_MEASURES, MEASURE_UNIT, RATIOS, SHOP_MEASURES, Query, Result

DOW = "월화수목금토일"
PATH_NAME = {"CURATION": "큐레이션", "BROWSE": "일반 탐색"}
SMALL_ORDERS = 20          # 비교 기간 주문이 이보다 적으면 '표본 적음' 표시
NO_REASON = "변화가 생긴 위치만 보여 줍니다. 왜 생겼는지는 이 데이터로 알 수 없습니다."


# ---------------------------------------------------------------------------
# 공통: 대상·조건 적용
# ---------------------------------------------------------------------------
class Scope:
    """고객 조건과 대상(카테고리·상품)을 적용한 장부. kind: 'all' | 'category' | 'product'."""

    def __init__(self, m: dict, q: Query, today, period=None):
        self.m_all = m
        if q.filters:
            m2, info = M.filter_mart(m, q.filters, period)
            self.filter_label = info["label"]
            self.sessions_ok = info["sessions_ok"]
        else:
            m2, self.filter_label, self.sessions_ok = m, "", True
        self.m = m2
        self.o, it = S.ledger(m2)
        cats = set(m["raw"]["product"]["category"])
        names = set(m["raw"]["product"]["product_name"])
        if q.product:
            if q.product not in names:
                raise ValueError(f"없는 상품입니다: {q.product}")
            it = it[it["product_name"].eq(q.product)]
            self.kind, self.name, self.label = "product", q.product, q.product
        elif q.category:
            if q.category not in cats:
                raise ValueError(f"없는 카테고리입니다: {q.category}")
            it = it[it["category"].eq(q.category)]
            self.kind, self.name, self.label = "category", q.category, f"{q.category} 카테고리"
        else:
            self.kind, self.name, self.label = "all", None, "쇼핑몰 전체"
        self.it = it
        self.today = pd.Timestamp(today).normalize()

    def tags(self, *extra) -> list[str]:
        out = [x for x in extra if x]
        if self.kind != "all":
            out.append(self.label)
        if self.filter_label:
            out.append(self.filter_label)
        return out

    def check_measure(self, measure: str) -> None:
        if self.kind != "all" and measure in ("완료 매출", "객단가"):
            raise ValueError(f"{measure}은(는) 주문 전체 금액이라 {self.label} 단위로 나눌 수 없습니다. 상품매출을 쓰십시오.")

    def daily(self, measure: str, by: str | None = None) -> pd.DataFrame:
        """일별 표(행 = 그룹). 대상이 있으면 그 대상의 주문 상품 장부로 센다."""
        self.check_measure(measure)
        if by is None and self.kind != "all":
            return S.daily(self.o, self.it.assign(_대상=self.label), measure, by="_대상")
        return S.daily(self.o, self.it, measure, by=by)


def _ratio_cmp(scope: Scope, measure: str, cur: list, base: list[list]) -> dict:
    num, den = RATIOS[measure]
    tn, td = scope.daily(num), scope.daily(den)
    cn, cd = S._compare(tn, cur, base).iloc[0], S._compare(td, cur, base).iloc[0]
    v = cn["현재"] / cd["현재"] if cd["현재"] else None
    b = cn["평소"] / cd["평소"] if cd["평소"] and pd.notna(cd["평소"]) else None
    if measure == "이익률":   # 비율 차이는 %p로, 판정은 하지 않는다
        return {"현재": v, "평소": b, "변화": (v - b) if v is not None and b is not None else None,
                "변화율": None, "판정": "–"}
    return {"현재": v, "평소": b, "변화": (v - b) if v is not None and b is not None else None,
            "변화율": (v / b - 1) if v is not None and b else None, "판정": S.level(v, b)}


def _cmp_one(scope: Scope, measure: str, cur: list, base: list[list]) -> dict:
    if measure in RATIOS:
        return _ratio_cmp(scope, measure, cur, base)
    r = S._compare(scope.daily(measure), cur, base).iloc[0]
    return {k: (None if pd.isna(r[k]) else r[k]) if k != "판정" else r[k] for k in ("현재", "평소", "변화", "변화율", "판정")}


def _chg_text(measure: str, c: dict) -> str:
    unit = MEASURE_UNIT[measure]
    if c["평소"] is None:
        return f"{F.value(c['현재'], unit)} (비교 불가)"
    if measure == "이익률":
        return f"{F.value(c['현재'], unit)} · 평소 {F.value(c['평소'], unit)} ({F.pp_signed(c['변화'])})"
    return f"{F.value(c['현재'], unit)} · 평소 {F.value(c['평소'], unit)} ({F.pct_signed(c['변화율'])}, {c['판정']})"


def _windows_for(q: Query, today) -> list[tuple[str, list, list[list], str]]:
    """[(이름, 현재 날짜들, 비교 묶음들, 비교 이름)]. 기간이 없으면 최근 3일·7일, 있으면 그 기간 하나."""
    if q.period:
        s, e = q.period
        base, bname = S.baseline(s, e)
        cur = list(pd.date_range(s, e - pd.Timedelta(days=1), freq="D"))
        return [(F.span(s, e), cur, base, bname)]
    out = []
    for n in S.WINDOWS:
        cur, base = S.windows(today, n)
        base = [b for b in base if b[0] >= M.PERIOD_START]
        out.append((f"최근 {n}일({F.span(cur[0], cur[-1] + pd.Timedelta(days=1))})", cur, base, f"지난 {S.WEEKS}주 같은 요일"))
    return out


def _days_note(cur: list, base: list[list]) -> str | None:
    if base and len(base[0]) != len(cur):
        return f"두 기간의 일수가 달라({len(cur)}일 vs {len(base[0])}일) 합계 비교는 일수 차이의 영향을 받습니다."
    return None


def _orders_in(scope: Scope, days: list) -> int:
    x = scope.it[scope.it["date"].isin(days)] if scope.kind != "all" else scope.o[scope.o["date"].isin(days)]
    return int(x["order_id"].nunique())


# ---------------------------------------------------------------------------
# 1. 현황
# ---------------------------------------------------------------------------
def status(m: dict, q: Query, today) -> Result:
    scope = Scope(m, q, today, q.period)
    measures = [q.measure] if q.measure else (SHOP_MEASURES if scope.kind == "all" else ITEM_MEASURES)
    for x in measures:
        scope.check_measure(x)
    wins = _windows_for(q, today)
    rows, key_w, facts, notes = [], [], [], []
    main = measures[0]
    for wname, cur, base, bname in wins:
        for x in measures:
            c = _cmp_one(scope, x, cur, base)
            rows.append({"기간": wname, "지표": x, "값": F.value(c["현재"], MEASURE_UNIT[x]),
                         f"평소({bname})": F.value(c["평소"], MEASURE_UNIT[x]) if c["평소"] is not None else "–",
                         "변화": (F.pp_signed(c["변화"]) if x == "이익률" else F.pct_signed(c["변화율"])),
                         "판정": c["판정"]})
            if x == main:
                key_w.append({"window": wname, "base_name": bname, **c})
                facts.append(f"{wname} {main} {_chg_text(main, c)}")
        n_orders = _orders_in(scope, cur)
        if n_orders < SMALL_ORDERS:
            notes.append(f"{wname} 주문이 {n_orders}건이라 숫자가 크게 흔들릴 수 있습니다.")
        d = _days_note(cur, base)
        if d and d not in notes:
            notes.append(d)
    if len(measures) > 1:     # 다른 지표는 첫 기간만 한 줄씩
        wname, cur, base, _ = wins[0]
        for x in measures[1:]:
            facts.append(f"{wname} {x} {_chg_text(x, _cmp_one(scope, x, cur, base))}")
    # 차트: 대상 일별 값 (최근 5주 또는 질문 기간과 비교 기간)
    last = wins[0][1][-1]
    first = min([wins[0][1][0]] + [b[0] for _, _, bs, _ in wins for b in bs]) if any(w[2] for w in wins) else wins[0][1][0]
    first = max(first, last - pd.Timedelta(days=62))
    series = (scope.daily(main).iloc[0] if main not in RATIOS else None)
    chart = None
    if series is not None:
        idx = pd.date_range(first, last, freq="D")
        df = series.reindex(idx, fill_value=0).rename_axis("날짜").reset_index(name=main)
        chart = {"kind": "line", "data": df, "x": "날짜", "y": main, "unit": MEASURE_UNIT[main],
                 "highlight": [wins[0][1][0], last]}
    return Result("status", f"{scope.label} {main}", scope.tags(wins[0][0], f"비교: {wins[0][3]}"),
                  {"target": scope.label, "measure": main, "windows": key_w},
                  facts, pd.DataFrame(rows), chart, notes)


# ---------------------------------------------------------------------------
# 2. 순위·비중
# ---------------------------------------------------------------------------
def rank(m: dict, q: Query, today) -> Result:
    period = q.period or S.default_period(today, "rank")
    s, e = period
    scope = Scope(m, q, today, period)
    if scope.kind == "product":
        raise ValueError("상품 하나의 순위는 볼 수 없습니다. 카테고리 안 상품 순위로 물어 주십시오.")
    by = "product" if scope.kind == "category" else (q.group_by or "category")
    col = "product_name" if by == "product" else "category"
    measure = q.measure or "상품매출"
    if measure in ("완료 매출", "객단가"):
        raise ValueError(f"{measure}은(는) 주문 전체 금액이라 {('상품' if by == 'product' else '카테고리')}별로 나눌 수 없습니다. 상품매출을 쓰십시오.")
    cur = list(pd.date_range(s, e - pd.Timedelta(days=1), freq="D"))
    base, bname = S.baseline(s, e)
    if measure in RATIOS:
        num, den = RATIOS[measure]
        tn, td = S.daily(scope.o, scope.it, num, by=col), S.daily(scope.o, scope.it, den, by=col)
        cn, cd = S._compare(tn, cur, base), S._compare(td, cur, base)
        val = (cn["현재"] / cd["현재"].where(cd["현재"] > 0))
        prev = (cn["평소"] / cd["평소"].where(cd["평소"] > 0))
        df = pd.DataFrame({"값": val, "평소": prev, "기준": cd["현재"]}).dropna(subset=["값"])
        df = df[df["기준"] > 0]
        share = None
    else:
        c = S._compare(S.daily(scope.o, scope.it, measure, by=col), cur, base)
        df = pd.DataFrame({"값": c["현재"], "평소": c["평소"], "변화율": c["변화율"]})
        df = df[df["값"] > 0]
        share = df["값"] / df["값"].sum() if df["값"].sum() else None
        if share is not None:
            df["비중"] = share
    df = df.sort_values("값", ascending=False)
    n = q.n or (len(df) if by == "category" else 10)
    top = df.head(n)
    unit = MEASURE_UNIT[measure]
    what = "상품" if by == "product" else "카테고리"
    tbl = pd.DataFrame({"순위": range(1, len(top) + 1), what: top.index, measure: [F.value(v, unit) for v in top["값"]]})
    if "비중" in top:
        tbl["비중"] = [F.pct(v, 1) for v in top["비중"]]
    if measure == "이익률":
        tbl[f"평소({bname})"] = [F.value(v, unit) for v in top["평소"]]
    elif base:
        tbl[f"변화({bname} 대비)"] = [F.pct_signed(v) for v in top["변화율"]]
    facts = [f"{i}위 {name}: {F.value(r['값'], unit)}" + (f" ({F.pct(r['비중'], 1)})" if "비중" in r else "")
             for i, (name, r) in enumerate(top.head(3).iterrows(), 1)]
    notes = []
    if by == "category" and scope.kind == "all" and measure == "상품매출":
        notes.append("카테고리 매출은 상품매출(쿠폰 차감 후 상품 금액, 배송비 제외)이라 더해도 완료 매출과 같지 않습니다.")
    d = _days_note(cur, base)
    if d:
        notes.append(d)
    chart = {"kind": "bar", "data": top.reset_index().rename(columns={top.index.name or "index": what})[[what, "값"]]
             .rename(columns={"값": measure}), "x": measure, "y": what, "unit": unit}
    return Result("rank", f"{scope.label} {what}별 {measure}", scope.tags(f"{F.span(s, e)}", f"비교: {bname}"),
                  {"by": what, "measure": measure, "top": [(name, r["값"]) for name, r in top.head(3).iterrows()],
                   "period": F.span(s, e), "count": len(df)},
                  facts, tbl, chart, notes)


# ---------------------------------------------------------------------------
# 3. 변화 위치
# ---------------------------------------------------------------------------
def _axes_for(kind: str) -> list[str]:
    out = list(AXES)
    if kind != "all":
        out.remove("category")
    if kind == "product":
        out.remove("product")
    return out


def _with_axis(scope: Scope, axis: str) -> tuple[pd.DataFrame, str]:
    it = scope.it.copy()
    if axis == "category":
        return it, "category"
    if axis == "product":
        return it, "product_name"
    if axis == "customer_type":
        it["고객 구분"] = it["customer_type"].fillna("확인 불가")
        return it, "고객 구분"
    if axis == "visitor_type":
        it["방문 구분"] = it["visitor_type"].map({"NEW": "신규 방문", "RETURNING": "재방문"}).fillna("확인 불가")
        return it, "방문 구분"
    if axis == "path":
        it["경로"] = it["path"].map(PATH_NAME).fillna("확인 불가")
        return it, "경로"
    if axis == "weekday":
        it["요일"] = it["date"].dt.dayofweek.map(lambda i: DOW[i])
        return it, "요일"
    if axis == "daypart":
        it["시간대"] = _daypart(it["order_time"].dt.hour)
        return it, "시간대"
    if axis == "grade_at_order":
        g = scope.m["orders"].set_index("order_id")["grade_at_order"]
        it["주문 당시 등급"] = it["order_id"].map(g).fillna("확인 불가")
        return it, "주문 당시 등급"
    attrs = M.customer_attrs(scope.m_all)
    col = {"gender": "gender", "age_group": "age_group", "region": "region", "signup_channel": "signup_channel"}[axis]
    v = it["customer_id"].map(attrs[col])
    if axis == "gender":
        v = v.map(M.GENDER_LABEL)
    it[AXES[axis]] = v.fillna("확인 불가")
    return it, AXES[axis]


def location(m: dict, q: Query, today) -> Result:
    scope = Scope(m, q, today, q.period)
    axis = q.axis or {"all": "category", "category": "product", "product": "customer_type"}[scope.kind]
    if axis not in _axes_for(scope.kind):
        raise ValueError(f"{scope.label}은(는) {AXES[axis]}로 나눌 수 없습니다.")
    measure = q.measure or "상품매출"
    if measure not in ("상품매출", "판매 수량", "이익"):
        raise ValueError(f"변화 위치는 상품매출·판매 수량·이익으로만 나눌 수 있습니다({measure} 불가).")
    unit = MEASURE_UNIT[measure]
    it, col = _with_axis(scope, axis)
    t = S.daily(scope.o, it, measure, by=col)
    wins = _windows_for(q, today)
    cmps = []
    for wname, cur, base, bname in wins:
        c = S._compare(t, cur, base)
        total = {"현재": c["현재"].sum(), "평소": c["평소"].sum() if base else None}
        total["변화"] = total["현재"] - total["평소"] if base else None
        total["변화율"] = (total["현재"] / total["평소"] - 1) if base and total["평소"] else None
        total["판정"] = S.level(total["현재"], total["평소"]) if base else S.LEVEL_NA
        cmps.append((wname, cur, base, bname, c, total))
    wname, cur, base, bname, c, total = cmps[0]
    alive = c.index[(c["현재"] != 0) | (c["평소"].fillna(0) != 0)]
    if len(cmps) > 1:
        c2_ = cmps[1][4]
        alive = alive.union(c2_.index[(c2_["현재"] != 0) | (c2_["평소"].fillna(0) != 0)])
    c = c.loc[c.index.isin(alive)]          # 두 기간 모두 0인 항목은 뺀다
    if not base:
        raise ValueError("비교할 이전 데이터가 없어 변화 위치를 계산할 수 없습니다.")
    down = (q.direction == "down") or (q.direction is None and (total["변화"] or 0) < 0)
    moving = c[c["변화"] < 0] if down else c[c["변화"] > 0]
    moved_sum = moving["변화"].sum()
    c = c.assign(비중=(c["변화"] / moved_sum).where(c.index.isin(moving.index)) if moved_sum else None)
    order = moving.sort_values("변화", ascending=down).index.tolist()
    rest = [i for i in c.sort_values("변화", ascending=down).index if i not in order]
    c = c.loc[order + rest]
    word, noun = ("줄어든", "감소분") if down else ("늘어난", "증가분")
    top = [(name, c.loc[name, "변화"], c.loc[name, "비중"]) for name in order[:3]]
    top_share = sum(x[2] for x in top if pd.notna(x[2]))
    facts = [f"{wname} {scope.label} {measure} {F.value(total['현재'], unit)} · 평소 {F.value(total['평소'], unit)} "
             f"({F.pct_signed(total['변화율'])}, {total['판정']})"]
    if top:
        facts.append(f"{AXES[axis]}별 {noun} 합계 중 {F.pct(top_share)}가 "
                     + ", ".join(f"{n}({F.won_signed(v) if unit == 'won' else F.count(v, '개')})" for n, v, _ in top)
                     + "에서 나왔습니다")
    else:
        facts.append(f"{AXES[axis]} 중 {word} 곳이 없습니다")
    if len(cmps) > 1:
        w2, _, _, _, c2, t2 = cmps[1]
        facts.append(f"{w2} {scope.label} {measure} {F.pct_signed(t2['변화율'])} ({t2['판정']})")
    notes = [NO_REASON]
    if total["판정"] == S.LEVEL_NORMAL:
        notes.append(f"{wname} 전체 변화는 평소 범위(±{S.BAND:.0%}) 안입니다.")
    n_orders = _orders_in(scope, cur)
    if n_orders < SMALL_ORDERS:
        notes.append(f"{wname} 주문이 {n_orders}건이라 숫자가 크게 흔들릴 수 있습니다.")
    tbl = pd.DataFrame({AXES[axis]: c.index,
                        f"{wname}": [F.value(v, unit) for v in c["현재"]],
                        f"평소({bname})": [F.value(v, unit) for v in c["평소"]],
                        "변화": [F.won_signed(v) if unit == "won" else F.count(v, "개") for v in c["변화"]],
                        "변화율": [F.pct_signed(v) for v in c["변화율"]],
                        f"{noun} 중 비중": [F.pct(v) if pd.notna(v) else "" for v in c["비중"]]})
    if len(cmps) > 1:
        tbl[f"{cmps[1][0]} 변화율"] = [F.pct_signed(v) for v in cmps[1][4].reindex(c.index)["변화율"]]
    chart_df = c.head(12).reset_index().rename(columns={col: AXES[axis]})[[AXES[axis], "변화"]]
    chart = {"kind": "diverging_bar", "data": chart_df, "x": "변화", "y": AXES[axis], "unit": unit}
    return Result("location", f"{scope.label} {measure} 변화 위치 · {AXES[axis]}별",
                  scope.tags(wname, f"비교: {bname}"),
                  {"target": scope.label, "measure": measure, "axis": AXES[axis], "direction": "down" if down else "up",
                   "total": total, "top": top, "top_share": top_share, "window": wname, "base_name": bname},
                  facts, tbl, chart, notes, axes_left=[a for a in _axes_for(scope.kind) if a != axis])


# ---------------------------------------------------------------------------
# 4. 추이
# ---------------------------------------------------------------------------
def trend(m: dict, q: Query, today) -> Result:
    period = q.period or S.default_period(today, "trend")
    s, e = period
    scope = Scope(m, q, today, period)
    measure = q.measure or ("완료 매출" if scope.kind == "all" else "상품매출")
    scope.check_measure(measure)
    days = (e - s).days
    grain = "일" if days <= 35 else "주"
    idx = pd.date_range(s, e - pd.Timedelta(days=1), freq="D")
    if measure in RATIOS:
        num, den = RATIOS[measure]
        sn, sd = scope.daily(num).iloc[0].reindex(idx, fill_value=0), scope.daily(den).iloc[0].reindex(idx, fill_value=0)
    else:
        sn, sd = scope.daily(measure).iloc[0].reindex(idx, fill_value=0), None
    notes = []
    if grain == "주":
        wk = idx.to_period("W-SUN").start_time
        gn = sn.groupby(wk).sum()
        gd = sd.groupby(wk).sum() if sd is not None else None
        ndays = pd.Series(1, index=idx).groupby(wk).sum()
        if ndays.iloc[-1] < 7:
            notes.append(f"마지막 주는 {int(ndays.iloc[-1])}일치만 들어 있습니다.")
        if ndays.iloc[0] < 7:
            notes.append(f"첫 주는 {int(ndays.iloc[0])}일치만 들어 있습니다.")
    else:
        gn, gd = sn, sd
    val = (gn / gd.where(gd > 0)) if gd is not None else gn
    unit = MEASURE_UNIT[measure]
    label = "주 시작일" if grain == "주" else "날짜"
    df = val.rename_axis(label).reset_index(name=measure)
    full = df.iloc[1:-1] if grain == "주" and len(df) > 2 else df
    hi = full.loc[full[measure].idxmax()] if len(full) else None
    lo = full.loc[full[measure].idxmin()] if len(full) else None
    facts = []
    if hi is not None:
        facts.append(f"{grain}별 최고: {F.day(hi[label])}{' 주' if grain == '주' else ''} {F.value(hi[measure], unit)}")
        facts.append(f"{grain}별 최저: {F.day(lo[label])}{' 주' if grain == '주' else ''} {F.value(lo[measure], unit)}")
    tbl = df.assign(**{label: df[label].map(F.day), measure: df[measure].map(lambda v: F.value(v, unit))})
    chart = {"kind": "line", "data": df, "x": label, "y": measure, "unit": unit}
    return Result("trend", f"{scope.label} {grain}별 {measure} 추이", scope.tags(F.span(s, e), f"{grain} 단위"),
                  {"target": scope.label, "measure": measure, "grain": grain,
                   "high": None if hi is None else (hi[label], hi[measure]),
                   "low": None if lo is None else (lo[label], lo[measure])},
                  facts, tbl, chart, notes)


# ---------------------------------------------------------------------------
# 5. 후보 찾기 (어디를 밀까)
# ---------------------------------------------------------------------------
KIND_DOWN, KIND_UP, KIND_MARGIN = "비중이 크면서 줄고 있음", "오르고 있음", "잘 팔리는데 마진이 낮음"


def _promo_flags(m: dict, today) -> dict[str, str]:
    y = S.last_day(today)
    out = {}
    for p in B.promo_status(m, y):
        if p["phase"] == "진행 중":
            out[p["category"]] = f"{p['name']} 진행 중({F.day(p['start'])}~{F.day(p['end'])})"
        elif p["phase"] == "종료" and (y - p["end"]).days <= B.PROMO["show_after_end"]:
            out[p["category"]] = f"{p['name']} 종료 후 {(y - p['end']).days}일({F.day(p['start'])}~{F.day(p['end'])})"
    return out


def candidate_table(m: dict, q: Query, today) -> pd.DataFrame:
    """카테고리별 후보 판단 재료(숫자). 행 = 카테고리."""
    s, e = S.default_period(today, "rank")
    scope = Scope(m, Query("candidates", filters=q.filters), today, (s, e))
    it = scope.it[(scope.it["date"] >= s) & (scope.it["date"] < e)]
    g = it.groupby("category").agg(sales=("net_sales", "sum"), profit=("profit", "sum"),
                                   orders=("order_id", "nunique"))
    days = it.groupby(["category", "date"])["order_id"].nunique().unstack(fill_value=0) \
        .reindex(columns=pd.date_range(s, e - pd.Timedelta(days=1)), fill_value=0)
    g["share"] = g["sales"] / g["sales"].sum()
    g["margin"] = g["profit"] / g["sales"]
    g["daily_orders"] = days.mean(axis=1)
    g["sale_days"] = (days > 0).mean(axis=1)
    g["testable"] = (g["daily_orders"] >= S.MIN_DAILY_ORDERS) & (g["sale_days"] >= S.MIN_SALE_DAYS)
    cb = S.compare_both(S.daily(scope.o, scope.it, "상품매출", by="category"), today)
    g = g.join(cb[["3일_변화율", "3일_판정", "7일_변화", "7일_변화율", "7일_판정"]])
    g.attrs.update(share_avg=1 / len(g), orders_avg=g["orders"].mean(),
                   margin_shop=g["profit"].sum() / g["sales"].sum(), period=(s, e))
    return g


def candidates(m: dict, q: Query, today) -> Result:
    g = candidate_table(m, q, today)
    a = g.attrs
    flags = _promo_flags(m, today)
    rows = []
    for cat, r in g.iterrows():
        kinds = []
        if r["share"] >= a["share_avg"] and r["3일_판정"] == S.LEVEL_LOW and r["7일_판정"] == S.LEVEL_LOW:
            kinds.append((KIND_DOWN, f"비중 {F.pct(r['share'], 1)}(평균 {F.pct(a['share_avg'], 1)} 이상), "
                                     f"3일 {F.pct_signed(r['3일_변화율'])} · 7일 {F.pct_signed(r['7일_변화율'])}"))
        if r["3일_판정"] == S.LEVEL_HIGH and r["7일_판정"] == S.LEVEL_HIGH:
            kinds.append((KIND_UP, f"3일 {F.pct_signed(r['3일_변화율'])} · 7일 {F.pct_signed(r['7일_변화율'])}"))
        if r["orders"] >= a["orders_avg"] and r["margin"] < a["margin_shop"]:
            kinds.append((KIND_MARGIN, f"주문 {F.count(r['orders'])}(평균 {F.count(a['orders_avg'])} 이상), "
                                       f"이익률 {F.pct(r['margin'], 1)}(쇼핑몰 {F.pct(a['margin_shop'], 1)}보다 낮음)"))
        only3 = (r["3일_판정"] in (S.LEVEL_LOW, S.LEVEL_HIGH) and r["7일_판정"] != r["3일_판정"])
        for kind, why in kinds:
            rows.append({"유형": kind, "카테고리": cat, "근거": why,
                         "효과 확인": "가능" if r["testable"] else f"어려움(하루 주문 {r['daily_orders']:.1f}건)",
                         "최근 프로모션": flags.get(cat, ""), "_impact": abs(r["7일_변화"] or 0)})
        if only3 and not kinds:
            rows.append({"유형": "최근 3일만 변화(후보 아님)", "카테고리": cat,
                         "근거": f"3일 {F.pct_signed(r['3일_변화율'])} · 7일 {F.pct_signed(r['7일_변화율'])}",
                         "효과 확인": "", "최근 프로모션": flags.get(cat, ""), "_impact": abs(r["7일_변화"] or 0)})
    if q.category:
        rows = [x for x in rows if x["카테고리"] == q.category]
    order = {KIND_DOWN: 0, KIND_UP: 1, KIND_MARGIN: 2}
    tbl = pd.DataFrame(rows, columns=["유형", "카테고리", "근거", "효과 확인", "최근 프로모션", "_impact"])
    tbl = tbl.sort_values(["유형", "_impact"], key=lambda c: c.map(order).fillna(9) if c.name == "유형" else -c) \
        .drop(columns="_impact").reset_index(drop=True)
    real = tbl[tbl["유형"].isin(order)]
    by_kind = {k: real.loc[real["유형"].eq(k), "카테고리"].tolist() for k in order}
    facts = [f"{k}: " + (", ".join(v) if v else "없음") for k, v in by_kind.items()]
    s, e = a["period"]
    notes = [f"비중·주문·이익률은 최근 28일({F.span(s, e)}), 증감은 지난 {S.WEEKS}주 같은 요일 대비입니다.",
             f"줄고 있음·오르고 있음은 최근 3일과 7일이 모두 ±{S.BAND:.0%} 밖이고 방향이 같을 때만 후보로 봅니다."]
    if q.category and real.empty:
        facts = [f"{q.category}은(는) 지금 기준으로 후보에 해당하지 않습니다."] + facts[:0]
    return Result("candidates", "밀어 볼 카테고리 후보", ["최근 28일 · 3일 · 7일"] + ([q.category] if q.category else []),
                  {"by_kind": by_kind, "category": q.category}, facts, tbl, None, notes)


# ---------------------------------------------------------------------------
# 6. 수단 참고 (무엇으로 밀까: 판단 재료만)
# ---------------------------------------------------------------------------
def levers(m: dict, q: Query, today) -> Result:
    if not (q.category or q.product):
        raise ValueError("수단 참고는 대상 카테고리가 있어야 합니다.")
    s, e = S.default_period(today, "rank")
    scope = Scope(m, q, today, (s, e))
    it = scope.it[(scope.it["date"] >= s) & (scope.it["date"] < e)]
    oid = it["order_id"].unique()
    o = scope.o.set_index("order_id").loc[oid]
    has_coupon = o["discount"].gt(0) if "discount" in o else o["has_coupon"].astype(bool)
    x = it.assign(coupon=it["order_id"].map(has_coupon))
    by = x.groupby("coupon").agg(sales=("net_sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
    m_c = by.loc[True, "profit"] / by.loc[True, "sales"] if True in by.index and by.loc[True, "sales"] else None
    m_n = by.loc[False, "profit"] / by.loc[False, "sales"] if False in by.index and by.loc[False, "sales"] else None
    under = (o["items_amount"] < S.FREE_SHIP_THRESHOLD).mean() if len(o) else None
    margin = it["profit"].sum() / it["net_sales"].sum() if it["net_sales"].sum() else None
    rows = [("대상 주문(최근 28일)", F.count(len(oid))),
            ("현재 이익률", F.pct(margin, 1)),
            ("쿠폰을 쓴 주문 비중", F.pct(has_coupon.mean(), 1) if len(o) else "–"),
            ("쿠폰을 쓴 주문의 이익률", F.pct(m_c, 1)),
            ("쿠폰을 안 쓴 주문의 이익률", F.pct(m_n, 1)),
            (f"무료배송 기준({S.FREE_SHIP_THRESHOLD:,}원) 미만 주문 비중", F.pct(under, 1))]
    facts = [f"{scope.label} 최근 28일 이익률 {F.pct(margin, 1)} (대상 주문 {F.count(len(oid))})",
             f"쿠폰을 쓴 주문 {F.pct(has_coupon.mean(), 1)} · 이익률 {F.pct(m_c, 1)} (안 쓴 주문 {F.pct(m_n, 1)})",
             f"무료배송 기준({S.FREE_SHIP_THRESHOLD:,}원) 미만 주문 {F.pct(under, 1)}"]
    cat = q.category or m["raw"]["product"].set_index("product_name").loc[q.product, "category"]
    if isinstance(cat, pd.Series):
        cat = cat.iloc[0]
    past = [p for p in B.promo_status(m, S.last_day(today)) if p["category"] == cat]
    for p in past:
        rows.append((f"지난 프로모션: {p['name']}", f"{F.day(p['start'])}~{F.day(p['end'])} · {p['phase']} · 판정 {p['status']}"))
    notes = ["쿠폰을 쓴 주문과 안 쓴 주문의 차이는 상관관계일 뿐, 쿠폰이 효과가 있다는 근거가 아닙니다.",
             "수단별 손익은 Growth Lab에서 확인합니다."]
    tbl = pd.DataFrame(rows, columns=["항목", "값"])
    return Result("levers", f"{scope.label} 수단 참고", scope.tags(f"최근 28일({F.span(s, e)})"),
                  {"target": scope.label, "margin": margin, "coupon_share": has_coupon.mean() if len(o) else None,
                   "margin_coupon": m_c, "margin_no_coupon": m_n, "under_free_ship": under,
                   "past": [p["name"] for p in past]},
                  facts, tbl, None, notes)


# ---------------------------------------------------------------------------
# 7. 프로모션 실적
# ---------------------------------------------------------------------------
def promo(m: dict, q: Query, today) -> Result:
    ps = B.promo_status(m, S.last_day(today))
    if q.category:
        ps = [p for p in ps if p["category"] == q.category]
    rows, facts = [], []
    for p in ps:
        rows.append({"프로모션": p["name"], "기간": f"{F.day(p['start'])}~{F.day(p['end'])}", "단계": p["phase"],
                     "판정": p["status"], "대상 일평균 매출": F.pct_signed(p["sales_chg"]),
                     "다른 카테고리 대비 효과": F.pct_signed(p["effect"]),
                     "이익률": f"{F.pct(p['margin_pre'], 1)} → {F.pct(p['margin_dur'], 1)}"})
        facts.append(f"{p['name']}({p['phase']}): {p['status']} · 대상 일평균 매출 {F.pct_signed(p['sales_chg'])} · "
                     f"이익률 {F.pct(p['margin_pre'], 1)} → {F.pct(p['margin_dur'], 1)}")
    if ps:
        facts.insert(0, f"프로모션 {F.count(len(ps))}")
    else:
        facts = [f"{q.category + ' ' if q.category else ''}프로모션 기록이 없습니다."]
    notes = ["판정: 시작 전 14일 대비 대상 카테고리 일매출 비중 변화(95% 구간), 이익률이 8%p 넘게 떨어지면 중단 검토.",
             "10월 프로모션은 모의 데이터입니다."]
    return Result("promo", "프로모션 실적", [q.category] if q.category else [],
                  {"promos": [(p["name"], p["phase"], p["status"]) for p in ps], "count": F.count(len(ps))},
                  facts, pd.DataFrame(rows) if rows else None, None, notes)


# ---------------------------------------------------------------------------
# 8. 퍼널·테마
# ---------------------------------------------------------------------------
def funnel_theme(m: dict, q: Query, today) -> Result:
    if q.category or q.product:
        raise ValueError("방문 단계(퍼널)와 테마 반응은 카테고리·상품별로 나눌 수 없습니다.")
    period = q.period or S.default_period(today, "rank")
    s, e = period
    scope = Scope(m, q, today, period)
    if not scope.sessions_ok:
        raise ValueError("첫 구매/기존 고객은 주문 기준이라 방문 단계에는 적용할 수 없습니다.")
    base, bname = S.baseline(s, e)
    if (q.topic or "funnel") == "funnel":
        path = q.path or "ALL"
        ses = scope.m["sessions"]
        cur = M.funnel(M.in_period(ses, "start", s, e), path)
        tbl = cur.rename(columns={"직전 단계 대비 전환율": "직전 단계 대비"})
        if base:
            prev = M.funnel(ses[ses["start"].dt.normalize().isin([d for b in base for d in b])], path)
            tbl[f"평소({bname})"] = prev["직전 단계 대비 전환율"].map(lambda v: F.pct(v, 1))
        tbl["세션 수"] = tbl["세션 수"].map(lambda v: F.count(v, "세션"))
        tbl["직전 단계 대비"] = tbl["직전 단계 대비"].map(lambda v: F.pct(v, 1))
        tbl = tbl.drop(columns=["첫 단계 대비"])
        steps = cur.dropna(subset=["직전 단계 대비 전환율"])
        wi = steps["직전 단계 대비 전환율"].idxmin()
        worst = steps.loc[wi]
        step_name = f"{cur.loc[wi - 1, '단계']} → {worst['단계']}"
        pname = {"ALL": "전체", "CURATION": "큐레이션 경유", "BROWSE": "일반 탐색"}[path]
        facts = [f"{pname} 방문 {F.count(cur.iloc[0]['세션 수'], '세션')} 중 구매 완료 {F.pct(cur.iloc[-1]['첫 단계 대비'], 1)}",
                 f"넘어가는 비율이 가장 낮은 단계: {step_name}({F.pct(worst['직전 단계 대비 전환율'], 1)})"]
        chart = {"kind": "funnel", "data": cur[["단계", "세션 수"]], "x": "세션 수", "y": "단계", "unit": "count"}
        return Result("funnel_theme", f"{pname} 구매 단계", scope.tags(F.span(s, e), f"비교: {bname}"),
                      {"topic": "funnel", "path": pname, "worst": step_name, "sessions": cur.iloc[0]["세션 수"],
                       "conv": cur.iloc[-1]["첫 단계 대비"], "worst_rate": worst["직전 단계 대비 전환율"]}, facts, tbl, chart, [])
    th = M.theme_table(scope.m, s, e)
    th = th[th["노출세션"] > 0]
    tbl = pd.DataFrame({"테마": th["테마"], "노출 방문": th["노출세션"].map(lambda v: F.count(v, "세션")),
                        "클릭률": th["클릭률"].map(lambda v: F.pct(v, 1)),
                        "장바구니→구매": th["장바구니→구매"].map(lambda v: F.pct(v, 1)),
                        "구매 전환율": th["구매전환율"].map(lambda v: F.pct(v, 1))})
    best = th.loc[th["구매전환율"].idxmax()]
    click = th.loc[th["클릭률"].idxmax()]
    facts = [f"구매 전환율 1위: {best['테마']}({F.pct(best['구매전환율'], 1)})",
             f"클릭률 1위: {click['테마']}({F.pct(click['클릭률'], 1)})"]
    chart = {"kind": "scatter", "data": th[["테마", "클릭률", "구매전환율"]].rename(columns={"구매전환율": "구매 전환율"}),
             "x": "클릭률", "y": "구매 전환율", "label": "테마", "unit": "rate"}
    return Result("funnel_theme", "큐레이션 테마 반응", scope.tags(F.span(s, e)),
                  {"topic": "theme", "best": best["테마"], "best_rate": best["구매전환율"],
                   "click": click["테마"], "click_rate": click["클릭률"]}, facts, tbl, chart, [])


# ---------------------------------------------------------------------------
FUNCS = {"status": status, "rank": rank, "location": location, "trend": trend, "candidates": candidates,
         "levers": levers, "promo": promo, "funnel_theme": funnel_theme}
assert set(FUNCS) == set(INTENTS)


def run(m: dict, q: Query, today) -> Result:
    return FUNCS[q.intent](m, q, today)

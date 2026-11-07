"""AI 분석가(챗봇)가 부르는 도구.

원칙
- 숫자는 전부 core/metrics.py 함수가 만든다. 도구는 그 결과를 '요약 문장 + 차트 + 표' 한 가지 모양으로 묶을 뿐이다.
- LLM은 질문을 보고 TOOLS 중 하나를 골라 params를 채운다(기간은 YYYY-MM-DD, 끝 날짜 미포함).
- 결과(dict)
    title: 제목, period: 기준 기간 문구, facts: 데이터로 확인된 사실 문장 목록,
    chart: {"kind": bar|line|scatter|funnel, "data": DataFrame, "x", "y", "color"?, "x_fmt"?, "y_fmt"?} 또는 None,
    table: DataFrame 또는 None, notes: 해석 주의 문구 목록
- 원인·대책 같은 '가설'은 도구가 만들지 않는다. LLM이 facts를 근거로, 가설임을 밝혀 덧붙인다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import analysis as A
from . import metrics as M
from . import simulation as S
from .data import PERIOD_END, PERIOD_START

LAST_DAY = PERIOD_END - pd.Timedelta(days=1)


# ---------------------------------------------------------------------------
# 표시 도우미 (ui.py는 streamlit을 불러오므로 여기서는 쓰지 않는다)
# ---------------------------------------------------------------------------
def won(v):
    if v is None or pd.isna(v):
        return "–"
    if abs(v) >= 1e8:
        return f"{v/1e8:,.2f}억원"
    if abs(v) >= 1e6:
        return f"{v/1e4:,.0f}만원"
    return f"{v:,.0f}원"


def pct(v, d=1):
    return "–" if v is None or pd.isna(v) else f"{v*100:.{d}f}%"


def chg(cur, prev, rate=False):
    if prev is None or pd.isna(prev) or pd.isna(cur):
        return ""
    if rate:
        return f" (비교 기간 대비 {(cur - prev) * 100:+.1f}%p)"
    return "" if prev == 0 else f" (비교 기간 대비 {(cur - prev) / prev * 100:+.1f}%)"


def _period(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    s, e = max(s, PERIOD_START), min(e, PERIOD_END)
    if s >= e:
        raise ValueError(f"데이터가 있는 기간은 {PERIOD_START:%Y-%m-%d} ~ {LAST_DAY:%Y-%m-%d} 입니다.")
    return s, e


def _label(p) -> str:
    return f"{p[0]:%Y-%m-%d} ~ {p[1] - pd.Timedelta(days=1):%Y-%m-%d}"


def _with_prev(start, end, compare=True):
    cur = _period(start, end)
    prev = M.compare_period(*cur) if compare else None
    return cur, prev, f"{_label(cur)}" + (f" (비교 {_label(prev)})" if prev else "")


def _result(title, period, facts, chart=None, table=None, notes=None):
    return {"title": title, "period": period, "facts": facts, "chart": chart, "table": table, "notes": notes or []}


# ---------------------------------------------------------------------------
# 도구
# ---------------------------------------------------------------------------
def get_kpis(m, start, end, compare=True):
    cur, prev, plabel = _with_prev(start, end, compare)
    k = M.kpis(m, *cur)
    kp = M.kpis(m, *prev) if prev else {}
    g = kp.get
    rows = [("완료 매출", won(k["revenue"]), chg(k["revenue"], g("revenue"))),
            ("완료 주문 수", f"{k['orders']:,}건", chg(k["orders"], g("orders"))),
            ("구매 고객 수", f"{k['buyers']:,}명", chg(k["buyers"], g("buyers"))),
            ("객단가", won(k["aov"]), chg(k["aov"], g("aov"))),
            ("세션 구매 전환율", pct(k["cvr"]), chg(k["cvr"], g("cvr"), True)),
            ("재구매 고객 비중", pct(k["repeat_rate"]), chg(k["repeat_rate"], g("repeat_rate"), True)),
            ("쿠폰 사용 주문 비중", pct(k["coupon_order_share"]), chg(k["coupon_order_share"], g("coupon_order_share"), True)),
            ("취소·환불 비중", pct(k["cancel_refund_rate"]), chg(k["cancel_refund_rate"], g("cancel_refund_rate"), True))]
    facts = [f"{a} {b}{c}" for a, b, c in rows]
    st_ = M.order_status_summary(m, *cur)
    facts.append(f"주문 접수(취소·환불 포함 전체) {int(st_['주문수'].sum()):,}건, 결제 금액 {won(st_['금액'].sum())} "
                 "(완료 매출은 이 중 완료 주문만)")
    table = st_.rename(columns={"order_status": "주문 상태"})
    return _result("핵심 지표", plabel, facts, None, table,
                   ["완료 매출은 배송비 포함 결제 금액(회계 순매출 아님)", "재구매 고객 비중은 기간이 짧을수록 낮게 나옴"])


def get_coupon_efficiency(m, start, end):
    cur = _period(start, end)
    ce = M.coupon_efficiency(m, *cur)
    t, by = ce["total"], ce["by_coupon"]
    facts = [f"쿠폰 할인 {won(t['discount'])}에 쿠폰 사용 주문 매출 {won(t['coupon_sales'])}, 효율 {t['efficiency']:.1f}배",
             f"쿠폰 사용 주문 {t['coupon_orders']:,}건 (완료 주문의 {pct(t['coupon_order_share'])})",
             f"객단가: 쿠폰 주문 {won(t['aov_coupon'])} vs 미사용 주문 {won(t['aov_no_coupon'])}"]
    big = by[by["주문수"] >= 30]
    if len(big):
        facts.append(f"주문 30건 이상 쿠폰 중 효율 1위: {big['쿠폰'].iloc[0]} ({big['효율'].iloc[0]:.1f}배)")
    chart = {"kind": "bar", "data": by, "x": "효율", "y": "쿠폰", "x_fmt": ".1f"}
    return _result("쿠폰 효율", _label(cur), facts, chart, by[["쿠폰", "할인 방식", "주문수", "할인액", "쿠폰주문매출", "효율"]],
                   ["쿠폰 때문에 생긴 매출이 아니라 쿠폰을 쓴 주문의 매출(쿠폰 없이도 샀을 고객 포함)",
                    "ROAS는 광고비·광고 유입 데이터가 없어 계산할 수 없음"])


def rank_items(m, start, end, target="product", n=5, metric="매출"):
    cur = _period(start, end)
    if target == "category":
        df = M.category_sales(m, *cur).rename(columns={"category": "카테고리", "net_sales": "상품매출"})
        facts = [f"{i+1}위 {r.카테고리}: {won(r.상품매출)} ({pct(r.비중)})" for i, r in enumerate(df.head(n).itertuples())]
        chart = {"kind": "bar", "data": df, "x": "상품매출", "y": "카테고리", "x_fmt": "~s"}
        title = "카테고리별 매출"
    else:
        qty = metric == "수량"
        df = M.top_products(m, *cur, n=n, sort="수량" if qty else "상품매출").rename(
            columns={"product_name": "상품", "category": "카테고리"})
        facts = [f"{i+1}위 {r.상품} ({r.카테고리}): " + (f"판매 수량 {r.수량:,}개, 상품매출 {won(r.상품매출)}" if qty else
                 f"{won(r.상품매출)}, 구매 고객 {r.구매고객:,}명") for i, r in enumerate(df.itertuples())]
        chart = {"kind": "bar", "data": df, "x": "수량" if qty else "상품매출", "y": "상품", "x_fmt": "," if qty else "~s"}
        title = f"{'판매 수량' if qty else '상품매출'} TOP {n}"
    return _result(title, _label(cur), facts, chart, df, ["상품매출 = 완료 주문의 쿠폰 차감 후 상품금액(배송비 제외)",
                                                          "기준을 밝히지 않은 '잘 팔린'은 매출 기준. 판매 개수 기준은 metric=수량"])


def explain_revenue_change(m, start, end):
    cur, prev, plabel = _with_prev(start, end)
    if prev is None:
        raise ValueError("비교할 직전 기간이 데이터 범위(4/1~) 밖입니다.")
    d = M.revenue_decomposition(m, cur, prev)
    k, kp = M.kpis(m, *cur), M.kpis(m, *prev)
    direction = "늘었습니다" if d["revenue_change"] >= 0 else "줄었습니다"
    facts = [f"완료 매출이 {won(kp['revenue'])} → {won(k['revenue'])}로 {won(abs(d['revenue_change']))} {direction}",
             f"주문 수 변화 효과 {won(d['order_effect'])} (주문 {kp['orders']:,} → {k['orders']:,}건)",
             f"객단가 변화 효과 {won(d['aov_effect'])} (객단가 {won(kp['aov'])} → {won(k['aov'])})"]
    ch = M.detect_changes(m, cur, prev)
    if ch:
        facts.append("함께 달라진 지표: " + ", ".join(f"{c['title']}({c['direction']})" for c in ch[:3]))
    data = pd.DataFrame({"요인": ["주문 수 효과", "객단가 효과"], "금액": [d["order_effect"], d["aov_effect"]]})
    return _result("매출 변화 나눠 보기", plabel, facts, {"kind": "bar", "data": data, "x": "금액", "y": "요인", "x_fmt": "~s"},
                   None, ["원인은 이 분해만으로 확정할 수 없음. 함께 달라진 지표는 '확인할 후보'"])


def compare_items(m, start, end, target="product", direction="down", n=None, metric="매출"):
    """n이 없으면(질문에 개수가 없으면) 해당 방향 항목 전부. 사실 문장은 앞 10개까지만, 나머지는 표에."""
    cur, prev, plabel = _with_prev(start, end)
    if prev is None:
        raise ValueError("비교할 직전 기간이 데이터 범위(4/1~) 밖입니다.")
    qty = metric == "수량"
    df = M.item_changes(m, cur, prev, target=target, metric=metric)
    what = "상품" if target == "product" else "카테고리"
    obj = "상품을" if target == "product" else "카테고리를"
    unit = "판매 수량" if qty else "상품매출"
    fmt = (lambda v: f"{v:,.0f}개") if qty else won
    down = direction != "up"
    sel = df[df["변화"] < 0].sort_values("변화") if down else df[df["변화"] > 0].sort_values("변화", ascending=False)
    if n:
        sel = sel.head(int(n))
    name = (lambda r: f"{r.product_name} ({r.category})") if target == "product" else (lambda r: r.category)
    facts = [f"비교: {_label(prev)} → {_label(cur)}, 같은 {obj} 두 기간에 맞대어 {unit} 비교",
             f"{unit}이 줄어든 {what} {int((df['변화'] < 0).sum()):,}개, 늘어난 {what} {int((df['변화'] > 0).sum()):,}개 "
             f"(두 기간 중 한 번이라도 팔린 {len(df):,}개 중)"]
    for i, r in enumerate(sel.head(10).itertuples()):
        rate = "" if pd.isna(r.변화율) else f", {r.변화율 * 100:+.1f}%"
        facts.append(f"{i+1}위 {name(r)}: {fmt(r.이전)} → {fmt(r.현재)} ({'+' if r.변화 > 0 else ''}{fmt(r.변화)}{rate})")
    if len(sel) > 10:
        facts.append(f"외 {len(sel) - 10:,}개 {what}은 표에 있음 (전체 {len(sel):,}개)")
    if sel.empty:
        facts.append(f"{unit}이 {'줄어든' if down else '늘어난'} {what}이 없습니다.")
    label_col = "product_name" if target == "product" else "category"
    amt = f"{unit} {'감소' if down else '증가'}" + ("량" if qty else "액")
    chart_df = sel.assign(**{amt: sel["변화"].abs()}).rename(columns={label_col: what})
    chart = {"kind": "bar", "data": chart_df, "x": amt, "y": what, "x_fmt": "," if qty else "~s"} if len(sel) else None
    cols = (["product_name", "category"] if target == "product" else ["category"])
    table = sel[cols + ["이전", "현재", "변화", "변화율"]].rename(columns={
        "product_name": "상품", "category": "카테고리", "이전": f"비교 기간 {unit}", "현재": f"분석 기간 {unit}"})
    notes = [f"각 기간의 TOP 목록끼리 비교한 것이 아니라 같은 {what}의 두 기간 값을 맞대어 본 변화",
             f"{'감소' if down else '증가'}{'량' if qty else '액'}이 큰 순. 비교 기간에 안 팔린 {what}은 변화율 없음"]
    if not qty:
        notes.append("상품매출 = 완료 주문의 쿠폰 차감 후 상품금액(배송비 제외)")
    disp = table.copy()
    for c in (f"비교 기간 {unit}", f"분석 기간 {unit}"):
        disp[c] = disp[c].map(fmt)
    disp["변화"] = disp["변화"].map(lambda v: ("+" if v > 0 else "") + fmt(v))
    disp["변화율"] = disp["변화율"].map(lambda v: "–" if pd.isna(v) else f"{v * 100:+.1f}%")
    title = f"{unit}이 {'줄어든' if down else '늘어난'} {what}" + (f" TOP {int(n)}" if n else f" {len(sel):,}개")
    res = _result(title, plabel, facts, chart, table, notes)
    res["display_table"] = disp
    return res


SLICE_SUFFIX = {"주문수": "건", "구매고객수": "명", "판매수량": "개", "방문수": "세션"}
ITEM_ONLY = {"상품", "카테고리"}


def _slice_fmt(metric):
    unit = A.SLICE_METRICS[metric][1]
    if unit == "won":
        return won, lambda v: ("+" if v > 0 else "") + won(v)
    if unit == "rate":
        return pct, lambda v: f"{v * 100:+.1f}%p"
    suf = SLICE_SUFFIX.get(metric, "")
    return (lambda v: f"{v:,.0f}{suf}"), (lambda v: f"{v:+,.0f}{suf}")


def _dim_label(v):
    return f"{v:%Y-%m-%d}" if isinstance(v, pd.Timestamp) else f"{v}시" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def analyze(m, start, end, measure="매출", dims=None, sort="높은순", n=10, compare=False):
    """조립형 분석: 지표(measure) × 기준(dims, 1~2개) × 기간(+ 직전 기간 비교). 계산은 metrics.slice_metric.
    (입력 이름이 다른 도구의 metric·by와 겹치지 않게 measure·dims를 쓴다)"""
    metric = measure
    by = [dims] if isinstance(dims, str) else list(dims or [])
    by = list(dict.fromkeys(by))[:2]
    if not by:
        raise ValueError("dims(무엇별로 볼지)를 1~2개 골라야 합니다. 예: ['요일'], ['카테고리', '성별']")
    bad = [b for b in by if b not in A.SLICE_DIMS]
    if bad or metric not in A.SLICE_METRICS:
        raise ValueError(f"지원하지 않는 {'기준: ' + ', '.join(bad) if bad else '지표: ' + str(metric)}. "
                         f"지표: {', '.join(A.SLICE_METRICS)} / 기준: {', '.join(A.SLICE_DIMS)}")
    notes = []
    if ITEM_ONLY & set(by):
        if metric == "매출":
            metric = "상품매출"
            notes.append("상품·카테고리별 매출은 상품매출(쿠폰 차감 후 상품금액, 배송비 제외)로 계산")
        if metric in ("객단가", "방문수", "구매전환율", "장바구니율"):
            raise ValueError(f"{metric}은(는) 상품·카테고리별로 나눌 수 없습니다. 상품매출·판매수량·주문수·구매고객수를 쓰세요.")
    unit = A.SLICE_METRICS[metric][0]
    bad = [b for b in by if unit not in A.SLICE_DIMS[b][1] and not (b in ITEM_ONLY)]
    if bad:
        raise ValueError(f"{metric}은(는) 방문 단위 지표라 '{', '.join(bad)}' 기준으로 나눌 수 없습니다(주문 단위 기준).")
    if sort in ("감소순", "증가순"):
        compare = True
    cur = _period(start, end)
    prev = M.compare_period(*cur) if compare else None
    if compare and prev is None:
        raise ValueError("비교할 직전 기간이 데이터 범위(4/1~) 밖입니다.")
    if unit == "order" and ITEM_ONLY & set(by):      # 주문수·구매고객수를 상품·카테고리별로
        calc = lambda p: _item_slice(m, p, metric, by)
    else:
        calc = lambda p: A.slice_metric(m, *p, metric, by)
    df = calc(cur)
    rate = A.SLICE_METRICS[metric][1] == "rate"
    if prev is not None:
        dp = calc(prev).rename(columns={"값": "이전", "표본": "이전 표본"})
        df = df.merge(dp, on=by, how="outer")
        if not rate:
            df[["값", "이전"]] = df[["값", "이전"]].fillna(0)
        df["변화"] = df["값"] - df["이전"]
        if not rate:
            df["변화율"] = df["변화"] / df["이전"].replace(0, np.nan)
    df["표본"] = df["표본"].fillna(0)
    small = rate & (df["표본"] < 30)
    fmt, dfmt = _slice_fmt(metric)
    ordered = len(by) == 1 and (by[0] in A.ORDERED_DIMS or by[0] in A.TIME_DIMS)
    if ordered and by[0] in A.ORDERED_DIMS:
        df = df.assign(_o=df[by[0]].map({v: i for i, v in enumerate(A.ORDERED_DIMS[by[0]])})).sort_values("_o").drop(columns="_o")
    elif ordered:
        df = df.sort_values(by[0])
    ok = df[~small] if rate else df
    if sort in ("감소순", "증가순"):
        ranked = ok[ok["변화"] < 0].sort_values("변화") if sort == "감소순" else ok[ok["변화"] > 0].sort_values("변화", ascending=False)
    else:
        ranked = ok.sort_values("값", ascending=sort == "낮은순")
    name = lambda r: " · ".join(_dim_label(r[b]) for b in by)
    facts = [f"지표: {A.SLICE_METRICS[metric][2]}, 기준: {' × '.join(by)}별"]
    if prev is not None:
        facts.append(f"비교: {_label(prev)} → {_label(cur)}")
    show = df if (ordered and sort in ("높은순", "낮은순") and len(df) <= 12) else ranked.head(int(n))
    for i, (_, r) in enumerate(show.iterrows()):
        line = f"{name(r)}: {fmt(r['값'])}"
        if prev is not None and pd.notna(r.get("이전")):
            line += f" (비교 기간 {fmt(r['이전'])}, {dfmt(r['변화'])}" + \
                    (f", {r['변화율'] * 100:+.1f}%" if not rate and pd.notna(r.get("변화율")) else "") + ")"
        if rate and r["표본"] < 30:
            line += f" - 표본 부족({int(r['표본'])}세션)"
        facts.append(("" if show is df and ordered else f"{i+1}위 ") + line)
    if ordered and len(ok) > 2 and sort in ("높은순", "낮은순"):
        hi, lo = ok.loc[ok["값"].idxmax()], ok.loc[ok["값"].idxmin()]
        facts.append(f"가장 높은 {by[0]}: {name(hi)} ({fmt(hi['값'])}), 가장 낮은 {by[0]}: {name(lo)} ({fmt(lo['값'])})")
    if sort in ("감소순", "증가순") and ranked.empty:
        facts.append(f"{'줄어든' if sort == '감소순' else '늘어난'} 항목이 없습니다.")
    if rate and small.any():
        notes.append("방문 30세션 미만 항목은 순위에서 빼고 '표본 부족'으로 표시")
    notes.append(A.SLICE_METRICS[metric][2])
    if "연령대" in by:
        notes.append("연령은 출생연도 기준 근사 나이(생일 정보 없음). 출생연도 없는 고객은 '정보 없음'")
    if unit == "session":
        notes.append("방문은 로그인 고객 세션만 셈")
    if {"주", "월"} & set(by):
        notes.append("처음·마지막 주(월)가 기간 중간에 걸리면 값이 작게 보일 수 있음. 주는 월요일 시작")
    # 차트
    if len(by) == 2:
        chart = {"kind": "heatmap", "data": df, "x": by[1], "y": by[0], "value": "값",
                 "fmt": ".1%" if rate else ",.0f", "x_order": A.ORDERED_DIMS.get(by[1]), "y_order": A.ORDERED_DIMS.get(by[0])}
    elif sort in ("감소순", "증가순"):
        amt = "감소 크기" if sort == "감소순" else "증가 크기"
        cd = ranked.head(int(n)).assign(**{amt: lambda d: d["변화"].abs(), by[0]: lambda d: d[by[0]].map(_dim_label)})
        chart = {"kind": "bar", "data": cd, "x": amt, "y": by[0], "x_fmt": ".1%" if rate else "~s"} if len(cd) else None
    elif by[0] in A.TIME_DIMS:
        chart = {"kind": "line", "data": df, "x": by[0], "y": "값", "y_fmt": ".1%" if rate else "~s"}
    elif ordered:
        cd = df.assign(**{by[0]: df[by[0]].map(_dim_label)})
        chart = {"kind": "bar", "vertical": True, "data": cd, "x": by[0], "y": "값", "y_fmt": ".1%" if rate else "~s"}
    else:
        cd = ranked.head(int(n)).assign(**{by[0]: lambda d: d[by[0]].map(_dim_label)})
        chart = {"kind": "bar", "data": cd, "x": "값", "y": by[0], "x_fmt": ".1%" if rate else "~s"}
    table = (df if ordered or len(by) == 2 else ranked.head(max(int(n), 30))).rename(columns={"값": metric})
    title = f"{' × '.join(by)}별 {metric}" + (f" ({sort})" if not ordered and len(by) == 1 else "")
    res = _result(title, _label(cur) + (f" (비교 {_label(prev)})" if prev is not None else ""), facts, chart, table, notes)
    # 화면용 표: 숫자를 원·%·건으로 (AI에 넘기는 table은 원래 숫자 그대로)
    disp = table.copy()
    for b in by:
        disp[b] = disp[b].map(_dim_label)
    for col in (metric, "이전"):
        if col in disp:
            disp[col] = disp[col].map(lambda v: "–" if pd.isna(v) else fmt(v))
    if "변화" in disp:
        disp["변화"] = disp["변화"].map(lambda v: "–" if pd.isna(v) else dfmt(v))
    if "변화율" in disp:
        disp["변화율"] = disp["변화율"].map(lambda v: "–" if pd.isna(v) else f"{v * 100:+.1f}%")
    disp = disp.rename(columns={"이전": "비교 기간", "표본": "표본(주문·세션 수)", "이전 표본": "비교 기간 표본"})
    if len(by) == 2:     # 교차표는 행 = 첫 기준, 열 = 둘째 기준
        pv = disp.pivot_table(index=by[0], columns=by[1], values=metric, aggfunc="first")
        for i, b in enumerate(by):
            order = [_dim_label(v) for v in (A.ORDERED_DIMS.get(b) or [])]
            if order:
                pv = pv.reindex(order, axis=i).dropna(how="all", axis=i)
        disp = pv.fillna("–").reset_index()
        disp.columns.name = None
    res["display_table"] = disp
    return res


def _item_slice(m, p, metric, by):
    """주문수·구매고객수를 상품·카테고리별로: 주문상품 단위에서 고유 주문·고객을 센다."""
    df = A._slice_frame(m, "item", *p, by)
    g = df.groupby(by, dropna=False, observed=True)
    col = "order_id" if metric == "주문수" else "customer_id"
    return g.agg(값=(col, "nunique"), 표본=("order_id", "nunique")).reset_index()


def get_trend(m, start, end, grain="month"):
    cur = _period(start, end)
    t = M.sales_trend(m, *cur, grain=grain)
    lab = {"date": "일", "week": "주", "month": "월"}[grain]
    best = t.loc[t["매출"].idxmax()]
    facts = [f"{lab}별 완료 매출: 최고 {best[grain]:%Y-%m-%d} {won(best['매출'])}",
             f"처음 {won(t['매출'].iloc[0])} → 마지막 {won(t['매출'].iloc[-1])}"]
    return _result(f"{lab}별 매출 추이", _label(cur), facts,
                   {"kind": "line", "data": t, "x": grain, "y": "매출", "y_fmt": "~s"}, t,
                   ["마지막 구간이 기간 중간에 끝나면 값이 작게 보일 수 있음"] if grain != "date" else [])


def get_funnel(m, start, end, path="ALL"):
    cur, prev, plabel = _with_prev(start, end)
    s = M.in_period(m["sessions"], "start", *cur)
    f = M.funnel(s, path)
    steps = f.iloc[1:-1]
    worst = steps.loc[steps["직전 단계 대비 전환율"].idxmin()]
    order = list(f["단계"])
    i = order.index(worst["단계"])
    facts = [f"{a} {int(n):,}세션" + (f" (직전 단계 대비 {pct(r)})" if pd.notna(r) else "")
             for a, n, r in zip(f["단계"], f["세션 수"], f["직전 단계 대비 전환율"])]
    facts.append(f"가장 많이 빠지는 구간: {order[i-1]} → {order[i]} ({pct(worst['직전 단계 대비 전환율'])})")
    sp = M.path_filter(s, path)
    facts.append(f"세션 구매 전환율(구매 세션 ÷ 방문 세션, {'전체' if path == 'ALL' else path}): {pct(sp['has_purchase'].mean())} "
                 f"({int(sp['has_purchase'].sum()):,} / {len(sp):,}세션)")
    # 경로 비교는 어느 경로를 보든 항상 함께 (경로 비교 질문의 기준 지표: 세션 구매 전환율)
    c, b = s[s["path"].eq("CURATION")], s[s["path"].eq("BROWSE")]
    _, p = M.two_prop_test(c["has_purchase"].sum(), len(c), b["has_purchase"].sum(), len(b))
    sig = "유의한 차이" if pd.notna(p) and p < 0.05 else "유의한 차이 아님"
    facts.append(f"세션 구매 전환율(구매 세션 ÷ 세션): 큐레이션 경유 {pct(c['has_purchase'].mean())} vs 일반 탐색 "
                 f"{pct(b['has_purchase'].mean())} (p={p:.3f}, {sig})")
    return _result("구매 퍼널", plabel, facts, {"kind": "funnel", "data": f, "x": "세션 수", "y": "단계"}, f,
                   ["'결제 진입' 이벤트가 없어 장바구니 다음이 바로 구매",
                    "경로별 차이는 고객 구성 차이일 수 있어 큐레이션 효과로 단정할 수 없음"])


def detect_changes(m, start, end, strict=True):
    cur, prev, plabel = _with_prev(start, end)
    if prev is None:
        raise ValueError("비교할 직전 기간이 데이터 범위(4/1~) 밖입니다.")
    alpha = 0.05 if strict else 0.20
    c = M.detect_changes(m, cur, prev, alpha=alpha)
    fmt = lambda x: won(x["previous"]) + " → " + won(x["current"]) if x["unit"] == "won" else pct(x["previous"]) + " → " + pct(x["current"])
    facts = [f"{x['title']} {x['direction']}: {fmt(x)}" for x in c[:6]] or ["기준을 넘는 큰 변화가 없습니다."]
    table = pd.DataFrame([{"변화": x["title"], "방향": x["direction"], "비교": x["previous"], "현재": x["current"],
                           "p값": x.get("p_value")} for x in c]) if c else None
    return _result(f"확인할 변화 {len(c)}개", plabel, facts, None, table,
                   [f"p<{alpha} 기준. 원인이 검토되지 않은 '확인할 후보'"])


def get_themes(m, start, end):
    cur = _period(start, end)
    tt, mx, my = M.theme_quadrant(m, *cur)
    best = tt.sort_values("구매전환율", ascending=False).iloc[0]
    low = tt.loc[tt["구분"].eq("관심↑ 구매↓"), "테마"].tolist()
    facts = [f"구매 전환율 1위: {best['테마']} ({pct(best['구매전환율'])})",
             f"클릭률 1위: {tt.sort_values('클릭률', ascending=False)['테마'].iloc[0]}",
             "관심은 높은데 구매가 낮은 테마: " + (", ".join(low) if low else "없음")]
    chart = {"kind": "scatter", "data": tt, "x": "클릭률", "y": "클릭후구매율", "color": "구분", "label": "테마",
             "x_fmt": ".0%", "y_fmt": ".0%"}
    table = tt[["테마", "노출세션", "클릭률", "클릭후구매율", "구매전환율", "경유매출", "구분"]]
    return _result("큐레이션 테마 반응", _label(cur), facts, chart, table,
                   ["사분면 기준선은 테마 중앙값", "경유 매출은 테마의 증분 효과가 아님"])


def get_retention(m, start, end):
    cur = _period(start, end)
    mix = M.customer_mix(m, *cur)
    g = M.repeat_gaps(m)
    facts = [f"첫 구매 고객 {int(mix.loc['첫 구매 고객', '고객수']):,}명 (매출 비중 {pct(mix.loc['첫 구매 고객', '매출 비중'])})",
             f"기존 구매 고객 {int(mix.loc['기존 구매 고객', '고객수']):,}명 (매출 비중 {pct(mix.loc['기존 구매 고객', '매출 비중'])})",
             f"재구매 간격 중앙값 {g['median_days']:.0f}일, 구매 고객당 완료 주문 {g['orders_per_buyer']:.2f}건 (전체 관측 기간)"]
    return _result("구매 고객 구성과 재구매", _label(cur), facts,
                   {"kind": "bar", "data": g["dist"], "x": "간격", "y": "비중", "vertical": True, "y_fmt": ".0%"},
                   mix.reset_index().rename(columns={"customer_type": "구분"}),
                   ["재구매 간격은 연속된 두 완료 주문 사이 일수"])


SEGMENT_BY = {"customer_type": "첫 구매/기존 구매 고객", "grade_at_order": "주문 당시 회원 등급", "visitor_type": "신규/재방문",
              "signup_channel": "가입 경로"}


def segment_preference(m, start, end, by="customer_type"):
    cur = _period(start, end)
    mix = M.segment_category_mix(m, *cur, by=by)
    labels = {"NEW": "신규 방문", "RETURNING": "재방문", "UNKNOWN": "판정 불가"}
    mix[by] = mix[by].map(lambda v: labels.get(v, v))
    facts = []
    for g, d in mix.sort_values("비중", ascending=False).groupby(by, sort=False):
        top = d.head(3)
        facts.append(f"{g}: " + ", ".join(f"{r.category} {pct(r.비중)}" for r in top.itertuples()))
    tops = mix.sort_values("비중", ascending=False).groupby(by).head(1)
    same = tops["category"].nunique() == 1
    facts.append("모든 고객군의 1위 카테고리가 같습니다: " + tops["category"].iloc[0] if same
                 else "고객군마다 1위 카테고리가 다릅니다")
    table = mix.rename(columns={by: SEGMENT_BY[by], "category": "카테고리", "net_sales": "상품매출"})
    return _result(f"{SEGMENT_BY[by]}별 선호 카테고리", _label(cur), facts,
                   {"kind": "bar", "data": tops.rename(columns={by: "고객군"}), "x": "비중", "y": "고객군", "x_fmt": ".0%"},
                   table, ["비중 = 고객군 상품매출 중 해당 카테고리 비중(행마다 합 100%)", "회원 등급은 현재가 아니라 주문 당시 등급"])


def segment_repeat(m, by="customer_type", start=None, end=None):
    """고객군별 30일 재구매율. 기간 입력은 받지만 쓰지 않는다(전체 관측 기간 기준)."""
    r = M.segment_repeat(m, by=by)
    ok = r[r["표본 충분"]]
    facts = [f"{x['고객군']}: 30일 재구매율 {pct(x['재구매율'])} (대상 {int(x['대상 고객']):,}명)"
             + ("" if x["표본 충분"] else " - 표본 부족") for _, x in r.iterrows()]
    if len(ok) >= 2:
        lo, hi = ok.iloc[0], ok.iloc[-1]
        rest = ok.iloc[1:]
        _, p = M.two_prop_test(lo["재구매 고객"], lo["대상 고객"], rest["재구매 고객"].sum(), rest["대상 고객"].sum())
        sig = "다른 고객군과 유의한 차이" if pd.notna(p) and p < 0.05 else "다른 고객군과 유의한 차이 아님"
        facts.insert(0, f"가장 낮은 고객군: {lo['고객군']} ({pct(lo['재구매율'])}, p={p:.3f}, {sig}) · "
                        f"가장 높은 고객군: {hi['고객군']} ({pct(hi['재구매율'])})")
    label = "첫 주문 당시 회원 등급" if by == "grade_at_order" else SEGMENT_BY[by]
    return _result(f"{label}별 30일 재구매율", "전체 관측 기간(2026-04-01 ~ 2026-09-30)", facts,
                   {"kind": "bar", "data": r, "x": "재구매율", "y": "고객군", "x_fmt": ".0%"}, r,
                   ["관측 기간 첫 완료 주문 후 30일 안에 다시 완료 주문한 고객 비율",
                    "30일이 관측 기간 안에 끝나는 고객(첫 주문 2026-08-31 이전)만 대상",
                    "대상 30명 미만 고객군은 순위에서 제외"])


def get_segments(m, start, end):
    cur = _period(start, end)
    s = M.rfm_summary(m, *cur)
    d = s.set_index("고객군")
    facts = [f"{r['고객군']}: {int(r['고객수']):,}명 (고객 {pct(r['고객 비중'])}, 매출 {pct(r['매출 비중'])})" for _, r in s.iterrows()]
    facts.insert(0, f"휴면 추정 고객 {int(d.loc['휴면 추정', '고객수']):,}명 ({pct(d.loc['휴면 추정', '고객 비중'])})")
    return _result("RFM 고객군", f"기준일 {cur[1] - pd.Timedelta(days=1):%Y-%m-%d}, 매출은 {_label(cur)}", facts,
                   {"kind": "bar", "data": s, "x": "고객수", "y": "고객군", "x_fmt": ","}, s,
                   ["구매 이력 규칙으로 나눈 고객군이며 이탈 확률이 아님"])


def find_potential_products(m, start, end, n=5):
    cur, prev, plabel = _with_prev(start, end)
    pp = M.product_potential(m, *cur, prev=prev)
    cand = pp[pp["구분"].eq("키울 후보")].head(n)
    facts = [f"{r['product_name']} ({r['category']}): 점수 {r['잠재력 점수']:.0f}, 상품매출 {won(r['상품매출'])}, "
             f"장바구니율 {pct(r['장바구니율'])}" for _, r in cand.iterrows()] if len(cand) else ["조건에 맞는 후보가 없습니다."]
    if prev:
        rp = M.rising_products(m, cur, prev, n=3)
        facts.append("매출 증가율 상위: " + ", ".join(f"{r['product_name']}({r['매출 증가율']*100:+.0f}%)" for _, r in rp.iterrows()))
    ok = pp[pp["구분"].ne("표본 부족") & pp["상품매출"].gt(0)]
    return _result("성장 잠재력 상품", plabel, facts,
                   {"kind": "scatter", "data": ok, "x": "상품매출", "y": "잠재력 점수", "color": "구분", "label": "product_name",
                    "x_log": True, "x_fmt": "~s"},
                   cand[["product_name", "category", "잠재력 점수", "상품매출", "장바구니율", "클릭당 주문"]],
                   ["규칙 기반 탐색 점수이며 미래 매출 예측이 아님"])


STEP_NAMES = {1: "방문 → 상품 클릭", 2: "상품 클릭 → 장바구니", 3: "장바구니 → 구매"}


def design_experiment(m, start, end, step=3, lift=0.05):
    cur = _period(start, end)
    s = M.in_period(m["sessions"], "start", *cur)
    n, d, p0 = M.step_rate(s, "ALL", int(step))
    per = M.sample_size_per_group(p0, float(lift))
    daily = d / max((cur[1] - cur[0]).days, 1)
    days = 2 * per / daily if daily else float("nan")
    facts = [f"기준 전환율({STEP_NAMES[int(step)]}): {pct(p0)} ({d:,}세션 중 {n:,}세션)",
             f"목표: 상대 {lift*100:.0f}% 개선 → {pct(p0 * (1 + lift))} (유의수준 0.05, 검정력 0.8)",
             f"그룹당 필요 세션 {per:,}개, 두 그룹 합계 {2*per:,}개",
             f"하루 {STEP_NAMES[int(step)].split(' → ')[0]} 세션 약 {daily:,.0f}개 → 약 {days:,.0f}일 필요"]
    return _result("실험 표본·기간 계산", _label(cur), facts, None, None,
                   ["기간은 이 단계에 도달한 세션을 두 그룹에 반씩 나눈다고 가정",
                    "개선폭을 작게 잡을수록 필요한 표본이 크게 늘어남"])


# ---------------------------------------------------------------------------
# 도구 목록 (LLM에 넘길 설명)
# ---------------------------------------------------------------------------
def simulate_policy(m, start, end, policy_config, simulation_scope=None, simulation_costs=None):
    """The same replay engine used by Growth Lab. This tool does not save records."""
    cur = _period(start, end)
    if not isinstance(policy_config, dict) or "policy" not in policy_config:
        raise ValueError("정책 유형과 변경 조건을 확인해 주세요.")
    required = {"price": "price_change_pct", "discount": "discount_value", "shipping": "shipping_fee",
                "benefit": "benefit_amount", "bundle": "bundle_discount_pct", "volume": "order_change_pct"}
    field = required.get(policy_config["policy"])
    if policy_config["policy"] == "price" and policy_config.get("price_overrides"):
        field = "price_overrides"
    if not field or field not in policy_config:
        raise ValueError("정책의 변경값을 질문에서 확인한 뒤 입력해 주세요.")
    if policy_config["policy"] == "shipping" and "free_shipping_threshold" not in policy_config:
        raise ValueError("무료배송 기준 금액도 확인해 주세요.")
    prepared = S.prepare(m, *cur, simulation_scope, simulation_costs)
    result = S.simulate(prepared, policy_config)
    target_table = S.comparison(result)
    profit = target_table.set_index("지표").loc[S.LABELS["profit"]]
    out = _result("정책 시뮬레이션 · " + S.POLICIES[result["config"]["policy"]], _label(cur),
        S.evidence(prepared, result),
        {"kind": "bar", "data": pd.DataFrame({"조건": ["현재", "변경안"],
         "반영 비용 차감 이익": [profit["현재"], profit["변경안"]]}),
         "x": "반영 비용 차감 이익", "y": "조건", "x_fmt": ",.0f"}, target_table, result["notes"])
    out["simulation"] = {"version": S.VERSION, "start": prepared["start"], "end": prepared["end"],
        "scope": prepared["scope"], "costs": prepared["costs"], "scenarios": [result["config"]],
        "selected": "A", "display_scope": "target_orders", "facts": out["facts"], "notes": out["notes"],
        "comparison": target_table.to_dict("records")}
    return out


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    fn: Callable
    questions: list = field(default_factory=list)   # 평가셋 질문 번호


PERIOD = {"start": "시작일 YYYY-MM-DD", "end": "끝 다음 날 YYYY-MM-DD (미포함)"}
FILTERS = {"filters": "고객 조건(성별·연령대·지역·가입 경로·등급·첫 구매/기존·신규 가입). 질문에 조건이 있을 때만"}

SESSION_TOOLS = {"get_funnel"}                       # 방문 단위 분석: 첫 구매/기존(주문 단위) 조건 불가
CUSTOMER_LEVEL_TOOLS = {"segment_repeat", "get_segments"}   # 고객의 구매 이력 전체를 보는 분석: 주문 단위 조건 불가


def with_filters(name: str, fn: Callable) -> Callable:
    """도구에 고객 조건(filters)을 붙인다: 조건에 맞는 데이터만 남긴 mart로 같은 계산을 하고,
    사실 목록 맨 앞에 '대상: …(구매 고객 N명)'을 넣는다. 대상이 30명 미만이면 표본 부족 경고."""
    def run(m, filters=None, **params):
        cur = _period(params["start"], params["end"]) if params.get("start") and params.get("end") else None
        m2, info = M.filter_mart(m, filters, cur)
        f = info["filters"]
        if not f:
            return fn(m, **params)
        if name in SESSION_TOOLS and not info["sessions_ok"]:
            raise ValueError("첫 구매/기존 구매 조건은 주문 단위라 방문·퍼널 분석에는 쓸 수 없습니다. "
                             "다른 조건만 넣거나 주문 기준 분석(매출·순위)을 쓰세요.")
        if name in CUSTOMER_LEVEL_TOOLS and ("customer_type" in f or f.get("grade_basis") == "당시"):
            raise ValueError("이 분석은 고객의 구매 이력 전체를 보므로 첫 구매/기존 구매나 '당시' 등급 조건을 쓸 수 없습니다. "
                             "등급은 grade_basis='현재'로, 첫 구매/기존은 고객군 기준(by)으로 나눠 보세요.")
        if f.get("new_signup"):
            if name in ("explain_revenue_change", "detect_changes"):
                raise ValueError("신규 가입 고객은 직전 기간에 아직 가입 전이라 직전 기간과 비교할 수 없습니다.")
            if name == "get_kpis":
                params["compare"] = False
        res = fn(m2, **params)
        if name in SESSION_TOOLS:
            s = m2["sessions"] if cur is None else M.in_period(m2["sessions"], "start", *cur)
            n, unit = s["customer_id"].nunique(), "방문 고객"
        else:
            o = M.completed_orders(m2, *(cur or (None, None)))
            n, unit = o["customer_id"].nunique(), "구매 고객"
        warn = (" - 조건에 맞는 고객이 없음" if n == 0 else
                " - 30명 미만이라 결과가 우연에 크게 좌우될 수 있음(표본 부족)" if n < 30 else "")
        res["facts"].insert(0, f"대상: {info['label']} ({'기간 내 ' if cur else ''}{unit} {n:,}명){warn}")
        res["title"] += f" · {info['label']}"
        res["notes"] = res.get("notes", []) + [
            "연령은 출생연도 기준 근사 나이(생일 정보 없음). 성별·출생연도가 없는 고객은 해당 조건에서 빠짐"]
        return res
    run.__name__ = fn.__name__
    return run


FILTERABLE = {"get_kpis", "get_coupon_efficiency", "rank_items", "compare_items", "analyze", "explain_revenue_change", "get_trend", "get_funnel",
              "segment_preference", "segment_repeat", "get_segments"}

_TOOL_LIST = [
    Tool("simulate_policy", "Growth Lab 정책 시뮬레이션. 가격·쿠폰·배송·혜택·묶음·노출 개선 조건을 바꿔 매출·비용·이익과 "
         "손익 유지 주문 변화를 계산한다. 고객 반응은 사용자 가정이며 기본 0%. 변경값은 질문 또는 현재 Growth Lab 설정에서 가져온다. "
         "simulation_scope로 상품·카테고리·고객·테마·기존 쿠폰을 제한한다.",
         PERIOD | {"policy_config": "정책 조건", "simulation_scope": "적용 대상", "simulation_costs": "반영 변동비"}, simulate_policy, []),
    Tool("get_kpis", "기간의 핵심 지표(매출·주문·고객·객단가·전환율·재구매·쿠폰·취소환불)와 직전 기간 대비 변화. "
         "'지난달 매출', '이번 주 주문 수', '객단가', '구매 고객 수', '취소·환불' 질문",
         PERIOD, get_kpis, [1, 2, 5, 6, 9]),
    Tool("get_coupon_efficiency", "쿠폰 할인액 대비 쿠폰 사용 주문 매출(쿠폰 효율)과 쿠폰별 효율. ROAS 대신 쓰는 지표",
         PERIOD, get_coupon_efficiency, [8]),
    Tool("rank_items", "상품 또는 카테고리 상품매출 순위·비중. 기간 언급이 없으면 이번 달(9월). 상품은 판매 수량(metric=수량) 순위도 가능",
         PERIOD | {"target": "product | category", "n": "개수", "metric": "매출 | 수량"}, rank_items, [3, 4]),
    Tool("compare_items", "두 기간 사이에 상품(또는 카테고리)별 상품매출·판매 수량이 얼마나 줄었는지/늘었는지. 같은 상품을 두 기간에 "
         "맞대어 '얼마 → 얼마'로 보여 주고 감소액(direction=down) 또는 증가액(direction=up)이 큰 순으로 정렬. "
         "'매출이 빠진/줄어든/떨어진 상품', '많이 늘어난 상품', '덜 팔린 카테고리' 질문. 보고 싶은 기간만 넘기면 "
         "직전 기간(달이면 전달, 달력 주면 그 전 주)과 자동 비교",
         PERIOD | {"target": "product | category", "direction": "down | up", "n": "개수(질문에 개수가 있을 때만)", "metric": "매출 | 수량"},
         compare_items, []),
    Tool("analyze", "조립형 분석: 지표(measure)를 기준(dims, 1~2개)별로 나눠 보고, 필요하면 직전 기간과 비교. 다른 전용 도구가 "
         "딱 맞지 않는 '무엇을 × 무엇별로' 질문에 쓴다. 예: 요일별·시간대별·평일/주말 매출, 성별·연령대·지역·가입경로·등급별 "
         "구매 고객 수나 객단가, 신규/재방문·경로·테마별 구매전환율, 카테고리×성별 상품매출, 요일×시간대 주문 수, "
         "지난주보다 줄어든 지역(sort=감소순). 방문 지표(방문수·구매전환율·장바구니율)는 상품·카테고리·첫구매기존으로 못 나눈다",
         PERIOD | {"measure": "지표", "dims": "기준 1~2개", "sort": "높은순 | 낮은순 | 감소순 | 증가순", "n": "개수",
                   "compare": "직전 기간과 비교"}, analyze, []),
    Tool("explain_revenue_change", "직전 기간 대비 완료 매출 변화를 주문 수 효과와 객단가 효과로 분해하고 함께 달라진 지표 제시",
         PERIOD, explain_revenue_change, [10, 20]),
    Tool("get_trend", "완료 매출·주문 수 추이. 기간 언급이 없으면 전체 기간(start=2026-04-01, end=2026-10-01)", PERIOD | {"grain": "date | week | month"}, get_trend, [11]),
    Tool("get_funnel", "방문→상품 클릭→장바구니→구매 퍼널과 가장 많이 빠지는 구간. 큐레이션 경유 vs 일반 탐색의 "
         "세션 구매 전환율 비교와 유의성도 항상 포함하므로 경로 비교 질문도 path=ALL로 한 번만 부른다",
         PERIOD | {"path": "ALL | CURATION | BROWSE"}, get_funnel, [13, 14, 28]),
    Tool("detect_changes", "직전 기간 대비 통계적으로 크게 달라진 지표 자동 탐지(p<0.05). '눈에 띄게 변한 거', '이상한 거' 질문", PERIOD,
         detect_changes, [19, 20]),
    Tool("get_themes", "큐레이션 테마별 클릭률·클릭 후 구매율·구매 전환율과 관심 vs 구매 사분면", PERIOD, get_themes, [7, 22, 27]),
    Tool("get_retention", "첫 구매 고객 vs 기존 구매 고객의 수·매출 비중, 재구매까지 걸리는 기간. "
         "휴면·이탈 고객 규모는 이 도구가 아니라 get_segments", PERIOD, get_retention, [12, 18]),
    Tool("get_segments", "RFM 규칙 기반 고객군(핵심·충성·성장 가능·관심 필요·이탈 우려·휴면 추정)의 고객 수와 매출 비중. "
         "'안 돌아오는 고객', '휴면 고객', '이탈 고객', '단골' 질문", PERIOD, get_segments, [24, 29]),
    Tool("segment_preference", "고객군별로 잘 팔리는 카테고리(상품매출 비중). 고객군 기준: customer_type(첫 구매/기존 구매), "
         "grade_at_order(주문 당시 회원 등급), visitor_type(신규/재방문), signup_channel(가입 경로)",
         PERIOD | {"by": "고객군 기준"}, segment_preference, [15]),
    Tool("segment_repeat", "고객군별 30일 재구매율(첫 주문 후 30일 안에 다시 산 비율)과 가장 낮은·높은 고객군. "
         "'재구매가 안 되는/잘 되는 고객군' 질문. 고객군 기준: customer_type(첫 구매/기존 구매), "
         "grade_at_order(첫 주문 당시 회원 등급), signup_channel(가입 경로). 전체 관측 기간 기준이라 기간 입력 불필요",
         {"by": "고객군 기준"}, segment_repeat, [25]),
    Tool("design_experiment", "A/B 실험에 필요한 그룹당 표본 수와 기간 계산. 기준 전환율은 기간의 퍼널 구간 전환율",
         PERIOD | {"step": "구간: 1=방문→상품 클릭, 2=상품 클릭→장바구니, 3=장바구니→구매", "lift": "목표 상대 개선폭 (0.05 = 5%)"},
         design_experiment, [30]),
    Tool("find_potential_products", "매출은 낮지만 관심·구매 의향·전환·성장 지표가 좋은 상품(키울 후보)과 뜨는 상품",
         PERIOD | {"n": "개수"}, find_potential_products, [21, 23]),
]

# 고객 조건을 받을 수 있는 도구에는 filters 입력을 붙이고 실행 함수를 감싼다
for _t in _TOOL_LIST:
    if _t.name in FILTERABLE:
        _t.params = _t.params | FILTERS
        _t.fn = with_filters(_t.name, _t.fn)
TOOLS = {t.name: t for t in _TOOL_LIST}


def run(m, name: str, **params) -> dict:
    """도구 실행. 이 도구에 없는 입력(AI가 다른 도구의 입력을 섞어 넣은 경우)은 버리고 결과 주의 문구에 남긴다."""
    t = TOOLS[name]
    extra = [k for k in params if k not in t.params]
    for k in extra:
        params.pop(k)
    res = t.fn(m, **params)
    if extra:
        res["notes"] = res.get("notes", []) + [f"이 분석에 없는 입력은 무시함: {', '.join(extra)}"]
    return res


# ---------------------------------------------------------------------------
# 예시 질문 (LLM 연결 전에는 이 버튼으로 도구를 바로 실행한다. 기간 규칙은 eval/cases.py와 같다)
# ---------------------------------------------------------------------------
SEP, AUG = ("2026-09-01", "2026-10-01"), ("2026-08-01", "2026-09-01")
EXAMPLES = [
    ("이번 달 판매가격을 5% 올리고 주문 수가 그대로면 이익은?", "simulate_policy",
     dict(start=SEP[0], end=SEP[1], policy_config={"policy": "price", "price_change_pct": 5})),
    ("이번 달 매출 어때?", "get_kpis", dict(start=SEP[0], end=SEP[1])),
    ("이번 달 매출 제일 많이 나온 상품 TOP5는?", "rank_items", dict(start=SEP[0], end=SEP[1], target="product", n=5)),
    ("지난달보다 매출이 왜 이만큼 변했어?", "explain_revenue_change", dict(start=SEP[0], end=SEP[1])),
    ("월별 매출 추이 보여줘", "get_trend", dict(start="2026-04-01", end=SEP[1], grain="month")),
    ("고객이 어느 단계에서 제일 많이 빠져?", "get_funnel", dict(start=SEP[0], end=SEP[1], path="ALL")),
    ("이번 달 눈에 띄게 변한 거 있어?", "detect_changes", dict(start=SEP[0], end=SEP[1])),
    ("관심은 많은데 구매로 안 이어지는 테마는?", "get_themes", dict(start=SEP[0], end=SEP[1])),
    ("지금 매출은 낮은데 키우면 될 상품은?", "find_potential_products", dict(start=SEP[0], end=SEP[1])),
    ("쿠폰 할인해 준 만큼 매출이 나왔어?", "get_coupon_efficiency", dict(start=SEP[0], end=SEP[1])),
    ("안 돌아오는 고객이 얼마나 돼?", "get_segments", dict(start=SEP[0], end=SEP[1])),
    ("지난주에 2주 전보다 매출이 빠진 상품 보여줘", "compare_items", dict(start="2026-09-21", end="2026-09-28")),
    ("이번 달 요일·시간대별 주문 수는?", "analyze", dict(start=SEP[0], end=SEP[1], measure="주문수", dims=["요일", "시간대"])),
    ("신규 방문이랑 재방문 중 구매전환율이 높은 쪽은?", "analyze", dict(start=SEP[0], end=SEP[1], measure="구매전환율", dims=["신규재방문"])),
]

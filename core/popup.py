"""AI 분석가 답변 → '대시보드로 보기' 팝업.

챗봇이 부른 도구의 기간·고객 조건을 그대로 받아, 그 질문에 맞는 작은 대시보드를 팝업(st.dialog)으로 띄운다.
- 숫자는 전부 core/metrics.py 함수가 만든다(대시보드 화면·챗봇 도구와 같은 함수). AI가 만든 숫자는 없다.
- 기간: 도구가 서로 다른 두 기간을 불렀으면(예: 9월, 8월을 따로) 늦은 쪽 = 분석 기간, 이른 쪽 = 비교 기간.
  한 기간만 불렀으면 비교 기간 규칙(metrics.compare_period)으로 비교 기간을 정한다.
- 모양: 방문·퍼널 질문(get_funnel, design_experiment)은 퍼널 중심, 나머지는 매출 중심.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from . import metrics as M
from . import ui
from .data import PERIOD_END, PERIOD_START

FUNNEL_TOOLS = {"get_funnel", "design_experiment"}
OVERLAY_MAX_DAYS = 62          # 이 일수 이하면 분석·비교 기간 일별 추이를 겹쳐 그린다


# ---------------------------------------------------------------------------
# 도구 호출 → 대시보드 설정
# ---------------------------------------------------------------------------
def spec_from_calls(calls: list[dict]) -> dict | None:
    """calls: [{"tool", "params"}] (성공한 호출만). 기간이 있는 호출이 없으면 None (버튼을 보이지 않음)."""
    periods, filters, tools = [], None, []
    for c in calls or []:
        p = c.get("params") or {}
        tools.append(c.get("tool"))
        if filters is None and p.get("filters"):
            filters = p["filters"]
        if p.get("start") and p.get("end"):
            try:
                s = max(pd.Timestamp(p["start"]), PERIOD_START)
                e = min(pd.Timestamp(p["end"]), PERIOD_END)
            except (ValueError, TypeError):
                continue
            if s < e and (s, e) not in periods:
                periods.append((s, e))
    if not periods:
        return None
    periods.sort()
    cur = periods[-1]
    prev = periods[-2] if len(periods) >= 2 and periods[-2][1] <= cur[0] else M.compare_period(*cur)
    try:
        f = M.clean_filters(filters)
    except ValueError:
        f = {}
    if f.get("new_signup"):
        prev = None          # 신규 가입 고객은 직전 기간에 아직 가입 전이라 비교할 수 없다
    return {"cur": cur, "prev": prev, "filters": f,
            "focus": "funnel" if any(t in FUNNEL_TOOLS for t in tools) else "sales"}


def short_label(p) -> str:
    """'9월', '7~9월', '09-21 ~ 09-27' 같은 짧은 기간 이름 (차트 범례용)."""
    s, e = p
    if s.day == 1 and e.day == 1 and s.normalize() == s and e.normalize() == e:
        last = e - pd.DateOffset(months=1)
        return f"{s.month}월" if last.month == s.month else f"{s.month}~{last.month}월"
    return f"{s:%m-%d} ~ {e - pd.Timedelta(days=1):%m-%d}"


# ---------------------------------------------------------------------------
# 부분 그림
# ---------------------------------------------------------------------------
def _colors(cur_l, prev_l):
    dom = [cur_l] + ([prev_l] if prev_l else [])
    return alt.Scale(domain=dom, range=[ui.C_MAIN, ui.C_PREV][:len(dom)])


def _trend(m, cur, prev, cur_l, prev_l):
    days = (cur[1] - cur[0]).days
    if prev is not None and days <= OVERLAY_MAX_DAYS:
        parts = []
        for p, lab in ((cur, cur_l), (prev, prev_l)):
            t = M.sales_trend(m, *p, grain="date")
            t["일차"] = (t["date"] - p[0]).dt.days + 1
            t["기간"] = lab
            parts.append(t)
        t = pd.concat(parts, ignore_index=True)
        ch = alt.Chart(t).mark_line(point=alt.OverlayMarkDef(size=28), strokeWidth=2).encode(
            x=alt.X("일차:Q", title="기간 시작부터 N일째", axis=alt.Axis(tickMinStep=1),
                    scale=alt.Scale(domain=[1, int(t["일차"].max())], nice=False)),
            y=alt.Y("매출:Q", title="완료 매출(원)", axis=alt.Axis(format="~s")),
            color=alt.Color("기간:N", scale=_colors(cur_l, prev_l), legend=alt.Legend(title=None)),
            tooltip=["기간", alt.Tooltip("date:T", title="날짜", format="%Y-%m-%d"),
                     alt.Tooltip("매출:Q", format=",.0f"), alt.Tooltip("주문수:Q", format=",")])
        st.altair_chart(ch.properties(height=260), width="stretch")
        ui.note("두 기간의 일별 완료 매출을 '시작부터 N일째'로 맞춰 겹쳤습니다. 요일이 다를 수 있습니다.")
        return
    grain = "date" if days <= OVERLAY_MAX_DAYS else "week" if days <= 120 else "month"
    lo = prev[0] if prev is not None else cur[0]
    t = M.sales_trend(m, lo, cur[1], grain=grain)
    t["기간"] = (t[grain] >= cur[0]).map({True: cur_l, False: prev_l or cur_l})
    fmt = {"date": "%m/%d", "week": "%m/%d", "month": "%Y-%m"}[grain]
    ch = alt.Chart(t).mark_bar(cornerRadiusEnd=2).encode(
        x=alt.X(f"{grain}:T", title=None, axis=alt.Axis(format=fmt)),
        y=alt.Y("매출:Q", title="완료 매출(원)", axis=alt.Axis(format="~s")),
        color=alt.Color("기간:N", scale=_colors(cur_l, prev_l), legend=alt.Legend(title=None)),
        tooltip=[alt.Tooltip(f"{grain}:T", title="시작일", format="%Y-%m-%d"),
                 alt.Tooltip("매출:Q", format=",.0f"), alt.Tooltip("주문수:Q", format=",")])
    st.altair_chart(ch.properties(height=260), width="stretch")
    ui.note({"date": "일별", "week": "주별(월요일 시작)", "month": "월별"}[grain] + " 완료 매출. "
            "처음·마지막 구간이 기간 중간에 걸리면 값이 작게 보일 수 있습니다." if grain != "date" else "일별 완료 매출")


def _categories(m, cur, prev, cur_l, prev_l):
    c1 = M.category_sales(m, *cur).assign(기간=cur_l)
    order = list(c1["category"])
    df = c1
    if prev is not None:
        c0 = M.category_sales(m, *prev).assign(기간=prev_l)
        df = pd.concat([c1, c0], ignore_index=True)
        order += [c for c in c0["category"] if c not in order]
    if df.empty:
        st.info("이 기간에 완료 주문이 없습니다.")
        return
    ch = alt.Chart(df).mark_bar(cornerRadiusEnd=2).encode(
        y=alt.Y("category:N", sort=order, title=None),
        yOffset=alt.YOffset("기간:N", sort=[cur_l, prev_l] if prev_l else [cur_l]),
        x=alt.X("net_sales:Q", title=None, axis=alt.Axis(format="~s")),
        color=alt.Color("기간:N", scale=_colors(cur_l, prev_l), legend=alt.Legend(title=None)),
        tooltip=["기간", alt.Tooltip("category:N", title="카테고리"), alt.Tooltip("net_sales:Q", title="상품매출", format=",.0f"),
                 alt.Tooltip("비중:Q", format=".1%")])
    st.altair_chart(ch.properties(height=max(200, len(order) * (34 if prev is not None else 22))), width="stretch")
    ui.note("상품매출 = 완료 주문의 쿠폰 차감 후 상품금액(배송비 제외)")


def _top_products(m, cur, prev, n=10):
    t = M.top_products(m, *cur, n=n)
    if t.empty:
        return
    out = pd.DataFrame({"순위": range(1, len(t) + 1), "상품": t["product_name"], "카테고리": t["category"],
                        "상품매출": t["상품매출"].map(ui.won), "구매 고객": t["구매고객"].map(lambda v: f"{v:,}명")})
    if prev is not None:
        p = M.top_products(m, *prev, n=100_000)
        p["순위"] = range(1, len(p) + 1)
        p = p.set_index("product_name")
        prev_sales = t["product_name"].map(p["상품매출"])
        prev_rank = t["product_name"].map(p["순위"])
        out["비교 기간 매출"] = prev_sales.map(ui.won)
        out["증감"] = [ui.fmt_delta(c, pv, "won") or "–" for c, pv in zip(t["상품매출"], prev_sales)]
        out["순위 변화"] = ["새로 진입" if pd.isna(r) else "–" if r == i else f"▲{int(r - i)}" if r > i else f"▼{int(i - r)}"
                         for i, r in zip(out["순위"], prev_rank)]
    st.dataframe(out, hide_index=True, width="stretch")


def _funnel(m, cur, prev, cur_l, prev_l):
    f1 = M.funnel(M.in_period(m["sessions"], "start", *cur), "ALL").assign(기간=cur_l)
    df = f1
    f0 = None
    if prev is not None:
        f0 = M.funnel(M.in_period(m["sessions"], "start", *prev), "ALL").assign(기간=prev_l)
        df = pd.concat([f1, f0], ignore_index=True)
    order = list(f1["단계"])
    ch = alt.Chart(df).mark_bar(cornerRadiusEnd=2).encode(
        x=alt.X("단계:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("기간:N", sort=[cur_l, prev_l] if prev_l else [cur_l]),
        y=alt.Y("첫 단계 대비:Q", title="방문 세션 대비", axis=alt.Axis(format=".0%")),
        color=alt.Color("기간:N", scale=_colors(cur_l, prev_l), legend=alt.Legend(title=None)),
        tooltip=["기간", "단계", alt.Tooltip("세션 수:Q", format=","), alt.Tooltip("첫 단계 대비:Q", format=".1%"),
                 alt.Tooltip("직전 단계 대비 전환율:Q", format=".1%")])
    st.altair_chart(ch.properties(height=260), width="stretch")
    rows = []
    for i in range(1, len(f1)):
        r = {"구간": f"{f1['단계'].iloc[i-1]} → {f1['단계'].iloc[i]}", cur_l: ui.pct(f1["직전 단계 대비 전환율"].iloc[i])}
        if f0 is not None:
            a, b = f1["직전 단계 대비 전환율"].iloc[i], f0["직전 단계 대비 전환율"].iloc[i]
            r[prev_l] = ui.pct(b)
            r["차이"] = ui.fmt_delta(a, b, "rate") or "–"
        rows.append(r)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    ui.note("'결제 진입' 이벤트가 없어 장바구니 다음이 바로 구매입니다. 방문은 로그인 고객 세션만 셉니다.")


def _go_to_overview(cur):
    """같은 기간으로 통합 현황 화면을 연다 (사이드바 조회 조건을 바꾼다)."""
    s, e = cur
    months = list(ui.MONTHS)
    one_month = s.day == 1 and e.day == 1 and (e - pd.DateOffset(months=1)).month == s.month and pd.Period(s, "M") in months
    if one_month:
        st.session_state.period_mode = "월"
        st.session_state.period_month = months.index(pd.Period(s, "M"))
    else:
        st.session_state.period_mode = "직접 선택"
        st.session_state.period_range = (s.date(), (e - pd.Timedelta(days=1)).date())
    st.session_state.period_compare = True
    st.session_state.goto_overview = True


# ---------------------------------------------------------------------------
# 팝업
# ---------------------------------------------------------------------------
@st.dialog("질문 대시보드", width="large")
def open_dashboard(m, spec: dict, question: str, results: list[dict], key: str):
    cur, prev, f = spec["cur"], spec["prev"], spec["filters"]
    cur_l = short_label(cur)
    prev_l = short_label(prev) if prev is not None else None
    if prev_l == cur_l:
        cur_l, prev_l = f"분석 {cur_l}", f"비교 {prev_l}"

    m2, info = M.filter_mart(m, f, cur) if f else (m, {"label": ""})
    st.markdown(f"**질문** · {question}")
    st.caption(f"분석 기간 {ui.period_label(cur)} · 비교 기간 {ui.period_label(prev)}"
               + (f" · 대상 {info['label']}" if info["label"] else ""))

    k = M.kpis(m2, *cur)
    kp = M.kpis(m2, *prev) if prev is not None else {}
    g, has_prev = kp.get, prev is not None
    if spec["focus"] == "funnel":
        ui.kpi_row([
            ("방문 세션", k["sessions"], g("sessions"), "count", "로그인 고객 세션 수"),
            ("구매 세션", k["purchase_sessions"], g("purchase_sessions"), "count", "구매 이벤트가 있는 세션"),
            ("세션 구매 전환율", k["cvr"], g("cvr"), "rate", "구매 세션 ÷ 방문 세션. 변화는 %p"),
            ("완료 매출", k["revenue"], g("revenue"), "won", "완료 주문 결제 금액 합(배송비 포함)"),
            ("객단가", k["aov"], g("aov"), "won", "완료 매출 ÷ 완료 주문 수"),
        ], has_prev)
    else:
        ui.kpi_row([
            ("완료 매출", k["revenue"], g("revenue"), "won", "완료 주문 결제 금액 합(배송비 포함, 회계 순매출 아님)"),
            ("완료 주문 수", k["orders"], g("orders"), "count", "완료 주문 수"),
            ("구매 고객 수", k["buyers"], g("buyers"), "count", "완료 주문이 있는 고유 고객 수"),
            ("객단가", k["aov"], g("aov"), "won", "완료 매출 ÷ 완료 주문 수"),
            ("세션 구매 전환율", k["cvr"], g("cvr"), "rate", "구매 세션 ÷ 방문 세션. 변화는 %p"),
        ], has_prev)
    if has_prev and (cur[1] - cur[0]) != (prev[1] - prev[0]):
        ui.note(f"두 기간의 일수가 달라({(cur[1]-cur[0]).days}일 vs {(prev[1]-prev[0]).days}일) "
                "합계 지표는 일수 차이의 영향을 받습니다.")
    dec = M.revenue_decomposition(m2, cur, prev, k, kp) if has_prev else None
    if dec:
        st.markdown(f"**매출 변화 나눠 보기** · {ui.won(dec['revenue_change'])} 변화 = 주문 수 효과 "
                    f"**{ui.won(dec['order_effect'])}** + 객단가 효과 **{ui.won(dec['aov_effect'])}**")

    if spec["focus"] == "funnel":
        st.markdown("##### 구매 퍼널")
        _funnel(m2, cur, prev, cur_l, prev_l)
        st.markdown("##### 매출 추이")
        _trend(m2, cur, prev, cur_l, prev_l)
    else:
        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown("##### 매출 추이")
            _trend(m2, cur, prev, cur_l, prev_l)
        with right:
            st.markdown("##### 카테고리별 상품매출")
            _categories(m2, cur, prev, cur_l, prev_l)
        st.markdown("##### 상품매출 TOP 10")
        _top_products(m2, cur, prev)

    if results:
        from .chat import show_result     # chat이 이 모듈을 불러오므로 여기서 불러온다
        with st.expander("이 질문에 AI가 쓴 분석 결과"):
            for res in results:
                show_result(res)

    st.divider()
    a, b = st.columns([3, 2], vertical_alignment="center")
    a.caption("숫자는 모두 대시보드 화면과 같은 계산 함수로 만든 값입니다. AI가 직접 만든 숫자는 없습니다.")
    if not f:
        b.button("이 기간으로 통합 현황 열기", icon=":material/dashboard:", key=f"goto_{key}",
                 on_click=_go_to_overview, args=(cur,), use_container_width=True)
    if st.session_state.pop("goto_overview", False):
        st.switch_page("views/overview.py")

"""AI 분석가 답변 → 질문 대시보드.

챗봇이 부른 도구의 기간·고객 조건을 그대로 받아, 그 질문에 맞는 대시보드를 왼쪽 화면 자리에 띄운다
(답변이 나오면 자동으로 열림, 오른쪽 채팅 패널은 그대로). app.py가 render()를 부른다.
- 숫자는 전부 core/metrics.py 함수가 만든다(대시보드 화면·챗봇 도구와 같은 함수). AI가 만든 숫자는 없다.
- 기간: 도구가 서로 다른 두 기간을 불렀으면(예: 9월, 8월을 따로) 늦은 쪽 = 분석 기간, 이른 쪽 = 비교 기간.
  한 기간만 불렀으면 비교 기간 규칙(metrics.compare_period)으로 비교 기간을 정한다.
- 모양: 챗봇이 그 질문에 답하려고 부른 분석만 패널로 그린다(도구 하나 = 패널 하나). 관련 없는 지표·차트는 넣지 않는다.
"""
from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

from . import metrics as M
from . import ui
from .data import PERIOD_END, PERIOD_START

CARD_CSS = """
<style>
  /* 일반 화면과 구분되게: 띄운 카드 + 'AI 분석가' 표시 (채팅 패널과 같은 초록 계열) */
  .st-key-qdash {background: #FFFFFF; border: 2px solid #1F6F5C; border-radius: 16px;
                 box-shadow: 0 10px 30px rgba(15, 50, 40, .18), 0 2px 6px rgba(15, 50, 40, .08);
                 padding: 1.1rem 1.4rem 1.2rem; margin-top: .4rem;}
  .qdash-badge {display: inline-flex; align-items: center; gap: .35rem; background: #1F6F5C; color: #fff;
                font-size: .82rem; font-weight: 600; padding: .28rem .7rem; border-radius: 999px;}
  .qdash-badge::before {content: "✦";}
  .qdash-q {font-size: 1.25rem; font-weight: 700; color: #111827; margin: .35rem 0 .1rem;}
  /* 뒤 배경을 살짝 어둡게: 팝업처럼 보이게 (채팅 패널은 그대로) */
  section.main, [data-testid="stMain"] {background: #EEF2F0;}
</style>
"""          # 이 일수 이하면 분석·비교 기간 일별 추이를 겹쳐 그린다


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
    seen, uniq = set(), []
    for c in calls:                       # 같은 도구·입력의 중복 호출은 한 번만
        k = (c.get("tool"), repr(sorted((c.get("params") or {}).items())))
        if k not in seen:
            seen.add(k)
            uniq.append({"tool": c.get("tool"), "params": dict(c.get("params") or {})})
    return {"cur": cur, "prev": prev, "filters": f, "calls": uniq,
            "explicit_prev": len(periods) >= 2 and periods[-2][1] <= cur[0]}


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


def _changes(m, cur, prev, cur_l, prev_l, params):
    """같은 상품(카테고리)을 두 기간에 맞대어 본 변화. 질문한 방향(줄어든/늘어난)만, 질문에 개수가 없으면 전부."""
    target, metric = params.get("target", "product"), params.get("metric", "매출")
    down = params.get("direction", "down") != "up"
    df = M.item_changes(m, cur, prev, target=target, metric=metric)
    qty = metric == "수량"
    what = "상품" if target == "product" else "카테고리"
    word = "줄어든" if down else "늘어난"
    df = df.assign(항목=df["product_name"] if target == "product" else df["category"])
    show = df[df["변화"] < 0].sort_values("변화") if down else df[df["변화"] > 0].sort_values("변화", ascending=False)
    if params.get("n"):
        show = show.head(int(params["n"]))
    st.markdown(f"##### {'판매 수량' if qty else '상품매출'}이 {word} {what} {len(show):,}개 ({prev_l} → {cur_l})")
    if show.empty:
        st.info(f"두 기간 사이에 {'판매 수량' if qty else '상품매출'}이 {word} {what}이 없습니다.")
        return
    top = show.head(30)
    amt = "감소" if down else "증가"
    top = top.assign(크기=top["변화"].abs())
    ch = alt.Chart(top).mark_bar(cornerRadiusEnd=2, color=ui.C_DOWN if down else ui.C_UP).encode(
        y=alt.Y("항목:N", sort=list(top["항목"]), title=None, axis=alt.Axis(labelOverlap=False, labelLimit=220)),
        x=alt.X("크기:Q", title=f"{amt}{'량' if qty else '액'}", axis=alt.Axis(format="," if qty else "~s")),
        tooltip=[alt.Tooltip("항목:N", title=what), alt.Tooltip("이전:Q", title=prev_l, format=","),
                 alt.Tooltip("현재:Q", title=cur_l, format=","), alt.Tooltip("변화:Q", format=","),
                 alt.Tooltip("변화율:Q", format="+.1%")])
    st.altair_chart(ch.properties(height=max(160, 28 * len(top))), width="stretch")
    if len(show) > len(top):
        ui.note(f"차트는 {amt}{'량' if qty else '액'}이 큰 {len(top)}개, 표에는 {len(show):,}개 전부")
    f = (lambda v: f"{v:,.0f}개") if qty else ui.won
    tbl = pd.DataFrame({what: show["항목"], **({"카테고리": show["category"]} if target == "product" else {}),
                        prev_l: show["이전"].map(f), cur_l: show["현재"].map(f),
                        "변화": [("+" if v > 0 else "") + f(v) for v in show["변화"]],
                        "변화율": show["변화율"].map(lambda v: "–" if pd.isna(v) else f"{v * 100:+.1f}%")})
    st.dataframe(tbl, hide_index=True, width="stretch")
    ui.note(f"같은 {what}의 두 기간 값을 맞대어 본 변화입니다(각 기간 TOP 목록끼리 비교한 것이 아님).")


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
    st.session_state.active_dash = None
    st.session_state.goto_overview = True


# ---------------------------------------------------------------------------
# 팝업
# ---------------------------------------------------------------------------
# 직전 기간과 비교하는 도구 (get_kpis는 compare=False가 아니면 비교)
COMPARE_TOOLS = {"get_kpis", "compare_items", "explain_revenue_change", "detect_changes", "get_funnel", "find_potential_products"}


def _kpi_panel(m, cur, prev):
    k = M.kpis(m, *cur)
    kp = M.kpis(m, *prev) if prev is not None else {}
    g = kp.get
    ui.kpi_row([
        ("완료 매출", k["revenue"], g("revenue"), "won", "완료 주문 결제 금액 합(배송비 포함, 회계 순매출 아님)"),
        ("완료 주문 수", k["orders"], g("orders"), "count", "완료 주문 수"),
        ("구매 고객 수", k["buyers"], g("buyers"), "count", "완료 주문이 있는 고유 고객 수"),
        ("객단가", k["aov"], g("aov"), "won", "완료 매출 ÷ 완료 주문 수"),
    ], prev is not None)
    if prev is not None:
        pl, cl = short_label(prev), short_label(cur)
        if pl == cl:
            pl, cl = f"비교 {pl}", f"분석 {cl}"
        rows = [("완료 매출", "revenue", "won"), ("완료 주문 수", "orders", "count"), ("구매 고객 수", "buyers", "count"),
                ("객단가", "aov", "won")]
        st.dataframe(pd.DataFrame([{"지표": a, pl: ui.fmt_value(kp[b], u), cl: ui.fmt_value(k[b], u),
                                    "변화": ui.fmt_delta(k[b], kp[b], u) or "–"} for a, b, u in rows]),
                     hide_index=True, width="stretch")
    if prev is not None and (cur[1] - cur[0]) != (prev[1] - prev[0]):
        ui.note(f"두 기간의 일수가 달라({(cur[1]-cur[0]).days}일 vs {(prev[1]-prev[0]).days}일) "
                "합계 지표는 일수 차이의 영향을 받습니다.")


def _result_panel(res):
    from .chat import draw_chart       # chat이 이 모듈을 불러오므로 여기서 불러온다
    st.markdown(f"##### {res['title']}")
    if res.get("chart") is not None:
        draw_chart(res["chart"])
    elif res.get("table") is None:      # 차트·표가 없는 결과(실험 표본 계산 등)는 사실 문장으로
        st.markdown("\n".join(f"- {x}" for x in res["facts"]))
    tbl = res.get("display_table") if res.get("display_table") is not None else res.get("table")
    if tbl is not None:
        st.dataframe(tbl, hide_index=True, width="stretch")
    for n_ in res.get("notes", []):
        ui.note(n_)


def _panel(m, m2, c, spec, cur_l, prev_l, key):
    """도구 하나 = 패널 하나. 도구 입력(기간·조건) 그대로 다시 계산해 그린다."""
    from . import tools as T
    tool, p = c["tool"], c["params"]
    try:
        cur = (max(pd.Timestamp(p["start"]), PERIOD_START), min(pd.Timestamp(p["end"]), PERIOD_END)) \
            if p.get("start") and p.get("end") else spec["cur"]
    except (ValueError, TypeError):
        cur = spec["cur"]
    prev = M.compare_period(*cur)
    cl, pl = short_label(cur), (short_label(prev) if prev is not None else None)
    try:
        if tool == "compare_items" and prev is not None:
            mm = M.filter_mart(m, p.get("filters"), cur)[0] if p.get("filters") else m
            _changes(mm, cur, prev, cl, pl, p)
        elif tool == "get_funnel" and prev is not None:
            mm = M.filter_mart(m, p.get("filters"), cur)[0] if p.get("filters") else m
            st.markdown(f"##### 구매 퍼널 ({pl} → {cl})")
            _funnel(mm, cur, prev, cl, pl)
        else:
            _result_panel(T.run(m, tool, **p))
    except Exception as ex:  # noqa: BLE001  (도구가 거절한 입력: 챗봇 답변에 이유가 나온다)
        st.info(f"이 분석은 그릴 수 없습니다: {ex}")


def close():
    st.session_state.active_dash = None


def render(m, spec: dict, question: str, key: str):
    cur, prev, f = spec["cur"], spec["prev"], spec["filters"]
    cur_l = short_label(cur)
    prev_l = short_label(prev) if prev is not None else None
    if prev_l == cur_l:
        cur_l, prev_l = f"분석 {cur_l}", f"비교 {prev_l}"

    st.markdown(CARD_CSS, unsafe_allow_html=True)
    with st.container(key="qdash"):
        _body(m, spec, question, key, cur, prev, f, cur_l, prev_l)


def _body(m, spec, question, key, cur, prev, f, cur_l, prev_l):
    h1, h2 = st.columns([6, 1], vertical_alignment="center")
    h1.markdown('<span class="qdash-badge">AI 분석가가 띄운 대시보드</span>', unsafe_allow_html=True)
    h2.button("닫기", icon=":material/close:", key=f"close_{key}", on_click=close, use_container_width=True,
              help="원래 보던 화면으로 돌아갑니다. 답변 아래 '대시보드 다시 보기'로 다시 열 수 있어요.")
    m2, info = M.filter_mart(m, f, cur) if f else (m, {"label": ""})
    st.markdown(f'<div class="qdash-q">“{html.escape(question)}”</div>', unsafe_allow_html=True)
    compares = spec["explicit_prev"] or any(
        (c["tool"] in COMPARE_TOOLS and c["params"].get("compare", True) is not False)
        or c["params"].get("compare") or c["params"].get("sort") in ("감소순", "증가순") for c in spec["calls"])
    st.caption(f"기간 {ui.period_label(cur)}" + (f" · 비교 {ui.period_label(prev)}" if compares and prev is not None else "")
               + (f" · 대상 {info['label']}" if info["label"] else ""))
    # 질문에 답하려고 챗봇이 부른 분석만 그린다(관련 없는 지표·차트는 넣지 않음)
    kpi_done = False
    for j, c in enumerate(spec["calls"]):
        if c["tool"] == "get_kpis":
            if not kpi_done:
                _kpi_panel(m2, cur, prev if compares else None)
                kpi_done = True
            continue
        _panel(m, m2, c, spec, cur_l, prev_l, key=f"{key}_{j}")

    st.divider()
    a, b = st.columns([3, 2], vertical_alignment="center")
    a.caption("숫자는 모두 대시보드 화면과 같은 계산 함수로 만든 값입니다. AI가 직접 만든 숫자는 없습니다.")
    if not f:
        b.button("이 기간으로 통합 현황 열기", icon=":material/dashboard:", key=f"goto_{key}",
                 on_click=_go_to_overview, args=(cur,), use_container_width=True)

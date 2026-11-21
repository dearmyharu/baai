"""아침 브리핑: 실무자가 업무 시작 시 처음 보는 화면.

전일 실적(최근 3일 판정) → 월간 누적 → 상품별 판매 동향(7일) → 진행 중인 프로모션 → 금일 확인 사항
계산은 engine/briefing.py. 이 파일은 표시만 한다.
"""
import altair as alt
import pandas as pd
import streamlit as st

from engine import briefing as B
from engine import ui

# ---------------- 기준일 (app.py 사이드바에서 정함) ----------------
today = pd.Timestamp(st.session_state.get("today", pd.Timestamp("2026-10-22")))
day = today - pd.Timedelta(days=1)


@st.cache_data(show_spinner="전일 실적을 집계하는 중입니다...")
def _brief(day_str: str):
    return B.brief(ui.get_mart(), pd.Timestamp(day_str))


b = _brief(f"{day:%Y-%m-%d}")
y, pace, mv = b["yesterday"], b["pace"], b["movers"]
LEVEL_COLOR = {"평소 대비 낮음": ui.C_DOWN, "평소 대비 높음": ui.C_UP}

st.title(f"{today.month}월 {today.day}일 ({B.DOW[today.dayofweek]}) 아침 브리핑")
with st.container(border=True):
    st.markdown(b["summary"])

# ---------------- 1. 전일 실적 ----------------
st.subheader("전일 실적")
span3 = f"{ui.md(y['span3'][0])}~{ui.md(y['span3'][1])}"


def _delta(v):
    if v is None:
        return None
    return f"{v:+.1%} 최근 3일 평소 대비" if abs(v) >= 0.0005 else "0.0% 최근 3일 평소 대비"


left, right = st.columns([1, 1.15], gap="large")
with left:
    a, c = st.columns(2)
    a.metric(f"매출 ({ui.md(day)})", ui.won(y["revenue"]), _delta(y["revenue3_chg"]))
    c.metric(f"이익 ({ui.md(day)})", ui.won(y["profit"]), _delta(y["profit3_chg"]),
             help=f"결제 금액 − 상품원가 − 배송 원가(주문당 {B.SHIP_COST:,}원)")
    a, c = st.columns(2)
    a.metric(f"주문 수 ({ui.md(day)})", f"{y['orders']:,.0f}건", _delta(y["orders3_chg"]))
    c.metric(f"객단가 ({ui.md(day)})", ui.won(y["aov"], short=False), _delta(y["aov3_chg"]))
    lvl = y["revenue3_level"]
    st.markdown(f"최근 3일({span3}) 매출 **{ui.won(y['revenue3'])}** · 평소 {ui.won(y['revenue3_base'])} → "
                f"<span style='color:{LEVEL_COLOR.get(lvl, ui.C_MAIN)};font-weight:600'>{lvl}</span>",
                unsafe_allow_html=True)
    st.caption(f"평소 = 지난 4주 같은 요일 3일 평균. 요일 구성 영향을 뺀 비교입니다. "
               f"±{B.LEVEL_BAND:.0%} 밖이면 낮음·높음으로 판정합니다.")
with right:
    t = b["trend"].copy()
    last3 = set(pd.date_range(y["span3"][0], y["span3"][1]))
    t["구분"] = t["date"].map(lambda d: "최근 3일" if d in last3 else "이전")
    t["날짜"] = t["date"].dt.strftime("%m/%d") + "(" + t["요일"] + ")"
    t["만원"] = t["revenue"] / 1e4
    color = LEVEL_COLOR.get(lvl, ui.C_MAIN)
    bars = alt.Chart(t).mark_bar().encode(
        x=alt.X("날짜:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("만원:Q", title="매출(만원)", axis=alt.Axis(format=",.0f")),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["최근 3일", "이전"], range=[color, ui.C_PREV]), legend=None),
        tooltip=[alt.Tooltip("날짜:N"), alt.Tooltip("revenue:Q", title="매출", format=",.0f"),
                 alt.Tooltip("profit:Q", title="이익", format=",.0f"), alt.Tooltip("orders:Q", title="주문 수")])
    st.markdown("**최근 14일 매출**")
    st.altair_chart(bars.properties(height=220), use_container_width=True)

# ---------------- 2. 월간 누적 ----------------
st.subheader("월간 누적 실적")
with st.container(border=True):
    a, c = st.columns([3, 1])
    prev_txt = f" · 지난달 같은 날까지 {ui.won(pace['prev_cum'])}" if pace["prev_cum"] else ""
    a.markdown(f"{pace['month']}월 1~{pace['day']}일 누적 **{ui.won(pace['cum'])}**{prev_txt}")
    if pace["chg"] is not None:
        c.markdown(f"<div style='text-align:right;color:{ui.C_DOWN if pace['chg'] < 0 else ui.C_UP}'>"
                   f"{'▼' if pace['chg'] < 0 else '▲'} {abs(pace['chg']):.1%}</div>", unsafe_allow_html=True)
    s = pace["series"].copy()
    s["만원"] = s["누적 매출"] / 1e4
    names = list(s["구분"].unique())
    line = alt.Chart(s).mark_line(point=alt.OverlayMarkDef(size=18)).encode(
        x=alt.X("일:Q", title="일", scale=alt.Scale(domain=[1, 31]), axis=alt.Axis(tickMinStep=1)),
        y=alt.Y("만원:Q", title="누적 매출(만원)", axis=alt.Axis(format=",.0f")),
        color=alt.Color("구분:N", scale=alt.Scale(domain=names, range=[ui.C_MAIN, ui.C_PREV][:len(names)]),
                        title=None),
        tooltip=["구분:N", "일:Q", alt.Tooltip("누적 매출:Q", format=",.0f")])
    st.altair_chart(line.properties(height=230), use_container_width=True)
    st.caption(f"현 추세 기준 {pace['month']}월 예상 매출 약 {ui.won(pace['projection'])}"
               + (f" (지난달 실적 {ui.won(pace['prev_full'])})" if pace["prev_full"] else "")
               + " · 산식: 누적 일평균 × 이번 달 일수")

# ---------------- 3. 상품별 판매 동향 ----------------
st.subheader("상품별 판매 동향")
span7 = f"{ui.md(mv['span'][0])}~{ui.md(mv['span'][1])}"
a, c = st.columns(2, gap="large")
for box, key, title, empty in [(a, "up", "판매 증가 상품", "직전 7일 대비 판매가 크게 늘어난 상품이 없습니다."),
                               (c, "down", "판매 감소 상품", "직전 7일 대비 판매가 크게 줄어든 상품이 없습니다.")]:
    with box.container(border=True):
        st.markdown(f"**{title}**")
        df = mv[key]
        if df.empty:
            st.caption(empty)
        for r in df.itertuples():
            st.markdown(f"{r.상품} · **{r._2:.0f}개** <span style='color:gray'>(직전 7일 {r._3:.0f}개)</span>",
                        unsafe_allow_html=True)
st.caption(f"최근 7일({span7}) 판매 수량을 직전 7일과 비교. 직전 또는 최근 7일에 10개 이상 팔린 상품만 봅니다.")

# ---------------- 4. 진행 중인 프로모션 ----------------
st.subheader("프로모션 점검")
STATUS_COLOR = {"효과 있음": ui.C_UP, "중단 검토": ui.C_DOWN, "효과 없음(감소)": ui.C_DOWN,
                "효과 불분명": ui.C_ACCENT, "판단 이름": ui.C_MUTED}
if not b["promos"]:
    st.caption("진행 중이거나 최근 14일 안에 끝난 프로모션이 없습니다.")
for p in b["promos"]:
    with st.container(border=True):
        l, r = st.columns([4, 1])
        sim = " · 모의" if p["is_simulated"] else ""
        l.markdown(f"**{p['name']}** <span style='color:gray;font-size:.85rem'>"
                   f"{ui.md(p['start'])}~{ui.md(p['end'])} · {p['phase']} {p['days']}/{p['total_days']}일{sim}</span>",
                   unsafe_allow_html=True)
        r.markdown(f"<div style='text-align:right;font-weight:600;color:{STATUS_COLOR.get(p['status'], ui.C_MUTED)}'>"
                   f"{p['status']}</div>", unsafe_allow_html=True)
        k1, k2, k3 = st.columns(3)
        k1.metric(f"{p['category']} 일평균 매출", ui.won(p["sales_dur"]),
                  f"{p['sales_chg']:+.0%} 시작 전 14일 대비" if p["sales_chg"] is not None else None)
        eff = "–" if p["effect"] is None else f"{p['effect']:+.0%}"
        band = ("" if p["effect_lo"] is None else f"95% 구간 {p['effect_lo']:+.0%} ~ {p['effect_hi']:+.0%}")
        k2.metric("다른 카테고리 대비 효과", eff, band or None, delta_color="off",
                  help="대상 카테고리의 매출 비중 변화. 같은 기간 다른 카테고리의 변화를 뺀 효과입니다.")
        k3.metric("이익률", ui.pct(p["margin_dur"]),
                  f"{-p['margin_drop_pp']:+.1f}%p 시작 전 대비" if p["margin_drop_pp"] is not None else None)
        st.caption(f"중단 기준: {p['stop_rule']} · 판정은 7일 이상 진행 후, 일 단위 재추출 95% 구간으로 합니다.")

# ---------------- 5. 금일 확인 사항 ----------------
st.subheader("금일 확인 사항")


def _seed(key: str):
    """확인 사항의 key('category:정육', 'product:상품명')를 AI 분석가의 분석 대상으로 넘긴다."""
    kind, _, name = key.partition(":")
    return {"type": kind, "value": name} if kind in ("category", "product") and name else None


def _ask(q: str, key: str = ""):
    st.session_state.pending_question = q
    st.session_state.pending_seed = _seed(key)
    st.session_state.goto = "chat"


def _lab(action: dict):
    st.session_state.lab_request = action
    st.session_state.goto = "lab"


TONE = {"problem": ("🔴", "리스크"), "opportunity": ("🟢", "기회"), "check": ("🟡", "점검")}
if not b["todos"]:
    st.success("금일 확인 사항은 없습니다.")
for i, x in enumerate(b["todos"], 1):
    with st.container(border=True):
        left, right = st.columns([5, 2])
        dot, word = TONE.get(x["tone"], ("", ""))
        n = x.get("streak", 1)
        rep = (f" · {n}일째" + (" 이상" if n >= 7 else "")) if n > 1 else " · 신규"
        left.markdown(f"**{i}. {x['title']}**  \n<span style='font-size:.85rem;color:gray'>{dot} {word}{rep}</span>",
                      unsafe_allow_html=True)
        for reason in x["reasons"]:
            left.caption(reason)
        with right:
            for j, act in enumerate(x["actions"]):
                if act["type"] == "ask":
                    st.button(act["label"], key=f"todo_{i}_{j}", on_click=_ask, args=(act["q"], x["key"]),
                              use_container_width=True, help=act["q"])
                elif act["type"] == "lab":
                    st.button(act["label"], key=f"todo_{i}_{j}", on_click=_lab, args=(act,),
                              use_container_width=True)
st.caption("선정 기준: 프로모션 판정을 먼저, 그다음 전일 급변, 그다음 최근 3일 변화의 금액 영향 순. 최대 4건. "
           "진행 중인 프로모션 대상 카테고리의 변화는 프로모션 점검에서 따로 봅니다.")

"""⓪ 아침 브리핑: 출근한 실무자가 처음 5분 동안 알고 싶은 것.

어제 장사 어땠지? → 이번 달은 괜찮게 가고 있나? → 어제 뭐가 팔리고 뭐가 안 팔렸지? → 오늘 뭘 해야 하지?
계산은 core/briefing.py. 이 파일은 표시만 한다.
"""
import altair as alt
import pandas as pd
import streamlit as st

from core import briefing as B
from core import ui
from core.data import PERIOD_END, PERIOD_START

m = ui.get_mart()

# 기준일(오늘) = 데이터 마지막 날 9/30. 브리핑은 '어제'를 본다.
sb = st.sidebar
sb.markdown("#### 브리핑 날짜")
today = sb.date_input("오늘", value=(PERIOD_END - pd.Timedelta(days=1)).date(),
                      min_value=(PERIOD_START + pd.Timedelta(days=35)).date(),
                      max_value=(PERIOD_END - pd.Timedelta(days=1)).date(), key="brief_today",
                      help="이 날 아침에 보는 화면입니다. '어제'는 하루 전, '평소'는 최근 4주 같은 요일입니다.")
sb.caption(f"이익 = 고객이 낸 돈 − 상품원가 − 배송 원가(주문당 {B.SHIP_COST:,}원 가정). 결제 수수료 등 기타 비용 제외")
today = pd.Timestamp(today)
day = today - pd.Timedelta(days=1)


@st.cache_data(show_spinner="어제 장사를 정리하는 중입니다...")
def _brief(day_str: str):
    return B.brief(ui.get_mart(), pd.Timestamp(day_str))


b = _brief(f"{day:%Y-%m-%d}")
y, pace, mv = b["yesterday"], b["pace"], b["movers"]

st.title(f"{today.month}월 {today.day}일 ({B.DOW[today.dayofweek]}) 아침 브리핑")
with st.container(border=True):
    st.markdown(b["summary"])


def _chg(v):
    return None if v is None else f"{v:+.0%} 평소 대비"     # 부호가 앞에 와야 화살표 방향이 맞다


# ---------------- 1. 어제 장사 ----------------
st.subheader("어제 장사 어땠지?")
left, right = st.columns([1, 1.15], gap="large")
with left:
    a, c = st.columns(2)
    a.metric("매출", ui.won(y["revenue"]), _chg(y["revenue_chg"]))
    c.metric("이익", ui.won(y["profit"]), _chg(y["profit_chg"]),
             help=f"고객이 낸 돈 − 상품원가 − 배송 원가(주문당 {B.SHIP_COST:,}원)")
    a, c = st.columns(2)
    a.metric("주문 수", f"{y['orders']:,.0f}건", _chg(y["orders_chg"]))
    c.metric("객단가", ui.won(y["aov"], short=False), _chg(y["aov_chg"]))
    st.caption(f"평소 = 최근 4주 {y['dow']}요일 평균 ({', '.join(f'{d.month}/{d.day}' for d in y['base_days'])})")
with right:
    t = b["trend"].copy()
    t["표시"] = t["어제"].map({True: "어제", False: "지난 날"})
    t["날짜"] = t["date"].dt.strftime("%m/%d") + "(" + t["요일"] + ")"
    color = ui.C_DOWN if y["level"] == "평소보다 낮음" else (ui.C_UP if y["level"] == "평소보다 높음" else ui.C_MAIN)
    bars = alt.Chart(t).mark_bar().encode(
        x=alt.X("날짜:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("revenue:Q", title="매출(원)", axis=alt.Axis(format="~s")),
        color=alt.Color("표시:N", scale=alt.Scale(domain=["어제", "지난 날"], range=[color, ui.C_PREV]), legend=None),
        tooltip=[alt.Tooltip("날짜:N"), alt.Tooltip("revenue:Q", title="매출", format=",.0f"),
                 alt.Tooltip("profit:Q", title="이익", format=",.0f"), alt.Tooltip("orders:Q", title="주문 수")])
    st.markdown(f"**최근 14일 매출** · 어제는 **{y['level']}**")
    st.altair_chart(bars.properties(height=210), width="stretch")
    if y["revenue_min"] is not None:
        st.caption(f"평소 {y['dow']}요일 범위 {ui.won(y['revenue_min'])} ~ {ui.won(y['revenue_max'])}")

# ---------------- 2. 이번 달 ----------------
st.subheader("이번 달은 괜찮게 가고 있나?")
with st.container(border=True):
    a, c = st.columns([3, 1])
    prev_txt = f" · 지난달 같은 날까지 {ui.won(pace['prev_cum'])}" if pace["prev_cum"] else ""
    a.markdown(f"{pace['month']}월 1~{pace['day']}일 누적 **{ui.won(pace['cum'])}**{prev_txt}")
    if pace["chg"] is not None:
        c.markdown(f"<div style='text-align:right;color:{ui.C_DOWN if pace['chg'] < 0 else ui.C_UP}'>"
                   f"{'▼' if pace['chg'] < 0 else '▲'} {abs(pace['chg']):.1%}</div>", unsafe_allow_html=True)
    st.progress(min(pace["progress"], 1.0))
    st.caption(f"이 속도면 {pace['month']}월 약 {ui.won(pace['projection'])}"
               + (f" (지난달 전체 {ui.won(pace['prev_full'])})" if pace["prev_full"] else "")
               + " · 단순 계산(지금까지 하루 평균 × 이번 달 일수)")

# ---------------- 3. 어제 상품 ----------------
st.subheader("어제 뭐가 팔리고 뭐가 안 팔렸지?")
a, c = st.columns(2, gap="large")
for box, key, title, empty in [(a, "up", "평소보다 잘 팔린 상품", "평소보다 눈에 띄게 잘 팔린 상품이 없어요."),
                               (c, "down", "평소보다 덜 팔린 상품", "평소보다 눈에 띄게 덜 팔린 상품이 없어요.")]:
    with box.container(border=True):
        st.markdown(f"**{title}**")
        df = mv[key]
        if df.empty:
            st.caption(empty)
        for r in df.itertuples():
            st.markdown(f"{r.상품} · **{r.어제:.0f}개** <span style='color:gray'>(평소 {r.평소:.1f}개)</span>",
                        unsafe_allow_html=True)
st.caption("평소 = 최근 4주 같은 요일 평균 판매량")

# ---------------- 4. 오늘 할 일 ----------------
st.subheader("오늘 뭘 해야 하지?")


def _ask(q: str):
    st.session_state.chat_open = True
    from core import chat
    chat.ask_next(q)


def _lab(scope: dict, d: str):
    """쿠폰을 없앤다면? 을 최근 28일 주문으로 다시 계산해 Growth Lab 비교 화면을 연다(주문 수 변화 0%)."""
    from core import chat, tools
    end = pd.Timestamp(d) + pd.Timedelta(days=1)
    try:
        res = tools.run(ui.get_mart(), "simulate_policy", start=f"{end - pd.Timedelta(days=28):%Y-%m-%d}",
                        end=f"{end:%Y-%m-%d}",
                        policy_config={"policy": "discount", "discount_type": "rate", "discount_value": 0},
                        simulation_scope=scope,
                        simulation_costs={"shipping_per_order": B.SHIP_COST, "fee_pct": 0, "other_per_order": 0})
    except Exception as ex:  # noqa: BLE001
        st.session_state.brief_error = f"Growth Lab으로 넘기지 못했습니다: {ex}"
        return
    chat.open_simulation(res["simulation"])


if err := st.session_state.pop("brief_error", None):
    st.error(err)
TONE = {"problem": ("🔴", "확인 필요"), "opportunity": ("🟢", "기회"), "check": ("🟡", "점검")}
if not b["todos"]:
    st.success("오늘은 평소와 크게 다른 게 없어요. 이번 주 계획한 일을 진행하세요.")
for i, x in enumerate(b["todos"], 1):
    with st.container(border=True):
        left, right = st.columns([5, 2])
        dot, word = TONE.get(x["tone"], ("", ""))
        left.markdown(f"**{i}. {x['title']}**  \n<span style='font-size:.85rem;color:gray'>{dot} {word}</span>",
                      unsafe_allow_html=True)
        for r in x["reasons"]:
            left.caption(r)
        with right:
            for j, act in enumerate(x["actions"]):
                if act["type"] == "ask":
                    st.button(act["label"] + " ↗", key=f"todo_{i}_{j}", on_click=_ask, args=(act["q"],),
                              width="stretch", help=act["q"])
                elif act["type"] == "lab":
                    st.button(act["label"], key=f"todo_{i}_{j}", on_click=_lab, args=(act["scope"], f"{day:%Y-%m-%d}"),
                              width="stretch", help="최근 28일 주문으로 '쿠폰을 없앤다면'을 계산해 Growth Lab에서 엽니다. "
                                                    "주문 수 변화는 0%(가정 없음)로 시작합니다.")
st.caption("할 일은 최근 3일(하루 급변은 어제)을 평소와 비교해 규칙으로 뽑고, 돈 영향이 큰 순서로 최대 4개를 보여 줍니다.")

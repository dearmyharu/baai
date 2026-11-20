"""⓪ 일일 브리핑: 실무자가 업무 시작 시 확인할 내용.

전일 실적 → 월간 누적 실적 → 전일 상품별 판매 동향 → 금일 확인 사항
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
sb.markdown("#### 브리핑 기준일")
today = sb.date_input("기준일", value=(PERIOD_END - pd.Timedelta(days=1)).date(),
                      min_value=(PERIOD_START + pd.Timedelta(days=35)).date(),
                      max_value=(PERIOD_END - pd.Timedelta(days=1)).date(), key="brief_today",
                      help="기준일 아침에 보는 화면입니다. 전일 = 기준일 하루 전, 평소 = 최근 4주 동일 요일.")
sb.caption(f"이익 = 결제 금액 − 상품원가 − 배송 원가(주문당 {B.SHIP_COST:,}원 가정). 결제 수수료 등 기타 비용 제외")
today = pd.Timestamp(today)
day = today - pd.Timedelta(days=1)


@st.cache_data(show_spinner="전일 실적을 집계하는 중입니다...")
def _brief(day_str: str):
    return B.brief(ui.get_mart(), pd.Timestamp(day_str))


b = _brief(f"{day:%Y-%m-%d}")
y, pace, mv = b["yesterday"], b["pace"], b["movers"]

st.title(f"{today.month}월 {today.day}일 ({B.DOW[today.dayofweek]}) 일일 브리핑")
with st.container(border=True):
    st.markdown(b["summary"])


def _chg(v):
    if v is None:
        return None
    return "0.0% 평소 대비" if abs(v) < 0.0005 else f"{v:+.1%} 평소 대비"     # 부호가 앞에 와야 화살표 방향이 맞다


# ---------------- 1. 전일 실적 ----------------
st.subheader("전일 실적")
left, right = st.columns([1, 1.15], gap="large")
with left:
    a, c = st.columns(2)
    a.metric("매출", ui.won(y["revenue"]), _chg(y["revenue_chg"]))
    c.metric("이익", ui.won(y["profit"]), _chg(y["profit_chg"]),
             help=f"결제 금액 − 상품원가 − 배송 원가(주문당 {B.SHIP_COST:,}원)")
    a, c = st.columns(2)
    a.metric("주문 수", f"{y['orders']:,.0f}건", _chg(y["orders_chg"]))
    c.metric("객단가", ui.won(y["aov"], short=False), _chg(y["aov_chg"]))
    st.caption(f"평소: 최근 4주 {y['dow']}요일 평균 ({', '.join(f'{d.month}/{d.day}' for d in y['base_days'])})")
with right:
    t = b["trend"].copy()
    t["표시"] = t["어제"].map({True: "전일", False: "이전"})
    t["날짜"] = t["date"].dt.strftime("%m/%d") + "(" + t["요일"] + ")"
    t["만원"] = t["revenue"] / 1e4
    color = ui.C_DOWN if y["level"] == "평소 대비 낮음" else (ui.C_UP if y["level"] == "평소 대비 높음" else ui.C_MAIN)
    bars = alt.Chart(t).mark_bar().encode(
        x=alt.X("날짜:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("만원:Q", title="매출(만원)", axis=alt.Axis(format=",.0f")),
        color=alt.Color("표시:N", scale=alt.Scale(domain=["전일", "이전"], range=[color, ui.C_PREV]), legend=None),
        tooltip=[alt.Tooltip("날짜:N"), alt.Tooltip("revenue:Q", title="매출", format=",.0f"),
                 alt.Tooltip("profit:Q", title="이익", format=",.0f"), alt.Tooltip("orders:Q", title="주문 수")])
    st.markdown(f"**최근 14일 매출** · 전일: **{y['level']}**")
    st.altair_chart(bars.properties(height=210), width="stretch")
    if y["revenue_min"] is not None:
        st.caption(f"최근 4주 {y['dow']}요일 범위 {ui.won(y['revenue_min'])} ~ {ui.won(y['revenue_max'])}")

# ---------------- 2. 월간 누적 ----------------
st.subheader("월간 누적 실적")
with st.container(border=True):
    a, c = st.columns([3, 1])
    prev_txt = f" · 전월 동기 {ui.won(pace['prev_cum'])}" if pace["prev_cum"] else ""
    a.markdown(f"{pace['month']}월 1~{pace['day']}일 누적 **{ui.won(pace['cum'])}**{prev_txt}")
    if pace["chg"] is not None:
        c.markdown(f"<div style='text-align:right;color:{ui.C_DOWN if pace['chg'] < 0 else ui.C_UP}'>"
                   f"{'▼' if pace['chg'] < 0 else '▲'} {abs(pace['chg']):.1%}</div>", unsafe_allow_html=True)
    st.progress(min(pace["progress"], 1.0))
    st.caption(f"현 추세 기준 {pace['month']}월 예상 매출 약 {ui.won(pace['projection'])}"
               + (f" (전월 실적 {ui.won(pace['prev_full'])})" if pace["prev_full"] else "")
               + " · 산식: 누적 일평균 × 당월 일수")

# ---------------- 3. 전일 상품 ----------------
st.subheader("전일 상품별 판매 동향")
a, c = st.columns(2, gap="large")
for box, key, title, empty in [(a, "up", "판매 증가 상품", "평소 대비 판매가 크게 증가한 상품이 없습니다."),
                               (c, "down", "판매 감소 상품", "평소 대비 판매가 크게 감소한 상품이 없습니다.")]:
    with box.container(border=True):
        st.markdown(f"**{title}**")
        df = mv[key]
        if df.empty:
            st.caption(empty)
        for r in df.itertuples():
            st.markdown(f"{r.상품} · **{r.어제:.0f}개** <span style='color:gray'>(평소 {r.평소:.1f}개)</span>",
                        unsafe_allow_html=True)
st.caption("평소: 최근 4주 동일 요일 평균 판매량")

# ---------------- 4. 금일 확인 사항 ----------------
st.subheader("금일 확인 사항")


def _ask(q: str):
    st.session_state.chat_open = True
    from core import chat
    chat.ask_next(q)


def _lab(scope: dict, d: str):
    """쿠폰 미적용 시 손익을 최근 28일 주문으로 다시 계산해 Growth Lab 비교 화면을 연다(주문 수 변화 0%)."""
    from core import chat, tools
    end = pd.Timestamp(d) + pd.Timedelta(days=1)
    try:
        res = tools.run(ui.get_mart(), "simulate_policy", start=f"{end - pd.Timedelta(days=28):%Y-%m-%d}",
                        end=f"{end:%Y-%m-%d}",
                        policy_config={"policy": "discount", "discount_type": "rate", "discount_value": 0},
                        simulation_scope=scope,
                        simulation_costs={"shipping_per_order": B.SHIP_COST, "fee_pct": 0, "other_per_order": 0})
    except Exception as ex:  # noqa: BLE001
        st.session_state.brief_error = f"Growth Lab 연결에 실패했습니다: {ex}"
        return
    chat.open_simulation(res["simulation"])


if err := st.session_state.pop("brief_error", None):
    st.error(err)
TONE = {"problem": ("🔴", "리스크"), "opportunity": ("🟢", "기회"), "check": ("🟡", "점검")}
if not b["todos"]:
    st.success("금일 특이 사항은 없습니다.")
for i, x in enumerate(b["todos"], 1):
    with st.container(border=True):
        left, right = st.columns([5, 2])
        dot, word = TONE.get(x["tone"], ("", ""))
        st_ = x.get("streak", 1)
        rep = f" · {st_}일째" + (" 이상" if st_ >= 7 else "") if st_ > 1 else " · 신규"
        left.markdown(f"**{i}. {x['title']}**  \n<span style='font-size:.85rem;color:gray'>{dot} {word}{rep}</span>",
                      unsafe_allow_html=True)
        for r in x["reasons"]:
            left.caption(r)
        with right:
            for j, act in enumerate(x["actions"]):
                if act["type"] == "ask":
                    st.button(act["label"], key=f"todo_{i}_{j}", on_click=_ask, args=(act["q"],),
                              width="stretch", help=act["q"])
                elif act["type"] == "lab":
                    st.button(act["label"], key=f"todo_{i}_{j}", on_click=_lab, args=(act["scope"], f"{day:%Y-%m-%d}"),
                              width="stretch", help="최근 28일 주문 기준으로 쿠폰 미적용 시 손익을 계산해 Growth Lab에서 엽니다. "
                                                    "주문 수 변화는 0%(가정 없음)로 시작합니다.")
st.caption("선정 기준: 최근 3일(급증·판매 없음은 전일)을 최근 4주 동일 요일과 비교. 금액 영향이 큰 순서로 최대 4건 표시.")

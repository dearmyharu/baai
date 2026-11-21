"""그로스 대시보드 ver.2

실행: run.bat 더블클릭, 또는 dashboard_v2 폴더에서 streamlit run app.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="그로스 대시보드 v2", page_icon="🥗", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-size: 1.5rem;}
  h1 {font-size: 1.8rem !important;}
  h3 {font-size: 1.15rem !important; margin-top: .6rem;}
</style>
""", unsafe_allow_html=True)

PAGES = {
    "home": st.Page("views/home.py", title="아침 브리핑", icon=":material/today:", default=True),
    "chat": st.Page("views/chat.py", title="AI 분석가", icon=":material/chat:"),
    "lab": st.Page("views/growth_lab.py", title="Growth Lab", icon=":material/science:"),
    "explore": st.Page("views/explore.py", title="자세히 보기", icon=":material/monitoring:"),
}
# 기준일(오늘): 모든 화면이 함께 쓴다. 이 날짜 아침 시점으로 보고, 데이터는 전일까지만 쓴다.
import pandas as pd  # noqa: E402
from engine.briefing import SHIP_COST  # noqa: E402
from engine.data import PERIOD_END, PERIOD_START  # noqa: E402

from engine import ui  # noqa: E402

# 기준일 범위는 실제로 읽은 데이터의 마지막 날에 맞춘다(DB에 10월이 아직 없으면 9/30까지)
_last = ui.get_mart()["orders"]["order_time"].max().normalize()
_max = min(_last + pd.Timedelta(days=1), PERIOD_END)
_default = min(pd.Timestamp("2026-10-22"), _max)
if "today" in st.session_state and pd.Timestamp(st.session_state["today"]) > _max:
    st.session_state["today"] = _max.date()
sb = st.sidebar
sb.date_input("기준일(오늘)", value=_default.date(),
              min_value=(PERIOD_START + pd.Timedelta(days=35)).date(), max_value=_max.date(),
              key="today", help="이 날짜 아침에 보는 화면입니다. 데이터는 전일까지만 씁니다.")
sb.caption(f"데이터: 2026-04-01 ~ {_last:%Y-%m-%d} (가상 데이터, 10월 프로모션은 모의)")
sb.caption(f"이익 = 결제 금액 − 상품원가 − 배송 원가(주문당 {SHIP_COST:,}원 가정). 결제 수수료 등 기타 비용 제외")

page = st.navigation({"오늘": [PAGES["home"]], "결정": [PAGES["chat"], PAGES["lab"]], "분석": [PAGES["explore"]]})
if target := st.session_state.pop("goto", None):
    st.switch_page(PAGES[target])
page.run()

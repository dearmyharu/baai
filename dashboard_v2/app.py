"""그로스 대시보드 ver.2

실행: run.bat 더블클릭, 또는 dashboard_v2 폴더에서 streamlit run app.py
- 기준일: 2026-10-26(월) 아침으로 고정, 데이터는 10/25까지 (engine/data.py TODAY)
- AI 분석가: 모든 화면 오른쪽 패널(engine/chat_panel.py). 답변의 계산 결과는 왼쪽에 질문 대시보드로 띄움(engine/popup.py)
  처리 순서: engine/pipeline.py (AI는 질문 해석만, 계산·문장은 코드)
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="그로스 대시보드 v2", page_icon="🥗", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1800px;}
  [data-testid="stMetricValue"] {font-size: 1.45rem;}
  h1 {font-size: 1.8rem !important;}
  h3 {font-size: 1.15rem !important; margin-top: .6rem;}
</style>
""", unsafe_allow_html=True)

import pandas as pd  # noqa: E402

from engine import chat_panel, popup, ui  # noqa: E402
from engine import data as D  # noqa: E402
from engine.briefing import SHIP_COST  # noqa: E402

ss = st.session_state
D.set_cutoff(D.TODAY)
ss["today"] = D.TODAY.date()          # 기존 화면 코드 호환(기준일 고정)

PAGES = {
    "home": st.Page("views/home.py", title="아침 브리핑", icon=":material/today:", default=True),
    "overview": st.Page("views/overview.py", title="통합 현황", icon=":material/dashboard:"),
    "curation": st.Page("views/curation.py", title="상품·큐레이션", icon=":material/storefront:"),
    "journey": st.Page("views/journey.py", title="고객 여정·전환", icon=":material/conversion_path:"),
    "retention": st.Page("views/retention.py", title="고객·리텐션", icon=":material/group:"),
    "lab": st.Page("views/growth_lab.py", title="Growth Lab", icon=":material/science:"),
}
page = st.navigation({"오늘": [PAGES["home"]],
                      "분석": [PAGES["overview"], PAGES["curation"], PAGES["journey"], PAGES["retention"]],
                      "실행": [PAGES["lab"]]})
if target := ss.pop("goto", None):
    st.switch_page(PAGES[target])

# 화면을 옮기면 질문 대시보드는 닫는다
if ss.get("page_title") != page.title:
    ss.page_title = page.title
    ss.active_dash = None

sb = st.sidebar
sb.markdown(f"**기준일 {D.TODAY:%Y-%m-%d}(월) 아침**  \n데이터 2026-04-01 ~ {ui.LAST_DAY:%Y-%m-%d}")
last = ui.get_mart()["orders"]["order_time"].max()
if pd.isna(last) or last.normalize() < ui.LAST_DAY:
    sb.warning(f"읽은 데이터가 {last:%Y-%m-%d}까지입니다. DB에 10월 데이터를 넣어야 10월 화면이 나옵니다.")
sb.caption(f"가상 데이터 · 10월 프로모션은 모의 · 이익 = 결제 금액 − 상품원가 − 배송 원가(주문당 {SHIP_COST:,}원 가정)")
ss.setdefault("chat_open", True)
show_chat = sb.toggle("AI 분석가 열기", key="chat_open",
                      help="모든 화면 오른쪽에 AI 분석가를 띄웁니다. 화면을 옮겨도 대화는 이어집니다.")

if not show_chat:
    page.run()
    st.stop()

main, side = st.columns([7, 3], gap="medium")
with side:                 # 패널을 먼저 그린다: 화면 코드가 st.stop()으로 일찍 끝나도 패널은 남는다
    chat_panel.render()
with main:
    result, q = chat_panel.dash()
    if result is not None:
        # 질문 대시보드를 화면 자리에 띄운다. 원래 화면은 숨겨서 계속 그린다(사이드바 입력값 유지)
        popup.render(result, q, chat_panel.close_dash, key=f"main_{ss.get('active_dash')}")
        st.markdown("<style>.st-key-page_hidden {display: none;}</style>", unsafe_allow_html=True)
        with st.container(key="page_hidden"):
            page.run()
    else:
        page.run()

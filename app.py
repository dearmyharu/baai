"""BAAI 식품 이커머스 그로스 대시보드.

실행:  streamlit run app.py   (dashboard 폴더에서)
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="그로스 대시보드", page_icon="🥗", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1800px;}
  [data-testid="stMetricValue"] {font-size: 1.55rem;}
  h1 {font-size: 1.8rem !important;}
  h3 {font-size: 1.15rem !important; margin-top: .4rem;}
</style>
""", unsafe_allow_html=True)

pages = {
    "분석": [
        st.Page("views/overview.py", title="통합 현황", icon=":material/dashboard:", default=True),
        st.Page("views/curation.py", title="상품·큐레이션", icon=":material/storefront:"),
        st.Page("views/journey.py", title="고객 여정·전환", icon=":material/conversion_path:"),
        st.Page("views/retention.py", title="고객·리텐션", icon=":material/group:"),
    ],
    "실행": [
        st.Page("views/growth_lab.py", title="Growth Lab", icon=":material/science:"),
    ],
}
page = st.navigation(pages)
st.session_state.growth_active = page.title == "Growth Lab"
if st.session_state.pop("goto_growth", False):
    st.switch_page("views/growth_lab.py")
if st.session_state.pop("goto_overview", False):      # 질문 대시보드의 '이 기간으로 통합 현황 열기'
    st.switch_page("views/overview.py")

# AI 분석가: 별도 화면이 아니라 모든 화면 오른쪽에 붙은 채팅 패널 (사이드바에서 열고 닫기)
show_chat = st.sidebar.toggle("AI 분석가 열기", value=True, key="chat_open",
                              help="모든 화면 오른쪽에 AI 분석가 채팅을 띄웁니다. 대화는 화면을 옮겨도 유지됩니다.")
# 다른 화면으로 옮기면 질문 대시보드는 닫는다
if st.session_state.get("last_page") != page.title:
    st.session_state.last_page = page.title
    st.session_state.active_dash = None

if show_chat:
    from core import chat, popup, ui
    main, side = st.columns([7, 3], gap="medium")
    with side:                 # 패널을 먼저 그린다: 화면 코드가 st.stop()으로 일찍 끝나도 패널은 남는다
        chat.render(ui.get_mart())
    with main:
        log, i = st.session_state.get("ask_log", []), st.session_state.get("active_dash")
        spec = popup.spec_from_calls(log[i].get("calls")) if i is not None and i < len(log) else None
        if spec:
            # 질문 대시보드를 화면 자리에 띄운다. 원래 화면은 숨겨서 계속 그린다(사이드바 기간 등 입력값 유지)
            popup.render(ui.get_mart(), spec, log[i]["q"], key=f"main_{i}")
            st.markdown("<style>.st-key-page_hidden {display: none;}</style>", unsafe_allow_html=True)
            with st.container(key="page_hidden"):
                page.run()
        else:
            page.run()
else:
    page.run()

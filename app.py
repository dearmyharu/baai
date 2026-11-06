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

# AI 분석가: 별도 화면이 아니라 모든 화면 오른쪽에 붙은 채팅 패널 (사이드바에서 열고 닫기)
show_chat = st.sidebar.toggle("AI 분석가 열기", value=True, key="chat_open",
                              help="모든 화면 오른쪽에 AI 분석가 채팅을 띄웁니다. 대화는 화면을 옮겨도 유지됩니다.")
if show_chat:
    from core import chat, ui
    main, side = st.columns([7, 3], gap="medium")
    with side:                 # 패널을 먼저 그린다: 화면 코드가 st.stop()으로 일찍 끝나도 패널은 남는다
        chat.render(ui.get_mart())
    with main:
        page.run()
else:
    page.run()

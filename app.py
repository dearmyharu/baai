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
  .block-container {padding-top: 2rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-size: 1.55rem;}
  h1 {font-size: 1.8rem !important;}
  h3 {font-size: 1.15rem !important; margin-top: .4rem;}
</style>
""", unsafe_allow_html=True)

pages = {
    "질문하기": [
        st.Page("views/ask.py", title="AI 분석가", icon=":material/chat:", default=True),
    ],
    "분석": [
        st.Page("views/overview.py", title="통합 현황", icon=":material/dashboard:"),
        st.Page("views/curation.py", title="상품·큐레이션", icon=":material/storefront:"),
        st.Page("views/journey.py", title="고객 여정·전환", icon=":material/conversion_path:"),
        st.Page("views/retention.py", title="고객·리텐션", icon=":material/group:"),
    ],
    "실행": [
        st.Page("views/growth_lab.py", title="Growth Lab", icon=":material/science:"),
    ],
}
st.navigation(pages).run()

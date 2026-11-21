"""Growth Lab (다음 단계에서 구현): 해결 방법의 손익·이익 확률·확인 기간을 계산하고 실행 계획을 등록한다."""
import streamlit as st

st.title("Growth Lab")
st.info("다음 단계에서 구현합니다. 아침 브리핑의 버튼으로 넘어온 요청은 아래에 표시됩니다.")
if req := st.session_state.get("lab_request"):
    st.json(req)

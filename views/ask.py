"""⓪ AI 분석가: 궁금한 것을 물으면 데이터를 찾아 차트로 보여준다.

GEMINI_API_KEY가 있으면: 질문 → Gemini가 도구(core/tools.py)와 기간을 고름 → 도구 실행 → Gemini가 결과를 근거로 설명.
키가 없으면: 예시 질문 버튼만 정해진 도구를 바로 실행한다.
"""
import os

import altair as alt
import pandas as pd
import streamlit as st

from core import llm, tools, ui

m = ui.get_mart()

st.title("AI 분석가")
st.caption("궁금한 것을 물어보면 데이터를 찾아 숫자와 차트로 보여 드립니다. 데이터 기간: 2026-04-01 ~ 2026-09-30")


def llm_key() -> str | None:
    try:
        v = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        v = None
    v = (v or os.getenv("GEMINI_API_KEY") or "").strip()
    return v if v and "붙여넣기" not in v else None


KEY = llm_key()
if not KEY:
    st.info("AI 모델이 아직 연결되지 않았습니다. 지금은 아래 **예시 질문**에 답할 수 있어요. "
            "Secrets에 GEMINI_API_KEY를 넣으면 자유롭게 질문할 수 있습니다.", icon=":material/info:")

@st.cache_data(ttl=3600, show_spinner=False)
def model_info(key: str) -> tuple[str, list[str]]:
    try:
        return llm.pick_model(key), llm.text_models(key)
    except Exception as e:  # 목록 조회 실패해도 화면은 계속
        return f"(확인 실패: {e})", []


if KEY:
    cur_model, all_models = model_info(KEY)
    with st.expander(f"AI 모델: {cur_model}", icon=":material/tune:"):
        st.markdown("기본은 이 키로 쓸 수 있는 **가장 낮은(가벼운) Flash 모델**을 자동으로 고릅니다. "
                    "다른 모델을 쓰려면 Streamlit Secrets에 아래 한 줄을 추가하고 앱을 다시 시작하세요.")
        st.code(f'GEMINI_MODEL = "{cur_model}"', language="toml")
        if all_models:
            st.caption("이 키로 쓸 수 있는 모델: " + ", ".join(all_models))

if "ask_log" not in st.session_state:
    st.session_state.ask_log = []
log = st.session_state.ask_log


# ---------------------------------------------------------------------------
# 결과 그리기
# ---------------------------------------------------------------------------
def draw_chart(c: dict):
    d = c["data"]
    kind = c["kind"]
    if kind in ("bar", "funnel") and not c.get("vertical"):
        sort = list(d[c["y"]]) if kind == "funnel" else "-x"
        ch = alt.Chart(d).mark_bar(color=ui.C_MAIN, cornerRadiusEnd=3).encode(
            x=alt.X(f"{c['x']}:Q", title=None, axis=alt.Axis(format=c.get("x_fmt", ",.0f"))),
            y=alt.Y(f"{c['y']}:N", sort=sort, title=None),
            tooltip=[c["y"], alt.Tooltip(c["x"], format=c.get("x_fmt", ",.0f"))])
        h = max(160, 30 * len(d))
    elif kind == "bar":
        ch = alt.Chart(d).mark_bar(color=ui.C_MAIN, cornerRadiusEnd=3).encode(
            x=alt.X(f"{c['x']}:N", sort=list(d[c["x"]]), title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{c['y']}:Q", title=None, axis=alt.Axis(format=c.get("y_fmt", ",.0f"))),
            tooltip=[c["x"], alt.Tooltip(c["y"], format=c.get("y_fmt", ",.0f"))])
        h = 240
    elif kind == "line":
        ch = alt.Chart(d).mark_line(point=True, color=ui.C_MAIN).encode(
            x=alt.X(f"{c['x']}:T", title=None),
            y=alt.Y(f"{c['y']}:Q", title=None, axis=alt.Axis(format=c.get("y_fmt", ",.0f"))),
            tooltip=[alt.Tooltip(f"{c['x']}:T"), alt.Tooltip(c["y"], format=",.0f")])
        h = 280
    else:  # scatter
        enc = dict(
            x=alt.X(f"{c['x']}:Q", title=c["x"], scale=alt.Scale(type="log") if c.get("x_log") else alt.Scale(zero=False),
                    axis=alt.Axis(format=c.get("x_fmt", ",.0f"))),
            y=alt.Y(f"{c['y']}:Q", title=c["y"], scale=alt.Scale(zero=False), axis=alt.Axis(format=c.get("y_fmt", ",.0f"))),
            tooltip=[c.get("label", c["x"]), alt.Tooltip(c["x"], format=c.get("x_fmt", ",.0f")),
                     alt.Tooltip(c["y"], format=c.get("y_fmt", ",.0f"))])
        if c.get("color"):
            enc["color"] = alt.Color(f"{c['color']}:N", legend=alt.Legend(title=None))
        ch = alt.Chart(d).mark_circle(size=90, opacity=0.85).encode(**enc)
        h = 320
    st.altair_chart(ch.properties(height=h), width="stretch")


def show_result(res: dict):
    st.markdown(f"**{res['title']}** · 기준 기간 {res['period']}")
    for f in res["facts"]:
        st.markdown(f"- {f}")
    if res.get("chart") is not None:
        draw_chart(res["chart"])
    if res.get("table") is not None:
        with st.expander("표로 보기"):
            st.dataframe(res["table"], hide_index=True, width="stretch")
    for n in res.get("notes", []):
        ui.note(n)


def run_direct(tool: str, params: dict) -> dict:
    """LLM 없이 정해진 도구를 바로 실행 (키가 없을 때 예시 질문용)."""
    try:
        return {"a": "", "results": [tools.run(m, tool, **params)], "tools": [tool]}
    except Exception as e:  # 기간이 데이터 밖이거나 계산 불가
        return {"a": f"이 질문은 지금 데이터로 답하기 어렵습니다: {e}"}


def answer(question: str, tool: str | None = None, params: dict | None = None):
    entry = {"q": question}
    if KEY:
        history = [{"q": e["q"], "a": e.get("a", "")} for e in log]
        try:
            with st.spinner("데이터를 찾아 분석하는 중..."):
                r = llm.ask(KEY, question, lambda name, p: tools.run(m, name, **p), history)
            entry.update(a=r["text"], model=r["model"],
                         results=[c["result"] for c in r["calls"] if "result" in c],
                         tools=[f"{c['tool']}({', '.join(f'{k}={v}' for k, v in c['params'].items())})" for c in r["calls"]])
        except Exception as e:  # API 오류·시간 초과 등: 앱이 멈추지 않게 안내만 한다
            msg = str(e) if isinstance(e, llm.LLMError) else f"AI 분석 중 문제가 생겼습니다({type(e).__name__}). 다시 질문해 주세요."
            entry.update(run_direct(tool, params or {}) if tool else {})
            entry["a"] = f"⚠️ {msg}" + (" 대신 정해진 분석 결과를 보여 드립니다." if tool else "")
    elif tool is None:
        entry["a"] = "AI 모델이 연결되면 이런 자유 질문에도 답할 수 있어요. 지금은 아래 예시 질문 중 비슷한 것을 골라 주세요."
    else:
        entry.update(run_direct(tool, params or {}))
    log.append(entry)


# ---------------------------------------------------------------------------
# 대화
# ---------------------------------------------------------------------------
for e in log:
    with st.chat_message("user"):
        st.markdown(e["q"])
    with st.chat_message("assistant"):
        if e.get("a"):
            st.markdown(e["a"])
        for res in e.get("results", []):
            show_result(res)
        if e.get("tools") and e.get("model"):
            st.caption(f"사용한 분석: {' · '.join(e['tools'])} · 모델 {e['model']}")

q = st.chat_input("예: 이번 달 매출 제일 많이 나온 상품은?")
if q:
    hit = next((ex for ex in tools.EXAMPLES if ex[0].replace(" ", "") == q.replace(" ", "")), None)
    answer(q, *(hit[1:] if hit else (None, None)))   # 키가 있으면 어떤 질문이든 Gemini가 답한다
    st.rerun()

st.markdown("**예시 질문**")
cols = st.columns(2)
for i, (eq, tool, params) in enumerate(tools.EXAMPLES):
    if cols[i % 2].button(eq, key=f"ex_{i}", use_container_width=True):
        answer(eq, tool, params)
        st.rerun()

if log:
    if st.button("대화 지우기", icon=":material/delete:"):
        log.clear()
        st.rerun()
ui.note("이번 달 = 2026년 9월, 지난달 = 8월로 해석합니다(데이터 마지막 날 기준). "
        "숫자는 모두 대시보드와 같은 계산 함수로 만듭니다. 원인·대책은 데이터로 확인된 사실이 아니라 가설입니다.")

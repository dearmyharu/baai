"""AI 분석가 = 모든 화면 오른쪽 채팅 패널 (app.py가 render()를 부른다).

- 질문 답변: llm(모델이 도구를 고르고 설명) + tools(숫자 계산). 숫자는 계산 엔진이 만든다.
- 분석 흐름(진단→원인→가설→실험→판정 조건, 되묻기, 다음 질문, Growth Lab 요청): case.py
- 답변에 쓴 분석은 왼쪽 화면에 '질문 대시보드'로 크게 띄운다(popup.py). 닫으면 원래 화면.
- 지금 보고 있는 화면의 요약(page_context, Growth Lab은 growth_context)을 함께 넘긴다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import case as C
from . import data as D
from . import llm as L
from . import popup
from . import tools as T
from . import ui

PANEL_CSS = """
<style>
  .st-key-chat_panel {background: #F6F9F8; border: 1px solid #DCE7E3; border-radius: 14px; padding: .6rem .7rem;}
  .st-key-chat_panel [data-testid="stChatMessage"] {padding: .35rem .2rem;}
  .st-key-chat_panel .stButton button {font-size: .85rem; text-align: left;}
</style>
"""
ss = st.session_state


@st.cache_data(max_entries=64, show_spinner=False)
def _diagnose(target_type: str, target_value: str):
    return C.diagnose(ui.get_mart(), {"type": target_type, "value": target_value}, D.TODAY)


def _diag(case):
    t = case.get("target")
    return _diagnose(t["type"], t["value"]) if t else None


def _history(log):
    out, last_q = [], None
    for e in log:
        if e["role"] == "user":
            last_q = e["text"]
        elif e["role"] == "assistant" and last_q:
            out.append({"q": last_q, "a": e.get("text", "")})
            last_q = None
    return out


def _context(case) -> str:
    parts = [C.context_text(case, _diag(case))]
    if ss.get("page_context"):
        parts.append("[사용자가 지금 보고 있는 화면] " + ss["page_context"])
    return "\n".join(p for p in parts if p)


def run_question(q: str):
    m = ui.get_mart()
    log, case = ss.chat_log, ss.case
    log.append({"role": "user", "text": q})
    key = L.api_key()
    if not key:
        log.append({"role": "assistant", "error": "AI 키가 없습니다. Secrets(또는 .streamlit/secrets.toml)에 OPENAI_API_KEY를 넣어 주십시오."})
        return
    on_lab = ss.get("page_title") == "Growth Lab"
    try:
        with st.spinner("분석하는 중입니다..."):
            r = L.ask(key, q, lambda n, p: T.run(m, n, **p), history=_history(log)[-L.HISTORY_TURNS:],
                      today=D.TODAY, case_context=_context(case),
                      growth_context=ss.get("growth_context") if on_lab else None)
    except L.LLMError as e:
        log.append({"role": "assistant", "error": str(e)})
        return
    a, calls = r.get("answer"), r.get("calls", [])
    C.update(case, m, a, q, calls)
    if on_lab and (sug := C._from_simulation(calls)):
        ss.lab_suggestion = sug               # Growth Lab 화면이 나중에 입력칸 반영에 쓸 값(버튼은 화면 개편 때)
    ok_calls = [c for c in calls if "result" in c]
    log.append({"role": "assistant", "q": q, "answer": a, "text": r.get("text", ""), "calls": calls,
                "clarify": r.get("clarify"), "model": r.get("model", ""), "usage": r.get("usage")})
    if popup.spec_from_calls(ok_calls):
        ss.active_dash = len(log) - 1        # 답이 나오면 질문 대시보드를 왼쪽에 바로 띄운다


# --------------------------------------------------------------------- 버튼 동작
def _queue(q: str):
    ss.pending_q = q


def _choose(step: str, label: str, values: dict):
    ss.case.update(values)
    ss.chat_log.append({"role": "note", "text": f"{step}: {label}(으)로 정했습니다."})


def _reset():
    ss.chat_log, ss.case, ss.active_dash = [], C.new_case(), None


def _to_lab(req: dict):
    ss.lab_request = req
    ss.active_dash = None
    ss.goto = "lab"


def _show_dash(i: int):
    ss.active_dash = i


def dash_spec():
    """왼쪽에 띄울 질문 대시보드 설정(없으면 None). app.py가 쓴다."""
    log, i = ss.get("chat_log", []), ss.get("active_dash")
    if i is None or i >= len(log) or log[i].get("role") != "assistant":
        return None, None
    calls = [c for c in log[i].get("calls") or [] if "result" in c]
    spec = popup.spec_from_calls(calls)
    return spec, log[i].get("q", "")


# --------------------------------------------------------------------- 화면
def _answer(e, i, last):
    if e.get("error"):
        st.error(e["error"])
        return
    a = e.get("answer")
    if a:
        st.markdown(f"**{a.get('conclusion', '')}**".replace("~", "\\~"))
        for ev in a.get("evidence", []):
            st.markdown(f"- {ev}".replace("~", "\\~"))
        if a.get("hypothesis"):
            st.markdown(f"<span style='color:{ui.C_ACCENT};font-weight:600'>가설</span> {a['hypothesis']}",
                        unsafe_allow_html=True)
        if a.get("notice"):
            st.caption(a["notice"])
    else:
        st.markdown(str(e.get("text", "")).replace("~", "\\~"))
    calls = [c for c in e.get("calls") or [] if "result" in c]
    if popup.spec_from_calls(calls):
        if ss.get("active_dash") == i:
            st.caption("← 왼쪽에 이 질문의 대시보드를 띄웠습니다.")
        else:
            st.button("대시보드 보기", key=f"dash_{i}", icon=":material/dashboard:", on_click=_show_dash, args=(i,))
    if e.get("clarify") and last:
        for j, lab in enumerate(e["clarify"]):
            st.button(lab, key=f"clar_{i}_{j}", on_click=_queue, args=(L.with_period(e["q"], lab, D.TODAY),),
                      width="stretch")


def _progress(case, checks):
    marks = " ".join(("✅" if c["ok"] else "⬜") + c["step"] for c in checks)
    with st.expander(f"분석 진행 {marks}", expanded=False):
        for c in checks:
            st.markdown(f"{'✅' if c['ok'] else '⬜'} **{c['step']}** <span style='font-size:.8rem;color:gray'>{c['note']}</span>",
                        unsafe_allow_html=True)
        if case.get("hypothesis"):
            st.caption(f"원인 가설(확인 전): {case['hypothesis']}")


def render():
    ss.setdefault("chat_log", [])
    ss.setdefault("case", C.new_case())
    m = ui.get_mart()
    # 브리핑 버튼으로 넘어온 질문·대상 / 버튼으로 고른 질문
    if q := ss.pop("pending_question", None):
        _reset()
        if seed := ss.pop("pending_seed", None):
            ss.case["target"] = seed
            d0 = _diagnose(seed["type"], seed["value"])
            if d0:
                ss.chat_log.append({"role": "diag", "text": f"{C.target_text(seed)} 진단(계산 엔진): {C.diag_text(d0)}"})
        run_question(q)
    elif q := ss.pop("pending_q", None):
        run_question(q)
    log, case = ss.chat_log, ss.case

    st.markdown(PANEL_CSS, unsafe_allow_html=True)
    with st.container(key="chat_panel"):
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown("**AI 분석가**")
        with h2.popover("", icon=":material/more_vert:"):
            st.button("새 분석 시작(대화 지우기)", on_click=_reset, width="stretch")
            st.caption(f"기준: {D.TODAY:%Y-%m-%d} 아침, 데이터는 {D.TODAY - pd.Timedelta(days=1):%Y-%m-%d}까지. "
                       "숫자는 모두 계산 엔진이 만들고, 원인·대책은 가설입니다.")
        checks = C.check(case, _diag(case))
        if log:
            _progress(case, checks)

        with st.container(height=540, border=False, key="chat_msgs"):
            if not log:
                st.caption("궁금한 것을 물어보면 데이터를 찾아 답합니다. 문제를 찾는 질문(무엇이 줄었나, 어디서 줄었나)으로 "
                           "시작하면 대상과 수단을 정해 Growth Lab으로 넘길 수 있습니다. 화면을 옮겨도 대화는 이어집니다.")
            last_ai = max([i for i, e in enumerate(log) if e["role"] == "assistant"], default=-1)
            for i, e in enumerate(log):
                if e["role"] == "user":
                    with st.chat_message("user"):
                        st.markdown(e["text"].replace("~", "\\~"))
                elif e["role"] == "note":
                    st.caption(f"✓ {e['text']}")
                elif e["role"] == "diag":
                    st.info(e["text"])
                else:
                    with st.chat_message("assistant"):
                        _answer(e, i, i == last_ai)

            # 다섯 조건이 다 차면 Growth Lab, 아니면 빠진 조건 되묻기(문제 분석을 시작한 경우만)
            if C.ready(checks):
                st.success("다섯 조건이 갖춰졌습니다.")
                st.button("Growth Lab에서 계획 세우기", type="primary", width="stretch",
                          on_click=_to_lab, args=(C.lab_request(case, _diag(case)),))
            elif case.get("target") or case.get("candidates") or case.get("lever"):
                mq = C.missing_question(case, m, D.TODAY, checks)
                if mq:
                    st.markdown(f"<span style='font-size:.9rem'>{mq['text']}</span>", unsafe_allow_html=True)
                    for j, ch in enumerate(mq["choices"]):
                        st.button(ch["label"], key=f"mq_{mq['step']}_{j}", on_click=_choose,
                                  args=(mq["step"], ch["label"], ch["set"]), width="stretch")
            st.caption("이어서 확인할 것" if log else "이렇게 시작할 수 있습니다")
            for j, nq in enumerate(C.next_questions(case)):
                st.button(nq, key=f"next_{len(log)}_{j}", icon=":material/subdirectory_arrow_right:",
                          on_click=_queue, args=(nq,), width="stretch")

        if q := st.chat_input("무엇이든 물어보십시오", key="chat_q"):
            _queue(q)
            st.rerun()

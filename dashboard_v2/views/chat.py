"""AI 분석가: 진단 → 원인 → 가설까지 대화로 좁히고, 조건이 갖춰지면 Growth Lab으로 넘긴다.

- 질문 답변: engine/llm.py(모델이 도구를 고르고 설명) + engine/tools.py(숫자 계산)
- 분석 흐름·조건 확인·되묻기·다음 질문: engine/case.py (코드가 정함)
- 기준일(오늘) 이전 데이터만 본다(engine/data.as_of).
"""
import pandas as pd
import streamlit as st

from engine import case as C
from engine import data as D
from engine import llm as L
from engine import tools as T
from engine import ui

ss = st.session_state
today = pd.Timestamp(ss.get("today", pd.Timestamp("2026-10-22")))
day_str = f"{today:%Y-%m-%d}"
D.set_cutoff(today)


@st.cache_resource(max_entries=3, show_spinner="기준일까지의 데이터를 준비하는 중입니다...")
def _mart(day: str):
    return D.as_of(ui.get_mart(), day)


@st.cache_data(max_entries=64, show_spinner=False)
def _diagnose(target_type: str, target_value: str, day: str):
    return C.diagnose(_mart(day), {"type": target_type, "value": target_value}, day)


mt = _mart(day_str)

# 기준일이 바뀌면 대화를 새로 시작한다(다른 날 아침의 분석이므로)
if ss.get("chat_day") != day_str:
    ss.chat_day, ss.chat_log, ss.case = day_str, [], C.new_case()
ss.setdefault("chat_log", [])
ss.setdefault("case", C.new_case())


def _history():
    out, last_q = [], None
    for e in ss.chat_log:
        if e["role"] == "user":
            last_q = e["text"]
        elif e["role"] == "assistant" and last_q:
            out.append({"q": last_q, "a": e.get("text", "")})
            last_q = None
    return out


def run_question(q: str):
    log, case = ss.chat_log, ss.case
    log.append({"role": "user", "text": q})
    key = L.api_key()
    if not key:
        log.append({"role": "assistant", "error": "AI 키가 없습니다. dashboard_v2/.streamlit/secrets.toml에 OPENAI_API_KEY를 넣어 주십시오."})
        return
    try:
        with st.spinner("분석하는 중입니다..."):
            t = case.get("target")
            diag = _diagnose(t["type"], t["value"], day_str) if t else None
            r = L.ask(key, q, lambda n, p: T.run(mt, n, **p), history=_history()[-L.HISTORY_TURNS:],
                      today=today, case_context=C.context_text(case, diag))
    except L.LLMError as e:
        log.append({"role": "assistant", "error": str(e)})
        return
    a = r.get("answer")
    C.update(case, mt, a, q, r.get("calls"))
    log.append({"role": "assistant", "q": q, "answer": a, "text": r.get("text", ""), "calls": r.get("calls", []),
                "clarify": r.get("clarify"), "model": r.get("model", ""), "usage": r.get("usage")})


def _queue(q: str):
    ss.queued_q = q


def _choose(step: str, label: str, values: dict):
    ss.case.update(values)
    ss.chat_log.append({"role": "note", "text": f"{step}: {label}(으)로 정했습니다."})


def _reset():
    ss.chat_log, ss.case = [], C.new_case()


def _to_lab(req: dict):
    ss.lab_request = req
    ss.goto = "lab"


# 브리핑에서 넘어온 질문·대상, 버튼으로 고른 질문
if q := ss.pop("pending_question", None):
    _reset()
    if seed := ss.pop("pending_seed", None):
        ss.case["target"] = seed
        d0 = _diagnose(seed["type"], seed["value"], day_str)
        if d0:
            ss.chat_log.append({"role": "diag", "text": f"{C.target_text(seed)} 진단(계산 엔진): {C.diag_text(d0)}"})
    run_question(q)
elif q := ss.pop("queued_q", None):
    run_question(q)
case, log = ss.case, ss.chat_log

# ---------------------------------------------------------------- 화면
st.title("AI 분석가")
st.caption(f"기준일 {today:%Y-%m-%d} 아침 · 데이터는 {today - pd.Timedelta(days=1):%Y-%m-%d}까지 · "
           "숫자는 계산 엔진이 만들고 AI는 분석을 고르고 설명합니다")
left, right = st.columns([2.2, 1], gap="large")


def _render_calls(calls: list[dict]):
    for c in calls:
        res = c.get("result")
        if not res:
            if c.get("error"):
                st.caption(f"계산 오류: {c['error']}")
            continue
        st.markdown(f"**{res.get('title', '')}** · {res.get('period', '')}")
        for f in res.get("facts", [])[:8]:
            st.markdown(f"- {f}")
        tb = res.get("table")
        if isinstance(tb, pd.DataFrame) and not tb.empty:
            st.dataframe(tb.head(30), hide_index=True, use_container_width=True)
        for n in res.get("notes", []) or []:
            st.caption(n)


with left:
    if not log:
        st.info("아침 브리핑의 '원인 분석' 버튼으로 시작하거나, 아래에서 질문을 입력하십시오. "
                "대상(어디서)과 수단(무엇으로)이 정해지면 Growth Lab으로 넘길 수 있습니다.")
    last_ai = max([i for i, e in enumerate(log) if e["role"] == "assistant"], default=-1)
    for i, e in enumerate(log):
        if e["role"] == "user":
            with st.chat_message("user"):
                st.markdown(e["text"])
        elif e["role"] == "note":
            st.caption(f"✓ {e['text']}")
        elif e["role"] == "diag":
            st.info(e["text"])
        else:
            with st.chat_message("assistant"):
                if e.get("error"):
                    st.error(e["error"])
                    continue
                a = e.get("answer")
                if a:
                    st.markdown(f"**{a.get('conclusion', '')}**")
                    for ev in a.get("evidence", []):
                        st.markdown(f"- {ev}")
                    if a.get("hypothesis"):
                        st.markdown(f"<span style='color:{ui.C_ACCENT};font-weight:600'>가설</span> {a['hypothesis']}",
                                    unsafe_allow_html=True)
                    if a.get("notice"):
                        st.caption(a["notice"])
                else:
                    st.markdown(e.get("text", ""))
                if e.get("calls"):
                    with st.expander("분석 근거 보기"):
                        _render_calls(e["calls"])
                if e.get("clarify") and i == last_ai:
                    cols = st.columns(len(e["clarify"]))
                    for j, lab in enumerate(e["clarify"]):
                        cols[j].button(lab, key=f"clar_{i}_{j}", on_click=_queue,
                                       args=(L.with_period(e["q"], lab, today),), use_container_width=True)
                if e.get("usage") and e.get("model"):
                    st.caption(L.usage_label(e["model"], e["usage"]))
    st.markdown("**이어서 확인할 것**" if log else "**이렇게 시작할 수 있습니다**")
    cols = st.columns(2)
    for i, q in enumerate(C.next_questions(case)):
        cols[i % 2].button(q, key=f"next_{len(log)}_{i}", on_click=_queue, args=(q,), use_container_width=True)
    if q := st.chat_input("질문을 입력하십시오 (예: 최근 7일 정육 매출이 왜 줄었어?)"):
        _queue(q)
        st.rerun()

with right:
    st.markdown("#### 분석 진행")
    t = case.get("target")
    diag = _diagnose(t["type"], t["value"], day_str) if t else None
    checks = C.check(case, diag)
    for c in checks:
        mark = "✅" if c["ok"] else "⬜"
        st.markdown(f"{mark} **{c['step']}**  \n<span style='font-size:.85rem;color:gray'>{c['note']}</span>",
                    unsafe_allow_html=True)
    if C.ready(checks):
        st.success("다섯 조건이 갖춰졌습니다. Growth Lab에서 손익·이익 확률·확인 기간을 확인하십시오.")
        st.button("Growth Lab에서 계획 세우기", type="primary", use_container_width=True,
                  on_click=_to_lab, args=(C.lab_request(case, diag),))
    elif case.get("target") or case.get("candidates") or case.get("lever"):   # 문제 분석을 시작한 경우에만 되묻는다
        mq = C.missing_question(case, mt, today, checks)
        if mq:
            with st.container(border=True):
                st.markdown(mq["text"])
                for j, ch in enumerate(mq["choices"]):
                    st.button(ch["label"], key=f"mq_{mq['step']}_{j}", on_click=_choose,
                              args=(mq["step"], ch["label"], ch["set"]), use_container_width=True)
    else:
        st.caption("문제를 찾는 질문(무엇이 줄었나, 어디서 줄었나)으로 시작하면 대상과 수단을 정해 Growth Lab으로 넘길 수 있습니다. "
                   "일반 조회 질문도 답합니다.")
    if case.get("hypothesis"):
        st.caption(f"원인 가설(확인 전): {case['hypothesis']}")
    st.divider()
    st.button("새 분석 시작", on_click=_reset, use_container_width=True)

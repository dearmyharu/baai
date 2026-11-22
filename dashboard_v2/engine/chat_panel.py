"""AI 분석가 = 모든 화면 오른쪽 패널 (app.py가 render()를 부른다).

처리: pipeline.ask(질문) → 답변 카드 / 안내 / 되묻기. 버튼(되묻기 선택지·다음 축·대상·수단)은 완성된 질의서를 들고 있어
AI 없이 바로 계산한다. 흐름 상태(대상·본 축·수단)는 flow.Flow, 넘김 요청은 Flow.lab_request.

화면 규칙(2026-11-22): 카드 = 조건 태그 + 결론 한 줄 + 숫자 최대 3개 + 주의 한 줄. 표·차트는 왼쪽 질문 대시보드.
다음 행동은 버튼, 맨 위 진행 표시줄, 최근 답 2개만 펼치고 이전 답은 결론 한 줄.
"""
from __future__ import annotations

import html
import inspect

import streamlit as st

from . import data as D
from . import flow as FL
from . import pipeline as PL
from . import ui
from .popup import tags_html
from .validate import Choice

ss = st.session_state
# 새 답이 오면 대화 칸을 아래로 (Streamlit 버전에 그 기능이 있을 때만)
SCROLL = {"autoscroll": True} if "autoscroll" in inspect.signature(st.container).parameters else {}
OPEN_ANSWERS = 2          # 펼쳐 보이는 최근 답 수
STARTERS = ["매출이 가장 많이 떨어진 카테고리는?", "어떤 카테고리를 밀어야 해?", "정육 매출 왜 떨어졌어?"]
TONE_COLOR = {"down": ui.C_DOWN, "up": ui.C_UP, "flat": ui.C_MUTED}
TONE_MARK = {"down": "▼", "up": "▲", "flat": ""}
PANEL_CSS = """
<style>
  .st-key-chat_panel {background: #F6F9F8; border: 1px solid #DCE7E3; border-radius: 14px; padding: .6rem .7rem;}
  .st-key-chat_panel .stButton button {font-size: .84rem; text-align: left; padding: .2rem .6rem; min-height: 0;}
  .ap-steps {display: flex; gap: .25rem; flex-wrap: wrap; margin: .1rem 0 .35rem;}
  .ap-step {font-size: .76rem; border-radius: 8px; padding: .15rem .45rem; background: #EEF2F0; color: #6B7280;}
  .ap-step.done {background: #1F6F5C; color: #fff;}
  .ap-card {background: #fff; border: 1px solid #E3EAE7; border-radius: 10px; padding: .55rem .7rem; margin: .2rem 0;}
  .ap-lead {font-size: .8rem; color: #6B7280; margin-bottom: .2rem;}
  .ap-concl {font-weight: 600; font-size: .92rem; line-height: 1.45;}
  .ap-num {display: flex; justify-content: space-between; font-size: .84rem; border-top: 1px dashed #E3EAE7;
           padding: .2rem 0; gap: .5rem;}
  .ap-num .v {font-weight: 600; white-space: nowrap;}
  .ap-note {font-size: .76rem; color: #6B7280; margin-top: .25rem;}
  .ap-user {text-align: right; margin: .45rem 0 .15rem;}
  .ap-user span {background: #1F6F5C; color: #fff; border-radius: 12px 12px 2px 12px; padding: .3rem .65rem;
                 font-size: .86rem; display: inline-block; max-width: 92%; text-align: left;}
  .ap-msg {font-size: .86rem; background: #fff; border-left: 3px solid #D99A2B; padding: .4rem .6rem; border-radius: 6px;}
  .ap-old {font-size: .8rem; color: #6B7280; margin: .1rem 0;}
</style>
"""


def _e(s: str) -> str:
    return html.escape(str(s)).replace("~", "&#126;")


# ---------------------------------------------------------------------------
# 상태
# ---------------------------------------------------------------------------
def _init():
    ss.setdefault("chat_log", [])          # [{'role': 'user'|'outcome'|'note', ...}]
    ss.setdefault("flow", FL.Flow())
    ss.setdefault("prev_query", None)
    ss.setdefault("active_dash", None)


def reset():
    ss.chat_log, ss.flow, ss.prev_query, ss.active_dash = [], FL.Flow(), None, None


def _append(label: str, out: PL.Outcome):
    ss.chat_log.append({"role": "user", "text": label})
    ss.chat_log.append({"role": "outcome", "out": out})
    if out.kind == "answer":
        ss.prev_query = out.query
        ss.flow.record(label, out.query, out.result)
        ss.active_dash = len(ss.chat_log) - 1      # 답이 나오면 질문 대시보드를 왼쪽에 바로 띄운다
    else:
        ss.active_dash = None                      # 안내·되묻기면 이전 질문의 대시보드는 닫는다


def _process_pending(m):
    p = ss.pop("pending", None)
    if not p:
        return
    with st.spinner("계산하는 중입니다..."):
        if p[0] == "question":
            _append(p[1], PL.ask(p[1], m, D.TODAY, prev=ss.prev_query))
        elif p[0] == "query":                     # 버튼: 완성된 질의서 (AI 없음)
            _append(p[1], PL.run_choice(p[1], Choice(p[1], p[2]), m, D.TODAY))
        elif p[0] == "choice":
            _append(p[1], PL.run_choice(p[1], p[2], m, D.TODAY))


# ---------------------------------------------------------------------------
# 버튼 동작
# ---------------------------------------------------------------------------
def _ask(text: str):
    ss.pending = ("question", text)


def _run(label: str, query):
    ss.pending = ("query", label, query)


def _choose(choice: Choice, question: str):
    ss.pending = ("choice", f"{question} → {choice.label}", choice)


def _set_target(cat: str):
    ss.flow.set_target(cat)
    ss.chat_log.append({"role": "note", "text": f"대상: {cat} 카테고리로 정했습니다."})


def _set_lever(policy: str, value):
    ss.flow.set_lever(policy, value)
    ss.chat_log.append({"role": "note", "text": f"수단: {ss.flow.lever['label']}(으)로 정했습니다."})


def _handoff(req: dict):
    ss.lab_request = req
    ss.active_dash = None
    ss.goto = "lab"


def _show_dash(i: int):
    ss.active_dash = i


def close_dash():
    ss.active_dash = None


def dash():
    """왼쪽에 띄울 질문 대시보드 (Result, 질문) 또는 (None, None). app.py가 쓴다."""
    log, i = ss.get("chat_log", []), ss.get("active_dash")
    if i is None or i >= len(log) or log[i]["role"] != "outcome" or log[i]["out"].result is None:
        return None, None
    return log[i]["out"].result, log[i]["out"].question


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
def _steps(m):
    f = ss.flow
    if not (f.target or f.seen):
        return
    steps = f.steps(m, D.TODAY)
    st.markdown("<div class='ap-steps'>" + "".join(
        f"<span class='ap-step{' done' if s['done'] else ''}' title='{_e(s['text'])}'>"
        f"{'✓ ' if s['done'] else ''}{_e(s['name'])}: {_e(s['text'])}</span>" for s in steps) + "</div>",
        unsafe_allow_html=True)
    if all(s["done"] for s in steps):
        st.button(f"Growth Lab에서 {f.target} 손익 보기", type="primary", width="stretch", icon=":material/science:",
                  on_click=_handoff, args=(f.lab_request(m, D.TODAY),), key="handoff")


def _card(out: PL.Outcome, i: int, last: bool):
    c = out.card
    if out.kind in ("message", "clarify", "error"):
        st.markdown(f"<div class='ap-msg'>{_e(c.conclusion)}</div>", unsafe_allow_html=True)
        if last:
            for j, ch in enumerate(out.choices):
                st.button(ch.label, key=f"ch_{i}_{j}", on_click=_choose, args=(ch, out.question), width="stretch")
        return
    nums = "".join(
        f"<div class='ap-num'><span>{_e(n.label)}</span><span class='v' style='color:{TONE_COLOR[n.tone]}'>"
        f"{TONE_MARK[n.tone]} {_e(n.value)}</span></div>"
        + (f"<div class='ap-note' style='margin:-.15rem 0 .1rem;text-align:right'>{_e(n.delta)}</div>" if n.delta else "")
        for n in c.numbers)
    st.markdown(
        "<div class='ap-card'>" + tags_html(c.tags)
        + (f"<div class='ap-lead'>{_e(c.lead)}</div>" if c.lead else "")
        + f"<div class='ap-concl'>{_e(c.conclusion)}</div>{nums}"
        + (f"<div class='ap-note'>참고: {_e(c.note)}</div>" if c.note else "") + "</div>", unsafe_allow_html=True)
    if c.has_dashboard and ss.get("active_dash") != i:
        st.button("대시보드 다시 보기", key=f"dash_{i}", icon=":material/dashboard:", on_click=_show_dash, args=(i,))
    if last:
        for j, a in enumerate(ss.flow.actions(out.query, out.result)):
            if a.kind == "query":
                st.button(a.label, key=f"act_{i}_{j}", on_click=_run, args=(a.label, a.query), width="stretch",
                          icon=":material/subdirectory_arrow_right:")
            elif a.kind == "set_target":
                st.button(a.label, key=f"act_{i}_{j}", on_click=_set_target, args=(a.value,), width="stretch",
                          icon=":material/flag:")


def _levers():
    f = ss.flow
    if f.target and not f.lever:
        st.markdown(f"<div class='ap-lead'>{_e(f.target)}에 쓸 수단을 고르십시오 (손익은 Growth Lab에서 계산합니다)</div>",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for j, a in enumerate(f.lever_actions()):
            cols[j % 2].button(a.label, key=f"lever_{j}", on_click=_set_lever, args=a.value, width="stretch")


def render():
    _init()
    m = ui.get_mart()
    _process_pending(m)
    log = ss.chat_log
    st.markdown(PANEL_CSS, unsafe_allow_html=True)
    with st.container(key="chat_panel"):
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown("**AI 분석가**")
        with h2.popover("", icon=":material/more_vert:"):
            st.button("새 분석 시작(대화 지우기)", on_click=reset, width="stretch")
            st.caption(f"기준: {D.TODAY:%Y-%m-%d} 아침, 데이터는 어제까지. AI는 질문을 해석만 하고, "
                       "숫자와 문장은 계산 함수가 만듭니다. 이유는 추정하지 않습니다.")
        _steps(m)
        with st.container(height=560, border=False, key="chat_msgs", **SCROLL):
            if not log:
                st.caption("데이터에서 찾을 것을 물어보십시오. 예: 어디서 줄었나, 무엇이 잘 팔리나. "
                           "변화 위치를 보고 대상과 수단을 정하면 Growth Lab에서 손익을 볼 수 있습니다.")
                for j, q in enumerate(STARTERS):
                    st.button(q, key=f"start_{j}", on_click=_ask, args=(q,), width="stretch")
            outs = [i for i, e in enumerate(log) if e["role"] == "outcome"]
            open_from = outs[-OPEN_ANSWERS] if len(outs) >= OPEN_ANSWERS else 0
            last = outs[-1] if outs else -1
            for i, e in enumerate(log):
                if e["role"] == "user":
                    st.markdown(f"<div class='ap-user'><span>{_e(e['text'])}</span></div>", unsafe_allow_html=True)
                elif e["role"] == "note":
                    st.caption(f"✓ {e['text']}")
                elif i < open_from:              # 이전 답은 결론 한 줄
                    st.markdown(f"<div class='ap-old'>{_e(e['out'].card.conclusion)}</div>", unsafe_allow_html=True)
                    if e["out"].result is not None and ss.get("active_dash") != i:
                        st.button("대시보드 다시 보기", key=f"dash_{i}", icon=":material/dashboard:",
                                  on_click=_show_dash, args=(i,))
                else:
                    _card(e["out"], i, i == last)
            _levers()
        if q := st.chat_input("데이터에서 찾을 것을 물어보십시오", key="chat_q"):
            _ask(q)
            st.rerun()

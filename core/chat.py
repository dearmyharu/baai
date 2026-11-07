"""AI 분석가 채팅 패널: 모든 화면 오른쪽에 붙어 있는 챗봇.

app.py가 화면(왼쪽) 옆에 render(m)을 불러 그린다. 대화 기록은 화면을 옮겨 다녀도 유지된다(session_state).
OPENAI_API_KEY(또는 GEMINI_API_KEY)가 있으면: 질문 → AI가 도구(core/tools.py)와 기간을 고름 → 도구 실행 → AI가 결과를 근거로 설명.
키가 없으면: 예시 질문 버튼만 정해진 도구를 바로 실행한다.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import llm, popup, store, tools, ui

EXAMPLES_SHOWN = 6        # 대화가 비어 있을 때 보여 줄 예시 질문 수

PANEL_CSS = """
<style>
  /* 채팅 패널이 든 열: 화면을 내려도 오른쪽에 붙어 있게 */
  div[data-testid="stColumn"]:has(.st-key-chat_panel) {position: sticky; top: 3.5rem; align-self: flex-start;}
  .st-key-chat_panel {background: #F7F9F8; border: 1px solid #E5E7EB; border-radius: 12px; padding: .9rem .9rem .6rem;}
  .st-key-chat_msgs {height: calc(100vh - 17rem) !important; min-height: 320px;}
  .st-key-chat_panel [data-testid="stChatMessage"] {padding: .4rem .2rem;}
  .st-key-chat_panel p, .st-key-chat_panel li {font-size: .92rem;}
</style>
"""


@st.cache_data(ttl=3600, show_spinner=False)
def model_list(key: str) -> list[str]:
    return llm.text_models(key)   # 실패하면 예외 → 캐시에 남지 않음



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
    elif kind == "heatmap":   # 기준 2개 교차표
        enc_x = alt.X(f"{c['x']}:O", title=None, sort=c.get("x_order") or "ascending", axis=alt.Axis(labelAngle=0))
        enc_y = alt.Y(f"{c['y']}:O", title=None, sort=c.get("y_order") or "ascending",
                      axis=alt.Axis(labelOverlap=False, labelLimit=160))
        h = max(200, 44 * d[c["y"]].nunique())
        base = alt.Chart(d).encode(x=enc_x, y=enc_y).properties(height=h)
        rect = base.mark_rect(cornerRadius=2).encode(
            color=alt.Color(f"{c['value']}:Q", scale=alt.Scale(scheme="greens"), legend=None),   # 칸 안에 숫자가 있어 범례 생략
            tooltip=[c["y"], c["x"], alt.Tooltip(c["value"], format=c.get("fmt", ",.0f"))])
        text = base.mark_text(fontSize=10).encode(text=alt.Text(f"{c['value']}:Q", format=c.get("fmt", ",.0f")))
        ch = alt.layer(rect, text).properties(height=h)
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


WARN_WORDS = ("표본 부족", "조건에 맞는 고객이 없음")


def show_result(res: dict, folded: bool = False):
    """도구 결과(사실·차트·표·주의). folded=True면 '분석 근거 보기' 안에 접는다(답변 글이 있을 때).
    표본 부족 같은 경고는 접지 않고 항상 보인다."""
    for f in res["facts"]:
        if any(w in f for w in WARN_WORDS):
            st.warning(f, icon=":material/warning:")
    box = st.expander(f"분석 근거 보기 · {res['title']}") if folded else st.container()
    with box:
        st.markdown(f"**{res['title']}** · 기준 기간 {res['period']}")
        for f in res["facts"]:
            st.markdown(f"- {f}")
        if res.get("chart") is not None:
            draw_chart(res["chart"])
        tbl = res.get("display_table") if res.get("display_table") is not None else res.get("table")
        if tbl is not None:
            st.dataframe(tbl, hide_index=True, width="stretch")
        for n in res.get("notes", []):
            ui.note(n)



def _md(t: str) -> str:
    """마크다운 기호가 서식으로 바뀌지 않게: '9-21~9-27'의 ~가 취소선이 되던 문제 등."""
    return str(t).replace("\\", "\\\\").replace("~", "\\~").replace("*", "\\*").replace("_", "\\_")


def show_answer(a: dict):
    """칸으로 받은 답변을 항상 같은 모양으로: 결론(굵게) → 근거 숫자 → 가설 → 참고."""
    st.markdown(f"**{_md(a['conclusion'])}**")
    if a.get("evidence"):
        st.markdown("\n".join(f"- {_md(x)}" for x in a["evidence"]))
    if a.get("hypothesis"):
        st.markdown(f":orange-badge[가설] {_md(a['hypothesis'])}")
    if a.get("notice"):
        st.caption(f"ℹ️ {_md(a['notice'])}")


def ask_next(q: str):
    st.session_state.pending_q = q


def save_to_lab(e: dict, res: dict, key: str):
    """분석 결과 하나를 Growth Lab 문제 후보로 저장 (질문·AI 설명·근거 사실을 함께 넘긴다)."""
    if res.get("simulation"):
        st.button("Growth Lab에서 이 정책 비교하기", key=f"open_{key}", on_click=open_simulation,
                  args=(res["simulation"],))
        return
    ctx = {"page": "AI 분석가", "period": res["period"], "compare": ""}
    default_title = res["title"]
    if key in e.get("saved", []) or store.already_saved(default_title, ctx):
        st.button("Growth Lab에 저장됨 ✓", key=key, disabled=True)
        return
    with st.popover("Growth Lab에 저장", icon=":material/bookmark_add:"):
        with st.form(f"form_{key}", border=False):
            title = st.text_input("문제 제목", value=default_title,
                                  help="Growth Lab 목록에 보일 이름입니다. 예: 9월 야식 테마 장바구니 이탈")
            memo = st.text_area("이 결과에서 문제라고 본 이유 (선택)",
                                placeholder="예: 다른 테마보다 장바구니→구매 전환율이 낮다")
            if st.form_submit_button("저장", type="primary"):
                cand = {"kind": "ask", "title": title.strip() or default_title, "metric": res["title"],
                        "definition": memo.strip() or f"AI 분석가 질문: {e['q']}",
                        "question": e["q"], "answer": e.get("a", ""), "facts": list(res.get("facts", [])),
                        "tools": e.get("tools", []), "unit": "rate", "calls": e.get("calls", [])}
                store.add_problem(cand, "AI 분석가", ctx)
                e.setdefault("saved", []).append(key)
                st.toast(f"'{cand['title']}'을(를) Growth Lab 문제 후보로 저장했습니다.")
                st.rerun()


def open_simulation(payload):
    """Explicitly import a scenario together with its period, scope and costs."""
    title = "AI 정책 비교 · " + tools.S.POLICIES[payload["scenarios"][0]["policy"]]
    pid = store.add_problem({"kind": "simulation", "title": title, "facts": payload["facts"]},
        "AI 분석가", {"period": payload["start"] + " ~ " + payload["end"]}, simulation=payload)
    st.session_state.growth_open_id = pid
    st.session_state.period_mode = "직접 선택"
    st.session_state.period_range = (pd.Timestamp(payload["start"]).date(),
                                    (pd.Timestamp(payload["end"]) - pd.Timedelta(days=1)).date())
    st.session_state.goto_growth = True
    st.session_state.active_dash = None


def _run_direct(m, tool: str, params: dict) -> dict:
    """LLM 없이 정해진 도구를 바로 실행 (키가 없을 때 예시 질문용)."""
    try:
        return {"a": "", "results": [tools.run(m, tool, **params)], "tools": [tool],
                "calls": [{"tool": tool, "params": dict(params)}]}
    except Exception as e:  # 기간이 데이터 밖이거나 계산 불가
        return {"a": f"이 질문은 지금 데이터로 답하기 어렵습니다: {e}"}


def _answer(m, key, log: list, question: str, tool: str | None = None, params: dict | None = None):
    entry = {"q": question}
    if (st.session_state.get("growth_active") and not st.session_state.get("growth_context")
            and any(word in question.replace(" ", "") for word in
                    ("이결과", "지금결과", "현재비교", "왜이익", "내가고른", "선택한상품"))):
        entry["a"] = "현재 변경안은 아직 계산하지 않았습니다. 변경값과 주문 수 가정을 확인하고 ‘결과 확인’을 누른 뒤 물어봐 주세요."
        log.append(entry)
        return
    if key:
        history = [{"q": e["q"], "a": e.get("a", "")} for e in log]
        try:
            with st.spinner("데이터를 찾아 분석하는 중..."):
                context = st.session_state.get("growth_context") if st.session_state.get("growth_active") else None
                r = llm.ask(key, question, lambda name, p: tools.run(m, name, **p), history, growth_context=context)
            entry.update(a=r["text"], answer=r.get("answer"), model=r["model"], usage=llm.usage_label(r["model"], r.get("usage")), clarify=r.get("clarify"),
                         unverified=llm.unsupported_in_answer(r["text"], r["calls"]),
                         results=[c["result"] for c in r["calls"] if "result" in c],
                         calls=[{"tool": c["tool"], "params": dict(c["params"])} for c in r["calls"] if "result" in c],
                         tools=[f"{llm.TOOL_KO.get(c['tool'], c['tool'])}({', '.join(f'{k}={v}' for k, v in c['params'].items())})" for c in r["calls"]])
        except Exception as e:  # API 오류·시간 초과 등: 앱이 멈추지 않게 안내만 한다
            msg = str(e) if isinstance(e, llm.LLMError) else f"AI 분석 중 문제가 생겼습니다({type(e).__name__}). 다시 질문해 주세요."
            entry.update(_run_direct(m, tool, params or {}) if tool else {})
            entry["a"] = f"⚠️ {msg}" + (" 대신 정해진 분석 결과를 보여 드립니다." if tool else "")
    elif tool is None:
        entry["a"] = "AI 모델이 연결되면 이런 자유 질문에도 답할 수 있어요. 지금은 예시 질문 중 비슷한 것을 골라 주세요."
    else:
        entry.update(_run_direct(m, tool, params or {}))
    log.append(entry)
    if popup.spec_from_calls(entry.get("calls")) and not st.session_state.get("growth_active"):
        st.session_state.active_dash = len(log) - 1      # 답변이 나오면 왼쪽에 대시보드를 바로 띄운다


def _show_dash(i: int):
    st.session_state.active_dash = i


def _model_settings(key):
    try:
        cur_model, all_models = llm.pick_model(key), model_list(key)   # 모델은 매번 확인(자동 교체 반영)
    except Exception as e:  # 목록 조회 실패해도 화면은 계속 (다음 화면 갱신 때 다시 시도)
        cur_model, all_models = f"(확인 실패: {e})", []
    st.markdown(f"**AI 모델: {cur_model}**  \n기본은 이 키로 쓸 수 있는 **가장 가벼운 등급의 모델**(GPT는 nano, Gemini는 Flash-Lite)을 "
                "자동으로 고릅니다. 다른 모델을 쓰려면 Streamlit Secrets에 아래 한 줄을 추가하고 앱을 다시 시작하세요.")
    st.code(f'{llm.model_setting(key)} = "{cur_model}"', language="toml")
    if all_models:
        st.caption("이 키로 쓸 수 있는 모델: " + ", ".join(all_models))


# ---------------------------------------------------------------------------
# 패널
# ---------------------------------------------------------------------------
def render(m):
    st.markdown(PANEL_CSS, unsafe_allow_html=True)
    key = llm.api_key()
    log = st.session_state.setdefault("ask_log", [])

    with st.container(key="chat_panel"):
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown("**AI 분석가**")
        with h2.popover("", icon=":material/more_vert:", help="설정·대화 지우기"):
            if key:
                _model_settings(key)
            if log and st.button("대화 지우기", icon=":material/delete:", use_container_width=True):
                log.clear()
                st.session_state.active_dash = None
                st.rerun()
            ui.note("이번 달 = 2026년 9월, 지난달 = 8월로 해석합니다(데이터 마지막 날 기준). "
                    "숫자는 모두 대시보드와 같은 계산 함수로 만듭니다. 원인·대책은 데이터로 확인된 사실이 아니라 가설입니다.")

        with st.container(height=520, border=False, key="chat_msgs"):
            if not log:
                st.caption("궁금한 것을 물어보면 데이터를 찾고, 정책을 바꾸면 가정에 따른 손익도 비교합니다. "
                           "다른 화면으로 옮겨 가도 대화는 이어집니다. 데이터 기간: 2026-04-01 ~ 2026-09-30")
                if not key:
                    st.info("AI 모델이 아직 연결되지 않아 예시 질문에만 답할 수 있어요. "
                            "Secrets에 OPENAI_API_KEY를 넣으면 자유롭게 질문할 수 있습니다.", icon=":material/info:")
                st.markdown("**이렇게 물어보세요**")
                for i, (eq, tool, params) in enumerate(tools.EXAMPLES[:EXAMPLES_SHOWN]):
                    if st.button(eq, key=f"ex_{i}", use_container_width=True):
                        _answer(m, key, log, eq, tool, params)
                        st.rerun()
            for i, e in enumerate(log):
                with st.chat_message("user"):
                    st.markdown(e["q"])
                with st.chat_message("assistant"):
                    if e.get("answer"):
                        show_answer(e["answer"])
                    elif e.get("a"):
                        st.markdown(str(e["a"]).replace("~", "\\~"))   # '9-21~9-27'이 취소선이 되지 않게
                    if e.get("unverified"):
                        st.warning(f"분석 결과에서 찾지 못한 숫자가 있습니다: {', '.join(e['unverified'])}. "
                                   "AI가 직접 계산했거나 잘못 옮겼을 수 있으니 아래 분석 결과로 확인해 주세요.",
                                   icon=":material/warning:")
                    for j, res in enumerate(e.get("results", [])):
                        show_result(res, folded=bool(e.get("a")))
                        save_to_lab(e, res, key=f"lab_{i}_{j}")
                    if popup.spec_from_calls(e.get("calls")):
                        if st.session_state.get("active_dash") == i:
                            st.caption(":material/arrow_back: 왼쪽에 이 질문의 대시보드를 띄웠습니다.")
                        else:
                            st.button("대시보드 다시 보기", key=f"dash_{i}", icon=":material/dashboard:",
                                      on_click=_show_dash, args=(i,),
                                      help="이 질문의 기간·조건으로 만든 대시보드를 왼쪽 화면에 띄웁니다.")
                    if e.get("clarify") and e is log[-1]:
                        for j, lab in enumerate(e["clarify"]):
                            if st.button(lab, key=f"clar_{len(log)}_{j}", use_container_width=True):
                                st.session_state.pending_q = llm.with_period(e["q"], lab)
                                st.rerun()
                    if e is log[-1] and (e.get("answer") or {}).get("next_questions"):
                        st.caption("이어서 물어보기")
                        for j, nq in enumerate(e["answer"]["next_questions"]):
                            st.button(nq, key=f"next_{i}_{j}", icon=":material/subdirectory_arrow_right:",
                                      on_click=ask_next, args=(nq,), use_container_width=True)
                    if e.get("tools") and e.get("model"):
                        with st.expander("개발용 분석 정보"):
                            st.caption(f"사용한 분석: {' · '.join(e['tools'])} · 모델 {e['model']}"
                                       + (f" · {e['usage']}" if e.get("usage") else ""))

        q = st.chat_input("무엇이든 물어보세요", key="chat_q") or st.session_state.pop("pending_q", None)
        if q:
            hit = next((ex for ex in tools.EXAMPLES if ex[0].replace(" ", "") == q.replace(" ", "")), None)
            _answer(m, key, log, q, *(hit[1:] if hit else (None, None)))   # 키가 있으면 어떤 질문이든 AI가 답한다
            st.rerun()

"""질문 대시보드: 답변의 계산 결과(Result)를 왼쪽 화면 자리에 크게 그린다.

다시 계산하지 않는다. 답변 카드와 같은 Result를 그리기만 하므로 범위·숫자가 답변과 어긋날 수 없다.
app.py가 render()를 부른다.
"""
from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

from . import ui
from .query import Result

CARD_CSS = """
<style>
  .st-key-qdash {background: #FFFFFF; border: 2px solid #1F6F5C; border-radius: 16px;
                 box-shadow: 0 10px 30px rgba(15, 50, 40, .18), 0 2px 6px rgba(15, 50, 40, .08);
                 padding: 1.1rem 1.4rem 1.2rem; margin-top: .4rem;}
  .qdash-badge {display: inline-flex; align-items: center; gap: .35rem; background: #1F6F5C; color: #fff;
                font-size: .82rem; font-weight: 600; padding: .28rem .7rem; border-radius: 999px;}
  .qdash-badge::before {content: "✦";}
  .qdash-q {font-size: 1.25rem; font-weight: 700; color: #111827; margin: .35rem 0 .1rem;}
  .qdash-tag {display: inline-block; font-size: .78rem; color: #1F6F5C; background: #EAF3F0; border-radius: 999px;
              padding: .1rem .55rem; margin: 0 .25rem .25rem 0;}
  section.main, [data-testid="stMain"] {background: #EEF2F0;}
</style>
"""
AXIS_FMT = {"won": ",.0f", "count": ",.0f", "qty": ",.0f", "people": ",.0f", "rate": ".0%"}


def tags_html(tags: list[str]) -> str:
    return "".join(f"<span class='qdash-tag'>{html.escape(t)}</span>" for t in tags)


def _chart(c: dict):
    df, x, y, unit = c["data"].copy(), c["x"], c["y"], c.get("unit", "won")
    fmt = AXIS_FMT.get(unit, ",.0f")
    kind = c["kind"]
    if kind == "line":
        enc_x = alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%m/%d"))
        base = alt.Chart(df).encode(x=enc_x, y=alt.Y(f"{y}:Q", title=None, axis=alt.Axis(format=fmt)),
                                    tooltip=[alt.Tooltip(f"{x}:T", format="%m/%d"), alt.Tooltip(y, format=fmt)])
        layers = [base.mark_line(color=ui.C_MAIN, point=True)]
        if c.get("highlight"):
            s, e = c["highlight"]
            band = pd.DataFrame({"s": [pd.Timestamp(s) - pd.Timedelta(hours=12)], "e": [pd.Timestamp(e) + pd.Timedelta(hours=12)]})
            layers.insert(0, alt.Chart(band).mark_rect(color=ui.C_ACCENT, opacity=.15).encode(x="s:T", x2="e:T"))
        return alt.layer(*layers).properties(height=280)
    if kind in ("bar", "funnel"):
        sort = None if kind == "funnel" else "-x"
        return alt.Chart(df).mark_bar(color=ui.C_MAIN, cornerRadiusEnd=3).encode(
            y=alt.Y(f"{y}:N", sort=sort, title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X(f"{x}:Q", title=None, axis=alt.Axis(format=fmt)),
            tooltip=[y, alt.Tooltip(x, format=fmt)]).properties(height=max(160, 26 * len(df)))
    if kind == "diverging_bar":
        df["방향"] = df[x].map(lambda v: "감소" if v < 0 else "증가")
        return alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y(f"{y}:N", sort=None, title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X(f"{x}:Q", title=None, axis=alt.Axis(format=fmt)),
            color=alt.Color("방향:N", scale=alt.Scale(domain=["감소", "증가"], range=[ui.C_DOWN, ui.C_UP]), legend=None),
            tooltip=[y, alt.Tooltip(x, format=fmt)]).properties(height=max(160, 26 * len(df)))
    if kind == "scatter":
        lab = c.get("label")
        pts = alt.Chart(df).mark_circle(size=90, color=ui.C_MAIN).encode(
            x=alt.X(f"{x}:Q", axis=alt.Axis(format=fmt)), y=alt.Y(f"{y}:Q", axis=alt.Axis(format=fmt)),
            tooltip=[lab, alt.Tooltip(x, format=fmt), alt.Tooltip(y, format=fmt)])
        text = pts.mark_text(align="left", dx=7, fontSize=11).encode(text=f"{lab}:N")
        return (pts + text).properties(height=320)
    raise ValueError(f"모르는 차트 종류: {kind}")


def render(r: Result, question: str, on_close, key: str = "qdash"):
    st.markdown(CARD_CSS, unsafe_allow_html=True)
    with st.container(key="qdash"):
        h1, h2 = st.columns([6, 1], vertical_alignment="center")
        h1.markdown("<span class='qdash-badge'>AI 분석가가 띄운 대시보드</span>", unsafe_allow_html=True)
        h2.button("닫기", key=f"{key}_close", icon=":material/close:", on_click=on_close, width="stretch")
        st.markdown(f"<div class='qdash-q'>“{html.escape(question)}”</div>{tags_html(r.tags)}", unsafe_allow_html=True)
        st.markdown(f"#### {r.title}")
        for f in r.facts[:3]:
            st.markdown(f"- {f}".replace("~", "\\~"))
        if r.chart is not None:
            st.altair_chart(_chart(r.chart), width="stretch")
        if r.table is not None:
            st.dataframe(r.table, hide_index=True, width="stretch")
        for n in r.notes:
            ui.note(n)
        st.caption("숫자는 모두 계산 함수가 만든 값입니다. AI는 질문을 해석만 했고 숫자를 만들지 않았습니다.")

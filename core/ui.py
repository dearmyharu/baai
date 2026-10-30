"""화면 공통 요소: 데이터 캐시, 기간 선택, 숫자 표시, KPI 카드, Growth Lab 저장 버튼."""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from . import store
from .data import PERIOD_END, PERIOD_START, backend_name, build_all
from .metrics import previous_period

# 색상: 현재 기간 / 비교 기간 / 하락 / 상승 / 보조
C_MAIN = "#1F6F5C"
C_PREV = "#A9B8B2"
C_DOWN = "#C2410C"
C_UP = "#15803D"
C_ACCENT = "#D99A2B"
LABELS = {"NEW": "신규 방문", "RETURNING": "재방문", "UNKNOWN": "판정 불가", True: "신규 가입(4/1 이후)",
          False: "기존 가입", "CURATION": "큐레이션 경유", "BROWSE": "일반 탐색"}
PALETTE = ["#1F6F5C", "#D99A2B", "#4C7FB8", "#B0577A", "#7A8B3A", "#8C6BB1", "#3E9C9C", "#C2410C", "#6B7280", "#A0522D"]


def _altair_theme():
    return {"config": {
        "font": "Pretendard, 'Noto Sans KR', sans-serif",
        "view": {"stroke": None},
        "axis": {"labelColor": "#4B5563", "titleColor": "#4B5563", "gridColor": "#EEF1EF", "domainColor": "#D1D5DB",
                 "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": "normal"},
        "legend": {"labelFontSize": 11, "titleFontSize": 11, "orient": "top"},
        "range": {"category": PALETTE},
    }}


try:
    alt.themes.register("baai", _altair_theme)
    alt.themes.enable("baai")
except Exception:  # altair 버전 차이
    pass


@st.cache_resource(show_spinner="데이터를 불러오고 계산하는 중입니다 (처음 한 번만)...")
def get_mart():
    return build_all()


# ---------------------------------------------------------------------------
# 표시 형식
# ---------------------------------------------------------------------------
def won(v, short=True):
    if v is None or pd.isna(v):
        return "–"
    if short and abs(v) >= 1e8:
        return f"{v/1e8:,.2f}억원"
    if short and abs(v) >= 1e6:
        return f"{v/1e4:,.0f}만원"
    return f"{v:,.0f}원"


def num(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.0f}"


def pct(v, d=1):
    return "–" if v is None or pd.isna(v) else f"{v*100:.{d}f}%"


def fmt_value(v, unit):
    return {"rate": pct, "won": won}.get(unit, num)(v)


def fmt_delta(cur, prev, unit):
    if prev is None or pd.isna(prev) or pd.isna(cur):
        return None
    if unit == "rate":
        return f"{(cur - prev) * 100:+.1f}%p"
    if prev == 0:
        return None
    return f"{(cur - prev) / prev * 100:+.1f}%"


def d(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def period_label(p):
    if p is None:
        return "비교 없음"
    return f"{d(p[0])} ~ {d(p[1] - pd.Timedelta(days=1))}"


# ---------------------------------------------------------------------------
# 공통 조회 조건 (사이드바, 모든 화면이 공유)
# ---------------------------------------------------------------------------
MONTHS = pd.period_range(PERIOD_START, PERIOD_END - pd.Timedelta(days=1), freq="M")


def period_controls():
    sb = st.sidebar
    sb.markdown("#### 조회 조건")
    mode = sb.segmented_control("기간 단위", ["월", "직접 선택"], default="월", key="period_mode") or "월"
    if mode == "월":
        labels = [f"{p.year}년 {p.month}월" for p in MONTHS]
        idx = sb.selectbox("분석 월", range(len(MONTHS)), index=len(MONTHS) - 1,
                           format_func=lambda i: labels[i], key="period_month")
        p = MONTHS[idx]
        cur = (p.start_time, (p + 1).start_time)
        prev = ((p - 1).start_time, p.start_time) if idx > 0 else None
    else:
        rng = sb.date_input("분석 기간", value=(pd.Timestamp("2026-09-01").date(), pd.Timestamp("2026-09-30").date()),
                            min_value=PERIOD_START.date(), max_value=(PERIOD_END - pd.Timedelta(days=1)).date(),
                            key="period_range")
        if not isinstance(rng, (list, tuple)) or len(rng) < 2:
            sb.info("시작일과 종료일을 모두 선택해 주세요.")
            st.stop()
        cur = (pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(days=1))
        prev = previous_period(*cur)
    compare = sb.toggle("이전 기간과 비교", value=True, key="period_compare")
    if not compare:
        prev = None
    elif prev is None:
        sb.caption("⚠️ 비교할 이전 기간이 4/1 이전이라 상세 데이터가 없습니다.")
    sb.caption(f"분석: {period_label(cur)}  \n비교: {period_label(prev)}")
    sb.divider()
    sb.caption(f"데이터: {'DB' if backend_name() == 'db' else '폴더 CSV (v2)'} · 2026-04-01 ~ 09-30  \n"
               "주문 상태는 9/30 기준 최종 상태")
    sb.text_input("내 이름", key="user_name", placeholder="Growth Lab 기록용",
                  help="Growth Lab에 저장·수정할 때 작성자로 남습니다.")
    return cur, prev


# ---------------------------------------------------------------------------
# KPI 카드
# ---------------------------------------------------------------------------
def kpi_row(items: list[tuple], prev_exists: bool):
    """items: (라벨, 현재값, 이전값, 단위, 도움말)"""
    cols = st.columns(len(items))
    for col, (label, cur, prev, unit, help_) in zip(cols, items):
        col.metric(label, fmt_value(cur, unit), fmt_delta(cur, prev, unit) if prev_exists else None,
                   help=help_, border=True)


# ---------------------------------------------------------------------------
# Growth Lab 저장
# ---------------------------------------------------------------------------
def save_to_lab_button(candidate: dict, source_page: str, cur, prev, key: str, label="Growth Lab에 저장"):
    ctx = {"page": source_page, "period": period_label(cur), "compare": period_label(prev)}
    if store.already_saved(candidate["title"], ctx):
        st.button("저장됨 ✓", key=key, disabled=True)
        return
    if st.button(label, key=key, icon=":material/bookmark_add:"):
        store.add_problem(candidate, source_page, ctx)
        st.toast(f"'{candidate['title']}'을(를) Growth Lab 문제 후보로 저장했습니다.")
        st.rerun()


def note(text: str):
    st.caption(f"ℹ️ {text}")


def small_sample_warning(n, what="표본"):
    if n is not None and n < 30:
        st.warning(f"{what}이 {int(n)}건으로 30건 미만입니다. 수치만 참고하고 순위·비교 결론은 내리지 마세요.")


def bar_compare(df: pd.DataFrame, x: str, y: str, color: str | None = None, fmt=",.0f", height=260, sort="-x"):
    base = alt.Chart(df).encode(
        y=alt.Y(f"{y}:N", sort=sort, title=None),
        x=alt.X(f"{x}:Q", title=None, axis=alt.Axis(format=fmt)),
        tooltip=[y, alt.Tooltip(x, format=fmt)])
    bars = base.mark_bar(cornerRadiusEnd=3, color=color or C_MAIN)
    return bars.properties(height=height)

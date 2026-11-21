"""화면 공통: 데이터 캐시, 표시 형식, 색, 분석 화면 조회 조건(ver.1에서 가져옴).

- 모든 화면은 get_mart()를 쓴다. 기준일(data.TODAY = 10/26 아침) 이전 데이터만 들어 있다.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from . import data as D
from .data import PERIOD_START, as_of, backend_name, build_all
from .metrics import compare_period

C_MAIN = "#1F6F5C"
C_PREV = "#A9B8B2"
C_DOWN = "#C2410C"
C_UP = "#15803D"
C_ACCENT = "#D99A2B"
C_MUTED = "#6B7280"
LABELS = {"NEW": "신규 방문", "RETURNING": "재방문", "UNKNOWN": "판정 불가", True: "신규 가입(4/1 이후)",
          False: "기존 가입", "CURATION": "큐레이션 경유", "BROWSE": "일반 탐색"}
PALETTE = ["#1F6F5C", "#D99A2B", "#4C7FB8", "#B0577A", "#7A8B3A", "#8C6BB1", "#3E9C9C", "#C2410C", "#6B7280", "#A0522D"]
LAST_DAY = D.TODAY - pd.Timedelta(days=1)          # 데이터 마지막 날(10/25)


def _theme():
    return {"config": {
        "font": "Pretendard, 'Noto Sans KR', sans-serif",
        "view": {"stroke": None},
        "axis": {"labelColor": "#4B5563", "titleColor": "#4B5563", "gridColor": "#EEF1EF", "domainColor": "#D1D5DB",
                 "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": "normal"},
        "legend": {"labelFontSize": 11, "titleFontSize": 11, "orient": "top"},
        "range": {"category": PALETTE},
    }}


try:
    alt.themes.register("baai_v2", _theme)
    alt.themes.enable("baai_v2")
except Exception:  # altair 버전 차이
    pass


@st.cache_resource(show_spinner="데이터를 불러오는 중입니다 (처음 한 번만)...")
def get_mart():
    """기준일(10/26) 이전 데이터만 남긴 마트. 브리핑·분석·챗봇·Growth Lab이 모두 같은 데이터를 본다."""
    return as_of(build_all(), D.TODAY)


# ---------------------------------------------------------------------------
# 표시 형식
# ---------------------------------------------------------------------------
def won(v, short=True):
    if v is None or pd.isna(v):
        return "–"
    if short and abs(v) >= 1e8:
        return f"{v / 1e8:,.2f}억원"
    if short and abs(v) >= 1e4:
        return f"{v / 1e4:,.0f}만원"
    return f"{v:,.0f}원"


def num(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.0f}"


def pct(v, d=1):
    return "–" if v is None or pd.isna(v) else f"{v * 100:.{d}f}%"


def times(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.1f}배"


def fmt_value(v, unit):
    return {"rate": pct, "won": won, "x": times}.get(unit, num)(v)


def fmt_delta(cur, prev, unit):
    if prev is None or pd.isna(prev) or pd.isna(cur):
        return None
    if unit == "rate":
        return f"{(cur - prev) * 100:+.1f}%p"
    if prev == 0:
        return None
    return f"{(cur - prev) / prev * 100:+.1f}%"


def md(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.month}/{ts.day}"


def d(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def period_label(p):
    if p is None:
        return "비교 없음"
    return f"{d(p[0])} ~ {d(p[1] - pd.Timedelta(days=1))}"


# ---------------------------------------------------------------------------
# 분석 화면 조회 조건 (사이드바). 데이터는 기준일 전날(10/25)까지
# ---------------------------------------------------------------------------
MONTHS = pd.period_range(PERIOD_START, LAST_DAY, freq="M")


def period_controls():
    sb = st.sidebar
    sb.markdown("#### 조회 조건")
    mode = sb.segmented_control("기간 단위", ["월", "직접 선택"], default="월", key="period_mode") or "월"
    if mode == "월":
        def _label(p):
            if p.end_time.normalize() > LAST_DAY:
                return f"{p.year}년 {p.month}월 (1~{LAST_DAY.day}일)"
            return f"{p.year}년 {p.month}월"
        idx = sb.selectbox("분석 월", range(len(MONTHS)), index=len(MONTHS) - 1,
                           format_func=lambda i: _label(MONTHS[i]), key="period_month")
        p = MONTHS[idx]
        end = min((p + 1).start_time, D.TODAY)
        cur = (p.start_time, end)
        if idx == 0:
            prev = None
        elif end < (p + 1).start_time:          # 진행 중인 달: 지난달 같은 날짜까지와 비교
            ps = (p - 1).start_time
            prev = (ps, ps + (end - p.start_time))
        else:
            prev = ((p - 1).start_time, p.start_time)
    else:
        rng = sb.date_input("분석 기간", value=((D.TODAY - pd.Timedelta(days=7)).date(), LAST_DAY.date()),
                            min_value=PERIOD_START.date(), max_value=LAST_DAY.date(), key="period_range")
        if not isinstance(rng, (list, tuple)) or len(rng) < 2:
            sb.info("시작일과 종료일을 모두 선택해 주십시오.")
            st.stop()
        cur = (pd.Timestamp(rng[0]), pd.Timestamp(rng[1]) + pd.Timedelta(days=1))
        prev = compare_period(*cur)
    compare = sb.toggle("이전 기간과 비교", value=True, key="period_compare")
    if not compare:
        prev = None
    elif prev is None:
        sb.caption("⚠️ 비교할 이전 기간이 4/1 이전이라 상세 데이터가 없습니다.")
    sb.caption(f"분석: {period_label(cur)}  \n비교: {period_label(prev)}")
    st.session_state["page_context"] = (f"{st.session_state.get('page_title', '분석')} 화면을 보고 있음. "
                                        f"조회 기간 {period_label(cur)}, 비교 기간 {period_label(prev)}")
    return cur, prev


# ---------------------------------------------------------------------------
# KPI 카드 · 기타
# ---------------------------------------------------------------------------
def kpi_row(items: list[tuple], prev_exists: bool):
    """items: (라벨, 현재값, 이전값, 단위, 도움말)"""
    cols = st.columns(len(items))
    for col, (label, cur, prev, unit, help_) in zip(cols, items):
        col.metric(label, fmt_value(cur, unit), fmt_delta(cur, prev, unit) if prev_exists else None,
                   help=help_, border=True)


def save_to_lab_button(*args, **kwargs):
    """ver.1의 'Growth Lab에 저장' 버튼. ver.2에서는 AI 분석가 → Growth Lab 흐름으로 대신하므로 표시하지 않는다."""
    return None


def note(text: str):
    st.caption(f"ℹ️ {text}")


def small_sample_warning(n, what="표본"):
    if n is not None and n < 30:
        st.warning(f"{what}이 {int(n)}건으로 30건 미만입니다. 수치만 참고하고 순위·비교 결론은 내리지 마십시오.")


def bar_compare(df: pd.DataFrame, x: str, y: str, color: str | None = None, fmt=",.0f", height=260, sort="-x"):
    base = alt.Chart(df).encode(
        y=alt.Y(f"{y}:N", sort=sort, title=None),
        x=alt.X(f"{x}:Q", title=None, axis=alt.Axis(format=fmt)),
        tooltip=[y, alt.Tooltip(x, format=fmt)])
    bars = base.mark_bar(cornerRadiusEnd=3, color=color or C_MAIN)
    return bars.properties(height=height)


def data_caption():
    st.sidebar.caption(f"데이터: {'DB' if backend_name() == 'db' else '폴더 CSV'} · 2026-04-01 ~ {d(LAST_DAY)} (가상 데이터)")

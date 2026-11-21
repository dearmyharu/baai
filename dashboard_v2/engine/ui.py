"""화면 공통: 데이터 캐시, 표시 형식, 색."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from .data import build_all

C_MAIN = "#1F6F5C"
C_PREV = "#A9B8B2"
C_DOWN = "#C2410C"
C_UP = "#15803D"
C_ACCENT = "#D99A2B"
C_MUTED = "#6B7280"
PALETTE = ["#1F6F5C", "#A9B8B2", "#D99A2B", "#4C7FB8", "#B0577A"]


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
    return build_all()


def won(v, short=True):
    if v is None or pd.isna(v):
        return "–"
    if short and abs(v) >= 1e8:
        return f"{v / 1e8:,.2f}억원"
    if short and abs(v) >= 1e4:
        return f"{v / 1e4:,.0f}만원"
    return f"{v:,.0f}원"


def pct(v, d=1):
    return "–" if v is None or pd.isna(v) else f"{v * 100:.{d}f}%"


def md(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.month}/{ts.day}"

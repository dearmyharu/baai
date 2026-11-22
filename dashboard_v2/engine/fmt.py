"""숫자·날짜 표기 (화면 코드 없이 계산 쪽에서 쓰는 것). 답변 문장과 표가 같은 표기를 쓴다."""
from __future__ import annotations

import math

import pandas as pd


def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (not isinstance(v, str) and pd.isna(v))


def won(v) -> str:
    if _bad(v):
        return "–"
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.2f}억원"
    if abs(v) >= 1e5:          # 10만원 이상은 만원 단위, 그 아래(객단가 등)는 원 단위
        return f"{v / 1e4:,.0f}만원"
    return f"{v:,.0f}원"


def won_signed(v) -> str:
    return "–" if _bad(v) else ("+" if v > 0 else "−" if v < 0 else "") + won(abs(v))


def count(v, unit: str = "건") -> str:
    return "–" if _bad(v) else f"{v:,.0f}{unit}"


def pct(v, digits: int = 0) -> str:
    return "–" if _bad(v) else f"{v * 100:.{digits}f}%"


def pct_signed(v, digits: int = 0) -> str:
    return "–" if _bad(v) else f"{v * 100:+.{digits}f}%"


def pp_signed(v, digits: int = 1) -> str:
    """비율 차이(소수) → '%p'."""
    return "–" if _bad(v) else f"{v * 100:+.{digits}f}%p"


def day(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.month}/{ts.day}"


def span(start, end_exclusive) -> str:
    """[start, end) → '10/19~10/25' (하루면 '10/25')."""
    s, e = pd.Timestamp(start), pd.Timestamp(end_exclusive) - pd.Timedelta(days=1)
    return day(s) if s == e else f"{day(s)}~{day(e)}"


def value(v, unit: str) -> str:
    """단위 이름(won·count·qty·rate·aov)으로 표기."""
    if unit == "won":
        return won(v)
    if unit == "count":
        return count(v, "건")
    if unit == "qty":
        return count(v, "개")
    if unit == "people":
        return count(v, "명")
    if unit == "rate":
        return pct(v, 1)
    raise ValueError(f"모르는 단위: {unit}")

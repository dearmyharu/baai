"""질문 속 기간 표현 → 날짜 [start, end). AI가 아니라 이 규칙이 정한다.

반환 Period:
- dates: (start, end) 또는 None(기간 표현 없음 → 의도별 기본값)
- no_data: 데이터가 아직 없는 기간이면 안내 문장 (예: 오늘, 월요일의 이번 주)
- alt: no_data일 때 대신 볼 기간 선택지 [(이름, (start, end))]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from . import fmt as F
from .data import PERIOD_START


@dataclass
class Period:
    dates: tuple[pd.Timestamp, pd.Timestamp] | None = None
    text: str = ""                     # 질문에서 찾은 표현
    no_data: str = ""
    alt: list = field(default_factory=list)
    note: str = ""                     # 데이터 범위에 맞춰 자른 경우 등


def _month_range(y: int, mth: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    s = pd.Timestamp(year=y, month=mth, day=1)
    return s, s + pd.DateOffset(months=1)


def _clip(p: Period, today: pd.Timestamp) -> Period:
    """데이터 범위(4/1 ~ 기준일 전날)에 맞춘다. 전부 밖이면 no_data."""
    if p.dates is None or p.no_data:
        return p
    s, e = p.dates
    if s >= today:
        p.no_data = f"{p.text}은(는) 아직 데이터가 없습니다. 데이터는 {F.day(today - pd.Timedelta(days=1))}까지 있습니다."
        p.dates = None
        return p
    if e <= PERIOD_START:
        p.no_data = f"{p.text}은(는) 데이터가 없습니다. 데이터는 {F.day(PERIOD_START)}부터 있습니다."
        p.dates = None
        return p
    if e > today:
        p.note = f"{p.text}은(는) {F.day(today - pd.Timedelta(days=1))}까지의 데이터로 봅니다."
        e = today
    if s < PERIOD_START:
        p.note = f"{p.text}은(는) 데이터가 있는 {F.day(PERIOD_START)}부터로 봅니다."
        s = PERIOD_START
    p.dates = (s, e)
    return p


def parse(question: str, today) -> Period:
    q = re.sub(r"\s+", " ", question or "")
    t = pd.Timestamp(today).normalize()
    y = t - pd.Timedelta(days=1)
    mon = t - pd.Timedelta(days=t.dayofweek)            # 이번 주 월요일
    last_week = (mon - pd.Timedelta(days=7), mon)

    if re.search(r"오늘|금일|지금\s*까지\s*오늘", q):
        return Period(None, "오늘", f"오늘 데이터는 아직 없습니다. 데이터는 어제({F.day(y)})까지 있습니다.",
                      [("어제", (y, t))])
    if m := re.search(r"(\d{1,2})\s*[/.월]\s*(\d{1,2})\s*일?\s*(?:부터|~|-|에서)\s*(?:(\d{1,2})\s*[/.월]\s*)?(\d{1,2})\s*일?", q):
        m1, d1, m2, d2 = int(m[1]), int(m[2]), int(m[3] or m[1]), int(m[4])
        s = pd.Timestamp(year=t.year, month=m1, day=d1)
        e = pd.Timestamp(year=t.year, month=m2, day=d2) + pd.Timedelta(days=1)
        return _clip(Period((s, e), m[0].strip()), t)
    if m := re.search(r"최근\s*(\d+)\s*(일|주|개월|달)|지난\s*(\d+)\s*(일|주)", q):
        n, unit = int(m[1] or m[3]), (m[2] or m[4])
        days = n * {"일": 1, "주": 7, "개월": 28, "달": 28}[unit]
        return _clip(Period((t - pd.Timedelta(days=days), t), m[0]), t)
    if re.search(r"최근\s*한\s*(?:달|주)", q):
        days = 28 if "달" in re.search(r"최근\s*한\s*(달|주)", q)[1] else 7
        return _clip(Period((t - pd.Timedelta(days=days), t), f"최근 {'한 달' if days == 28 else '한 주'}",
                            note="최근 한 달은 요일 구성이 같은 28일로 봅니다." if days == 28 else ""), t)
    if re.search(r"그제|그저께", q):
        return _clip(Period((y - pd.Timedelta(days=1), y), "그제"), t)
    if re.search(r"어제|전일", q):
        return _clip(Period((y, t), "어제"), t)
    if re.search(r"지지난\s*주", q):
        return _clip(Period((last_week[0] - pd.Timedelta(days=7), last_week[0]), "지지난주"), t)
    if re.search(r"지난\s*주말|저번\s*주말", q):
        sat = mon - pd.Timedelta(days=2)
        return _clip(Period((sat, mon), "지난 주말"), t)
    if re.search(r"지난\s*주|저번\s*주|전주", q):
        return _clip(Period(last_week, "지난주"), t)
    if re.search(r"이번\s*주|금주|이번주", q):
        if t == mon:
            return Period(None, "이번 주", "오늘이 월요일이라 이번 주 데이터는 아직 없습니다.", [("지난주", last_week)])
        return _clip(Period((mon, t), "이번 주"), t)
    if re.search(r"지지난\s*달", q):
        s = (t.replace(day=1) - pd.DateOffset(months=2))
        return _clip(Period((s, s + pd.DateOffset(months=1)), "지지난달"), t)
    if re.search(r"지난\s*달|저번\s*달|전월", q):
        s = t.replace(day=1) - pd.DateOffset(months=1)
        return _clip(Period((s, t.replace(day=1)), "지난달"), t)
    if re.search(r"이번\s*달|이달|당월", q):
        s = t.replace(day=1)
        if s == t:
            ps = s - pd.DateOffset(months=1)
            return Period(None, "이번 달", "오늘이 1일이라 이번 달 데이터는 아직 없습니다.", [("지난달", (ps, s))])
        return _clip(Period((s, t), "이번 달"), t)
    months = re.findall(r"(?<!\d)(1[0-2]|[1-9])\s*월(?!\s*\d+\s*일)", q)
    if months:
        ms = sorted({int(x) for x in months})
        mth = ms[-1]                                   # 두 달이 나오면 늦은 달을 보고, 비교는 직전 달
        s, e = _month_range(t.year, mth)
        note = ""
        if len(ms) > 1 and ms[-2] != mth - 1:
            note = f"비교는 {mth}월의 직전 달({mth - 1}월)과 합니다."
        return _clip(Period((s, e), f"{mth}월", note=note), t)
    return Period(None, "")

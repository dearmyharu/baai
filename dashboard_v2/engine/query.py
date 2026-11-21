"""질의서: 질문 해석(AI)과 검증(코드)을 거쳐 계산 함수로 들어가는 유일한 입력 형식.

계산 함수는 이 형식만 받는다. 여기 없는 값은 받지 않는다(조용히 버리지 않고 오류).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# 의도 8개
INTENTS = {
    "status": "현황",            # 어제·최근 며칠·특정 기간 지표와 평소 대비
    "rank": "순위·비중",         # 카테고리·상품 순위와 비중
    "location": "변화 위치",     # 증감이 어디서 생겼나 (이유는 다루지 않는다)
    "trend": "추이",
    "candidates": "후보 찾기",   # 어디를 밀까
    "levers": "수단 참고",       # 무엇으로 밀까 (판단 재료만)
    "promo": "프로모션 실적",
    "funnel_theme": "퍼널·테마",
}

# 변화 위치를 쪼개는 축: 키 → 이름
AXES = {
    "category": "카테고리",
    "product": "상품",
    "customer_type": "첫 구매/기존 고객",
    "visitor_type": "신규 방문/재방문",
    "path": "쇼핑몰 안 경로(큐레이션/일반 탐색)",
    "weekday": "요일",
    "daypart": "시간대",
    "gender": "성별",
    "age_group": "연령대",
    "region": "지역",
    "signup_channel": "회원가입 수단",
    "grade_at_order": "주문 당시 회원 등급",
}

# 측정값: 이름 → (단위, 계산 위치). 비율은 분자·분모로 계산한다.
MEASURE_UNIT = {"완료 매출": "won", "상품매출": "won", "판매 수량": "qty", "주문 수": "count",
                "구매 고객 수": "people", "이익": "won", "객단가": "won", "이익률": "rate"}
RATIOS = {"객단가": ("완료 매출", "주문 수"), "이익률": ("이익", "상품매출")}
SHOP_MEASURES = ["완료 매출", "주문 수", "객단가", "이익"]          # 쇼핑몰 전체 현황
ITEM_MEASURES = ["상품매출", "판매 수량", "주문 수", "이익률"]       # 카테고리·상품 현황


@dataclass
class Query:
    intent: str
    category: str | None = None          # 대상 카테고리 (실제 이름)
    product: str | None = None           # 대상 상품 (실제 이름)
    filters: dict = field(default_factory=dict)   # metrics.FILTER_KEYS 형식의 고객 조건
    measure: str | None = None
    period: tuple[pd.Timestamp, pd.Timestamp] | None = None   # [start, end). None이면 의도별 기본
    group_by: str | None = None          # rank: 'category' | 'product'
    axis: str | None = None              # location: AXES 키
    direction: str | None = None         # 'down' | 'up' | None(둘 다)
    n: int | None = None
    topic: str | None = None             # funnel_theme: 'funnel' | 'theme'
    path: str | None = None              # funnel: 'ALL' | 'CURATION' | 'BROWSE'

    def __post_init__(self):
        if self.intent not in INTENTS:
            raise ValueError(f"의도가 아닙니다: {self.intent}")
        if self.axis is not None and self.axis not in AXES:
            raise ValueError(f"나눌 수 없는 기준입니다: {self.axis}")
        if self.measure is not None and self.measure not in MEASURE_UNIT:
            raise ValueError(f"측정값이 아닙니다: {self.measure}")
        if self.direction not in (None, "down", "up"):
            raise ValueError(f"방향은 down·up입니다: {self.direction}")
        if self.group_by not in (None, "category", "product"):
            raise ValueError(f"순위 기준은 category·product입니다: {self.group_by}")
        if self.period is not None:
            s, e = (pd.Timestamp(x).normalize() for x in self.period)
            if s >= e:
                raise ValueError("기간이 비어 있습니다.")
            self.period = (s, e)


@dataclass
class Result:
    """계산 결과의 단일 형식. 답변 카드와 질문 대시보드는 이것을 그리기만 한다(다시 계산하지 않음)."""
    intent: str
    title: str                                   # 대시보드 제목
    tags: list[str]                              # 조건 칩: 기간·비교 기준·대상·고객 조건
    key: dict                                    # 답변 틀이 결론 문장에 쓰는 값
    facts: list[str]                             # 코드가 만든 사실 문장 (카드에는 앞 3개)
    table: pd.DataFrame | None = None            # 표시용 표 (한글 열 이름, 값은 표기 완료)
    chart: dict | None = None                    # {'kind','data','x','y',...}
    notes: list[str] = field(default_factory=list)   # 주의 (표본 적음, 일수 다름 등)
    axes_left: list[str] = field(default_factory=list)  # 변화 위치: 아직 안 본 축(흐름 관리가 씀)

"""질문 해석 평가: 질문 → (AI 초안 → 검증) 결과가 기대한 질의서와 같은가. 기준일 2026-10-26(월) 아침.

expect 칸: kind('query'|'message'|'clarify', 여러 개 허용은 집합), intent, category, product, filters, axis(집합 허용),
measure, period(시작, 끝), why. 적지 않은 칸은 채점하지 않는다.
"""
import pandas as pd

from engine.query import Query

P = lambda a, b: (pd.Timestamp(a), pd.Timestamp(b))  # noqa: E731
YDAY = P("2026-10-25", "2026-10-26")
LAST3 = P("2026-10-23", "2026-10-26")
LAST7 = P("2026-10-19", "2026-10-26")
LASTWEEK = P("2026-10-19", "2026-10-26")
SEP = P("2026-09-01", "2026-10-01")

CASES = [
    # 시연: 카테고리 단위
    ("D01", "어제 매출 얼마야?", dict(kind="query", intent="status", category=None, period=YDAY)),
    ("D02", "정육 매출 어때?", dict(kind="query", intent="status", category="정육", period=None)),
    ("D03", "최근 7일 정육 카테고리에서 매출이 줄어든 상품은?", dict(kind="query", intent="location", category="정육",
                                                       axis={None, "product"}, period=LAST7)),
    ("D04", "매출이 가장 많이 떨어진 카테고리는?", dict(kind="query", intent="location", category=None, axis={None, "category"})),
    ("D05", "정육 매출 왜 떨어졌어?", dict(kind="query", intent="location", category="정육", why=True)),
    ("D06", "잘 팔리는 카테고리 순위 보여줘", dict(kind="query", intent="rank", category=None)),
    ("D07", "정육에서 제일 잘 팔리는 상품은?", dict(kind="query", intent="rank", category="정육")),
    ("D08", "수산 매출 추이 보여줘", dict(kind="query", intent="trend", category="수산")),
    ("D09", "어떤 카테고리를 밀어야 해?", dict(kind="query", intent="candidates")),
    ("D10", "정육은 프로모션 후보야?", dict(kind="query", intent="candidates", category="정육")),
    ("D11", "정육에 쓸 만한 수단 참고 자료 보여줘", dict(kind="query", intent="levers", category="정육")),
    ("D12", "지난번 정육 할인 결과는?", dict(kind="query", intent="promo", category="정육")),
    ("D13", "캠핑 할인 지금 어떻게 되고 있어?", dict(kind="query", intent="promo", category="캠핑·바비큐")),
    ("D14", "정육 매출 고객별로 보면 어디서 줄었어?", dict(kind="query", intent="location", category="정육", axis="customer_type")),
    ("D15", "정육 시간대별로 보면?", dict(kind="query", intent="location", category="정육", axis="daypart")),
    ("D16", "고기 매출 최근 3일 어때?", dict(kind="query", intent="status", category="정육", period=LAST3)),
    ("D17", "생선 쪽은 요즘 어때?", dict(kind="query", intent="status", category="수산")),
    ("D18", "밀키트 이익률은?", dict(kind="query", intent="status", category="밀키트", measure="이익률")),
    ("D19", "음료 매출 1위 상품은?", dict(kind="query", intent="rank", category="음료·커피")),
    ("D20", "과자 매출 왜 늘었어?", dict(kind="query", intent="location", category="과자·간식", why=True)),
    # 쇼핑몰 전체·기타
    ("G01", "지난주 주문 수는?", dict(kind="query", intent="status", measure="주문 수", period=LASTWEEK)),
    ("G02", "9월 매출은 8월보다 줄었어?", dict(kind="query", intent="status", period=SEP)),
    ("G03", "객단가 어때?", dict(kind="query", intent="status", measure="객단가")),
    ("G04", "장바구니에서 구매로 넘어가는 비율은?", dict(kind="query", intent="funnel_theme")),
    ("G05", "큐레이션 테마 중 반응 좋은 건?", dict(kind="query", intent="funnel_theme")),
    # 고객 조건
    ("F01", "40대 여성 고객 매출은?", dict(kind="query", intent="status", filters={"age_groups": ["40대"], "gender": "F"})),
    ("F02", "카카오로 가입한 고객의 정육 매출은?", dict(kind="query", intent="status", category="정육",
                                              filters={"signup_channels": ["KAKAO"]})),
    ("F03", "VIP 고객이 많이 사는 카테고리는?", dict(kind="query", intent="rank", filters={"grades": ["VIP"]})),
    ("F04", "서울 고객 매출 어때?", dict(kind="query", intent="status", filters={"regions": ["서울특별시"]})),
    ("F05", "신규 가입 고객 매출은?", dict(kind="query", intent="status", filters={"new_signup": True})),
    # 기간 없음·데이터 없음
    ("P01", "이번 주 매출 어때?", dict(kind="clarify")),
    ("P02", "오늘 매출 얼마야?", dict(kind="clarify")),
    ("P03", "11월 매출은?", dict(kind="message")),
    # 데이터에 없는 항목 (사전 목록에 없는 표현 포함: AI의 unmapped 또는 근거 검사로 막혀야)
    ("X01", "인스타 광고 유입 고객 매출", dict(kind="message")),
    ("X02", "단톡방 보고 온 고객 구매율은?", dict(kind="message")),
    ("X03", "엄마들이 많이 사는 상품은?", dict(kind="message")),
    ("X04", "택배 지연 때문에 매출 줄었어?", dict(kind={"message", "query"})),
    ("X05", "날씨 때문에 매출 줄었어?", dict(kind="message")),
    ("X06", "회사 근처 사는 고객 매출은?", dict(kind="message")),
    ("X07", "무료 샘플 받은 고객 재구매율은?", dict(kind="message")),
    # 애매함
    ("A01", "삼겹살 매출 어때?", dict(kind="clarify")),
    ("A02", "정육 어때?", dict(kind={"query", "clarify"}, category="정육")),
]

# 이어지는 질문: (id, 직전 질의서, 질문, 기대)
FOLLOW = [
    ("C01", Query("location", category="정육"), "그럼 수산은?", dict(kind="query", intent="location", category="수산")),
    ("C02", Query("location", category="정육"), "요일별로는?", dict(kind="query", intent="location", category="정육", axis="weekday")),
    ("C03", Query("status", category="정육"), "지난주는?", dict(kind="query", intent="status", category="정육", period=LASTWEEK)),
    ("C04", Query("status", period=YDAY), "정육 매출 왜 떨어졌어?", dict(kind="query", intent="location", category="정육",
                                                                  period=None, why=True)),
    ("C05", Query("location", category="수산"), "고객별로는?", dict(kind="query", intent="location", category="수산",
                                                             axis="customer_type")),
    ("C06", Query("location", category="정육"), "어떤 카테고리를 밀어야 해?", dict(kind="query", intent="candidates", category=None)),
]

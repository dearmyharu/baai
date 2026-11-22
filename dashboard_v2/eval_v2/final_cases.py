"""최종 평가(2026-11-22): 규칙을 고칠 때 한 번도 보지 않은 질문. 결과를 보고 규칙을 고치지 않는다."""
from eval_v2.parse_cases import P
from engine.query import Query

LAST3 = P("2026-10-23", "2026-10-26")
LASTWEEK = P("2026-10-19", "2026-10-26")
OCT = P("2026-10-01", "2026-10-26")

CASES = [
    # 시연형: 카테고리
    ("F01", "어제 정육 얼마나 팔렸어?", dict(kind="query", intent="status", category="정육", period=P("2026-10-25", "2026-10-26"))),
    ("F02", "요즘 수산 매출 괜찮아?", dict(kind="query", intent="status", category="수산")),
    ("F03", "지난주 카테고리별 매출 순위", dict(kind="query", intent="rank", category=None, period=LASTWEEK)),
    ("F04", "이번 달 제일 많이 팔린 카테고리가 뭐야?", dict(kind="query", intent="rank", period=OCT)),
    ("F05", "최근 3일 동안 가장 크게 빠진 카테고리 알려줘", dict(kind="query", intent="location", category=None, period=LAST3)),
    ("F06", "간편식은 어떤 상품 때문에 줄었어?", dict(kind="query", intent="location", category="간편식")),
    ("F07", "반찬 매출 줄어든 거 고객 유형별로 보면?", dict(kind="query", intent="location", category="반찬·김치", axis="customer_type")),
    ("F08", "냉동식품 매출 시간대별로 어디가 줄었어?", dict(kind="query", intent="location", category="냉동식품", axis="daypart")),
    ("F09", "양념 카테고리 왜 이렇게 안 팔려?", dict(kind="query", intent="location", category="양념·소스", why=True)),
    ("F10", "어디에 프로모션을 거는 게 좋을까?", dict(kind="query", intent="candidates")),
    ("F11", "수산은 밀어볼 만한 후보야?", dict(kind="query", intent="candidates", category="수산")),
    ("F12", "유제품 계란 쪽 무료배송 기준 미만 주문 비중은?", dict(kind="query", intent="levers", category="유제품·계란")),
    ("F13", "정육 할인 끝나고 어떻게 됐어?", dict(kind="query", intent="promo", category="정육")),
    ("F14", "진행 중인 프로모션 성과 보여줘", dict(kind="query", intent="promo")),
    ("F15", "과자 매출 흐름 주 단위로", dict(kind="query", intent="trend", category="과자·간식")),
    ("F16", "밀키트에서 1등 상품은?", dict(kind="query", intent="rank", category="밀키트")),
    ("F17", "채소 과일 이익률 어때?", dict(kind="query", intent="status", category="채소·과일", measure="이익률")),
    # 쇼핑몰 전체·고객
    ("F18", "지난주 객단가는 평소랑 비교해서 어때?", dict(kind="query", intent="status", measure="객단가", period=LASTWEEK)),
    ("F19", "50대 고객이 제일 많이 산 카테고리", dict(kind="query", intent="rank", filters={"age_groups": ["50대"]})),
    ("F20", "골드 등급 고객 매출 어때?", dict(kind="query", intent="status", filters={"grades": ["GOLD"]})),
    ("F21", "경기도 사는 여성 고객 매출은?", dict(kind="query", intent="status",
                                         filters={"regions": ["경기도"], "gender": "F"})),
    ("F22", "구글로 가입한 사람들 주문 수", dict(kind="query", intent="status", measure="주문 수",
                                       filters={"signup_channels": ["GOOGLE"]})),
    ("F23", "테마별로 클릭률 높은 거 보여줘", dict(kind="query", intent="funnel_theme")),
    # 기간 경계
    ("F24", "오늘 들어온 주문 있어?", dict(kind="clarify")),
    ("F25", "12월 매출 예상은?", dict(kind="message")),
    ("F26", "9월 첫째 주 매출", dict(kind={"query", "message", "clarify"})),
    # 데이터에 없는 것
    ("F27", "카톡 광고 보고 들어온 고객 매출", dict(kind="message")),
    ("F28", "대학생들이 많이 사는 카테고리는?", dict(kind="message")),
    ("F29", "포인트 많이 쓴 고객 재구매율", dict(kind="message")),
    ("F30", "앱 푸시 보낸 날 매출 늘었어?", dict(kind="message")),
]
FOLLOW = [
    ("F31", Query("location", category="간편식"), "그럼 밀키트는?", dict(kind="query", intent="location", category="밀키트")),
    ("F32", Query("location", category="정육"), "지역별로는?", dict(kind="query", intent="location", category="정육", axis="region")),
    ("F33", Query("rank", category="정육"), "그럼 이익률 기준으로는?", dict(kind="query", intent="rank", category="정육",
                                                                    measure="이익률")),
    ("F34", Query("status", category="수산"), "지난달은?", dict(kind="query", intent="status", category="수산",
                                                           period=P("2026-09-01", "2026-10-01"))),
]

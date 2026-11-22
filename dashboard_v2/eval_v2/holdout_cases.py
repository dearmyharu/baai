"""홀드아웃: 규칙을 고칠 때 보지 않은 질문. 이 세트의 결과로는 규칙을 고치지 않고 정답률만 본다."""
from eval_v2.parse_cases import LAST7, LASTWEEK, P, SEP, YDAY  # noqa: F401
from engine.query import Query

CASES = [
    ("H01", "그저께 주문 몇 건이었어?", dict(kind="query", intent="status", measure="주문 수", period=P("2026-10-24", "2026-10-25"))),
    ("H02", "반찬 카테고리 요즘 장사 어때?", dict(kind="query", intent="status", category="반찬·김치")),
    ("H03", "냉동식품에서 매출 빠진 상품 알려줘", dict(kind="query", intent="location", category="냉동식품")),
    ("H04", "샐러드 매출 떨어진 이유가 뭐야?", dict(kind="query", intent="location", category="샐러드·건강식", why=True)),
    ("H05", "최근 2주 동안 많이 팔린 카테고리 top 5", dict(kind="query", intent="rank", category=None, n=5)),
    ("H06", "베이커리 주별 매출 흐름", dict(kind="query", intent="trend", category="베이커리·브런치")),
    ("H07", "프로모션 걸 만한 카테고리 추천해줘", dict(kind="query", intent="candidates")),
    ("H08", "유제품 쪽 쿠폰 쓰는 비중이랑 이익률 보여줘", dict(kind="query", intent="levers", category="유제품·계란")),
    ("H09", "음료 할인 행사 효과 있었어?", dict(kind="query", intent="promo", category="음료·커피")),
    ("H10", "큐레이션으로 들어온 사람들 구매 전환율", dict(kind="query", intent="funnel_theme")),
    ("H11", "20대 남성 매출 어때?", dict(kind="query", intent="status", filters={"age_groups": ["20대"], "gender": "M"})),
    ("H12", "네이버로 가입한 사람들 객단가는?", dict(kind="query", intent="status", measure="객단가",
                                           filters={"signup_channels": ["NAVER"]})),
    ("H13", "부산 고객 정육 매출", dict(kind="query", intent="status", category="정육", filters={"regions": ["부산광역시"]})),
    ("H14", "밀키트 매출 연령대별로 나눠 보면?", dict(kind="query", intent="location", category="밀키트", axis="age_group")),
    ("H15", "수산 요일별로 보면 어디가 빠졌어?", dict(kind="query", intent="location", category="수산", axis="weekday")),
    ("H16", "10월 1일부터 10일까지 매출", dict(kind="query", intent="status", period=P("2026-10-01", "2026-10-11"))),
    ("H17", "8월 매출 얼마였어?", dict(kind="query", intent="status", period=P("2026-08-01", "2026-09-01"))),
    ("H18", "다음 주 매출 예측해줘", dict(kind={"message", "clarify"})),
    ("H19", "유튜브 보고 온 고객 많아?", dict(kind="message")),
    ("H20", "외국인 고객 매출은?", dict(kind="message")),
    ("H21", "정기배송 이용 고객 재구매율은?", dict(kind="message")),
    ("H22", "닭가슴살 매출 어때?", dict(kind={"clarify", "query", "message"})),
    ("H23", "육류 매출 지난주 대비 어때?", dict(kind="query", intent="status", category="정육")),
]
FOLLOW = [
    ("H24", Query("rank", category="정육"), "그럼 수산에서는?", dict(kind="query", intent="rank", category="수산")),
    ("H25", Query("location", category="밀키트"), "성별로는?", dict(kind="query", intent="location", category="밀키트", axis="gender")),
]

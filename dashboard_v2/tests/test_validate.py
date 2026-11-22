"""검증 규칙 시험 (AI 없이, 손으로 쓴 초안으로). 실행: DATA_BACKEND=csv python tests/test_validate.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from engine import data as D  # noqa: E402
from engine.query import Query  # noqa: E402
from engine.validate import validate  # noqa: E402

prod = D.load_raw()["product"][["product_name", "category"]] if hasattr(D, "load_raw") else None
if prod is None:
    from engine.data import as_of, build_all
    D.set_cutoff(D.TODAY)
    prod = as_of(build_all(), D.TODAY)["raw"]["product"][["product_name", "category"]]
T = D.TODAY                     # 2026-10-26(월)
ok = n = 0


def check(name, cond, d=None):
    global ok, n
    n += 1
    ok += bool(cond)
    print(("OK  " if cond else "FAIL") + " " + name + ("" if cond or d is None else f"  → {d}"))


def V(q, draft, prev=None):
    return validate(q, draft, T, prod, prev)


def cat(v, ev):
    return {"value": v, "evidence": ev}


# 1. 데이터에 없는 항목
for q in ["인스타 광고로 들어온 고객 구매율은?", "지인 추천으로 온 고객 구매율은?", "모바일 주문 비중은?", "쿠팡보다 싸?"]:
    d = V(q, {"intent": "status"})
    check(f"데이터에 없음: {q}", d.kind == "message" and "없" in d.text, d)
# 2. 사전에 없는 말을 조건으로 바꾸면 거절 (근거 표현 검사)
d = V("단톡방 보고 온 고객 구매율은?", {"intent": "status", "filters": [{"key": "signup_channels", "value": "KAKAO", "evidence": "단톡방"}]})
check("'단톡방'→카카오 가입으로 바꾸면 거절", d.kind == "message" and "바꿔 계산하지" in d.text, d)
d = V("단톡방 보고 온 고객 구매율은?", {"intent": "status", "unmapped": ["단톡방 보고 온 고객"]})
check("AI가 매핑 불가로 적으면 안내", d.kind == "message" and "단톡방" in d.text, d)
d = V("카카오로 가입한 고객 매출은?", {"intent": "status", "filters": [{"key": "signup_channels", "value": "KAKAO", "evidence": "카카오"}]})
check("카카오 가입은 통과", d.kind == "query" and d.query.filters == {"signup_channels": ["KAKAO"]}, d)
d = V("40대 여성 매출은?", {"intent": "status", "filters": [{"key": "age_groups", "value": "40대", "evidence": "40대"},
                                                         {"key": "gender", "value": "F", "evidence": "여성"}]})
check("40대 여성 통과", d.kind == "query" and d.query.filters == {"age_groups": ["40대"], "gender": "F"}, d)
d = V("매출 어때?", {"intent": "status", "filters": [{"key": "gender", "value": "F", "evidence": ""}]})
check("근거 없는 성별 조건 거절", d.kind == "message", d)
# 3. 대상
d = V("고기 매출 어때?", {"intent": "status", "category": cat("정육", "고기")})
check("'고기' → 정육", d.kind == "query" and d.query.category == "정육", d)
d = V("매출 어때?", {"intent": "status", "category": cat("정육", "")})
check("근거 없는 카테고리는 버림(쇼핑몰 전체)", d.kind == "query" and d.query.category is None, d)
d = V("수산 매출 어때?", {"intent": "status", "category": cat("정육", "수산")})
check("근거와 다른 카테고리는 버림", d.kind == "query" and d.query.category is None, d)
d = V("삼겹살 매출 어때?", {"intent": "status", "product": cat(None, "삼겹살")})
check("'삼겹살' 여러 상품 → 되묻기", d.kind == "clarify" and len(d.choices) > 1 and all(c.query.product for c in d.choices), d)
# 4. 의도·왜
d = V("정육 매출 왜 떨어졌어?", {"intent": "status", "category": cat("정육", "정육")})
check("'왜' → 변화 위치 + why", d.kind == "query" and d.query.intent == "location" and d.why, d)
d = V("정육 어때?", {"intent": "unknown", "category": cat("정육", "정육"), "near_intents": ["status", "location"]})
check("의도 모름 → 가까운 의도 선택지(질의서 포함)", d.kind == "clarify" and [c.query.intent for c in d.choices][:2] == ["status", "location"]
      and all(c.query.category == "정육" for c in d.choices), d)
# 5. 기간 (코드 규칙)
d = V("이번 주 매출 어때?", {"intent": "status"})
check("월요일의 '이번 주' → 지난주 선택지", d.kind == "clarify" and d.choices[0].query.period == (pd.Timestamp("2026-10-19"), T), d)
d = V("오늘 주문 몇 건?", {"intent": "status", "measure": "주문 수"})
check("'오늘' → 어제 선택지", d.kind == "clarify" and d.choices[0].query.period == (pd.Timestamp("2026-10-25"), T), d)
d = V("9월 매출은?", {"intent": "status"})
check("9월 = 9/1~10/1", d.kind == "query" and d.query.period == (pd.Timestamp("2026-09-01"), pd.Timestamp("2026-10-01")), d)
d = V("8월 대비 9월 매출은?", {"intent": "status"})
check("'8월 대비 9월' → 9월", d.kind == "query" and d.query.period[0] == pd.Timestamp("2026-09-01"), d)
d = V("11월 매출은?", {"intent": "status"})
check("11월 → 데이터 없음", d.kind == "message" and "아직" in d.text, d)
d = V("어제 매출", {"intent": "status"})
check("어제 = 10/25", d.kind == "query" and d.query.period == (pd.Timestamp("2026-10-25"), T), d)
d = V("10/1부터 10/14까지 정육 매출", {"intent": "status", "category": cat("정육", "정육")})
check("날짜 범위", d.kind == "query" and d.query.period == (pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-15")), d)
d = V("잘 팔리는 카테고리는?", {"intent": "rank"})
check("기간 없는 순위 → 기간 비워 둠(계산에서 28일)", d.kind == "query" and d.query.period is None, d)
# 6. 측정값 보정·축
d = V("정육 매출 어때?", {"intent": "status", "category": cat("정육", "정육"), "measure": "완료 매출"})
check("카테고리 + 완료 매출 → 상품매출(안내)", d.kind == "query" and d.query.measure == "상품매출" and d.notes, d)
d = V("정육 매출 변화", {"intent": "location", "category": cat("정육", "정육"), "axis": cat("signup_channel", "")})
check("근거 없는 축은 버림(기본 축)", d.kind == "query" and d.query.axis is None, d)
d = V("정육 시간대별로 보면?", {"intent": "location", "category": cat("정육", "정육"), "axis": cat("daypart", "시간대")})
check("시간대 축 통과", d.kind == "query" and d.query.axis == "daypart", d)
# 7. 이어지는 질문
prev = Query("location", category="정육")
d = V("그럼 수산은?", {"intent": "location", "inherit": True, "category": cat("수산", "수산")}, prev)
check("이어지는 질문: 대상만 바뀜", d.kind == "query" and d.query.category == "수산" and d.query.intent == "location", d)
d = V("고객별로는?", {"intent": "location", "inherit": True, "axis": cat("customer_type", "고객별")}, prev)
check("이어지는 질문: 축만 바뀌고 정육 유지", d.kind == "query" and d.query.category == "정육" and d.query.axis == "customer_type", d)
print(f"\n{ok}/{n} 통과")

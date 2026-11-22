"""답변 카드 규칙 시험 (AI 없이). 실행: DATA_BACKEND=csv python tests/test_answer.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from engine import answer as A, compute as C, data as D  # noqa: E402
from engine.data import as_of, build_all  # noqa: E402
from engine.query import Query  # noqa: E402

D.set_cutoff(D.TODAY)
m = as_of(build_all(), D.TODAY)
T = D.TODAY
P = lambda a, b: (pd.Timestamp(a), pd.Timestamp(b))  # noqa: E731
ok = n = 0


def check(name, cond):
    global ok, n
    n += 1
    ok += bool(cond)
    print(("OK  " if cond else "FAIL") + " " + name)


cats = sorted(m["raw"]["product"]["category"].unique())
qs = [Query("status"), Query("rank"), Query("location"), Query("trend"), Query("candidates"), Query("promo"),
      Query("funnel_theme"), Query("funnel_theme", topic="theme")]
qs += [Query(i, category=c) for c in cats for i in ("status", "location", "rank", "levers", "candidates")]
cards = [(q, C.run(m, q, T)) for q in qs]
cards = [(q, r, A.card(r)) for q, r in cards]
banned = ("할인하", "추천", "때문", "원인은", "가설", "하십시오. 할인", "쿠폰을 쓰")
check(f"카드 {len(cards)}장 모두 결론이 있음", all(c.conclusion for _, _, c in cards))
check("카드에 이유·추천·수단 제안 문장 없음",
      not [c.text() for _, _, c in cards if any(b in c.conclusion for b in banned)])
check("숫자 칸은 최대 3개", all(len(c.numbers) <= 3 for _, _, c in cards))
check("카테고리 질문의 결론에 그 카테고리 이름", all(q.category in c.conclusion for q, _, c in cards
                                              if q.category and q.intent in ("status", "location", "candidates")))
# 결론 속 숫자는 모두 계산 결과(사실 문장·표)에 있는 표기
def nums(t):
    return set(re.findall(r"[\d,.]+(?:만원|억원|원|%|건|개|세션)", t))
missing = []
for q, r, c in cards:
    src = " ".join(r.facts) + " " + (r.table.to_string() if r.table is not None else "")
    for x in nums(c.conclusion):
        if x not in src:
            missing.append((q.intent, q.category, x))
check("결론 속 숫자는 모두 계산 결과에 있음", not missing)
if missing:
    print("   ", missing[:5])
# 비교 기준 말
c = A.card(C.run(m, Query("status", period=P("2026-09-01", "2026-10-01")), T))
check("9월 질문은 '지난달보다'(평소 아님)", "지난달보다" in c.conclusion and "평소" not in c.conclusion)
c = A.card(C.run(m, Query("status"), T))
check("기본 질문은 '평소'", "평소" in c.conclusion)
# '왜' 질문
c = A.card(C.run(m, Query("location", category="정육"), T), why=True)
check("'왜' + 변화 위치 → 위치 안내", c.lead == A.WHY_LEAD)
c = A.card(C.run(m, Query("status", category="정육"), T), why=True)
check("'왜' + 현황 → 일반 안내", c.lead == A.WHY_LEAD_PLAIN)
# 이름 구분자
c = A.card(C.run(m, Query("location"), T))
check("여러 이름은 쉼표로 구분(가운뎃점은 이름 안에서만)", ", " in c.conclusion)
print(f"\n{ok}/{n} 통과")

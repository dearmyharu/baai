"""흐름 관리 규칙 시험 (AI 없이). 실행: DATA_BACKEND=csv python tests/test_flow.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from engine import compute as C, data as D, flow as FL  # noqa: E402
from engine.data import as_of, build_all  # noqa: E402
from engine.query import Query  # noqa: E402

D.set_cutoff(D.TODAY)
m = as_of(build_all(), D.TODAY)
T = D.TODAY
ok = n = 0


def check(name, cond, d=None):
    global ok, n
    n += 1
    ok += bool(cond)
    print(("OK  " if cond else "FAIL") + " " + name + ("" if cond or d is None else f"  → {d}"))


def answer(f, q, question="질문"):
    r = C.run(m, q, T)
    f.record(question, q, r)
    return r, f.actions(q, r)


# 1. 예전 버그: '정육 상품 감소' 질문만으로 대상·수단이 정해지면 안 된다
f = FL.Flow()
q = Query("location", category="정육", period=(pd.Timestamp("2026-10-19"), T))
r, acts = answer(f, q, "최근 7일 정육 카테고리에서 매출이 줄어든 상품은?")
check("질문만으로는 대상 미정", f.target is None)
check("질문만으로는 수단 미정", f.lever is None)
check("넘김 조건 미충족", not f.ready(m, T))
check("답에 '대상으로 정하기' 버튼이 있음(누르기 전엔 미정)", any(a.kind == "set_target" and a.value == "정육" for a in acts))
check("다음 축 버튼은 아직 안 본 축", all(a.query.axis != "product" for a in acts if a.kind == "query" and a.query.intent == "location"))
check("수단 버튼은 대상 정하기 전엔 없음", not f.lever_actions())
# 2. 실무자가 정하는 순서
f.set_target("정육", "정육 매출 왜 떨어졌어?")
steps = f.steps(m, T)
check("대상 정함 → 어디를 밀까 완료", steps[1]["done"] and steps[0]["done"])
check("수단 선택지 4개, 기본값 없음", len(f.lever_actions()) == 4 and f.lever is None)
check("수단 선택지에 지켜보기·묶음 없음", not any("지켜" in a.label or "묶음" in a.label for a in f.lever_actions()))
check("수단 전엔 넘김 불가", not f.ready(m, T))
f.set_lever("price", 5)
check("대상·수단·원인 좁히기·확인 가능 → 넘김 가능", f.ready(m, T), FL.summary(f, m, T))
req = f.lab_request(m, T)
check("넘김 대상은 카테고리", req["target"] == {"type": "category", "value": "정육"})
check("판매가 할인은 음수로(Growth Lab 형식)", req["lever"] == {"policy": "price", "value": -5})
check("가설 문장 없음", req["hypothesis"] == "" and req["cause_hypothesis"] == "")
check("근거는 변화 위치 사실 문장", req["evidence"] and "정육" in req["evidence"][0])
check("진단은 공통 기준(3일·7일)", abs(req["diagnosis"]["change3"] - C.candidate_table(m, Query("candidates"), T).loc["정육", "3일_변화율"]) < 1e-9)
# 3. 대상을 바꾸면 수단 초기화
f.set_target("수산")
check("대상 바꾸면 수단 다시 고름", f.lever is None and not f.ready(m, T))
check("수산은 변화 위치를 안 봤으니 원인 좁히기 미완료", not f.steps(m, T)[0]["done"])
# 4. 대상 없이 수단 고르기 거절
g = FL.Flow()
try:
    g.set_lever("price", 5)
    check("대상 없이 수단 거절", False)
except ValueError:
    check("대상 없이 수단 거절", True)
# 5. 후보 결과 → 후보 카테고리로 들어가는 버튼
g = FL.Flow()
r, acts = answer(g, Query("candidates"))
check("후보 결과에서 후보 카테고리 변화 위치 버튼", [a.query.category for a in acts if a.kind == "query"][:2] == ["정육", "수산"], acts)
# 6. 효과 확인이 어려운 카테고리는 넘김 불가
tbl = C.candidate_table(m, Query("candidates"), T)
hard = tbl.index[~tbl["testable"]].tolist()
if hard:
    h = FL.Flow()
    answer(h, Query("location", category=hard[0]))
    h.set_target(hard[0]); h.set_lever("price", 5)
    check(f"효과 확인 어려운 {hard[0]}은 넘김 불가", not h.ready(m, T))
else:
    check("(효과 확인 어려운 카테고리 없음: 건너뜀)", True)
print(f"\n{ok}/{n} 통과")

"""계산 함수 규칙 시험 (AI 없이). 실행: DATA_BACKEND=csv python tests/test_compute.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from engine import basis as S, briefing as B, compute as C, data as D  # noqa: E402
from engine.data import as_of, build_all  # noqa: E402
from engine.query import Query  # noqa: E402

D.set_cutoff(D.TODAY)
m = as_of(build_all(), D.TODAY)
T = D.TODAY
ok = 0


def check(name, cond):
    global ok
    print(("OK  " if cond else "FAIL") + " " + name)
    ok += bool(cond)
    return cond


def raises(name, fn):
    try:
        fn()
    except ValueError:
        return check(name, True)
    return check(name, False)


o, it = S.ledger(m)
# 1. 기준: 브리핑과 같은 숫자
y = B.brief(m, S.last_day(T))["yesterday"]
c = S.compare(S.daily(o, it, "완료 매출"), T, 3).loc["전체"]
check("쇼핑몰 3일 매출·평소가 브리핑과 같음", float(c["현재"]) == float(y["revenue3"]) and float(c["평소"]) == float(y["revenue3_base"]))
cat3 = S.compare(S.daily(o, it, "상품매출", by="category"), T, 3)["현재"].sum()
shop3 = S.compare(S.daily(o, it, "상품매출"), T, 3).loc["전체", "현재"]
check("카테고리 상품매출 합 = 쇼핑몰 상품매출", abs(cat3 - shop3) < 1)
# 2. 받을 수 없는 입력은 거절 (조용히 전체로 바꾸지 않음)
raises("완료 매출을 카테고리별로 나누면 거절", lambda: S.daily(o, it, "완료 매출", by="category"))
raises("카테고리 현황에 완료 매출이면 거절", lambda: C.run(m, Query("status", category="정육", measure="완료 매출"), T))
raises("없는 카테고리 거절", lambda: C.run(m, Query("status", category="인스타"), T))
raises("상품 하나의 순위는 거절", lambda: C.run(m, Query("rank", product="한우마루 한돈 삼겹살 500g 매운맛"), T))
raises("퍼널을 카테고리로 나누면 거절", lambda: C.run(m, Query("funnel_theme", category="정육"), T))
raises("모르는 축 거절", lambda: Query("location", axis="인스타"))
# 3. 범위가 결과에 그대로
r = C.run(m, Query("status", category="정육"), T)
check("정육 현황은 정육 숫자", r.key["target"] == "정육 카테고리" and r.key["windows"][0]["현재"] < shop3 / 5)
# 4. 변화 위치: 감소분 비중 합 100%, 이유 문장 없음
r = C.run(m, Query("location", category="정육"), T)
shares = pd.to_numeric(r.table["감소분 중 비중"].str.rstrip("%"), errors="coerce").sum()
check("정육 상품별 감소분 비중 합 ≈ 100%", 98 <= shares <= 102)
check("변화 위치에 '이유 모름' 안내", C.NO_REASON in r.notes)
check("결과에 수단·할인 제안 없음", not any(w in " ".join(r.facts) for w in ("할인", "쿠폰", "추천")))
check("3일·7일 모두 0인 상품 제외", not ((r.table.iloc[:, 1] == "0원") & (r.table.iloc[:, 2] == "0원")
                                       & (r.table.iloc[:, -1] == "–")).any())
# 5. 후보 규칙
g = C.candidate_table(m, Query("candidates"), T)
r = C.run(m, Query("candidates"), T)
down = r.key["by_kind"][C.KIND_DOWN]
check("줄고 있음 후보는 3일·7일 모두 낮음", all(g.loc[x, "3일_판정"] == S.LEVEL_LOW and g.loc[x, "7일_판정"] == S.LEVEL_LOW for x in down))
check("샐러드·건강식(3일만 하락)은 후보 아님", "샐러드·건강식" not in sum(r.key["by_kind"].values(), []))
check("정육 후보에 할인 종료 사실 표시", "종료 후" in r.table.set_index("카테고리").loc["정육", "최근 프로모션"].iloc[0]
      if isinstance(r.table.set_index("카테고리").loc["정육", "최근 프로모션"], pd.Series)
      else "종료 후" in r.table.set_index("카테고리").loc["정육", "최근 프로모션"])
# 6. 기간 비교 규칙
check("9월은 8월 전체와 비교", S.baseline("2026-09-01", "2026-10-01")[1] == "지난달")
check("진행 중인 10월은 9월 같은 날짜와 비교", S.baseline("2026-10-01", "2026-10-26")[1] == "지난달 같은 날짜")
check("기간 없는 순위 = 최근 28일", S.default_period(T, "rank") == (pd.Timestamp("2026-09-28"), T))
# 7. 모든 의도가 실행됨
for q in [Query("status"), Query("rank"), Query("location"), Query("trend"), Query("candidates"),
          Query("levers", category="정육"), Query("promo"), Query("funnel_theme"), Query("funnel_theme", topic="theme")]:
    try:
        C.run(m, q, T)
        check(f"실행: {q.intent} {q.topic or ''}", True)
    except Exception as e:  # noqa: BLE001
        check(f"실행: {q.intent} ({e})", False)
print(f"\n{ok} 통과")

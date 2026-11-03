"""홀드아웃 2차(30문항): 일반 원칙 수정·고객 조건 필터를 만든 뒤 한 번만 돌려 일반화를 확인한다.

검증 기준 (팀에서 받은 세 가지)
1. 질문이 달라져도 같은 의미를 이해하는가 → A. 표현 바꾸기
2. 조건과 데이터가 바뀌어도 올바른 결과를 내는가 → B. 조건 조합, D. KPI 정의 (+ eval/data_change.py)
3. 처음 보는 문제에 근거로 답하거나 모르는 것을 인정하는가 → C. 없는 정보, E. 분석 일반화

원칙
- 1차 홀드아웃(eval/holdout.py)과 겹치지 않는 문항. 결과를 보고 이 문항에 맞춘 규칙을 넣지 않는다.
- 조건 문항(B)의 정답은 core/metrics.filter_mart를 쓰지 않고 원자료(고객·주문·방문)에서 따로 계산한다(필터 구현 검증).
- kind: check(도구 결과 = 정답) / tool(알맞은 도구) / refuse(데이터에 없다고 밝힘) / hypo(확정할 수 없다·가설이라고 밝힘)
- text_fn(정답) → 답변에 하나라도 들어 있어야 하는 표현 목록 (전제 바로잡기, 기준 밝히기 등)
"""
from __future__ import annotations

import pandas as pd

from core import metrics as M
from core import tools as T
from eval.holdout import label, ok_if, has  # noqa: F401  (공용 도우미)

P = pd.Timestamp
SEP = (P("2026-09-01"), P("2026-10-01"))
AUG = (P("2026-08-01"), P("2026-09-01"))
JUN = (P("2026-06-01"), P("2026-07-01"))
YDAY = (P("2026-09-29"), P("2026-09-30"))


def d(p):
    return {"start": f"{p[0]:%Y-%m-%d}", "end": f"{p[1]:%Y-%m-%d}"}


# ---------------------------------------------------------------------------
# 원자료에서 직접 계산 (필터 구현과 독립)
# ---------------------------------------------------------------------------
def _cust(m, gender=None, age=None, region=None, channel=None, grade_now=None, signup=None):
    c = m["raw"]["customer"]
    k = pd.Series(True, index=c.index)
    if gender:
        k &= c["gender"].eq(gender)
    if age:
        a = 2026 - c["birth_year"]
        k &= a.between(*age)
    if region:
        k &= c["region"].eq(region)
    if channel:
        k &= c["signup_channel"].eq(channel)
    if grade_now:
        k &= c["membership_grade"].eq(grade_now)
    if signup:
        k &= (c["signup_date"] >= signup[0]) & (c["signup_date"] < signup[1])
    return set(c.loc[k, "customer_id"])


def _orders(m, p, ids=None, grade_at=None, ctype=None):
    o = m["orders"]
    o = o[(o["order_time"] >= p[0]) & (o["order_time"] < p[1]) & o["order_status"].eq("COMPLETED")]
    if ids is not None:
        o = o[o["customer_id"].isin(ids)]
    if grade_at:
        o = o[o["grade_at_order"].eq(grade_at)]
    if ctype:
        o = o[o["customer_type"].eq(ctype)]
    return o


def _items(m, o):
    return m["items"][m["items"]["order_id"].isin(o["order_id"])]


def cat_top(p, **kw):
    def f(m):
        it = _items(m, _orders(m, p, _cust(m, **kw) if kw else None))
        s = (it["sales_amount"] - it["allocated_coupon_discount"]).groupby(it["category"]).sum().sort_values(ascending=False)
        return {"1위": s.index[0]}
    return f


def prod_top(p, n=5, sort="net", **kw):
    def f(m):
        o = _orders(m, p, _cust(m, **kw) if kw else None)
        it = _items(m, o).assign(net=lambda x: x["sales_amount"] - x["allocated_coupon_discount"])
        g = it.groupby("product_name").agg(net=("net", "sum"), qty=("quantity", "sum"))
        g = g.sort_values([sort, "net"], ascending=False)
        return {"상품": list(g.index[:n]), "구매 고객": o["customer_id"].nunique()}
    return f


def revenue(p, grade_at=None, ctype=None, **kw):
    def f(m):
        o = _orders(m, p, _cust(m, **kw) if kw else None, grade_at, ctype)
        return {"매출": o["total_amount"].sum(), "주문": o["order_id"].nunique(), "구매 고객": o["customer_id"].nunique(),
                "객단가": o["total_amount"].sum() / max(o["order_id"].nunique(), 1)}
    return f


def cvr(p, **kw):
    def f(m):
        s = m["sessions"]
        s = s[(s["start"] >= p[0]) & (s["start"] < p[1]) & s["customer_id"].isin(_cust(m, **kw))]
        return {"전환율": s["has_purchase"].mean()}
    return f


def funnel_last(p, **kw):
    def f(m):
        s = m["sessions"]
        s = s[(s["start"] >= p[0]) & (s["start"] < p[1]) & s["customer_id"].isin(_cust(m, **kw))]
        fn = M.funnel(s, "ALL")
        return {"장바구니→구매": fn["직전 단계 대비 전환율"].iloc[-1]}
    return f


def decomposition(p):
    def f(m):
        prev = M.compare_period(*p)
        dd = M.revenue_decomposition(m, p, prev)
        k, kp = M.kpis(m, *p), M.kpis(m, *prev)
        return {"변화": dd["revenue_change"], "매출": k["revenue"], "구매자 변화": k["buyers"] - kp["buyers"]}
    return f


def themes(p):
    def f(m):
        tt, _, _ = M.theme_quadrant(m, *p)
        return {"클릭률 1위": tt.sort_values("클릭률", ascending=False)["테마"].iloc[0],
                "관심↑ 구매↓": tt.loc[tt["구분"].eq("관심↑ 구매↓"), "테마"].tolist()}
    return f


def potential(p):
    def f(m):
        pp = M.product_potential(m, *p, prev=M.compare_period(*p))
        return {"후보": list(pp[pp["구분"].eq("키울 후보")]["product_name"].head(5))}
    return f


# ---------------------------------------------------------------------------
# 확인 함수
# ---------------------------------------------------------------------------
def target_has(*words):
    """사실 목록 첫 줄 '대상: …'에 조건이 모두 들어 있는가 (조건을 제대로 걸었는지)."""
    def f(r):
        first = r["facts"][0] if r["facts"] else ""
        return first.startswith("대상:") and all(w in first for w in words)
    return f


def table_prefix(col, key, k_min=3):
    def f(r, e):
        t = r.get("table")
        got = list(t[col]) if t is not None and col in t else []
        k = min(len(got), len(e[key]))
        return ok_if(k >= min(k_min, len(e[key])) and got[:k] == e[key][:k], f"{key} 순서 불일치 {got[:3]}")
    return f


def with_target(check, *words):
    def f(r, e):
        if not target_has(*words)(r):
            return f"고객 조건 불일치(대상: {r['facts'][0][:60] if r['facts'] else '-'})"
        return check(r, e)
    return f


def fact_won(key):
    return lambda r, e: ok_if(has(r, T.won(e[key])), f"{key} {T.won(e[key])} 없음")


def fact_pct(key):
    return lambda r, e: ok_if(has(r, T.pct(e[key])), f"{key} {T.pct(e[key])} 없음")


def first_row(col, key):
    return lambda r, e: ok_if(r.get("table") is not None and col in r["table"] and r["table"][col].iloc[0] == e[key],
                              f"{key} 불일치")


AGE30, AGE40 = (30, 39), (40, 49)
CASES = [
    # A. 같은 의미, 다른 표현 (기준 1)
    dict(id="V01", period=SEP, level="A 표현", q="가장 돈을 많이 벌어다 준 제품 TOP 5는?", kind="check", expected=prod_top(SEP),
         checks=[("rank_items", table_prefix("상품", "상품"))], params=("rank_items", d(SEP) | {"target": "product", "n": 5})),
    dict(id="V02", period=SEP, level="A 표현", q="매출액 기준 상위 다섯 상품을 순서대로 보여줘.", kind="check", expected=prod_top(SEP),
         checks=[("rank_items", table_prefix("상품", "상품"))], params=("rank_items", d(SEP) | {"target": "product", "n": 5})),
    dict(id="V03", period=SEP, level="A 표현", q="어떤 제품이 제일 잘 팔려?", kind="check", expected=prod_top(SEP),
         checks=[("rank_items", table_prefix("상품", "상품", 1))], params=("rank_items", d(SEP) | {"target": "product"}),
         text_fn=lambda e: ["매출 기준", "매출액 기준", "상품매출 기준", "매출 순", "매출이 가장", "매출 1위", "수량"]),
    dict(id="V04", period=AUG, level="A 표현", q="지난달 기준으로 잘 팔린 제품 5개만 뽑아줘.", kind="check", expected=prod_top(AUG),
         checks=[("rank_items", table_prefix("상품", "상품"))], params=("rank_items", d(AUG) | {"target": "product", "n": 5})),
    dict(id="V05", period=SEP, level="A 표현", q="이번 달에 몇 개씩 제일 많이 팔린 상품 3개는?", kind="check",
         expected=prod_top(SEP, sort="qty"),
         checks=[("rank_items", table_prefix("상품", "상품"))], params=("rank_items", d(SEP) | {"target": "product", "n": 3, "metric": "수량"})),
    # B. 조건 변경·조합 (기준 2) - 정답은 원자료에서 따로 계산
    dict(id="V06", period=JUN, level="B 조건", q="6월 매출이 가장 높은 카테고리는?", kind="check", expected=cat_top(JUN),
         checks=[("rank_items", first_row("카테고리", "1위"))], params=("rank_items", d(JUN) | {"target": "category"})),
    dict(id="V07", period=JUN, level="B 조건", q="여성 고객의 6월 매출이 높은 카테고리는?", kind="check", expected=cat_top(JUN, gender="F"),
         checks=[("rank_items", with_target(first_row("카테고리", "1위"), "여성"))],
         params=("rank_items", d(JUN) | {"target": "category", "filters": {"gender": "F"}})),
    dict(id="V08", period=JUN, level="B 조건", q="여성 고객 중 50대의 6월 매출이 높은 카테고리는?", kind="check",
         expected=cat_top(JUN, gender="F", age=(50, 59)),      # 전체·여성 전체(냉동식품)와 답이 다른 조합
         checks=[("rank_items", with_target(first_row("카테고리", "1위"), "여성", "50대"))],
         params=("rank_items", d(JUN) | {"target": "category", "filters": {"gender": "F", "age_groups": ["50대"]}})),
    dict(id="V09", period=JUN, level="B 조건", q="여성 30대 중 6월에 새로 가입한 고객이 구매한 상품 TOP 5는?", kind="check",
         expected=prod_top(JUN, gender="F", age=AGE30, signup=JUN),
         checks=[("rank_items", with_target(table_prefix("상품", "상품", 1), "여성", "30대", "신규 가입"))],
         params=("rank_items", d(JUN) | {"target": "product", "filters": {"gender": "F", "age_groups": ["30대"], "new_signup": True}}),
         text_fn=lambda e: ["표본", "적어", "작아", "적은"] if e["구매 고객"] < 30 else [""]),
    dict(id="V10", period=JUN, level="B 조건", q="6월에 VIP 등급이었던 고객들의 6월 매출은?", kind="check", expected=revenue(JUN, grade_at="VIP"),
         checks=[("get_kpis", with_target(fact_won("매출"), "당시", "VIP"))],
         params=("get_kpis", d(JUN) | {"filters": {"grades": ["VIP"], "grade_basis": "당시"}})),
    dict(id="V11", period=JUN, level="B 조건", q="지금 VIP인 고객들은 6월에 얼마나 샀어?", kind="check", expected=revenue(JUN, grade_now="VIP"),
         checks=[("get_kpis", with_target(fact_won("매출"), "현재", "VIP"))],
         params=("get_kpis", d(JUN) | {"filters": {"grades": ["VIP"], "grade_basis": "현재"}})),
    dict(id="V12", period=AUG, level="B 조건", q="서울 사는 고객의 지난달 객단가는?", kind="check", expected=revenue(AUG, region="서울특별시"),
         checks=[("get_kpis", with_target(fact_won("객단가"), "서울특별시"))],
         params=("get_kpis", d(AUG) | {"filters": {"regions": ["서울특별시"]}})),
    dict(id="V13", period=SEP, level="B 조건", q="카카오로 가입한 고객들의 9월 구매 전환율은?", kind="check", expected=cvr(SEP, channel="KAKAO"),
         checks=[("get_kpis", with_target(fact_pct("전환율"), "KAKAO"))],
         params=("get_kpis", d(SEP) | {"filters": {"signup_channels": ["KAKAO"]}})),
    dict(id="V14", period=SEP, level="B 조건", q="9월 신규 고객 매출은 얼마야?", kind="check", expected=revenue(SEP, ctype="첫 구매 고객"),
         checks=[("get_kpis", with_target(fact_won("매출"), "첫 구매"))],
         params=("get_kpis", d(SEP) | {"filters": {"customer_type": "첫 구매"}}),
         text_fn=lambda e: ["첫 구매"]),
    dict(id="V15", period=SEP, level="B 조건", q="9월에 가입한 사람 중 실제로 구매한 사람은 몇 명이야?", kind="check",
         expected=revenue(SEP, signup=SEP),
         checks=[("get_kpis", with_target(lambda r, e: ok_if(has(r, f"구매 고객 수 {e['구매 고객']:,}명"), "구매 고객 수 불일치"), "신규 가입"))],
         params=("get_kpis", d(SEP) | {"filters": {"new_signup": True}})),
    dict(id="V16", period=SEP, level="B 조건", q="40대 남성 고객은 장바구니에 담은 뒤 얼마나 구매로 이어져?", kind="check",
         expected=funnel_last(SEP, gender="M", age=AGE40),
         checks=[("get_funnel", with_target(fact_pct("장바구니→구매"), "남성", "40대"))],
         params=("get_funnel", d(SEP) | {"filters": {"gender": "M", "age_groups": ["40대"]}})),
    # C. 없는 정보·환각 (기준 3)
    dict(id="V17", level="C 모름", q="우리 고객들이 가장 많이 쓰는 결제수단은?", kind="refuse"),
    dict(id="V18", level="C 모름", q="경쟁사 대비 우리 쇼핑몰 시장점유율은?", kind="refuse"),
    dict(id="V19", level="C 모름", q="다음 달 매출이 정확히 얼마가 될지 알려줘.", kind="refuse"),
    dict(id="V20", level="C 모름", q="고객들이 상품을 사지 않은 가장 큰 이유가 뭐야?", kind="hypo"),
    dict(id="V21", period=YDAY, level="C 모름", q="어제 매출이 왜 감소했어?", kind="check", expected=decomposition(YDAY),
         checks=[("explain_revenue_change", fact_won("매출")), ("get_kpis", fact_won("매출"))],
         params=("explain_revenue_change", d(YDAY)),
         text_fn=lambda e: (["매출이 늘", "매출은 늘", "늘었", "증가했", "증가한", "올랐", "상승", "감소하지 않", "오히려", "전제"]
                            if e["변화"] > 0 else ["줄", "감소", "떨어", "하락"])),
    # D. KPI 정의 (기준 2)
    dict(id="V22", period=AUG, level="D 정의", q="지난달 매출액과 주문 수 알려줘.", kind="check", expected=revenue(AUG),
         checks=[("get_kpis", lambda r, e: ok_if(has(r, T.won(e["매출"]), f"{e['주문']:,}건"), "완료 매출·주문 수 불일치"))],
         params=("get_kpis", d(AUG))),
    dict(id="V23", period=AUG, level="D 정의", q="지난달 취소·환불까지 포함한 주문 접수 금액은?", kind="check",
         expected=lambda m: {"접수": m["orders"][(m["orders"]["order_time"] >= AUG[0]) & (m["orders"]["order_time"] < AUG[1])]["total_amount"].sum()},
         checks=[("get_kpis", lambda r, e: ok_if(has(r, T.won(e["접수"])), "주문 접수 금액 불일치"))], params=("get_kpis", d(AUG))),
    dict(id="V24", period=SEP, level="D 정의", q="테마 클릭률이 가장 높은 큐레이션은?", kind="check", expected=themes(SEP),
         checks=[("get_themes", lambda r, e: ok_if(has(r, f"클릭률 1위: {e['클릭률 1위']}"), "클릭률 1위 불일치"))],
         params=("get_themes", d(SEP))),
    dict(id="V25", level="D 정의", q="처음 방문한 고객과 다시 방문한 고객 중 구매전환율이 높은 쪽은?", kind="refuse"),
    dict(id="V26", period=SEP, level="D 정의", q="9월에 가장 많이 팔린 상품(개수)과 매출 1위 상품이 같아?", kind="check",
         expected=lambda m: {"수량 1위": prod_top(SEP, 1, "qty")(m)["상품"][0], "매출 1위": prod_top(SEP, 1)(m)["상품"][0]},
         checks=[("rank_items", lambda r, e: ok_if(r.get("table") is not None and "상품" in r["table"]
                                                  and r["table"]["상품"].iloc[0] in (e["수량 1위"], e["매출 1위"]), "1위 상품 불일치"))],
         params=("rank_items", d(SEP) | {"target": "product", "metric": "수량"}),
         text_fn=lambda e: ["같습니다", "같아요", "동일"] if e["수량 1위"] == e["매출 1위"] else ["다릅니다", "달라요", "다른", "아닙니다"]),
    # E. 분석 일반화 (기준 3)
    dict(id="V27", period=SEP, level="E 일반화", q="이번 달 매출은 늘었는데 구매자 수는 줄었다면 왜 그런 거야?", kind="check",
         expected=decomposition(SEP),
         checks=[("explain_revenue_change", fact_won("매출")), ("get_kpis", fact_won("매출"))], params=("explain_revenue_change", d(SEP)),
         text_fn=lambda e: (["매출이 줄", "매출은 줄", "매출이 감소", "매출은 감소", "매출이 떨어", "매출은 떨어", "매출이 하락",
                             "매출은 하락", "늘지 않", "늘어나지 않", "증가하지 않", "오히려", "전제", "사실과 다", "함께 줄",
                             "패턴이 아니라"]
                            if e["변화"] < 0 else [""])),      # 전제(매출 증가)가 틀렸음을 바로잡아야
    dict(id="V28", period=SEP, level="E 일반화", q="클릭은 많이 되는데 구매로는 잘 안 이어지는 테마 찾아줘.", kind="check", expected=themes(SEP),
         checks=[("get_themes", lambda r, e: ok_if(all(t in " ".join(r["facts"]) for t in e["관심↑ 구매↓"]), "관심↑ 구매↓ 테마 불일치"))],
         params=("get_themes", d(SEP))),
    dict(id="V29", level="E 일반화", q="최근 성과가 나빠진 큐레이션을 찾고 개선 실험을 제안해줘.", kind="tool",
         tools={"get_themes", "detect_changes"}),
    dict(id="V30", period=SEP, level="E 일반화", q="성장 잠재력이 높은 상품 추천해줘.", kind="check", expected=potential(SEP),
         checks=[("find_potential_products", table_prefix("product_name", "후보"))], params=("find_potential_products", d(SEP))),
]

ALL_CASES = CASES


def selfcheck(data_dir=None) -> int:
    """정답 도구를 올바른 입력으로 부르면 통과하는지 + 조건을 빼면 떨어지는지(필터가 결과를 실제로 바꾸는지)."""
    from core.data import build_all
    from eval.holdout import check_fn
    m = build_all(data_dir)
    bad = 0
    for c in ALL_CASES:
        if c["kind"] != "check":
            continue
        tool, params = c["params"]
        e = c["expected"](m)
        fn = check_fn(c, tool)
        try:
            why = fn(T.run(m, tool, **params), e)
        except Exception as ex:  # noqa: BLE001
            why = f"오류 {ex!r}"
        extra = ""
        if "filters" in params:
            loose = {k: v for k, v in params.items() if k != "filters"}
            extra = " · 조건 빼면 " + ("떨어짐(정상)" if fn(T.run(m, tool, **loose), e) else "!! 그래도 통과")
        print(f"{'OK' if why is None else 'NG'}  {c['id']}  {tool:<22} {why or ''}{extra}  정답={str(e)[:70]}")
        bad += why is not None
    n = sum(c["kind"] == "check" for c in ALL_CASES)
    print(f"\n{n - bad}/{n} 정답 계산 확인")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(selfcheck(sys.argv[1] if len(sys.argv) > 1 else None))

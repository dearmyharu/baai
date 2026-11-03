"""처음 보는 질문 평가셋(홀드아웃): 오버피팅 확인용.

eval/cases.py의 36문항을 보고 AI 지시문·도구를 고쳐 왔으므로, 그 점수만으로는 처음 보는 질문도 잘 맞히는지 알 수 없다.
이 파일의 문항은 지시문·도구를 고치는 데 쓰지 않는다. 틀려도 이 문항에 맞춘 규칙을 넣지 말고,
일반적인 원인을 찾아 고친 뒤 '새' 홀드아웃 문항으로 다시 확인한다.

구성 (만든 날 2026-11-03, 작성: Claude. 팀원 질문은 TEAM 목록에 추가)
- 말만 바꾼 질문, 다른 기간(7월·6~8월·지난주), 같은 도구의 다른 쓰임, 새 미지원·범위 밖 질문
- kind: "check"(도구 결과가 정답과 같아야) / "tool"(알맞은 도구 사용) / "refuse"(데이터에 없다고 밝힘)
- checks: [(도구, 확인 함수)] 중 하나라도 통과하면 정답. 확인 함수(결과, 정답) → 불일치 설명 또는 None
- params: 정답 도구를 올바른 기간으로 불렀을 때의 입력(정답 계산 자체를 검사하는 데 씀)
"""
from __future__ import annotations

import pandas as pd

from core import metrics as M
from core import tools as T

P = pd.Timestamp
SEP = (P("2026-09-01"), P("2026-10-01"))
AUG = (P("2026-08-01"), P("2026-09-01"))
JUL = (P("2026-07-01"), P("2026-08-01"))
JUN_AUG = (P("2026-06-01"), P("2026-09-01"))
THIS_WEEK = (P("2026-09-28"), P("2026-10-01"))   # 달력 주 9/28(월)~9/30(수), 지난주 같은 요일과 비교
ALL = (P("2026-04-01"), P("2026-10-01"))


def d(p):
    return {"start": f"{p[0]:%Y-%m-%d}", "end": f"{p[1]:%Y-%m-%d}"}


def has(r, *needles):
    text = " ".join(r["facts"]) + " " + r["title"]
    return all(n in text for n in needles)


def ok_if(cond, why):
    return None if cond else why


def label(p) -> str:
    return f"{p[0]:%Y-%m-%d} ~ {p[1] - pd.Timedelta(days=1):%Y-%m-%d}"


def check_fn(c, tool):
    """사례의 확인 함수. 사례에 period가 있으면 도구 결과의 기준 기간도 같아야 통과
    (기간이 달라도 1위가 같은 경우가 있어 결과만으로는 기간 해석을 확인할 수 없음)."""
    fn = dict(c["checks"]).get(tool)
    if fn is None:
        return None
    if "period" not in c:
        return fn

    def wrapped(r, e):
        if not r["period"].startswith(label(c["period"])):
            return f"기준 기간 불일치({r['period'][:23]}, 정답 {label(c['period'])})"
        return fn(r, e)
    return wrapped


# ---------------------------------------------------------------------------
# 정답 계산 (core/metrics.py 직접 사용)
# ---------------------------------------------------------------------------
def kpi(p, key):
    return lambda m: {key: M.kpis(m, *p)[key]}


def top_products(p, n):
    return lambda m: {"상품": list(M.top_products(m, *p, n=n)["product_name"])}


def top_category(p):
    return lambda m: {"1위": M.category_sales(m, *p)["category"].iloc[0]}


def coupon_eff(p):
    return lambda m: {"효율": M.coupon_efficiency(m, *p)["total"]["efficiency"]}


def best_theme(p):
    def f(m):
        tt, _, _ = M.theme_quadrant(m, *p)
        return {"1위": tt.sort_values("구매전환율", ascending=False)["테마"].iloc[0]}
    return f


def worst_step(p):
    def f(m):
        fn = M.funnel(M.in_period(m["sessions"], "start", *p), "ALL")
        steps = fn.iloc[1:-1]
        w = steps.loc[steps["직전 단계 대비 전환율"].idxmin()]
        order = list(fn["단계"])
        i = order.index(w["단계"])
        return {"구간": f"{order[i-1]} → {order[i]}"}
    return f


def weekly(m):
    return {"매출": list(M.sales_trend(m, *ALL, grain="week")["매출"])}


def pref_top(p, by):
    def f(m):
        mix = M.segment_category_mix(m, *p, by=by)
        mix[by] = mix[by].map(lambda v: {"NEW": "신규 방문", "RETURNING": "재방문", "UNKNOWN": "판정 불가"}.get(v, v))
        top = mix.sort_values("비중", ascending=False).groupby(by).head(1)
        return {"1위": {r[by]: r["category"] for _, r in top.iterrows()}}
    return f


def repeat_low(by):
    def f(m):
        r = M.segment_repeat(m, by=by)
        return {"가장 낮은 고객군": r[r["표본 충분"]].iloc[0]["고객군"]}
    return f


def rev_change(p):
    def f(m):
        prev = M.compare_period(*p)
        dd = M.revenue_decomposition(m, p, prev)
        return {"변화": dd["revenue_change"], "매출": M.kpis(m, *p)["revenue"]}
    return f


def changes(p):
    return lambda m: {"개수": len(M.detect_changes(m, p, M.compare_period(*p), alpha=0.05))}


def potential(p):
    def f(m):
        pp = M.product_potential(m, *p, prev=M.compare_period(*p))
        return {"후보": list(pp[pp["구분"].eq("키울 후보")]["product_name"].head(5))}
    return f


def rfm_count(name):
    return lambda m: {"고객수": int(M.rfm_summary(m, *SEP).set_index("고객군").loc[name, "고객수"])}


def sample(step, lift):
    def f(m):
        s = M.in_period(m["sessions"], "start", *SEP)
        n, den, p0 = M.step_rate(s, "ALL", step)
        return {"그룹당": M.sample_size_per_group(p0, lift)}
    return f


# ---------------------------------------------------------------------------
# 확인 함수
# ---------------------------------------------------------------------------
def c_won(key):
    return lambda r, e: ok_if(has(r, T.won(e[key])), f"{key} {T.won(e[key])} 없음")


def c_count(key, unit):
    return lambda r, e: ok_if(has(r, f"{e[key]:,}{unit}"), f"{key} {e[key]:,}{unit} 없음")


def c_pct(key):
    return lambda r, e: ok_if(has(r, T.pct(e[key])), f"{key} {T.pct(e[key])} 없음")


def c_prefix(col, key):
    def f(r, e):
        got = list(r["table"][col]) if r.get("table") is not None and col in r["table"] else []
        want = e[key]
        k = min(len(got), len(want))
        return ok_if(k >= min(3, len(want)) and got[:k] == want[:k], f"{key} 순서 불일치: {got[:3]}")
    return f


def c_trend_sum(key):
    def f(r, e):
        t = r.get("table")
        return ok_if(t is not None and abs(t["매출"].sum() - e[key]) < 1, "기간 매출 합계 불일치")
    return f


CASES = [
    # L1: 말만 바꾼 질문, 다른 기간
    dict(id="H01", period=JUL, level="L1", q="7월 매출 얼마였어?", kind="check", expected=kpi(JUL, "revenue"),
         checks=[("get_kpis", c_won("revenue")), ("get_trend", c_trend_sum("revenue"))], params=("get_kpis", d(JUL))),
    dict(id="H02", period=AUG, level="L1", q="8월에 주문 몇 건 들어왔어?", kind="check", expected=kpi(AUG, "orders"),
         checks=[("get_kpis", c_count("orders", "건"))], params=("get_kpis", d(AUG))),
    dict(id="H03", period=SEP, level="L1", q="9월 베스트셀러 3개만 알려줘", kind="check", expected=top_products(SEP, 5),
         checks=[("rank_items", c_prefix("상품", "상품"))], params=("rank_items", d(SEP) | {"target": "product", "n": 3})),
    dict(id="H04", period=AUG, level="L1", q="8월에 제일 많이 팔린 카테고리는?", kind="check", expected=top_category(AUG),
         checks=[("rank_items", lambda r, e: ok_if(r.get("table") is not None and "카테고리" in r["table"]
                                                    and r["table"]["카테고리"].iloc[0] == e["1위"], "1위 카테고리 불일치"))],
         params=("rank_items", d(AUG) | {"target": "category"})),
    dict(id="H05", period=AUG, level="L1", q="지난달 주문 한 건당 평균 얼마 썼어?", kind="check", expected=kpi(AUG, "aov"),
         checks=[("get_kpis", c_won("aov"))], params=("get_kpis", d(AUG))),
    dict(id="H06", period=JUN_AUG, level="L1", q="6월부터 8월까지 매출 합계는?", kind="check", expected=kpi(JUN_AUG, "revenue"),
         checks=[("get_kpis", c_won("revenue")), ("get_trend", c_trend_sum("revenue"))], params=("get_kpis", d(JUN_AUG))),
    dict(id="H07", period=AUG, level="L1", q="8월 쿠폰 효율 어땠어?", kind="check", expected=coupon_eff(AUG),
         checks=[("get_coupon_efficiency", lambda r, e: ok_if(has(r, f"{e['효율']:.1f}배"), "쿠폰 효율 불일치"))],
         params=("get_coupon_efficiency", d(AUG))),
    dict(id="H08", period=SEP, level="L1", q="이번 달 주문 중에 취소되거나 환불된 비율은?", kind="check", expected=kpi(SEP, "cancel_refund_rate"),
         checks=[("get_kpis", c_pct("cancel_refund_rate"))], params=("get_kpis", d(SEP))),
    # L2: 같은 도구의 다른 쓰임
    dict(id="H09", period=AUG, level="L2", q="8월에 구매 전환이 제일 잘 된 큐레이션 테마는?", kind="check", expected=best_theme(AUG),
         checks=[("get_themes", lambda r, e: ok_if(has(r, f"구매 전환율 1위: {e['1위']}"), "1위 테마 불일치"))],
         params=("get_themes", d(AUG))),
    dict(id="H10", period=JUL, level="L2", q="7월에는 구매 과정 중 어디서 제일 많이 이탈했어?", kind="check", expected=worst_step(JUL),
         checks=[("get_funnel", lambda r, e: ok_if(has(r, e["구간"]), "이탈 구간 불일치"))], params=("get_funnel", d(JUL))),
    dict(id="H11", period=ALL, level="L2", q="주 단위로 매출 흐름 보여줘", kind="check", expected=weekly,
         checks=[("get_trend", lambda r, e: ok_if(r.get("table") is not None and list(r["table"]["매출"]) == e["매출"],
                                                  "주별 매출(전체 기간) 불일치"))],
         params=("get_trend", d(ALL) | {"grain": "week"})),
    dict(id="H12", period=SEP, level="L2", q="VIP 등급 고객은 어떤 카테고리를 많이 사?", kind="check", expected=pref_top(SEP, "grade_at_order"),
         checks=[("segment_preference", lambda r, e: ok_if(has(r, f"VIP: {e['1위']['VIP']}"), "VIP 1위 카테고리 불일치"))],
         params=("segment_preference", d(SEP) | {"by": "grade_at_order"})),
    dict(id="H13", level="L2", q="가입 경로에 따라 재구매율이 달라?", kind="check", expected=repeat_low("signup_channel"),
         checks=[("segment_repeat", lambda r, e: ok_if(has(r, f"가장 낮은 고객군: {e['가장 낮은 고객군']}"), "가입 경로별 결과 아님"))],
         params=("segment_repeat", {"by": "signup_channel"})),
    dict(id="H14", period=SEP, level="L2", q="처음 온 방문자와 다시 온 방문자가 사는 카테고리가 달라?", kind="check",
         expected=pref_top(SEP, "visitor_type"),
         checks=[("segment_preference", lambda r, e: ok_if(all(has(r, f"{g}: {c}") for g, c in e["1위"].items()
                                                               if g != "판정 불가"), "신규/재방문 1위 카테고리 불일치"))],
         params=("segment_preference", d(SEP) | {"by": "visitor_type"})),
    dict(id="H15", period=AUG, level="L2", q="8월 매출이 7월보다 늘어난 이유가 뭐야?", kind="check", expected=rev_change(AUG),
         checks=[("explain_revenue_change", lambda r, e: ok_if(has(r, T.won(abs(e["변화"])), "늘었습니다" if e["변화"] >= 0 else "줄었습니다"),
                                                               "8월 vs 7월 매출 분해 아님"))],
         params=("explain_revenue_change", d(AUG))),
    # L3: 탐색·진단
    dict(id="H16", period=AUG, level="L3", q="8월에 7월이랑 비교해서 눈에 띄게 달라진 게 있어?", kind="check", expected=changes(AUG),
         checks=[("detect_changes", lambda r, e: ok_if(r["title"] == f"확인할 변화 {e['개수']}개", "8월 기준 변화 탐지 아님")),
                 ("explain_revenue_change", lambda r, e: ok_if(r["period"].startswith("2026-08-01"), "8월 기준 아님"))],
         params=("detect_changes", d(AUG))),
    dict(id="H17", period=AUG, level="L3", q="8월 데이터로 보면 밀어줄 만한 상품이 뭐야?", kind="check", expected=potential(AUG),
         checks=[("find_potential_products", c_prefix("product_name", "후보"))], params=("find_potential_products", d(AUG))),
    dict(id="H18", level="L3", q="충성 고객은 몇 명이야?", kind="check", expected=rfm_count("충성"),
         checks=[("get_segments", lambda r, e: ok_if(has(r, f"충성: {e['고객수']:,}명"), "충성 고객 수 불일치"))],
         params=("get_segments", d(SEP))),
    dict(id="H19", period=THIS_WEEK, level="L3", q="이번 주 매출이 지난주보다 줄었어?", kind="check", expected=rev_change(THIS_WEEK),
         checks=[("get_kpis", lambda r, e: ok_if(has(r, T.won(e["매출"])) and r["period"].startswith("2026-09-24"), "이번 주 매출 아님")),
                 ("explain_revenue_change", lambda r, e: ok_if(has(r, T.won(abs(e["변화"]))), "이번 주 vs 지난주 아님"))],
         params=("explain_revenue_change", d(THIS_WEEK))),
    # L4: 제안
    dict(id="H20", period=SEP, level="L4", q="상품 클릭에서 장바구니로 가는 비율을 10% 올리는 실험을 하려면 표본이 얼마나 필요해?", kind="check",
         expected=sample(2, 0.10),
         checks=[("design_experiment", lambda r, e: ok_if(has(r, f"그룹당 필요 세션 {e['그룹당']:,}개"), "단계·개선폭 불일치"))],
         params=("design_experiment", d(SEP) | {"step": 2, "lift": 0.10})),
    dict(id="H21", level="L4", q="VIP 고객이 더 자주 사게 하려면 뭘 해볼까?", kind="tool",
         tools={"segment_repeat", "segment_preference", "get_segments", "get_retention"}),
    dict(id="H22", level="L4", q="큐레이션 테마를 개편한다면 어떤 테마부터 손봐야 해?", kind="tool", tools={"get_themes"}),
    # 미지원·범위 밖 (새 질문)
    dict(id="H23", level="범위 밖", q="인스타그램 광고 효율은 어때?", kind="refuse"),
    dict(id="H24", level="범위 밖", q="다음 달 매출 얼마나 나올 것 같아?", kind="refuse"),
    dict(id="H25", level="범위 밖", q="남성 고객이 많이 사는 상품은?", kind="refuse"),
    dict(id="H26", level="범위 밖", q="주말이랑 평일 중에 언제 더 많이 팔려?", kind="refuse"),
    dict(id="H27", level="범위 밖", q="상품 리뷰 평점이 제일 높은 건 뭐야?", kind="refuse"),
    dict(id="H28", level="범위 밖", q="우리 가격이 쿠팡보다 비싸?", kind="refuse"),
]

# 팀원이 적어 준 질문 (정답은 Claude가 계산해 추가). 예: dict(id="T01", level="L1", q="...", kind="check", ...)
TEAM: list[dict] = []

ALL_CASES = CASES + TEAM


def selfcheck(data_dir=None) -> int:
    """정답 도구를 올바른 기간으로 부르면 통과하는지(정답 계산·확인 함수 자체의 검사). python eval/holdout.py"""
    from core.data import build_all
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
        print(f"{'OK' if why is None else 'NG'}  {c['id']}  {tool:<24} {why or ''}")
        bad += why is not None
    print(f"\n{sum(c['kind'] == 'check' for c in ALL_CASES) - bad}/{sum(c['kind'] == 'check' for c in ALL_CASES)} 정답 계산 확인")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(selfcheck(sys.argv[1] if len(sys.argv) > 1 else None))

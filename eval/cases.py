"""AI 챗봇 평가셋: 실무자 질문 30선 + 데이터로 답할 수 없는 질문 6개.

각 질문에 대해
- period: 챗봇이 질문 속 기간 표현을 어떻게 해석해야 하는지 (아래 기간 규칙)
- tool: 챗봇이 불러야 할 도구(core/metrics.py 함수)
- expected(m): 정답을 계산하는 함수. 챗봇 답변의 숫자는 이 값과 같아야 한다
- check: 채점 방법

기간 규칙 (데이터 마지막 날 2026-09-30 기준, 챗봇 답변 첫 줄에 기준 기간을 밝힌다)
- 이번 달 = 2026-09,  지난달 = 2026-08,  비교 = 직전 같은 길이 기간
- 이번 주 = 최근 7일(9/24~9/30),  최근 2주 = 9/17~9/30
- 기간이 없으면 이번 달(9월) 기준, 추이 질문은 전체 관측 기간(4~9월)
"""
from __future__ import annotations

import pandas as pd

from core import metrics as M

P = pd.Timestamp
THIS_MONTH = (P("2026-09-01"), P("2026-10-01"))
LAST_MONTH = (P("2026-08-01"), P("2026-09-01"))
MONTH_BEFORE_LAST = (P("2026-07-01"), P("2026-08-01"))
THIS_WEEK = (P("2026-09-24"), P("2026-10-01"))
PREV_WEEK = (P("2026-09-17"), P("2026-09-24"))
LAST_2W = (P("2026-09-17"), P("2026-10-01"))
PREV_2W = (P("2026-09-03"), P("2026-09-17"))
ALL = (P("2026-04-01"), P("2026-10-01"))

# 채점 방법
EXACT = "숫자 일치: 정답값과 같은 숫자(표시 반올림 허용)를 말하고 기준 기간을 밝혀야 정답"
RANK = "순위 일치: 정답 순서대로 항목을 제시해야 정답(상위 항목 순서가 바뀌면 오답)"
FACTS = "근거 일치: 정답의 핵심 사실(항목·수치)을 포함하고 틀린 수치가 없어야 정답"
HYPO = "근거+가설 구분: 정답의 데이터 근거를 정확히 말하고, 원인·대책은 '가설'로 표시해야 정답. 데이터에 없는 원인을 단정하면 오답"
REFUSE = "범위 밖 처리: 데이터에 없다고 밝히고 대체 지표를 제시해야 정답. 숫자를 지어내면 오답"
PARTIAL = "부분 지원: 현재 도구로 답할 수 없음을 밝히고, 가능한 범위(대체 분석)를 안내해야 정답. 숫자를 지어내면 오답"


def _r(v, d=4):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return round(v, d) if isinstance(v, float) else v


def _rows(df: pd.DataFrame, cols: list[str], n: int | None = None) -> list[dict]:
    df = df[cols] if n is None else df[cols].head(n)
    return [{c: _r(r[c]) if not isinstance(r[c], str) else r[c] for c in cols} for _, r in df.iterrows()]


def _kpi(m, period, prev, key):
    k, kp = M.kpis(m, *period), M.kpis(m, *prev)
    return {key: _r(k[key]), f"비교 기간 {key}": _r(kp[key]), "변화율": _r(M.pct_change(k[key], kp[key]))}


# ---------------------------------------------------------------------------
# 정답 계산
# ---------------------------------------------------------------------------
def q07(m):
    t = M.theme_table(m, *THIS_MONTH)
    return {"구매 전환율 1위": t.sort_values("구매전환율", ascending=False)["테마"].iloc[0],
            "클릭률 1위": t.sort_values("클릭률", ascending=False)["테마"].iloc[0],
            "구매 전환율 순위": _rows(t.sort_values("구매전환율", ascending=False), ["테마", "구매전환율", "클릭률"], 3)}


def q08(m):
    ce = M.coupon_efficiency(m, *THIS_MONTH)
    by = ce["by_coupon"][ce["by_coupon"]["주문수"] >= 30]
    return {"쿠폰 효율(배)": _r(ce["total"]["efficiency"]), "쿠폰 할인액": _r(ce["total"]["discount"]),
            "쿠폰 주문 매출": _r(ce["total"]["coupon_sales"]),
            "효율 1위 쿠폰(30건 이상)": by["쿠폰"].iloc[0] if len(by) else None,
            "주의": "쿠폰 때문에 생긴 매출이 아니라 쿠폰을 쓴 주문의 매출임을 밝혀야 함"}


def q09(m):
    s = M.order_status_summary(m, *THIS_MONTH)
    return {"취소·환불 비율": _r(M.kpis(m, *THIS_MONTH)["cancel_refund_rate"]),
            "상태별": _rows(s, ["order_status", "주문수", "금액", "비율"])}


def q10(m):
    d = M.revenue_decomposition(m, THIS_MONTH, LAST_MONTH)
    return {k: _r(v) for k, v in d.items()}


def q13(m):
    s = M.in_period(m["sessions"], "start", *THIS_MONTH)
    f = M.funnel(s, "ALL")
    steps = f.iloc[1:-1]  # '구매 완료'는 이탈 단계가 아니라 주문 상태라 제외
    worst = steps.sort_values("직전 단계 대비 전환율").iloc[0]
    order = list(f["단계"])
    i = order.index(worst["단계"])
    return {"가장 많이 빠지는 구간": f"{order[i-1]} → {order[i]}", "구간 전환율": _r(worst["직전 단계 대비 전환율"]),
            "퍼널": _rows(f, ["단계", "세션 수", "직전 단계 대비 전환율"])}


def q14(m):
    s = M.in_period(m["sessions"], "start", *THIS_MONTH)
    c, b = s[s["path"].eq("CURATION")], s[s["path"].eq("BROWSE")]
    _, p = M.two_prop_test(c["has_purchase"].sum(), len(c), b["has_purchase"].sum(), len(b))
    return {"큐레이션 경유 세션 구매 전환율": _r(c["has_purchase"].mean()), "일반 탐색 세션 구매 전환율": _r(b["has_purchase"].mean()),
            "p값": _r(p, 6), "주의": "경로 차이는 고객 구성 차이일 수 있어 큐레이션 효과로 단정하면 안 됨"}


def q15(m):
    mix = M.segment_category_mix(m, *THIS_MONTH, by="customer_type")
    top = mix.sort_values("비중", ascending=False).groupby("customer_type").head(1)
    return {"고객 구분별 1위 카테고리": {r.customer_type: {"카테고리": r.category, "비중": _r(r.비중)} for r in top.itertuples()}}


def q18(m):
    g = M.repeat_gaps(m)
    rr = M.repeat_rates(m)
    r30 = rr[rr["기준"].eq("30일 재구매율")]
    w = (r30["재구매율"] * r30["대상 고객"]).sum() / r30["대상 고객"].sum()
    return {"재구매 간격 중앙값(일)": _r(g["median_days"], 1), "구매 고객당 완료 주문": _r(g["orders_per_buyer"], 2),
            "30일 재구매율(전체 가중)": _r(w)}


def q19(m):
    c = M.detect_changes(m, THIS_MONTH, LAST_MONTH, alpha=0.05)
    return {"탐지된 변화 수": len(c), "상위 변화": [{"변화": x["title"], "방향": x["direction"], "현재": _r(x["current"]),
                                            "비교": _r(x["previous"])} for x in c[:5]]}


def q20(m):
    d = M.revenue_decomposition(m, LAST_2W, PREV_2W)
    c = M.detect_changes(m, LAST_2W, PREV_2W, alpha=0.05)
    return {"매출 변화": _r(d["revenue_change"]), "주문 수 효과": _r(d["order_effect"]), "객단가 효과": _r(d["aov_effect"]),
            "실제로 하락했는가": bool(d["revenue_change"] < 0),
            "함께 달라진 지표": [x["title"] for x in c[:5]],
            "주의": "매출이 늘었다면 질문의 전제를 바로잡아야 함. 원인은 가설로만"}


def q21(m):
    p = M.product_potential(m, *THIS_MONTH, prev=LAST_MONTH)
    cand = p[p["구분"].eq("키울 후보")]
    return {"키울 후보 상위 5": _rows(cand, ["product_name", "category", "잠재력 점수", "상품매출", "장바구니율", "매출 증가율"], 5),
            "주의": "잠재력 점수는 규칙 기반 탐색 점수이며 미래 매출 예측이 아님"}


def q22(m):
    tt, mx, my = M.theme_quadrant(m, *THIS_MONTH)
    return {"관심↑ 구매↓ 테마": list(tt.loc[tt["구분"].eq("관심↑ 구매↓"), "테마"]),
            "클릭률 중앙값": _r(mx), "클릭 후 구매율 중앙값": _r(my)}


def q23(m):
    r = M.rising_products(m, THIS_MONTH, LAST_MONTH, n=5)
    return {"매출 증가율 상위 5(지난달 주문 10건 이상)": _rows(r, ["product_name", "category", "매출 증가율", "상품매출", "이전 상품매출"])}


def q24(m):
    s = M.rfm_summary(m, *THIS_MONTH).set_index("고객군")
    return {"휴면 추정 고객 수": _r(s.loc["휴면 추정", "고객수"]), "휴면 추정 고객 비중": _r(s.loc["휴면 추정", "고객 비중"]),
            "이탈 우려 고객 수": _r(s.loc["이탈 우려", "고객수"]), "주의": "규칙 분류이며 이탈 확률이 아님"}


def q27(m):
    tt, mx, my = M.theme_quadrant(m, *THIS_MONTH)
    r = tt.set_index("theme_id").loc["T002"]
    seg = M.theme_segments(m, "T002", *THIS_MONTH, by="visitor_type").set_index("visitor_type")
    return {"테마": r["테마"], "사분면": r["구분"], "클릭률": _r(r["클릭률"]), "클릭 후 구매율": _r(r["클릭후구매율"]),
            "구매 전환율": _r(r["구매전환율"]),
            "방문 유형별 구매 전환율": {k: _r(v) for k, v in seg["구매 전환율"].items()}}


def q28(m):
    sc = M.in_period(m["sessions"], "start", *THIS_MONTH)
    sp = M.in_period(m["sessions"], "start", *LAST_MONTH)
    n, d, r = M.step_rate(sc, "ALL", 3)
    g = M.step_breakdown(sc, sp, "ALL", 3, "visitor_type")
    return {"장바구니→구매 전환율": _r(r), "장바구니 세션": d,
            "방문 유형별": {k: {"분석 기간": _r(v["분석 기간"]), "비교 기간": _r(v["비교 기간"]), "p값": _r(v["p값"], 6)}
                         for k, v in g.iterrows() if k != "nan"}}


def q29(m):
    s = M.rfm_summary(m, *THIS_MONTH).set_index("고객군")
    return {"휴면 추정 고객 수": _r(s.loc["휴면 추정", "고객수"]), "경과일 중앙값": _r(s.loc["휴면 추정", "경과일중앙값"]),
            "분석 기간 매출": _r(s.loc["휴면 추정", "분석 기간 매출"])}


def q30(m):
    sc = M.in_period(m["sessions"], "start", *THIS_MONTH)
    n, d, p0 = M.step_rate(sc, "ALL", 3)
    per_group = M.sample_size_per_group(p0, 0.05)
    daily = d / (THIS_MONTH[1] - THIS_MONTH[0]).days
    return {"기준 전환율(장바구니→구매)": _r(p0), "목표": "상대 5% 개선, 유의수준 0.05, 검정력 0.8",
            "그룹당 필요 세션": per_group, "하루 장바구니 세션": _r(daily, 1),
            "필요 기간(일, 두 그룹)": _r(2 * per_group / daily, 1)}


# ---------------------------------------------------------------------------
# 질문 목록
# ---------------------------------------------------------------------------
CASES = [
    # L1 조회
    dict(id=1, level="L1", q="지난달 매출 얼마야?", period="2026-08 (비교 2026-07)", tool="get_kpis", check=EXACT,
         expected=lambda m: _kpi(m, LAST_MONTH, MONTH_BEFORE_LAST, "revenue")),
    dict(id=2, level="L1", q="이번 주 주문 몇 건이야?", period="9/24~9/30 (비교 9/17~9/23)", tool="get_kpis", check=EXACT,
         expected=lambda m: _kpi(m, THIS_WEEK, PREV_WEEK, "orders")),
    dict(id=3, level="L1", q="매출 제일 많이 나온 상품 TOP5는?", period="2026-09", tool="rank_items", check=RANK,
         expected=lambda m: {"TOP5": _rows(M.top_products(m, *THIS_MONTH, n=5), ["product_name", "category", "상품매출"])}),
    dict(id=4, level="L1", q="카테고리별 매출은 어떻게 나뉘어?", period="2026-09", tool="rank_items", check=RANK,
         expected=lambda m: {"카테고리별": _rows(M.category_sales(m, *THIS_MONTH), ["category", "net_sales", "비중"])}),
    dict(id=5, level="L1", q="객단가 얼마야?", period="2026-09 (비교 2026-08)", tool="get_kpis", check=EXACT,
         expected=lambda m: _kpi(m, THIS_MONTH, LAST_MONTH, "aov")),
    dict(id=6, level="L1", q="이번 달 산 사람 몇 명이야?", period="2026-09 (비교 2026-08)", tool="get_kpis", check=EXACT,
         expected=lambda m: _kpi(m, THIS_MONTH, LAST_MONTH, "buyers")),
    dict(id=7, level="L1", q="반응 제일 좋은 큐레이션 테마는?", period="2026-09", tool="get_themes",
         check=FACTS + ". '반응'의 기준(구매 전환율/클릭률)을 밝히고 그 기준의 1위를 말해야 함", expected=q07),
    dict(id=8, level="L1", q="쿠폰 할인해 준 만큼 매출이 나왔어?", period="2026-09", tool="get_kpis", check=FACTS, expected=q08),
    dict(id=9, level="L1", q="취소·환불은 얼마나 돼?", period="2026-09", tool="get_kpis", check=EXACT, expected=q09),
    # L2 비교·분석
    dict(id=10, level="L2", q="지난달보다 매출이 왜 이만큼 변했어?", period="2026-09 vs 2026-08", tool="explain_revenue_change",
         check=EXACT + ". 주문 수 효과와 객단가 효과로 나눠 말해야 함", expected=q10),
    dict(id=11, level="L2", q="월별 매출 추이 보여줘", period="2026-04~09", tool="get_trend", check=EXACT + ". 선 그래프",
         expected=lambda m: {"월별": _rows(M.sales_trend(m, *ALL, grain="month").assign(month=lambda d: d["month"].dt.strftime("%Y-%m")),
                                         ["month", "매출", "주문수"])}),
    dict(id=12, level="L2", q="첫 구매 고객이랑 기존 고객 중 누가 더 많이 사?", period="2026-09", tool="get_retention", check=FACTS,
         expected=lambda m: {"구성": _rows(M.customer_mix(m, *THIS_MONTH).reset_index(), ["customer_type", "고객수", "매출", "매출 비중"])}),
    dict(id=13, level="L2", q="고객이 어느 단계에서 제일 많이 빠져?", period="2026-09", tool="get_funnel", check=FACTS, expected=q13),
    dict(id=14, level="L2", q="큐레이션으로 들어온 고객이 일반 탐색보다 더 잘 사?", period="2026-09", tool="get_funnel",
         check=FACTS + ". 유의성(p값)과 '효과로 단정할 수 없음'을 함께 말해야 함", expected=q14),
    dict(id=15, level="L2", q="고객군마다 잘 팔리는 카테고리가 달라?", period="2026-09", tool="get_segments", check=FACTS, expected=q15),
    dict(id=16, level="L2", q="연령대나 성별, 지역에 따라 구매가 달라?", period="2026-09", tool="(미지원)", check=PARTIAL,
         expected=lambda m: {"상태": "연령·성별·지역 컬럼은 customer 테이블에 있으나 분석 도구에 아직 연결 안 됨",
                             "대체 안내": "방문 유형·첫 구매/기존·주문 당시 등급별 비교"}),
    dict(id=17, level="L2", q="무슨 요일, 몇 시에 주문이 많아?", period="2026-09", tool="(미지원)", check=PARTIAL,
         expected=lambda m: {"상태": "요일×시간대 주문 집계 도구 없음", "대체 안내": "테마·퍼널 구간을 평일/주말·시간대로 나눠 보기"}),
    dict(id=18, level="L2", q="첫 구매하고 다시 사기까지 얼마나 걸려?", period="전체 관측 기간", tool="get_retention", check=EXACT, expected=q18),
    # L3 탐색·진단
    dict(id=19, level="L3", q="요즘 눈에 띄게 변한 거 있어?", period="2026-09 vs 2026-08 (엄격 p<0.05)", tool="detect_changes",
         check=FACTS + ". 상위 변화를 '확인할 후보'로 제시", expected=q19),
    dict(id=20, level="L3", q="지난 2주 매출이 왜 떨어졌어?", period="9/17~9/30 vs 9/3~9/16", tool="explain_revenue_change + detect_changes",
         check=HYPO, expected=q20),
    dict(id=21, level="L3", q="지금 매출은 낮은데 키우면 될 상품은?", period="2026-09 (성장은 vs 2026-08)", tool="product_potential",
         check=FACTS + ". 점수가 예측이 아님을 밝혀야 함", expected=q21),
    dict(id=22, level="L3", q="관심은 많은데 구매로 안 이어지는 테마는?", period="2026-09", tool="get_themes", check=FACTS, expected=q22),
    dict(id=23, level="L3", q="요즘 뜨는 상품은?", period="2026-09 vs 2026-08", tool="product_potential", check=RANK, expected=q23),
    dict(id=24, level="L3", q="안 돌아오는 고객이 얼마나 돼?", period="기준일 2026-09-30", tool="get_segments", check=EXACT, expected=q24),
    dict(id=25, level="L3", q="재구매가 특히 안 되는 고객군은?", period="-", tool="(미지원)", check=PARTIAL,
         expected=lambda m: {"상태": "고객군별 30일 재구매율 도구 없음",
                             "대체 안내": "RFM 고객군 규모·매출 비중, 첫 구매/기존 고객 재구매율"}),
    dict(id=26, level="L3", q="같이 많이 사는 상품 조합은?", period="-", tool="(미지원)", check=PARTIAL,
         expected=lambda m: {"상태": "동시 구매(장바구니 분석) 도구 없음", "대체 안내": "테마 편성 상품별 성과"}),
    # L4 제안
    dict(id=27, level="L4", q="T002 테마 구매 전환을 높이려면 뭘 해봐야 해?", period="2026-09", tool="get_themes + plan_experiment",
         check=HYPO + ". Growth Lab 저장을 제안", expected=q27),
    dict(id=28, level="L4", q="장바구니에서 구매로 더 넘어가게 하려면?", period="2026-09 vs 2026-08", tool="get_funnel + plan_experiment",
         check=HYPO, expected=q28),
    dict(id=29, level="L4", q="휴면 고객 다시 사게 하려면?", period="기준일 2026-09-30", tool="get_segments + plan_experiment",
         check=HYPO, expected=q29),
    dict(id=30, level="L4", q="장바구니→구매 전환율을 5% 올리는 실험, 몇 명한테 며칠 돌려야 해?", period="2026-09 기준 전환율",
         tool="plan_experiment", check=EXACT, expected=q30),
]

OUT_OF_SCOPE = [
    dict(id="X1", q="광고 효과(ROAS)는 어때?", missing="광고비·광고 유입", alternative="쿠폰 효율(8번), 가입 채널은 광고 유입과 다르다고 명시"),
    dict(id="X2", q="결제 페이지에서 얼마나 이탈해?", missing="결제 진입 이벤트", alternative="장바구니 → 구매 전환율"),
    dict(id="X3", q="상세페이지 오래 보는 상품이 잘 팔려?", missing="체류 시간", alternative="클릭 후 구매율"),
    dict(id="X4", q="경쟁사보다 우리가 비싸서 안 팔려?", missing="경쟁사 가격", alternative="가설로만 제시, Growth Lab 확인 항목으로 저장"),
    dict(id="X5", q="비회원 방문자는 어때?", missing="비로그인 세션", alternative="로그인 고객 기준임을 명시"),
    dict(id="X6", q="다음 달 매출 얼마 나올까?", missing="예측 모델", alternative="최근 추이와 '예측 아님' 표시"),
]

"""도구-정답 일치 검사: 챗봇이 올바른 도구를 올바른 기간으로 부르면 평가셋 정답과 같은 숫자가 나오는지 확인한다.

dashboard 폴더에서:  python eval/check_tools.py
도구(core/tools.py)나 계산(core/metrics.py)을 바꾼 뒤 실행한다. 하나라도 어긋나면 종료 코드 1.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core import tools as T  # noqa: E402
from core.data import build_all  # noqa: E402
from eval.cases import CASES  # noqa: E402

SEP, AUG = dict(start="2026-09-01", end="2026-10-01"), dict(start="2026-08-01", end="2026-09-01")


def has(facts, *needles):
    text = " ".join(facts)
    return all(n in text for n in needles)


# 질문 번호 → (도구, 입력값, 확인 함수(결과, 정답) → 불일치 설명 또는 None)
CHECKS = {
    1: ("get_kpis", AUG, lambda r, e: None if has(r["facts"], T.won(e["revenue"]), f"{e['변화율']*100:+.1f}%") else "매출·변화율"),
    2: ("get_kpis", dict(start="2026-09-24", end="2026-10-01"),
        lambda r, e: None if has(r["facts"], f"{e['orders']:,}건", f"{e['변화율']*100:+.1f}%") else "주문 수·변화율"),
    3: ("rank_items", SEP | dict(target="product", n=5),
        lambda r, e: None if list(r["table"]["상품"]) == [x["product_name"] for x in e["TOP5"]] else "TOP5 순서"),
    4: ("rank_items", SEP | dict(target="category"),
        lambda r, e: None if list(r["table"]["카테고리"]) == [x["category"] for x in e["카테고리별"]] else "카테고리 순서"),
    5: ("get_kpis", SEP, lambda r, e: None if has(r["facts"], T.won(e["aov"])) else "객단가"),
    6: ("get_kpis", SEP, lambda r, e: None if has(r["facts"], f"{e['buyers']:,}명") else "구매 고객 수"),
    7: ("get_themes", SEP, lambda r, e: None if has(r["facts"], e["구매 전환율 1위"], e["클릭률 1위"]) else "1위 테마"),
    8: ("get_coupon_efficiency", SEP,
        lambda r, e: None if has(r["facts"], f"{e['쿠폰 효율(배)']:.1f}배", e["효율 1위 쿠폰(30건 이상)"]) else "쿠폰 효율"),
    9: ("get_kpis", SEP, lambda r, e: None if has(r["facts"], T.pct(e["취소·환불 비율"])) else "취소·환불 비율"),
    10: ("explain_revenue_change", SEP,
         lambda r, e: None if has(r["facts"], T.won(abs(e["revenue_change"])), T.won(e["order_effect"]), T.won(e["aov_effect"]))
         else "매출 분해"),
    11: ("get_trend", dict(start="2026-04-01", end="2026-10-01", grain="month"),
         lambda r, e: None if list(r["table"]["매출"]) == [x["매출"] for x in e["월별"]] else "월별 매출"),
    13: ("get_funnel", SEP, lambda r, e: None if has(r["facts"], e["가장 많이 빠지는 구간"]) else "이탈 구간"),
    14: ("get_funnel", SEP, lambda r, e: None if has(r["facts"], T.pct(e["큐레이션 경유 세션 구매 전환율"]),
                                                    T.pct(e["일반 탐색 세션 구매 전환율"])) else "경로별 전환율"),
    15: ("segment_preference", SEP | dict(by="customer_type"),
         lambda r, e: None if has(r["facts"], *[v["카테고리"] for v in e["고객 구분별 1위 카테고리"].values()]) else "고객군별 1위 카테고리"),
    18: ("get_retention", SEP, lambda r, e: None if has(r["facts"], f"{e['재구매 간격 중앙값(일)']:.0f}일") else "재구매 간격"),
    19: ("detect_changes", SEP, lambda r, e: None if r["title"] == f"확인할 변화 {e['탐지된 변화 수']}개"
         and has(r["facts"], *[x["변화"] for x in e["상위 변화"][:3]]) else "탐지 결과"),
    20: ("explain_revenue_change", dict(start="2026-09-17", end="2026-10-01"),
         lambda r, e: None if has(r["facts"], T.won(abs(e["매출 변화"])), "늘었습니다" if e["매출 변화"] >= 0 else "줄었습니다")
         else "2주 매출 변화"),
    21: ("find_potential_products", SEP,
         lambda r, e: None if list(r["table"]["product_name"]) == [x["product_name"] for x in e["키울 후보 상위 5"]] else "키울 후보"),
    22: ("get_themes", SEP, lambda r, e: None if has(r["facts"], ", ".join(e["관심↑ 구매↓ 테마"])) else "관심↑ 구매↓ 테마"),
    23: ("find_potential_products", SEP,
         lambda r, e: None if has(r["facts"], *[x["product_name"] for x in e["매출 증가율 상위 5(지난달 주문 10건 이상)"][:3]])
         else "뜨는 상품"),
    25: ("segment_repeat", dict(by="customer_type"),
         lambda r, e: None if any(has(r["facts"], f"가장 낮은 고객군: {v['가장 낮은 고객군']}") for v in e["기준별"].values())
         else "가장 낮은 고객군"),
    24: ("get_segments", SEP, lambda r, e: None if has(r["facts"], f"휴면 추정 고객 {e['휴면 추정 고객 수']:,}명") else "휴면 고객 수"),
}


def main(data_dir=None) -> int:
    m = build_all(data_dir)
    exp = {c["id"]: c["expected"](m) for c in CASES}
    bad = 0
    for qid, (tool, params, fn) in CHECKS.items():
        try:
            r = T.run(m, tool, **params)
            why = fn(r, exp[qid])
        except Exception as ex:  # noqa: BLE001
            why = f"오류 {ex!r}"
        print(f"{'OK ' if why is None else 'NG '} #{qid:<3} {tool:<24} {'' if why is None else why}")
        bad += why is not None
    print(f"\n{len(CHECKS) - bad}/{len(CHECKS)} 질문에서 도구 결과 = 정답")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

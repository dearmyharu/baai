"""AI 분석가 ↔ Growth Lab 연결 (streamlit 없음, 시험 가능).

1) 챗봇 → Growth Lab: planner_state(lab_request, cats)
   chat_panel이 넘긴 type=plan 요청(flow.Flow.lab_request)을 Growth Lab 입력칸 값(session_state 키)으로 바꾼다.
2) Growth Lab → 챗봇: context_card(growth_context)
   Growth Lab 화면이 남긴 growth_context를 답변 카드 한 장으로 만든다. AI를 부르지 않고, 숫자·문장은 이 코드가 만든다.
"""
from __future__ import annotations

from . import answer as A
from . import fmt as F

SHIP_MAX = 30000          # Growth Lab 무료배송 기준 입력칸 최대값(현재 기준 3만원)
LEVER_NAME = {"price": "판매가 할인", "discount": "할인 쿠폰", "shipping": "무료배송 기준 변경"}


def planner_state(request: dict, cats: list[str]) -> tuple[dict, list[str]]:
    """lab_request(type=plan) → ({session_state 키: 값}, 안내 문장들).

    Growth Lab이 지원하지 않는 대상·수단은 넣지 않고 안내만 남긴다.
    """
    state: dict = {"gl_screen": "새 프로모션 분석"}
    notes: list[str] = []
    target = (request or {}).get("target") or {}
    if target.get("type") == "category" and target.get("value") in cats:
        state["gl_cat"] = target["value"]
    elif target:
        notes.append(f"대상 '{target.get('value')}'은(는) Growth Lab 카테고리 목록에 없어 직접 선택해야 합니다.")
    lever = (request or {}).get("lever") or {}
    policy, value = lever.get("policy"), lever.get("value")
    if policy == "price" and value is not None:
        state["gl_policy"] = "price"
        state["gl_price_pct"] = float(abs(value))             # 요청은 내리면 음수(%), 입력칸은 할인율(양수)
    elif policy == "discount" and value is not None:
        state["gl_policy"] = "discount"
        state["gl_coupon_mode"] = "할인율 (%)"
        state["gl_coupon_pct"] = float(value)
    elif policy == "shipping" and value is not None:
        state["gl_policy"] = "shipping"
        state["gl_ship_threshold"] = int(min(max(value, 0), SHIP_MAX))
    elif policy:
        notes.append(f"수단 '{policy}'은(는) Growth Lab에서 지원하지 않아 직접 선택해야 합니다.")
    return state, notes


def request_text(state: dict) -> str:
    """넘겨받은 조건 한 줄 (Growth Lab 화면 안내용)."""
    parts = []
    if "gl_cat" in state:
        parts.append(f"{state['gl_cat']} 카테고리")
    p = state.get("gl_policy")
    if p == "price":
        parts.append(f"판매가 {state['gl_price_pct']:g}% 할인")
    elif p == "discount":
        parts.append(f"할인 쿠폰 {state['gl_coupon_pct']:g}%")
    elif p == "shipping":
        parts.append(f"무료배송 {state['gl_ship_threshold']:,}원 이상")
    return " · ".join(parts)


def _pct(v) -> str:
    return "–" if v is None else f"{v:.1%}"


def context_card(ctx: dict | None) -> A.Card:
    """growth_context → 답변 카드. 값이 없으면 안내 카드."""
    if not ctx:
        return A.message("Growth Lab에서 '프로모션 분석하기'를 실행하면 그 결과를 여기서 요약합니다.", ["Growth Lab"])
    screen = ctx.get("화면", "")
    cat = ctx.get("카테고리", "")
    tags = ["Growth Lab"] + ([f"{cat} 카테고리"] if cat else [])
    if screen == "Growth Lab 프로모션 결과":
        return A.Card(tags, f"{ctx.get('프로모션', '')}의 아침 브리핑 판정은 '{ctx.get('판정', '')}'입니다.", [],
                      "관측 전후 비교이며 무작위 실험에 의한 인과 검증이 아닙니다.")
    promo = ctx.get("프로모션", "")
    req = ctx.get("본전 주문 증가율")
    if req is None:
        concl = f"{promo}을(를) 적용하면 주문 수가 같을 때 이익이 0 이하가 되어 본전 주문 증가율을 계산할 수 없습니다."
    elif req <= 0:
        concl = f"{promo}은(는) 주문이 늘지 않아도 최근 28일 기준 이익이 줄지 않는 조건입니다."
    else:
        concl = f"{promo}의 할인 비용을 메우려면 주문이 {req:.1%} 더 늘어야 합니다."
    days = ctx.get("운영 일수")
    nums = [A.Number("본전 주문 증가율", _pct(None if req is None else max(req, 0.0))),
            A.Number(f"예상 매출 중앙값({days}일)" if days else "예상 매출 중앙값", F.won(ctx.get("예상 매출 중앙값"))),
            A.Number("예상 이익률 중앙값", _pct(ctx.get("예상 이익률 중앙값")))]
    lo, mode, hi = (ctx.get("주문 반응 가정") or (None, None, None))[:3]
    note = (f"주문 반응은 가정값입니다(최소 {lo:+.0%} · 최빈 {mode:+.0%} · 최대 {hi:+.0%}, 예측 아님). "
            if lo is not None else "주문 반응은 가정값입니다(예측 아님). ")
    note += f"손익 기준 {ctx.get('손익 기준', '최근 28일')}, 기타 비용 제외."
    return A.Card(tags, concl, nums, note)

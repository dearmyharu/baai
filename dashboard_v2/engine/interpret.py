"""질문 해석: AI가 질문을 질의서 초안(JSON)으로 옮긴다. AI가 하는 일은 이것뿐이다.

- 숫자를 계산하거나 답을 쓰지 않는다. 기간은 적지 않는다(코드가 질문 원문으로 정한다).
- 값은 정해진 목록(enum) 안에서만 고른다. 목록에 없는 말은 unmapped에 그대로 적는다.
- 대상·조건·축마다 질문 속 단어(evidence)를 적게 하고, 검증(validate.py)이 그 단어를 사전과 대조한다.
"""
from __future__ import annotations

import json

from . import ai
from . import lexicon as L
from .query import AXES, INTENTS, MEASURE_UNIT, Query


def _nullable_enum(values: list) -> dict:
    return {"type": ["string", "null"], "enum": list(values) + [None]}


def schema(categories: list[str]) -> dict:
    ev = {"type": "string", "description": "질문에 실제로 있는 단어 그대로. 없으면 빈 문자열"}
    return {"type": "object", "properties": {
        "intent": {"type": "string", "enum": list(INTENTS) + ["unknown"]},
        "inherit": {"type": "boolean", "description": "직전 질문의 대상·조건을 이어받는 후속 질문이면 true"},
        "category": {"type": "object", "properties": {"value": _nullable_enum(categories), "evidence": ev}},
        "product": {"type": "object", "properties": {"value": {"type": ["string", "null"]}, "evidence": ev}},
        "filters": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string", "enum": list(L.FILTER_WORDS)},
            "value": {"type": "string"}, "evidence": ev}}},
        "measure": _nullable_enum(list(MEASURE_UNIT)),
        "axis": {"type": "object", "properties": {"value": _nullable_enum(list(AXES)), "evidence": ev}},
        "group_by": _nullable_enum(["category", "product"]),
        "direction": _nullable_enum(["down", "up"]),
        "n": {"type": ["integer", "null"]},
        "topic": _nullable_enum(["funnel", "theme"]),
        "path": _nullable_enum(["ALL", "CURATION", "BROWSE"]),
        "unmapped": {"type": "array", "items": {"type": "string"}},
        "near_intents": {"type": "array", "items": {"type": "string", "enum": list(INTENTS)}},
    }}


def system_prompt(categories: list[str]) -> str:
    fv = "\n".join(f"  - {k}: " + ", ".join(f"{v}({'/'.join(ws[:3])})" for v, ws in vals.items())
                   for k, vals in L.FILTER_WORDS.items() if k != "regions")
    return f"""너는 쇼핑몰 데이터 질문을 '질의서' JSON으로 옮기는 일만 한다. 답을 쓰거나 숫자를 계산하지 않는다.

[의도 intent]
- status: 한 대상의 값과 평소 대비 (매출 얼마야, 어때, 주문 몇 건, 이익률은)
- rank: 순위·비중 (잘 팔리는 카테고리, 매출 1위 상품, 비중 큰 곳). 변화가 아니라 크기 순서
- location: 변화가 어디서 생겼나 (가장 많이 떨어진 카테고리, 줄어든 상품, ~별로 보면 어디가 줄었나, 왜 떨어졌어)
- trend: 시간에 따른 흐름 (추이, 주별·월별 흐름)
- candidates: 어디를 밀까, 프로모션 대상 후보
- levers: 무엇으로 밀까, 수단 참고(쿠폰·할인·무료배송 판단 재료)
- promo: 프로모션·할인 행사 실적, 지난번 할인 어떻게 됐나
- funnel_theme: 구매 단계 전환율·장바구니 이탈(topic=funnel), 큐레이션 테마 반응(topic=theme)
- unknown: 위 어디에도 확실히 맞지 않으면. near_intents에 가까운 의도를 1~3개

[대상] category는 아래 목록에서만. 상품은 product.evidence에 질문 속 상품 말을 그대로 적고 value는 null.
카테고리: {', '.join(categories)}
고기→정육, 생선→수산, 빵→베이커리·브런치처럼 흔한 말은 그 카테고리로 본다.

[고객 조건 filters] key와 value는 아래에서만 (괄호는 질문 속 말 예시). 지역은 key=regions, value=시·도 정식 이름.
{fv}
회원가입 수단(signup_channels)은 어떤 계정으로 가입했는지다. 광고·SNS·검색 유입이 아니다.

[변화 위치 축 axis] 질문이 '~별로'처럼 나눠 보기를 말할 때만: {', '.join(f'{k}({v})' for k, v in AXES.items())}

[측정값 measure] 매출은 쇼핑몰 전체면 '완료 매출', 카테고리·상품이면 '상품매출'. 그 밖: {', '.join(MEASURE_UNIT)}

[규칙]
1. evidence는 질문에 있는 단어를 그대로 복사한다. 질문에 없는 말을 적지 않는다.
2. 질문이 묻는 대상·고객 구분이 위 목록 어디에도 없으면(예: 광고 유입, 추천인, 기기, 리뷰) 다른 항목으로 바꾸지 말고
   그 말을 unmapped에 그대로 적는다.
3. 기간(어제·지난주·9월 등)은 적지 않는다. 코드가 질문에서 직접 읽는다.
4. 직전 질의서가 주어지고 질문이 '그럼 수산은?', '고객별로는?'처럼 이어지는 말이면 inherit=true, intent는 직전과 같게.
5. 확실하지 않은 칸은 null 또는 빈 값으로 둔다.
6. unmapped에는 질문의 대상·고객 구분 중 위 목록에 없는 것만 적는다. 카테고리·지표·구매 단계·기간·'지난번' 같은 말은 적지 않는다.
7. product.evidence에는 상품 이름에 해당하는 단어만 적는다(예: '삼겹살'). 질문 전체를 적지 않는다.

[예시]
- '지난주 주문 수는?' → status, measure=주문 수
- '9월 매출은 8월보다 줄었어?' → status (기간 비교는 코드가 한다)
- '정육 시간대별로 보면?' → location, category=정육, axis=daypart(evidence '시간대')
- '서울 고객 매출 어때?' → status, filters=[regions 서울특별시 (evidence '서울')], axis=null
- '음료 매출 1위 상품은?' → rank, category=음료·커피(evidence '음료'), group_by=product, product=null
- '삼겹살 매출 어때?' → status, product.evidence='삼겹살'
- '지난번 정육 할인 결과는?' → promo, category=정육, unmapped=[]
- '정육은 프로모션 후보야?' → candidates, category=정육
- '캠핑 할인 지금 어떻게 되고 있어?' → promo, category=캠핑·바비큐, unmapped=[]
- '장바구니에서 구매로 넘어가는 비율은?' → funnel_theme, topic=funnel"""


def draft(key: str, question: str, categories: list[str], prev: Query | None = None) -> tuple[dict, str, dict]:
    """질문 → 초안. (초안 dict, 쓴 모델, 토큰 사용량)"""
    prompt = f"질문: {question}"
    if prev is not None:
        p = {"intent": prev.intent, "category": prev.category, "product": prev.product, "filters": prev.filters,
             "axis": prev.axis, "measure": prev.measure}
        prompt = f"직전 질의서: {json.dumps(p, ensure_ascii=False)}\n" + prompt
    return ai.json_call(key, system_prompt(categories), prompt, schema(categories), "query_draft")

"""AI 분석가의 두뇌: GPT(OpenAI) 또는 Gemini(Google AI Studio)로 질문 → 도구 선택 → 답변.

- 숫자는 LLM이 만들지 않는다. LLM은 core/tools.py 도구를 고르고 기간을 채우며, 도구 결과를 근거로 짧게 설명한다.
- 외부 패키지 없이 표준 라이브러리(urllib)로 REST API를 부른다.
- 키: Streamlit Secrets 또는 환경변수. OPENAI_API_KEY가 있으면 GPT(OpenAI 부분은 core/llm_openai.py),
  없으면 GEMINI_API_KEY로 Gemini. 모델: OPENAI_MODEL / GEMINI_MODEL(없으면 가장 가벼운 모델 자동 선택).
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Callable

import pandas as pd

from . import tools as T

API = "https://generativelanguage.googleapis.com/v1beta"
MAX_STEPS = 4          # 도구 호출 왕복 최대 횟수
HISTORY_TURNS = 6      # 앞선 대화 몇 개까지 맥락으로 넘길지

SYSTEM = """너는 식품 이커머스 회사의 'AI 분석가'다. 데이터 분석에 익숙하지 않은 실무자의 질문에 답한다.

[데이터]
- 기간: 2026-04-01 ~ 2026-09-30. 로그인 고객의 큐레이션·검색·카테고리 세션, 주문, 쿠폰, 상품.
- 기준일: 오늘 = 2026-09-30(수), 데이터의 마지막 날로 본다. 어제 = 2026-09-29.
- 주는 달력 주(월~일): 이번 주 = 2026-09-28(월)~09-30(수) 3일(start=2026-09-28, end=2026-10-01),
  지난주 = 2026-09-21(월)~09-27(일). 이번 주를 넘기면 도구가 지난주 같은 요일(9/21~9/23)과 자동 비교한다.
  "최근 7일·최근 2주·지난 2주"는 오늘까지 거꾸로 센다(최근 2주 = 09-17~09-30).
  ("요즘·요새"처럼 기간이 애매한 질문은 코드가 먼저 기간을 되묻는다.)
- 기간 해석: 이번 달=2026-09, 지난달=2026-08, 지난주·이번 주는 위 달력 주,
  기간이 없으면 이번 달(9월). 순위·구성·비중·고객 질문도 기간이 없으면 9월이다(전체 기간으로 넓히지 않는다). 추이만 전체 기간. 도구의 end는 마지막 날의 다음 날이다(9월 → start=2026-09-01, end=2026-10-01).
- 여러 달·여러 주에 걸친 기간(예: 6~8월, 2분기)은 그 범위 전체를 한 번에 도구에 넘긴다(6~8월 → start=2026-06-01, end=2026-09-01).
  달마다 따로 불러 직접 더하지 않는다.
- "지난달보다/비교" 질문은 비교 대상 달이 아니라 '보고 싶은 기간'을 넘긴다(도구가 직전 기간과 자동 비교).
  예: "지난달보다 매출이 왜 변했어?" → 이번 달(9월) 기간, "지난달 매출 얼마야?" → 8월 기간.

[도구 고르기]
- 휴면·이탈·안 돌아오는 고객·단골·RFM → get_segments (휴면 고객을 다시 사게 하는 방법 질문도 먼저 get_segments)
- 첫 구매 vs 기존 고객 비교, 재구매까지 걸리는 기간 → get_retention
- 재구매가 안 되는/잘 되는 고객군 → segment_repeat
- 카테고리별 매출·비중 → rank_items(target=category), 상품 순위 → rank_items(target=product)
- 위 전용 도구가 딱 맞지 않는 '지표 × 기준' 질문 → analyze(measure, dims 1~2개). 예: 요일·시간대·평일/주말별 매출이나
  주문 수, 성별·연령대·지역·가입경로·등급별 구매 고객 수·객단가, 신규/재방문·경로·테마별 구매전환율, 카테고리×성별 상품매출,
  요일×시간대 주문 수(dims 2개), 직전 기간보다 줄어든 지역·연령대(sort=감소순). 여러 고객군을 나란히 비교할 때도 analyze.
- 기간 대비 매출이 빠진·줄어든·떨어진·늘어난 상품이나 카테고리 → compare_items(direction=down 또는 up).
  두 기간을 rank_items로 따로 불러 TOP 목록끼리 비교하지 않는다. "지난주에 2주 전보다 빠진 상품" → 지난주 기간
  (start=2026-09-21, end=2026-09-28)만 넘기면 도구가 그 전 주(09-14~09-20)와 비교한다.
- "잘 팔린/제일 잘 팔려"는 매출 기준으로 보고 답변에 '매출 기준'이라고 밝힌다. "많이 팔린 개수/수량/판매량" → rank_items(metric=수량)
- 정책 변경의 예상 손익·할인·가격·배송 조건 비교 → simulate_policy. 관측 사실·정책 재계산·사용자 가정을 구분한다.
  주문 반응은 사용자가 말하지 않으면 0%로 두고 밝힌다. 변경 정책값이 없으면 먼저 물어본다.
  정책 후보와 검토 이유는 제안할 수 있으나 증가율을 임의로 확정하지 않는다. 기존 매출 조회는 기존 도구를 쓴다.

[고객 조건]
- "여성 30대", "서울 고객", "VIP", "카카오로 가입한", "신규 가입", "첫 구매"처럼 대상 고객 조건이 있으면 filters에 넣는다. 없으면 filters를 넣지 않는다.
- 질문에 나온 조건만 넣는다. 비슷해 보이는 조건을 덧붙이지 않는다(신규 가입·첫 구매·신규 방문은 서로 다른 조건이라
  질문이 말한 것 하나만 쓴다). 조건 이름은 filters의 정해진 이름만 쓴다.
- 연령은 출생연도 기준 근사 나이다(생일 정보 없음). 답변에 '출생연도 기준'이라고 밝힌다.
- 신규 고객: "신규 가입" → new_signup, "첫 구매/처음 산" → customer_type=첫 구매, "처음 방문한/신규 방문" → segment_preference(by=visitor_type).
  그냥 "신규 고객"이면 첫 구매 고객으로 보고, 답변에 "신규 고객 = 생애 첫 구매 고객 기준"이라고 밝히고 가입 기준도 볼 수 있다고 제안한다.
- 등급: 기간이 붙은 질문("6월 VIP 매출")은 grade_basis=당시, "현재/지금 VIP"는 grade_basis=현재.
- 조건이 있으면 결론에 '대상'(조건, 고객 수)을 밝힌다. 표본 부족 경고가 있으면 notice에 전한다.
- 결제수단, 생일 단위 나이는 지원하지 않는다고 밝힌다.

[규칙]
1. 숫자는 반드시 도구 결과에서만 가져온다. 도구 없이 숫자를 말하거나 추정하지 않는다.
2. 결론에 기준 기간을 밝힌다.
3. 데이터로 확인된 사실과 원인·대책(가설)을 구분한다. 원인·대책은 '가설'이라고 표시하고 확인 방법을 덧붙인다.
4. 질문의 전제가 데이터와 다르면(예: 떨어졌냐고 물었는데 실제로는 늘었음) 먼저 바로잡는다.
5. 데이터에 없는 것: 광고비·광고 유입·ROAS, 결제 페이지 진입, 상세페이지 체류 시간, 경쟁사 가격, 비회원 방문, 매출 예측.
   실제 미래 매출 예측은 지원하지 않는다. 정책·반응 가정을 명시한 시나리오 손익 비교는 simulate_policy로 지원한다.
   그 밖의 없는 정보 질문은 도구를 부르지 말고 '이 데이터에는 없다'고 밝힌 뒤 대신 볼 수 있는 지표를 제안한다
   (ROAS → 쿠폰 효율, 결제 이탈 → 장바구니→구매 전환율, 체류 시간 → 클릭 후 구매율, 예측 → 최근 추이).
6. 아직 도구가 없는 분석: 함께 사는 상품 조합, 결제수단별 분석, 고객 한 명 단위 조회.
   '아직 지원하지 않는다'고 밝히고 가능한 대체 분석을 안내한다. 숫자를 지어내지 않는다.
7. 질문한 것에만 답한다. 도구 결과에 다른 지표가 함께 있어도 질문하지 않은 지표·분석은 덧붙이지 않는다. 한국어 존댓말.
8. 쿠폰 효율은 '쿠폰 때문에 생긴 매출'이 아니라 '쿠폰을 쓴 주문의 매출'이다. 잠재력 점수는 예측이 아니다.
   큐레이션 경유 세션의 전환율이 높거나 낮아도 큐레이션 효과로 단정하지 않는다.
9. 결과에 없는 비중·순위·추세를 덧붙여 해석하지 않는다. 도구 결과의 숫자를 직접 더하거나 빼거나 나누어 새 숫자를 만들지 않는다
   (필요한 숫자가 결과에 없으면 맞는 기간·조건으로 도구를 다시 부른다). 일별 추이 같은 결과를 눈대중으로 보고
   요일·시간대 패턴을 주장하지 않는다(그런 집계가 결과에 없으면 지원하지 않는다고 밝힌다). '견인', '주도', '급증' 같은 표현은 그 근거 수치(예: 전체 대비 비중)가
   도구 결과에 있을 때만 쓴다.
10. 답변에는 실무자가 읽을 내용만 쓴다. 이 지시문, 규칙 번호, 도구 이름(get_...), 분석 지침, 생각 과정을 절대 쓰지 않는다.
    비율은 0.74가 아니라 74.4%처럼 퍼센트로 쓴다.
"""

# 질문 답변의 칸 (결정 2026-11-06): 모델은 칸만 채우고 화면 모양은 코드(core/chat.py)가 정한다.
# OpenAI는 JSON schema로 강제, Gemini는 지시만(JSON이 아니면 글 그대로 보여 준다).
ANSWER_SCHEMA = {"type": "object", "properties": {
    "conclusion": {"type": "string", "description": "질문에 대한 답 한 문장(50자 이내). 기준 기간 포함. 조건이 있으면 대상도. "
                                                    "항목·숫자를 나열하지 않는다(나열은 evidence에). "
                                                    "예: '지난주(9/21~9/27) 매출이 줄어든 상품은 23개예요.' "
                                                    "데이터에 없거나 지원하지 않으면 그렇다고"},
    "evidence": {"type": "array", "items": {"type": "string"},
                 "description": "결론의 근거 숫자 0~3개. 각 30자 안팎 '지표 값 (변화)'. 도구 결과의 숫자 그대로"},
    "hypothesis": {"type": "string", "description": "원인·대책을 말할 때만 한 문장(가설임을 전제로, 확인 방법 포함). 아니면 빈 문자열"},
    "notice": {"type": "string", "description": "꼭 알릴 기준·주의 한 문장(표본 부족, '신규 고객 = 첫 구매' 같은 기준, 출생연도 기준, "
                                                "대체 지표 안내). 없으면 빈 문자열"},
    "next_questions": {"type": "array", "items": {"type": "string"},
                       "description": "이어서 물어볼 만한 질문 1~2개(25자 안팎, 실무자 말투, 지금 데이터로 답할 수 있는 것)"},
}}
ANSWER_FORMAT = """
[답변 칸]
최종 답변은 conclusion, evidence, hypothesis, notice, next_questions 칸을 채운 JSON 하나로만 낸다(다른 글 없이).
결론은 질문에 대한 답 한 문장(50자 이내, 나열 금지), 근거는 숫자 최대 3개, 가설·주의는 필요할 때만 한 문장씩.
기간은 '9/21~9/27'처럼 쓴다.
"""


def compose_answer(a: dict) -> str:
    """칸으로 받은 답변을 글로 (대화 맥락·평가·Growth Lab 저장용. 화면은 chat.py가 칸으로 그린다)."""
    out = [a.get("conclusion", "").strip()]
    out += [f"- {e}" for e in a.get("evidence", []) if e.strip()]
    if a.get("hypothesis", "").strip():
        out.append(f"가설: {a['hypothesis'].strip()}")
    if a.get("notice", "").strip():
        out.append(f"참고: {a['notice'].strip()}")
    return "\n".join(x for x in out if x)


def parse_answer(text: str) -> dict | None:
    """모델 답변이 칸(JSON)이면 정리해 돌려주고, 아니면 None. 개수는 코드가 자른다(근거 3, 다음 질문 2)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").removeprefix("json").strip()
    if not t.startswith("{"):
        mm = re.search(r"\{.*\}", t, re.S)
        if not mm:
            return None
        t = mm.group(0)
    try:
        d = json.loads(t)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict) or not str(d.get("conclusion", "")).strip():
        return None
    lst = lambda v: [clean(str(x)) for x in (v if isinstance(v, list) else [v] if v else []) if str(x).strip()]
    return {"conclusion": clean(str(d.get("conclusion", ""))), "evidence": lst(d.get("evidence"))[:3],
            "hypothesis": clean(str(d.get("hypothesis") or "")), "notice": clean(str(d.get("notice") or "")),
            "next_questions": lst(d.get("next_questions"))[:2]}


# 도구 입력값의 형식 (Gemini function declaration, OpenAPI 스키마)
PARAM_SCHEMA = {
    "policy_config": {"type": "object", "description": "질문·Growth Lab에서 확인한 정책 조건. 비율은 % 단위(5 = 5%).", "properties": {
        "policy": {"type": "string", "enum": ["price", "discount", "shipping", "benefit", "bundle", "volume"]},
        "price_change_pct": {"type": "number", "description": "선택 상품 판매가격 변화 %"},
        "discount_type": {"type": "string", "enum": ["rate", "fixed"]},
        "discount_value": {"type": "number", "description": "정률 % 또는 정액 원. 기존 주문 쿠폰 교체"},
        "discount_cap": {"type": "number", "description": "최대 할인 원. 0은 제한 없음"},
        "minimum_order": {"type": "number", "description": "쿠폰 차감 전 최소 주문 상품금액 원"},
        "adoption_pct": {"type": "number", "description": "새 쿠폰·혜택 적용 주문 비중 %. 기본 100"},
        "shipping_fee": {"type": "number", "description": "고객 부담 배송비 원"},
        "free_shipping_threshold": {"type": "number", "description": "쿠폰 차감 후 무료배송 기준 원. 0은 전체 무료"},
        "benefit_amount": {"type": "number", "description": "사용 주문당 적립금·사은품 원가 원"},
        "bundle_discount_pct": {"type": "number", "description": "묶음 구성 상품 추가 할인 %"},
        "order_change_pct": {"type": "number", "description": "대상 주문 변화 가정 %. 지정하지 않으면 0"},
        "fixed_cost": {"type": "number", "description": "기간 전체 추가 실행비 원"}}, "required": ["policy"]},
    "simulation_scope": {"type": "object", "properties": {
        "product_ids": {"type": "array", "items": {"type": "string"}},
        "categories": {"type": "array", "items": {"type": "string"}},
        "theme_id": {"type": "string"}, "coupon_id": {"type": "string"}}},
    "simulation_costs": {"type": "object", "properties": {
        "shipping_per_order": {"type": "number", "description": "주문당 배송 원가 원"},
        "fee_pct": {"type": "number", "description": "결제 수수료율 %"},
        "other_per_order": {"type": "number", "description": "기타 주문당 변동비 원"}}},
    "start": {"type": "string", "description": "시작일 YYYY-MM-DD"},
    "end": {"type": "string", "description": "끝 다음 날 YYYY-MM-DD (미포함). 9월이면 2026-10-01"},
    "target": {"type": "string", "enum": ["product", "category"], "description": "상품별 또는 카테고리별"},
    "direction": {"type": "string", "enum": ["down", "up"], "description": "down = 줄어든 순(기본), up = 늘어난 순"},
    "n": {"type": "integer", "description": "보여줄 개수. 질문에 개수(TOP5, 3개 등)가 있을 때만 넣는다"},
    "metric": {"type": "string", "enum": ["매출", "수량"], "description": "기준: 매출(기본) 또는 판매 수량"},
    "grain": {"type": "string", "enum": ["date", "week", "month"], "description": "일·주·월 단위"},
    "path": {"type": "string", "enum": ["ALL", "CURATION", "BROWSE"], "description": "전체 / 큐레이션 경유 / 일반 탐색"},
    "by": {"type": "string", "enum": ["customer_type", "grade_at_order", "visitor_type", "signup_channel"],
           "description": "고객군 기준: 첫 구매/기존 구매, 주문 당시 등급, 신규/재방문, 가입 경로 (기본 customer_type)"},
    "step": {"type": "integer", "description": "1=방문→상품 클릭, 2=상품 클릭→장바구니, 3=장바구니→구매"},
    # 고객 조건: 9개 도구에 반복해 붙으므로 짧게 쓴다(설명은 시스템 지시 [고객 조건]에)
    "filters": {"type": "object", "description": "대상 고객 조건(질문에 있을 때만)", "properties": {
        "gender": {"type": "string", "enum": ["F", "M"]},
        "age_groups": {"type": "array", "items": {"type": "string", "enum": ["10대 이하", "20대", "30대", "40대", "50대", "60대 이상"]}},
        "regions": {"type": "array", "items": {"type": "string"}, "description": "시·도 정식 이름(서울특별시, 경기도…)"},
        "signup_channels": {"type": "array", "items": {"type": "string", "enum": ["DIRECT", "EMAIL", "GOOGLE", "KAKAO", "NAVER"]}},
        "grades": {"type": "array", "items": {"type": "string", "enum": ["BRONZE", "SILVER", "GOLD", "VIP"]}},
        "grade_basis": {"type": "string", "enum": ["당시", "현재"]},
        "customer_type": {"type": "string", "enum": ["첫 구매", "기존 구매"]},
        "new_signup": {"type": "boolean"},
    }},
    "lift": {"type": "number", "description": "목표 상대 개선폭. 5%면 0.05"},
    # 조립형 분석(analyze)
    "measure": {"type": "string", "enum": ["매출", "상품매출", "판매수량", "주문수", "구매고객수", "객단가", "방문수", "구매전환율", "장바구니율"],
                "description": "볼 지표"},
    "dims": {"type": "array", "items": {"type": "string", "enum": ["상품", "카테고리", "테마", "경로", "요일", "평일주말", "시간대", "시각",
                                                                    "일", "주", "월", "성별", "연령대", "지역", "가입경로", "등급",
                                                                    "첫구매기존", "신규재방문"]},
             "description": "무엇별로 나눌지 1~2개. 2개면 교차표(예: 요일, 시간대)"},
    "sort": {"type": "string", "enum": ["높은순", "낮은순", "감소순", "증가순"],
             "description": "높은순(기본)·낮은순 = 값 기준, 감소순·증가순 = 직전 기간 대비 변화 기준(자동 비교)"},
    "compare": {"type": "boolean", "description": "직전 기간과 비교해 변화도 볼지"},
}
REQUIRED = ["start", "end"]
PARAM_SCHEMA["simulation_scope"]["properties"]["filters"] = PARAM_SCHEMA["filters"]


class LLMError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류. code: HTTP 상태(없으면 0, 시간 초과는 -1), detail: 원문 일부."""

    def __init__(self, msg, code=0, detail=""):
        super().__init__(msg)
        self.code, self.detail = code, detail


def function_declarations() -> list[dict]:
    out = []
    for t in T.TOOLS.values():
        props = {p: PARAM_SCHEMA[p] for p in t.params}
        required = [r for r in REQUIRED if r in props]
        if t.name == "simulate_policy":
            required.append("policy_config")
        out.append({"name": t.name, "description": t.description,
                    "parameters": {"type": "object", "properties": props, "required": required}})
    return out


# 답변에 도구 이름이 새어 나오면 실무자용 이름으로 바꾼다 (시스템 지시 10번의 안전장치)
TOOL_KO = {
    "simulate_policy": "정책 시뮬레이션",
    "get_kpis": "핵심 지표", "get_coupon_efficiency": "쿠폰 효율 분석", "rank_items": "매출 순위",
    "explain_revenue_change": "매출 변화 분해", "get_trend": "매출 추이", "get_funnel": "구매 퍼널 분석",
    "detect_changes": "변화 탐지", "get_themes": "큐레이션 테마 분석", "get_retention": "재구매 분석",
    "get_segments": "고객군(RFM) 분석", "segment_preference": "고객군별 선호 카테고리", "segment_repeat": "고객군별 재구매율",
    "design_experiment": "실험 설계", "find_potential_products": "성장 잠재력 상품 분석",
    "compare_items": "상품별 매출 변화", "analyze": "기준별 분석",
}
_TOOL_RE = re.compile(r"`?(?<![A-Za-z0-9_])(" + "|".join(sorted(TOOL_KO, key=len, reverse=True)) + r")(?![A-Za-z0-9_])(?:\(\))?`?")
_RULE_RE = re.compile(r"\s*\(?(?:규칙|지시문?) ?\d+번(?:에 따라|에 의해)?\)?,?")


# 도구 없이 나온 숫자(금액·비율·건수·인원) 탐지: 날짜는 제외
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:원|%|건|명|배|개)")
FORCE_TOOL_MSG = ("방금 답변의 숫자는 데이터 도구 결과가 아닙니다. 지어낸 숫자는 쓰면 안 됩니다. "
                  "알맞은 도구를 호출해 결과를 받은 뒤 그 숫자로만 다시 답하세요.")


_ANY_TOOL_RE = re.compile(r"`?(?<![A-Za-z0-9_])(get_[a-z_]+|[a-z]+(?:_[a-z]+)+)(?![A-Za-z0-9_])(?:\(\))?`?")


def _tool_label(name: str) -> str:
    """모델이 지어낸 도구 이름(get_segment_repeat 등)도 가장 비슷한 도구의 한글 이름으로."""
    import difflib
    base = name[4:] if name.startswith("get_") else name
    hit = difflib.get_close_matches(name, TOOL_KO, n=1, cutoff=0.6) or difflib.get_close_matches(base, TOOL_KO, n=1, cutoff=0.6)
    return TOOL_KO[hit[0]] if hit else "관련 분석"


def clean(text: str) -> str:
    """도구 이름·규칙 번호 같은 내부 표현을 지운다."""
    text = _TOOL_RE.sub(lambda mm: TOOL_KO[mm.group(1)], text)
    # 그 밖의 영어 snake_case 식별자(get_로 시작하거나 도구와 비슷한 것)도 바꾼다
    text = _ANY_TOOL_RE.sub(lambda mm: _tool_label(mm.group(1)) if mm.group(1).startswith("get_")
                            or _tool_label(mm.group(1)) != "관련 분석" else mm.group(0), text)
    return _RULE_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# 토큰 사용량: 응답마다 API가 알려 주는 입력·출력 토큰을 모은다 (키만으로도 사용량을 볼 수 있게)
# ---------------------------------------------------------------------------
# 1M 토큰당 달러 (입력, 출력). 공개 단가 기준 추정치이며 실제 청구액과 다를 수 있다. 없는 모델은 비용 표시 안 함.
PRICES = {
    "gpt-5.4-nano": (0.20, 1.25), "gpt-5-nano": (0.05, 0.40), "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1-nano": (0.10, 0.40), "gpt-4.1-mini": (0.40, 1.60), "gpt-4o-mini": (0.15, 0.60),
}


def new_usage() -> dict:
    return {"input": 0, "output": 0}


def add_usage(usage: dict, d: dict) -> None:
    """OpenAI(usage) 또는 Gemini(usageMetadata) 응답의 토큰 수를 더한다."""
    u = d.get("usage")
    if u:
        usage["input"] += u.get("prompt_tokens") or 0
        usage["output"] += u.get("completion_tokens") or 0
        return
    g = d.get("usageMetadata") or {}
    usage["input"] += g.get("promptTokenCount") or 0
    usage["output"] += (g.get("candidatesTokenCount") or 0) + (g.get("thoughtsTokenCount") or 0)


def cost(model: str, usage: dict) -> float | None:
    p = PRICES.get(re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model or ""))
    return None if not p or not usage else (usage["input"] * p[0] + usage["output"] * p[1]) / 1e6


def usage_label(model: str, usage: dict | None) -> str:
    """'토큰 입력 1,234 · 출력 567 (약 $0.0012)'"""
    if not usage or not (usage["input"] or usage["output"]):
        return ""
    c = cost(model, usage)
    return f"토큰 입력 {usage['input']:,} · 출력 {usage['output']:,}" + (f" (약 ${c:.4f})" if c is not None else "")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _call(key: str, path: str, body: dict | None = None, timeout=90) -> dict:
    req = urllib.request.Request(
        f"{API}/{path}", data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        if e.code in (400, 401, 403) and ("API key" in detail or "API_KEY" in detail or "PERMISSION" in detail or "UNAUTH" in detail):
            raise LLMError("Gemini API 키가 올바르지 않거나 권한이 없습니다. Secrets의 GEMINI_API_KEY를 확인해 주세요.") from e
        if e.code == 429:
            raise LLMError("Gemini API 사용량 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.", 429, detail) from e
        raise LLMError(f"Gemini API 오류 {e.code}: {detail}", e.code, detail) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise LLMError("Gemini 응답이 너무 오래 걸려 중단했습니다. 잠시 후 다시 질문해 주세요.", -1) from e
        raise LLMError(f"Gemini API에 연결하지 못했습니다: {e.reason}") from e
    except (TimeoutError, socket.timeout) as e:
        raise LLMError("Gemini 응답이 너무 오래 걸려 중단했습니다. 잠시 후 다시 질문해 주세요.", -1) from e
    except (http.client.HTTPException, ConnectionError, json.JSONDecodeError) as e:
        raise LLMError(f"Gemini API 응답을 받지 못했습니다: {type(e).__name__}") from e


def _thinking(model: str) -> dict | None:
    """도구 고르기는 깊은 추론이 필요 없어 생각 단계를 줄여 응답 시간을 줄인다."""
    v = re.findall(r"gemini-(\d+(?:\.\d+)?)", model)
    ver = float(v[0]) if v else 0.0
    if ver >= 3:
        return {"thinkingLevel": "low"}
    if ver >= 2.5 and "flash" in model:
        return {"thinkingBudget": 0}
    return None


def _generate(key: str, model: str, body: dict) -> dict:
    """generateContent 호출. 생각 설정을 모델이 거부하면 빼고, 시간 초과면 한 번 더 시도한다."""
    for attempt in range(3):
        try:
            return _call(key, f"models/{model}:generateContent", body)
        except LLMError as e:
            gc = body.get("generationConfig", {})
            if e.code == 400 and "thinkingConfig" in gc and "think" in e.detail.lower():
                gc.pop("thinkingConfig")
                continue
            if e.code == -1 and attempt == 0:
                time.sleep(1)
                continue
            if e.code == 429 and attempt == 0:    # 분당 한도: 잠깐 기다렸다 한 번 더
                time.sleep(6)
                continue
            raise
    raise LLMError("Gemini 응답을 받지 못했습니다. 잠시 후 다시 질문해 주세요.")


_MODEL_CACHE: dict[str, str] = {}
_UNAVAILABLE: dict[str, set] = {}   # 목록에는 있지만 이 키로는 거절된 모델 (예: 신규 사용자에게 종료된 모델)


def _setting(name: str) -> str:
    """Streamlit Secrets 또는 환경변수에서 설정값을 읽는다."""
    try:
        import streamlit as st
        v = st.secrets.get(name)
        if v:
            return str(v).strip()
    except Exception:
        pass
    return (os.getenv(name) or "").strip()


def api_key() -> str | None:
    """AI 키 (Secrets 또는 환경변수). OPENAI_API_KEY가 있으면 GPT, 없으면 GEMINI_API_KEY로 Gemini.
    예시 문구('붙여넣기')가 그대로면 없는 것으로 본다."""
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        v = _setting(name)
        if v and "붙여넣기" not in v:
            return v
    return None


def provider(key: str) -> str:
    """'openai' 또는 'gemini'. OpenAI 키는 sk- 로 시작한다."""
    return "openai" if key and (key.startswith("sk-") or key == _setting("OPENAI_API_KEY")) else "gemini"


def model_setting(key: str) -> str:
    """모델을 고정할 때 쓰는 Secrets 이름."""
    return "OPENAI_MODEL" if provider(key) == "openai" else "GEMINI_MODEL"


def _openai():
    from . import llm_openai
    return llm_openai


def text_models(key: str) -> list[str]:
    """이 키로 쓸 수 있는 텍스트 생성 모델 (실험·미리보기 제외)."""
    if provider(key) == "openai":
        return _openai().text_models(key)
    d = _call(key, "models?pageSize=200")
    names = [m["name"].split("/", 1)[1] for m in d.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "embedding", "exp", "preview", "thinking", "learnlm", "gemma", "aqa")
    return [n for n in names if n.startswith("gemini-") and not any(b in n for b in bad)]


def _version(n: str) -> float | None:
    v = re.findall(r"gemini-(\d+(?:\.\d+)?)", n)
    return float(v[0]) if v else None


def candidates(key: str) -> list[str]:
    """자동 선택 후보를 '가장 낮은(가벼운) 순'으로: 버전 낮은 순, 같은 버전이면 flash-lite 먼저. 거절된 모델은 뺀다."""
    names = text_models(key)
    pool = [n for n in names if "flash" in n and _version(n) is not None]
    if not pool:
        pool = [n for n in names if _version(n) is not None] or names
    gone = _UNAVAILABLE.get(key, set())
    return sorted((n for n in pool if n not in gone),
                  key=lambda n: (_version(n) or 99, "lite" not in n, "latest" in n, len(n)))


def pick_model(key: str) -> str:
    """GEMINI_MODEL이 있으면 그 모델. 없으면 이 키로 실제로 쓸 수 있는 가장 낮은(가벼운) Flash 계열 모델.
    OpenAI 키면 OPENAI_MODEL 또는 가장 가벼운 등급(nano → mini)의 최신 GPT."""
    if provider(key) == "openai":
        return _openai().pick_model(key)
    fixed = _setting("GEMINI_MODEL")
    if fixed:
        return fixed
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    c = candidates(key)
    if not c:
        raise LLMError("이 키로 쓸 수 있는 Gemini 모델을 찾지 못했습니다.")
    _MODEL_CACHE[key] = c[0]
    return c[0]


def _next_model(key: str, failed: str, detail: str) -> str | None:
    """거절된 모델을 기록하고 다음 후보를 고른다. 오류 문구에 추천 모델이 있으면 그것을 먼저."""
    _UNAVAILABLE.setdefault(key, set()).add(failed)
    _MODEL_CACHE.pop(key, None)
    sug = re.search(r"use (?:models/)?(gemini-[\w.\-]+)", detail)
    sug = sug.group(1).rstrip(".-") if sug else None
    nxt = sug if sug and sug not in _UNAVAILABLE[key] else None
    if not nxt:
        c = candidates(key)
        nxt = c[0] if c else None
    if nxt:
        _MODEL_CACHE[key] = nxt
    return nxt


# ---------------------------------------------------------------------------
# 도구 결과 → LLM에 돌려줄 요약 (JSON)
# ---------------------------------------------------------------------------
def _jsonable(v):
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        return None if pd.isna(v) else round(v, 4)
    return v


def summarize(res: dict, rows: int = 12) -> dict:
    out = {k: res[k] for k in ("title", "period", "facts", "notes")}
    t = res.get("table")
    if t is not None and len(t):
        out["table_head"] = [{str(c): _jsonable(v) for c, v in r.items()} for r in t.head(rows).to_dict("records")]
        out["table_rows"] = len(t)
    return out


# ---------------------------------------------------------------------------
# 공통: 모델 호출(거절 시 다음 모델로) · 도구 호출 반복
# ---------------------------------------------------------------------------
def _new_body(system: str, contents: list[dict], model: str, tools: bool = True) -> dict:
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
            "generationConfig": {"temperature": 0}}
    if tools:
        body["tools"] = [{"functionDeclarations": function_declarations()}]
        body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
    if _thinking(model):
        body["generationConfig"]["thinkingConfig"] = _thinking(model)
    return body


def _generate_any(key: str, model: str, body: dict) -> tuple[dict, str]:
    """generateContent. 모델이 거절(404)되면 다음 후보로 바꿔 다시 부른다. (응답, 실제 쓴 모델)"""
    fixed = bool(_setting("GEMINI_MODEL"))
    for _ in range(4):
        try:
            return _generate(key, model, body), model
        except LLMError as e:
            if e.code != 404:
                raise
            if fixed:
                raise LLMError(f"Secrets의 GEMINI_MODEL '{model}'은(는) 이 키로 쓸 수 없습니다. "
                               "AI 모델 칸의 목록에서 다른 모델로 바꾸거나 그 줄을 지워 자동 선택을 쓰세요.", 404) from e
            nxt = _next_model(key, model, e.detail)
            if not nxt:
                raise LLMError("이 키로 쓸 수 있는 Gemini 모델을 찾지 못했습니다.", 404) from e
            model = nxt
            gc = body["generationConfig"]
            gc.pop("thinkingConfig", None)
            if _thinking(model):
                gc["thinkingConfig"] = _thinking(model)
    raise LLMError("쓸 수 있는 Gemini 모델을 찾지 못했습니다. 잠시 후 다시 시도해 주세요.")


def _first(d: dict) -> list[dict]:
    cands = d.get("candidates") or []
    if not cands:
        reason = (d.get("promptFeedback") or {}).get("blockReason", "응답 없음")
        raise LLMError(f"Gemini가 답하지 않았습니다 ({reason}).")
    return cands[0].get("content") or {"role": "model", "parts": []}


def _tool_loop(key: str, system: str, contents: list[dict], run_tool: Callable[[str, dict], dict],
               model: str, steps: int = MAX_STEPS, answer_schema: dict | None = None) -> dict:
    if provider(key) == "openai":
        return _openai().tool_loop(key, system, contents, run_tool, model, steps, answer_schema)
    return _tool_loop_gemini(key, system, contents, run_tool, model, steps)


def _tool_loop_gemini(key: str, system: str, contents: list[dict], run_tool: Callable[[str, dict], dict],
                      model: str, steps: int = MAX_STEPS) -> dict:
    """모델이 도구를 부르면 실행해 결과를 돌려주기를 반복. 도구 없이 숫자를 말하면 도구 호출을 강제해 다시 묻는다.
    반환: {"text", "calls": [{"tool", "params", "result" 또는 "error"}], "model"}"""
    body = _new_body(system, contents, model)
    calls, forced, usage = [], False, new_usage()
    for _ in range(steps + 1):
        d, model = _generate_any(key, model, body)
        add_usage(usage, d)
        content = _first(d)
        parts = content.get("parts") or []
        fcs = [p["functionCall"] for p in parts if "functionCall" in p]
        if not fcs:
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if not calls and not forced and _NUM_RE.search(text):
                # 도구를 부르지 않고 숫자를 말함 → 지어낸 숫자. 도구 호출을 강제해 한 번 더 묻는다.
                forced = True
                body["contents"].append(content)
                body["contents"].append({"role": "user", "parts": [{"text": FORCE_TOOL_MSG}]})
                body["toolConfig"]["functionCallingConfig"]["mode"] = "ANY"
                continue
            if not calls and _NUM_RE.search(text):
                text = "데이터 도구로 확인한 숫자가 없어 답할 수 없습니다. 질문을 조금 더 구체적으로 해 주세요."
            return {"text": clean(text), "calls": calls, "model": model, "usage": usage}
        body["toolConfig"]["functionCallingConfig"]["mode"] = "AUTO"
        body["contents"].append(content)            # 모델 응답은 그대로 돌려준다(생각 서명 보존)
        responses = []
        for fc in fcs:
            name, params = fc.get("name"), dict(fc.get("args") or {})
            entry = {"tool": name, "params": params}
            if name not in T.TOOLS:
                entry["error"] = f"없는 도구: {name}"
                payload = {"error": entry["error"]}
            else:
                try:
                    res = run_tool(name, params)
                    entry["result"] = res
                    payload = summarize(res)
                except (ValueError, TypeError, KeyError) as e:
                    entry["error"] = str(e)
                    payload = {"error": str(e)}
            calls.append(entry)
            responses.append({"functionResponse": {"name": name, "response": payload}})
        body["contents"].append({"role": "user", "parts": responses})
    return {"text": "질문이 복잡해 여러 단계 분석이 필요합니다. 아래 결과를 참고해 주세요.", "calls": calls, "model": model,
            "usage": usage}


# ---------------------------------------------------------------------------
# 애매한 기간 되묻기 (결정 2026-11-03): "요즘·요새·최근(숫자 없이)"은 사람마다 기간이 달라
# 추측해서 답하지 않고 기간을 고르게 한다. 지시문이 아니라 코드로 정해 항상 같게 동작한다.
# ---------------------------------------------------------------------------
_VAGUE_RE = re.compile(r"요즘|요새|근래|최근(?!\s*\d)|얼마\s*전|lately|recently")
_EXPLICIT_RE = re.compile(r"\d+\s*(?:월|주|일|개월|년)|\d{4}-\d{2}|이번\s*달|지난\s*달|이번\s*주|지난\s*주|어제|오늘|"
                          r"전체\s*기간|상반기|하반기|분기")
PERIOD_CHOICES = [("최근 7일", "2026-09-24 ~ 2026-09-30"), ("최근 2주", "2026-09-17 ~ 2026-09-30"),
                  ("이번 달", "2026-09-01 ~ 2026-09-30"), ("최근 3개월", "2026-07-01 ~ 2026-09-30")]


def vague_period(question: str) -> bool:
    """기간이 애매한 말("요즘")만 있고 정확한 기간("9월", "최근 2주", "이번 주")은 없는 질문인가."""
    return bool(_VAGUE_RE.search(question or "")) and not _EXPLICIT_RE.search(question or "")


def with_period(question: str, label: str) -> str:
    """되묻기에서 고른 기간을 질문에 붙인다. 예: '요즘 뜨는 상품은? (기간: 최근 2주, 2026-09-17 ~ 2026-09-30)'"""
    rng = dict(PERIOD_CHOICES).get(label, "")
    return f"{question} (기간: {label}{', ' + rng if rng else ''})"


def clarify_period(question: str) -> dict:
    word = _VAGUE_RE.search(question).group(0)
    text = (f"'{word}'은(는) 사람마다 떠올리는 기간이 달라서, 추측해서 숫자를 드리면 틀릴 수 있어요. "
            "어느 기간으로 볼지 골라 주세요(오늘 = 2026-09-30 기준). 원하는 기간을 직접 적어 다시 물어보셔도 돼요.\n\n"
            + "\n".join(f"- {k}: {v}" for k, v in PERIOD_CHOICES))
    return {"text": text, "calls": [], "model": "", "usage": new_usage(), "clarify": [k for k, _ in PERIOD_CHOICES]}


# ---------------------------------------------------------------------------
# 질문 하나에 답하기 (AI 분석가)
# ---------------------------------------------------------------------------
def ask(key: str, question: str, run_tool: Callable[[str, dict], dict], history: list[dict] | None = None,
        model: str | None = None, growth_context: dict | None = None) -> dict:
    """반환: {"text": 답변, "calls": [{"tool", "params", "result" 또는 "error"}], "model": 모델명}
    기간이 애매한 질문이면 AI를 부르지 않고 {"clarify": [기간 선택지]}를 함께 돌려준다(토큰 0)."""
    if vague_period(question):
        return clarify_period(question)
    contents = []
    for h in (history or [])[-HISTORY_TURNS:]:
        contents.append({"role": "user", "parts": [{"text": h["q"]}]})
        if h.get("a"):
            contents.append({"role": "model", "parts": [{"text": h["a"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})
    system = SYSTEM + ANSWER_FORMAT
    if growth_context:
        system += ("\n[현재 Growth Lab 비교 화면]\n다음 JSON은 Python 계산값과 사용자 가정이다. "
                   "설명 요청은 selected와 scenarios에서 선택안을 찾아 simulate_policy를 호출한다. "
                   "기간·대상·비용을 그대로 전달하고 사용자가 바꾸라고 한 값만 변경한다. "
                   "관측값과 가정 기반 결과를 구분한다. 가설 3개·ICE·실험안을 강제하지 않는다. "
                   "입력하지 않은 반응률을 만들지 않는다.\n" + json.dumps(growth_context, ensure_ascii=False, default=str))
    r = _tool_loop(key, system, contents, run_tool, model or pick_model(key), answer_schema=ANSWER_SCHEMA)
    a = parse_answer(r["text"])
    if a:
        r["answer"], r["text"] = a, compose_answer(a)
    return r


# ---------------------------------------------------------------------------
# Growth Lab 초안: 문제 → (도구로 근거 확인) → 가설·전략(ICE)·실험 설계 초안
# ---------------------------------------------------------------------------
DRAFT_GATHER = SYSTEM + """
[Growth Lab 초안 작업]
지금은 실무자의 질문이 아니라, 팀이 Growth Lab에 저장한 '문제'에 대한 가설·전략·실험 초안을 만들기 위해 근거를 모으는 단계다.
- 문제의 분석 기간을 기준으로, 원인을 좁히는 데 필요한 도구를 2~4개 호출한다(예: 퍼널 구간, 테마, 고객군, 상품, 변화 탐지).
- 다 확인했으면 '확인된 사실'(도구 숫자 그대로)과 '원인 후보와 각 후보의 근거·반대 근거'를 한국어로 정리한다(규칙 7의 길이 제한은 적용하지 않는다).
"""

DRAFT_WRITE = """너는 식품 이커머스 그로스팀의 분석가다. 아래 [문제]와 [근거]만 사용해 Growth Lab 초안을 JSON으로 쓴다.
규칙
1. 숫자는 [근거]나 [문제]에 있는 숫자만 그대로 쓴다. 새 숫자를 계산·추정·창작하지 않는다(ICE 점수와 최소 검출 효과는 예외).
2. 가설은 3개. 각각 근거(데이터로 확인된 사실), 반대 근거(가설을 약하게 만드는 사실이나 아직 모르는 점), 추가 확인(이 데이터로 할 수 있는 확인 방법).
   근거가 없으면 '근거 데이터 없음 - 확인 필요'라고 쓴다.
3. 전략은 2~3개. 실행 가능한 개선 액션, 연결 가설(가설 문장 그대로), 기대 영향, Impact·Confidence·Ease(각 1~10 정수)와 점수 근거.
   Confidence는 근거 데이터가 강할수록 높게, Ease는 화면·운영 변경만으로 되면 높게.
4. 실험은 ICE가 가장 높은 전략 1개. 실험군(B)과 대조군(A)을 구체적으로, 주요 지표는 문제 지표와 같은 비율 지표 1개,
   배정 단위는 보통 '고객', 최소 검출 효과(상대 %)는 5~30 사이에서 현실적으로, 중단 기준 포함.
5. 이 데이터에 없는 것(광고비·ROAS, 결제 페이지 진입, 체류 시간, 경쟁사 가격, 비회원)을 근거나 지표로 쓰지 않는다.
6. 도구 이름, 규칙 번호, 영어 변수명을 쓰지 않는다. 한국어 존댓말 대신 간결한 개조식 문장. 비율은 퍼센트로.
"""

_S = {"type": "string"}
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "근거 요약 2~3문장"},
        "hypotheses": {"type": "array", "items": {"type": "object", "properties": {
            "hypothesis": _S, "evidence": _S, "counter": _S, "check": _S},
            "required": ["hypothesis", "evidence", "counter", "check"]}},
        "strategies": {"type": "array", "items": {"type": "object", "properties": {
            "action": _S, "hypothesis": _S, "impact_text": _S, "impact": {"type": "integer"},
            "confidence": {"type": "integer"}, "ease": {"type": "integer"}, "reason": _S},
            "required": ["action", "hypothesis", "impact_text", "impact", "confidence", "ease", "reason"]}},
        "experiment": {"type": "object", "properties": {
            "name": _S, "hypothesis": _S, "treatment": _S, "control": _S, "unit": {"type": "string", "enum": ["고객", "세션"]},
            "target": _S, "metric": _S, "mde": {"type": "number"}, "stop": _S},
            "required": ["name", "hypothesis", "treatment", "control", "unit", "target", "metric", "mde", "stop"]},
    },
    "required": ["summary", "hypotheses", "strategies", "experiment"],
}


def problem_brief(p: dict) -> str:
    """Growth Lab 문제를 모델에게 넘길 글로."""
    obs, ctx, dfn = p.get("observed") or {}, p.get("context") or {}, p.get("definition") or {}
    lines = [f"제목: {p.get('title', '')}", f"출처 화면: {p.get('source_page', '')}",
             f"분석 기간: {ctx.get('period', '')} (도구의 end는 마지막 날의 다음 날) / 비교 기간: {ctx.get('compare', '')}"]
    keys = {"metric": "지표", "segment": "대상", "definition": "정의", "previous": "비교 기간 값", "current": "분석 기간 값",
            "direction": "방향", "n_current": "분모", "p_value": "p값"}
    for k, lab in keys.items():
        v = obs.get(k)
        if v is None or v == "":
            continue
        if k in ("previous", "current") and obs.get("unit", "rate") == "rate" and isinstance(v, (int, float)):
            v = f"{v * 100:.1f}%"
        elif isinstance(v, float):
            v = f"{v:,.4g}"
        lines.append(f"{lab}: {v}")
    if obs.get("kind") == "ask":      # AI 분석가에서 저장한 문제: 실무자의 질문과 당시 도구 결과 사실
        lines.append(f"실무자의 질문: {obs.get('question', '')}")
        for f in obs.get("facts", []):
            lines.append(f"관찰된 사실: {re.sub(r'[*`]', '', str(f))}")
    for k, lab in {"statement": "팀이 쓴 문제 문장", "target": "대상 고객", "impact": "비즈니스 영향"}.items():
        if dfn.get(k):
            lines.append(f"{lab}: {dfn[k]}")
    return "\n".join(lines)


_VAL_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(만\s*)?(원|%|%p|건|명|배|개|일)")


_KR_AMOUNT_RE = re.compile(r"(?:(\d[\d,]*(?:\.\d+)?)\s*억\s*)?(?:(\d[\d,]*(?:\.\d+)?)\s*만\s*)?(\d[\d,]*)?\s*원")


def _normalize_amounts(text: str) -> str:
    """'827만 5,493원', '1억 1,357만 원', '1.03억원' 같은 한글 단위 금액을 '8,275,493원'처럼 한 숫자로 바꾼다."""
    def rep(mm):
        eok, man, rest = mm.groups()
        if not (eok or man):
            return mm.group(0)
        v = float((eok or "0").replace(",", "")) * 1e8 + float((man or "0").replace(",", "")) * 1e4 \
            + float((rest or "0").replace(",", ""))
        return f"{v:,.0f}원"
    return _KR_AMOUNT_RE.sub(rep, text or "")


def _numbers(text: str) -> list[tuple[float, str]]:
    out = []
    for num, man, unit in _VAL_RE.findall(text or ""):
        v = float(num.replace(",", "")) * (10000 if man else 1)
        out.append((v, unit))
    return out


def unverified_numbers(text: str, evidence: str) -> list[str]:
    """text 속 숫자 중 evidence(도구 결과·문제 정보)에 없는 것. 반올림 차이는 허용."""
    ev = _numbers(_normalize_amounts(evidence))
    bad = []
    for m_ in _VAL_RE.finditer(_normalize_amounts(text)):
        v, u = _numbers(m_.group(0))[0]
        same = [e for e, eu in ev if eu == u]
        # 원 단위는 '만원·억원' 표시 반올림을 고려해 1% 허용, 비율은 0.05%p
        tol = 0.051 if u in ("%", "%p", "배") else max(0.5, abs(v) * 0.01) if u == "원" else 0.5
        if not any(abs(e - v) <= tol for e in same):
            bad.append(m_.group(0))
    return bad


_DATE_RE = re.compile(r"\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}\s*년|\d{1,2}\s*월")
_COUNT_RE = re.compile(r"^(\d{1,2})\s*(개|일)$")


def _call_evidence(calls: list[dict]) -> str:
    """도구 결과(사실·표 앞부분)를 숫자 대조용 글로. 표의 비율(0.164)은 퍼센트(16.4%)로도 넣는다."""
    parts = []
    for c in calls:
        if "result" not in c:
            continue
        s = summarize(c["result"])
        parts += [s["title"], s["period"], *s["facts"], *s.get("notes", [])]
        for row in s.get("table_head", []):
            for v in row.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if abs(v) <= 1.5:
                        parts.append(f"{v * 100:.4f}% {v * 100:.4f}%p")
                    parts.append(" ".join(f"{v}{u}" for u in ("원", "건", "명", "개", "일", "배")))
    return "\n".join(parts)


def unsupported_in_answer(text: str, calls: list[dict]) -> list[str]:
    """답변 속 숫자(원·%·건·명 등) 중 도구 결과에서 찾지 못한 것. 날짜와 '3개', '7일' 같은 작은 개수·기간 길이는 뺀다.
    AI가 직접 계산한 숫자(합계·차이)나 잘못 옮긴 숫자를 잡는 안전장치."""
    if not calls:
        return []
    bad = unverified_numbers(_DATE_RE.sub(" ", text or ""), _call_evidence(calls))
    out = []
    for b in bad:
        mm = _COUNT_RE.match(b.strip())
        if not (mm and int(mm.group(1)) <= 90) and b not in out:
            out.append(b)
    return out


def _evidence_text(brief: str, calls: list[dict]) -> str:
    parts = [brief]
    for c in calls:
        if "result" in c:
            r = summarize(c["result"])
            parts.append(json.dumps(r, ensure_ascii=False))
            parts.extend(r["facts"])
    return "\n".join(parts)


def _clamp(v, lo=1, hi=10):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return 5


def draft(key: str, problem: dict, run_tool: Callable[[str, dict], dict], model: str | None = None) -> dict:
    """Growth Lab 초안. 반환: {"summary", "hypotheses", "strategies", "experiment", "calls", "model", "warnings"}
    hypotheses/strategies는 Growth Lab 표의 열 이름(가설·근거·…·Impact·…)으로 바꿔 돌려준다."""
    brief = problem_brief(problem)
    model = model or pick_model(key)
    g = _tool_loop(key, DRAFT_GATHER, [{"role": "user", "parts": [{"text": "[문제]\n" + brief}]}], run_tool, model)
    calls, model, usage = g["calls"], g["model"], dict(g["usage"])
    evidence = _evidence_text(brief, calls)
    facts = "\n".join(f"- {f}" for c in calls if "result" in c for f in c["result"]["facts"])
    prompt = f"[문제]\n{brief}\n\n[근거: 데이터 도구 결과]\n{facts or '(도구 결과 없음)'}\n\n[근거 정리]\n{g['text']}"
    if provider(key) == "openai":
        raw, model, u = _openai().json_call(key, model, DRAFT_WRITE, prompt, DRAFT_SCHEMA, "growth_lab_draft")
        for k in usage:
            usage[k] += u[k]
    else:
        body = _new_body(DRAFT_WRITE, [{"role": "user", "parts": [{"text": prompt}]}], model, tools=False)
        body["generationConfig"].update(responseMimeType="application/json", responseSchema=DRAFT_SCHEMA)
        d, model = _generate_any(key, model, body)
        add_usage(usage, d)
        raw = "".join(p.get("text", "") for p in _first(d).get("parts") or [] if not p.get("thought")).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError("AI 초안 형식이 올바르지 않습니다. 다시 시도해 주세요.") from e

    warnings = []

    def check(s: str, mark: bool = True) -> str:
        s = clean(str(s or ""))
        bad = unverified_numbers(s, evidence)
        if bad:
            warnings.extend(bad)
            if mark:
                s += f" ⚠️ 확인 필요: 근거 데이터에서 찾지 못한 숫자({', '.join(bad)})"
        return s

    hyps = [{"채택": False, "가설": check(h.get("hypothesis"), mark=False), "근거": check(h.get("evidence")),
             "반대 근거": check(h.get("counter")), "추가 확인": check(h.get("check")), "작성": "AI 초안"}
            for h in out.get("hypotheses") or []]
    strat = []
    for s in out.get("strategies") or []:
        i, c, e = _clamp(s.get("impact")), _clamp(s.get("confidence")), _clamp(s.get("ease"))
        strat.append({"선택": False, "개선 액션": check(s.get("action")), "연결 가설": check(s.get("hypothesis"), mark=False),
                      "기대 영향": check(s.get("impact_text")), "Impact": i, "Confidence": c, "Ease": e,
                      "ICE 근거": check(s.get("reason")), "ICE": i * c * e})
    strat.sort(key=lambda s: -s["ICE"])
    if strat:
        strat[0]["선택"] = True
    # 전략이 연결한 가설은 '채택' 후보로 표시 (사람이 검토 후 해제 가능)
    linked = {s["연결 가설"] for s in strat}
    for h in hyps:
        h["채택"] = h["가설"] in linked
    ex = out.get("experiment") or {}
    # 실험 설계의 숫자(중단 기준 5% 등)는 데이터 주장이 아니라 설계 값이라 확인 대상에서 뺀다
    exp = {k: clean(str(ex.get(k) or "")) for k in ("name", "hypothesis", "treatment", "control", "target", "metric", "stop")}
    exp["unit"] = ex.get("unit") if ex.get("unit") in ("고객", "세션") else "고객"
    exp["mde"] = float(_clamp(ex.get("mde", 10), 1, 50))
    return {"summary": check(out.get("summary")), "hypotheses": hyps, "strategies": strat, "experiment": exp,
            "calls": calls, "model": model, "warnings": warnings, "usage": usage}

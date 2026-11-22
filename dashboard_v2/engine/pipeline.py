"""질문 하나를 처리하는 순서: 데이터에 없는 항목 검사 → 해석(AI) → 검증 → 계산 → 답변 카드.

화면(채팅 패널)은 ask()와 run_choice()만 부른다. 이 파일은 streamlit을 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ai
from . import answer as A
from . import compute as C
from . import interpret as I
from . import validate as V
from .query import Query, Result


@dataclass
class Outcome:
    question: str
    card: A.Card
    kind: str                                # 'answer' | 'message' | 'clarify' | 'error'
    query: Query | None = None               # 계산한 질의서 (다음 질문의 '직전 질의서')
    result: Result | None = None             # 질문 대시보드가 그리는 것
    choices: list[V.Choice] = field(default_factory=list)
    draft: dict | None = None                # AI 초안 (기록·평가용)
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    model: str = ""


def _compute(question: str, q: Query, why: bool, notes: list[str], m: dict, today) -> Outcome:
    try:
        r = C.run(m, q, today)
    except ValueError as e:                  # 계산 함수가 거절한 입력: 그 이유를 그대로 안내
        return Outcome(question, A.message(str(e)), "message", q)
    card = A.card(r, why=why)
    if notes:
        card.note = " ".join(notes + ([card.note] if card.note else []))
    return Outcome(question, card, "answer", q, r)


def run_choice(question: str, choice: V.Choice, m: dict, today) -> Outcome:
    """되묻기 선택지를 눌렀을 때: 선택지가 들고 있는 질의서로 바로 계산(AI 다시 안 부름)."""
    return _compute(question, choice.query, choice.why, [], m, today)


def ask(question: str, m: dict, today, key: str | None = None, prev: Query | None = None) -> Outcome:
    question = (question or "").strip()
    pre = V.out_of_data(question)
    if pre:                                  # AI를 부르지 않는다
        return Outcome(question, A.message(pre.text), "message")
    key = key or ai.api_key()
    if not key:
        return Outcome(question, A.message("AI 키(OPENAI_API_KEY)가 설정되지 않아 질문을 해석할 수 없습니다."), "error")
    products = m["raw"]["product"][["product_name", "category"]]
    cats = sorted(products["category"].unique())
    try:
        draft, model, usage = I.draft(key, question, cats, prev)
    except ai.LLMError as e:
        return Outcome(question, A.message(str(e)), "error")
    d = V.validate(question, draft, today, products, prev)
    if d.kind == "message":
        return Outcome(question, A.message(d.text), "message", draft=draft, usage=usage, model=model)
    if d.kind == "clarify":
        card = A.message(d.text)
        return Outcome(question, card, "clarify", choices=d.choices, draft=draft, usage=usage, model=model)
    out = _compute(question, d.query, d.why, d.notes, m, today)
    out.draft, out.usage, out.model = draft, usage, model
    return out

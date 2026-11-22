"""검증: AI가 쓴 질의서 초안(draft) + 질문 원문 → 계산할 질의서(Query) / 정해진 안내 / 되묻기.

AI 초안은 믿지 않는다. 여기서 코드로 확인한다.
1. 데이터에 없는 항목(사전 NOT_IN_DATA) 또는 AI가 '매핑 불가'로 적은 말 → 계산하지 않고 안내
2. 대상·고객 조건은 '근거 표현'이 질문에 실제로 있고, 사전의 동의어여야 통과 (이어지는 질문은 직전 질의서에서 상속)
3. 기간은 질문 원문을 periods.parse가 정한다 (AI의 기간 판단은 쓰지 않음)
4. 의도를 못 정했으면 가장 가까운 의도를 선택지로 되묻는다 (선택지는 완성된 질의서를 들고 있어 다시 해석하지 않는다)
5. '왜' 질문은 코드가 찾아(WHY_RE) 변화 위치로 답한다
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import pandas as pd

from . import lexicon as L
from . import periods as PR
from .query import AXES, INTENTS, MEASURE_UNIT, Query

# 초안 형식 (AI가 채우는 JSON). 질문 해석(2-5)이 이 형식을 쓴다.
DRAFT_KEYS = ("intent", "inherit", "category", "product", "filters", "measure", "axis", "group_by", "direction",
              "n", "topic", "path", "unmapped", "near_intents")

INTENT_LABEL = {
    "status": "{t} 현황(평소 대비)", "rank": "{t} 순위·비중", "location": "{t} 변화가 생긴 곳",
    "trend": "{t} 추이", "candidates": "밀어 볼 카테고리 후보", "levers": "{t} 수단 참고 자료",
    "promo": "프로모션 실적", "funnel_theme": "구매 단계 전환율",
}


@dataclass
class Choice:
    label: str
    query: Query
    why: bool = False


@dataclass
class Decision:
    kind: str                        # 'query' | 'message' | 'clarify'
    query: Query | None = None
    why: bool = False
    text: str = ""                   # message·clarify 문장
    choices: list[Choice] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # 기간을 자른 경우 등 (카드 주의에 붙인다)


def _msg(text: str) -> Decision:
    return Decision("message", text=text)


def out_of_data(question: str) -> Decision | None:
    """AI 호출 전에 쓰는 검사: 데이터에 없는 항목이면 정해진 안내."""
    hit = L.not_in_data(question)
    if not hit:
        return None
    name, alt = hit
    text = f"이 데이터에는 {name} 정보가 없어 답할 수 없습니다."
    if alt:
        text += f" {alt}"
    return _msg(text + f" (데이터에 있는 항목: {L.HAVE_IN_DATA})")


_EMPTY = {"", "null", "none", "없음", "n/a"}


def _field(d: dict, key: str) -> tuple:
    """(값, 근거). AI가 빈 값을 'null' 같은 글자로 적어도 빈 값으로 본다."""
    v = d.get(key) or {}
    if isinstance(v, str):
        v = {"value": v, "evidence": ""}
    val = v.get("value")
    val = None if val is None or str(val).strip().lower() in _EMPTY else val
    ev = v.get("evidence") or ""
    return val, ("" if ev.strip().lower() in _EMPTY else ev)


def _in_question(evidence: str, question: str) -> bool:
    return bool(evidence) and L.norm(evidence) in L.norm(question)


def _match_products(evidence: str, names: list[str]) -> list[str]:
    toks = [t for t in evidence.split() if len(t) >= 2] or [evidence]
    hits = [n for n in names if all(L.norm(t) in L.norm(n) for t in toks)]
    return hits or [n for n in names if any(L.norm(t) in L.norm(n) for t in toks)]


def validate(question: str, draft: dict, today, products: pd.DataFrame, prev: Query | None = None) -> Decision:
    """draft: AI 초안(dict). products: 상품 표(product_name, category). prev: 직전 질의서(이어지는 질문).

    순서: 데이터에 없는 항목 → 매핑 불가 → 기간 → 고객 조건 → 대상 → 나머지 칸 → 의도 → 측정값 보정 → 데이터 없는 기간
    """
    pre = out_of_data(question)
    if pre:
        return pre
    cats = sorted(products["category"].unique())
    names = sorted(products["product_name"].unique())
    # 기간 표현이나 사전에 있는 말이 든 항목은 '매핑 불가'로 인정하지 않는다(AI가 잘못 넣는 경우)
    unmapped = [u for u in (draft.get("unmapped") or [])
                if str(u).strip() and not PR.parse(str(u), today).text and not L.known_term(str(u), cats)
                and not L.generic_only(str(u))]
    if unmapped:
        return _msg(f"'{', '.join(unmapped)}'은(는) 이 데이터에 없는 항목이라 답할 수 없습니다. "
                    f"(데이터에 있는 항목: {L.HAVE_IN_DATA})")
    # 이어받기는 질문이 이어지는 형태일 때만 (AI의 inherit만으로는 이어받지 않는다)
    inherit = bool(draft.get("inherit")) and prev is not None and bool(L.FOLLOW_RE.search(question))
    notes: list[str] = []

    # 기간 (질문 원문 → 코드 규칙)
    per = PR.parse(question, today)
    period = per.dates
    if per.note:
        notes.append(per.note)
    if period is None and not per.text and inherit:
        period = prev.period

    # 고객 조건 (근거 표현이 질문에 있고 사전 동의어여야)
    filters: dict = dict(prev.filters) if inherit else {}
    for f in draft.get("filters") or []:
        key, val, ev = f.get("key"), f.get("value"), (f.get("evidence") or "").strip()
        if not _in_question(ev, question):
            continue                            # 질문에 근거 단어가 없는 조건 = 질문에 없는 조건 → 쓰지 않는다
        words = L.FILTER_WORDS.get(key, {})
        if key == "new_signup":
            val = True
        if key == "regions" and val not in words:   # '서울' 같은 줄임말 → 정식 이름
            val = next((k for k, ws in words.items() if L.norm(str(val)) in map(L.norm, ws)), val)
        if (key not in L.FILTER_WORDS or val not in words) and any(L.words_match(ev, ws) for ws in L.AXIS_WORDS.values()):
            continue                            # '연령대'처럼 구분 이름을 조건 값으로 적은 경우: 나눠 보기(축)로 처리된다
        if key not in L.FILTER_WORDS or val not in words:
            return _msg(f"'{ev}' 조건은 이 데이터로 나눌 수 없습니다. (데이터에 있는 항목: {L.HAVE_IN_DATA})")
        if not L.words_match(ev, words[val]):   # 질문 속 말을 다른 항목으로 바꿔 넣은 경우(예: 단톡방 → 카카오)
            return _msg(f"'{ev}'은(는) 이 데이터에 없는 구분이라 다른 조건으로 바꿔 계산하지 않았습니다. "
                        f"(데이터에 있는 항목: {L.HAVE_IN_DATA})")
        if key in ("age_groups", "regions", "signup_channels", "grades"):
            filters[key] = list(dict.fromkeys(list(filters.get(key, [])) + [val]))
        else:
            filters[key] = val

    # 나머지 칸 (대상·의도 제외)
    rest = _rest(draft, question)
    if isinstance(rest, Decision):
        return rest

    def make(intent="status", category=None, product=None) -> Query:
        return Query(intent, category=category, product=product, filters=filters, period=period, **rest)

    # 대상: 카테고리
    category = product = None
    cv, ce = _field(draft, "category")
    if not cv:
        found = L.category_in(question, cats)  # AI가 비웠어도 질문에 카테고리 말이 하나면
        if found:
            cv, ce = found, next(w for w in L.category_words(found) if L.norm(w) in L.norm(question))
    if cv:
        if cv not in cats:
            return _msg(f"'{cv}' 카테고리는 없습니다. 카테고리: {', '.join(cats)}")
        if (_in_question(ce, question) and L.words_match(ce, L.category_words(cv))) or (inherit and prev.category == cv):
            category = cv                       # 근거 없는 카테고리는 쓰지 않는다
    # 대상: 상품 (이름 일부로 찾고, 여러 개면 되묻는다)
    pv, pe = _field(draft, "product")
    pe = "" if L.known_term(pe, []) and not _match_products(_product_words(pe, cats), names) else _product_words(pe, cats)
    if not pe and not (inherit and prev.product):
        pe = _product_words(_mentioned_product(question, names, cats), cats)   # AI가 놓친 상품 언급
    if pv or pe:
        if pv in names and ((_in_question(pe, question) and L.words_match(pe, [pv] + pv.split()))
                            or (inherit and prev.product == pv)):
            product = pv
        elif pe:
            hits = _match_products(pe, names)
            if category:
                cat_of = products.drop_duplicates("product_name").set_index("product_name")["category"]
                hits = [h for h in hits if cat_of[h] == category] or hits
            if len(hits) == 1:
                product = hits[0]
            elif len(hits) > 1:
                why = bool(L.WHY_RE.search(question))
                intent = _intent(draft, why)
                return Decision("clarify", text=f"'{pe}'에 해당하는 상품이 여러 개입니다. 어느 상품인가요?",
                                choices=[Choice(h, make(intent if intent in INTENTS else "status", product=h), why)
                                         for h in hits[:4]], notes=notes)
            else:
                return _msg(f"'{pe}' 상품을 찾지 못했습니다. 상품 이름을 조금 더 정확히 적어 주십시오.")
    if product:
        category = None
    if inherit and not (category or product) and not (cv or pv or pe):
        category, product = prev.category, prev.product

    # 의도
    why = bool(L.WHY_RE.search(question))
    intent = _intent(draft, why, rest["axis"])
    if per.no_data and not per.alt:             # 데이터가 없는 기간이면 의도와 상관없이 안내
        return _msg(per.no_data)
    if per.no_data and intent not in INTENTS:
        intent = "status"
    if intent not in INTENTS:
        near = [i for i in (draft.get("near_intents") or []) if i in INTENTS]
        near = (near + [i for i in ("status", "location", "rank") if i not in near])[:3]
        t = product or category or "쇼핑몰"
        return Decision("clarify", text="어떤 것을 보시겠습니까?", notes=notes,
                        choices=[Choice(INTENT_LABEL[i].format(t=t), make(i, category, product), why) for i in near])
    try:
        q = make(intent, category, product)
    except ValueError as e:
        return _msg(str(e))
    # 매출: 카테고리·상품 대상이면 상품매출 (완료 매출·객단가는 주문 전체 금액이라 나눌 수 없다)
    if (q.category or q.product) and q.measure in ("완료 매출", "객단가"):
        notes.append(f"{q.category or q.product} 매출은 상품매출(쿠폰 차감 후 상품 금액, 배송비 제외)로 봅니다.")
        q = replace(q, measure="상품매출" if q.measure == "완료 매출" else None)
    # 데이터가 없는 기간
    if per.no_data:
        if per.alt:
            return Decision("clarify", text=per.no_data, notes=notes,
                            choices=[Choice(f"{name}로 보기", replace(q, period=dates), why) for name, dates in per.alt])
        return _msg(per.no_data)
    return Decision("query", q, why, notes=notes)


def _intent(draft: dict, why: bool, axis: str | None = None) -> str | None:
    intent = draft.get("intent")
    if why and intent in ("status", "trend", "unknown", None):
        return "location"                       # '왜'는 변화가 생긴 위치로 답한다
    if axis and axis not in ("category", "product") and intent in ("status", "trend", "rank", "unknown", None):
        return "location"                       # 고객·시간 등으로 나눠 보기(근거 있는 축)는 변화 위치에만 있다
    return intent


def _product_words(evidence: str, cats: list[str]) -> str:
    """상품 근거에서 일반어·카테고리 말을 뺀 나머지 (예: '음료 매출 1위 상품은?' → '')."""
    cat_words = {L.norm(w) for c in cats for w in L.category_words(c)}
    toks = [t for t in (evidence or "").replace("?", " ").split()
            if L.norm(t) not in L.STOP_WORDS and L.norm(t) not in cat_words and not PR.parse(t, PR.pd.Timestamp("2026-12-31")).text
            and L.norm(t).rstrip("은는이가을를의") not in L.STOP_WORDS | cat_words]
    return " ".join(toks)


def _mentioned_product(question: str, names: list[str], cats: list[str]) -> str:
    """질문에 상품 이름 단어(예: 삼겹살)가 있으면 그 단어들. AI가 상품을 놓쳐도 범위가 조용히 바뀌지 않게."""
    toks = L.product_tokens(names, cats)
    found = [w for w in re.split(r"[\s?!.,]+", question) if L.norm(w).rstrip("은는이가을를의도") in toks]
    return " ".join(L.norm(w).rstrip("은는이가을를의도") for w in found)


def _rest(draft: dict, question: str) -> dict:
    """의도·대상·조건·기간을 뺀 칸. 근거 없는 축과 상품 순위 기준은 쓰지 않는다(계산 함수 기본값)."""
    measure = draft.get("measure") if draft.get("measure") in MEASURE_UNIT else None
    av, ae = _field(draft, "axis")
    axis = av if av in AXES and _in_question(ae, question) and L.words_match(ae, L.AXIS_WORDS[av]) else None
    if axis is None and av is None:
        axis = L.axis_in(question)              # AI가 축을 비웠어도 질문에 구분 이름이 있으면
    group_by = draft.get("group_by") if draft.get("group_by") in ("category", "product") else None
    if group_by == "product" and not L.words_match(question, L.AXIS_WORDS["product"]):
        group_by = None
    n = draft.get("n")
    return {"measure": measure, "axis": axis, "group_by": group_by,
            "direction": draft.get("direction") if draft.get("direction") in ("down", "up") else None,
            "n": n if isinstance(n, int) and 0 < n <= 30 else None,
            "topic": draft.get("topic") if draft.get("topic") in ("funnel", "theme") else None,
            "path": draft.get("path") if draft.get("path") in ("ALL", "CURATION", "BROWSE") else None}

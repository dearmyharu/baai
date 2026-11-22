"""답변 카드: 계산 결과(Result) → 카드 한 장. 문장은 모두 이 파일의 정해진 틀로 만든다(AI 없음).

카드 = 조건 태그 + 결론 한 줄 + 숫자 최대 3개 + 주의 한 줄 (+ '왜' 질문이면 고정 안내 한 줄).
숫자는 모두 Result.key에서 가져온다. 이 파일은 계산하지 않는다(표기만).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import basis as S
from . import fmt as F
from .compute import KIND_DOWN, KIND_MARGIN, KIND_UP, NO_REASON
from .query import MEASURE_UNIT, Result

WHY_LEAD = "왜 그런지는 이 데이터로 알 수 없어, 변화가 생긴 위치를 보여 드립니다."
WHY_LEAD_PLAIN = "왜 그런지는 이 데이터로 알 수 없습니다. 확인된 숫자만 보여 드립니다."
TONE = {S.LEVEL_LOW: "down", S.LEVEL_HIGH: "up", S.LEVEL_NORMAL: "flat", S.LEVEL_NA: "flat", "–": "flat"}


@dataclass
class Number:
    label: str
    value: str
    delta: str = ""
    tone: str = "flat"          # down | up | flat (화살표·색)


@dataclass
class Card:
    tags: list[str]
    conclusion: str
    numbers: list[Number] = field(default_factory=list)
    note: str = ""
    lead: str = ""              # '왜' 질문일 때 맨 위 고정 안내
    has_dashboard: bool = False
    title: str = ""

    def text(self) -> str:
        """글자만으로 본 카드(평가·기록용)."""
        out = []
        if self.tags:
            out.append(" · ".join(self.tags))
        if self.lead:
            out.append(self.lead)
        out.append(self.conclusion)
        out += [f"- {n.label}: {n.value}" + (f" ({n.delta})" if n.delta else "") for n in self.numbers]
        if self.note:
            out.append(f"참고: {self.note}")
        return "\n".join(out)


def _josa(word: str, pair: str) -> str:
    """받침에 맞는 조사. pair: '은는' '이가' '을를' '과와' '으로로'."""
    ch = word.rstrip(")）'\" ")[-1:] or "가"
    code = ord(ch) - 0xAC00
    if 0 <= code < 11172:
        has = code % 28 != 0
        rieul = code % 28 == 8
    else:                                   # 숫자·영문: 읽는 소리 대신 보수적으로 받침 있음
        has, rieul = ch not in "2459", False
    if pair == "으로로":
        return "로" if (not has or rieul) else "으로"
    return pair[0] if has else pair[1]


def _base_word(base_name: str) -> str:
    """비교 기준 이름 → 문장 속 말. 지난 4주 같은 요일 = '평소'."""
    return "평소" if base_name.startswith("지난 ") and "주" in base_name else base_name


def _short(window: str) -> str:
    """'최근 3일(10/23~10/25)' → '최근 3일'. 날짜는 태그에 있다."""
    return window.split("(")[0] if window.startswith("최근") else window


def _rate_phrase(rate, level: str, base_name: str = "지난 4주 같은 요일") -> str:
    w = _base_word(base_name)
    if rate is None or pd.isna(rate):
        return "비교할 이전 데이터가 없습니다"
    if level == S.LEVEL_NORMAL:
        return (f"{w}{_josa(w, '과와')} 비슷한 수준입니다({F.pct_signed(rate)})" if w != "평소"
                else f"평소 수준입니다({F.pct_signed(rate)})")
    return f"{w}보다 {abs(rate) * 100:.0f}% {'낮습니다' if rate < 0 else '높습니다'}"


def _names(xs) -> str:
    return ", ".join(xs)


def _note(r: Result, skip: tuple[str, ...] = ()) -> str:
    """주의 한 줄: 표본 적음 > 일수 다름 > 나머지 순서로 하나."""
    notes = [n for n in r.notes if n not in skip]
    for key in ("흔들릴", "일수가 달라", "평소 범위"):
        for n in notes:
            if key in n:
                return n
    return notes[0] if notes else ""


# ---------------------------------------------------------------------------
def _status(r: Result) -> Card:
    k = r.key
    w0 = k["windows"][0]
    unit = MEASURE_UNIT[k["measure"]]
    if k["measure"] == "이익률":
        concl = (f"{k['target']} 이익률은 {_short(w0['window'])} {F.value(w0['현재'], unit)}입니다"
                 f"({_base_word(w0['base_name'])} 대비 {F.pp_signed(w0['변화'])}).")
    else:
        v = F.value(w0['현재'], unit)
        concl = (f"{k['target']} {k['measure']}{_josa(k['measure'], '은는')} {_short(w0['window'])} {v}"
                 f"{_josa(v, '으로로')} {_rate_phrase(w0['변화율'], w0['판정'], w0['base_name'])}.")
    nums = [Number(f"{_short(w['window'])} {k['measure']}", F.value(w["현재"], unit),
                   F.pp_signed(w["변화"]) if k["measure"] == "이익률" else
                   (f"{F.pct_signed(w['변화율'])} · {_base_word(w['base_name'])} {F.value(w['평소'], unit)}"
                    if w["평소"] is not None else "비교 불가"),
                   TONE.get(w["판정"], "flat")) for w in k["windows"]]
    return Card(r.tags, concl, nums[:3], _note(r))


def _rank(r: Result) -> Card:
    k = r.key
    unit = MEASURE_UNIT[k["measure"]]
    if not k["top"]:
        return Card(r.tags, f"{k['period']} 기간에 {k['measure']} 기록이 없습니다.", [], _note(r))
    name, v = k["top"][0]
    concl = f"{k['period']} {k['by']}별 {k['measure']} 1위는 {name}({F.value(v, unit)})입니다."
    nums = []
    tbl = r.table
    for i, (n, val) in enumerate(k["top"], 1):
        share = tbl.loc[i - 1, "비중"] if "비중" in tbl else ""
        nums.append(Number(f"{i}위 {n}", F.value(val, unit), f"비중 {share}" if share else ""))
    return Card(r.tags, concl, nums, _note(r))


def _location(r: Result, why: bool) -> Card:
    k = r.key
    unit = MEASURE_UNIT[k["measure"]]
    t = k["total"]
    m = k["measure"]
    head = f"{k['target']} {m}{_josa(m, '은는')} {_short(k['window'])} {_rate_phrase(t['변화율'], t['판정'], k['base_name'])}"
    noun = "감소분" if k["direction"] == "down" else "증가분"
    if k["top"]:
        names = _names(n for n, _, _ in k["top"])
        concl = f"{head.rstrip('.')}. {k['axis']}별로 보면 {noun}의 {F.pct(k['top_share'])}가 {names}에서 나왔습니다."
    else:
        concl = f"{head.rstrip('.')}. {k['axis']}별로 {('줄어든' if k['direction'] == 'down' else '늘어난')} 곳이 없습니다."
    nums = [Number(f"{n}", F.won_signed(v) if unit == "won" else F.count(v, "개"),
                   f"{noun}의 {F.pct(s)}" if pd.notna(s) else "", "down" if v < 0 else "up")
            for n, v, s in k["top"]]
    return Card(r.tags, concl, nums[:3], _note(r, skip=(NO_REASON,)), WHY_LEAD if why else "")


def _trend(r: Result) -> Card:
    k = r.key
    unit = MEASURE_UNIT[k["measure"]]
    if not k["high"]:
        return Card(r.tags, f"{k['target']} {k['measure']} 기록이 없습니다.", [], _note(r))
    g = " 주" if k["grain"] == "주" else ""
    (hd, hv), (ld, lv) = k["high"], k["low"]
    concl = (f"{k['target']} {k['grain']}별 {k['measure']}{_josa(k['measure'], '은는')} {F.day(hd)}{g}가 가장 높았고"
             f"({F.value(hv, unit)}), {F.day(ld)}{g}가 가장 낮았습니다({F.value(lv, unit)}).")
    nums = [Number(f"최고 {F.day(hd)}{g}", F.value(hv, unit), tone="up"),
            Number(f"최저 {F.day(ld)}{g}", F.value(lv, unit), tone="down")]
    return Card(r.tags, concl, nums, _note(r))


def _candidates(r: Result) -> Card:
    k = r.key
    bk = k["by_kind"]
    if k["category"]:
        kinds = [kind for kind, cats in bk.items() if k["category"] in cats]
        cat = k["category"]
        concl = (f"{cat}{_josa(cat, '은는')} '{' / '.join(kinds)}' 후보입니다." if kinds
                 else f"{cat}{_josa(cat, '은는')} 지금 기준으로 후보에 해당하지 않습니다.")
        nums = [Number(row["유형"], row["근거"], row["최근 프로모션"]) for _, row in r.table.iterrows()]
        return Card(r.tags, concl, nums[:3], "기준에 걸친 경계 사례는 근거 숫자를 보고 판단하십시오.")
    else:
        concl = (f"지금 기준에 해당하는 카테고리는 줄고 있음 {len(bk[KIND_DOWN])}곳, 오르고 있음 {len(bk[KIND_UP])}곳, "
                 f"마진 낮음 {len(bk[KIND_MARGIN])}곳입니다.")
    tone = {KIND_DOWN: "down", KIND_UP: "up", KIND_MARGIN: "flat"}
    nums = [Number(kind, _names(cats) if cats else "없음", tone=tone[kind]) for kind, cats in bk.items()]
    return Card(r.tags, concl, nums, "기준에 걸친 경계 사례는 표의 근거 숫자를 보고 판단하십시오.")


def _levers(r: Result) -> Card:
    k = r.key
    concl = (f"{k['target']} 최근 28일 이익률은 {F.pct(k['margin'], 1)}이고, "
             f"쿠폰을 쓴 주문은 {F.pct(k['coupon_share'], 1)}입니다.")
    nums = [Number("이익률", F.pct(k["margin"], 1)),
            Number("쿠폰 쓴 주문 이익률", F.pct(k["margin_coupon"], 1), f"안 쓴 주문 {F.pct(k['margin_no_coupon'], 1)}"),
            Number(f"무료배송 기준({S.FREE_SHIP_THRESHOLD:,}원) 미만 주문", F.pct(k["under_free_ship"], 1))]
    return Card(r.tags, concl, nums, r.notes[0])


def _promo(r: Result) -> Card:
    ps = r.key["promos"]
    if not ps:
        return Card(r.tags, r.facts[0], [], "")
    if len(ps) == 1:
        n, ph, st = ps[0]
        concl = f"{n}{_josa(n, '은는')} {ph}이고, 판정은 '{st}'입니다."
    else:
        concl = f"프로모션 {r.key['count']}: " + ", ".join(f"{n} '{st}'" for n, _, st in ps) + "."
    tone = {"효과 있음": "up", "중단 검토": "down"}
    nums = []
    for (n, ph, st), row in zip(ps, r.table.itertuples(index=False)):
        nums.append(Number(n, st, f"{ph} · 대상 일평균 매출 {row[4]}", tone.get(st, "flat")))
    return Card(r.tags, concl, nums[:3], r.notes[0])


def _funnel_theme(r: Result) -> Card:
    k = r.key
    if k["topic"] == "funnel":
        concl = (f"{k['path']} 방문 {F.count(k['sessions'], '세션')} 중 {F.pct(k['conv'], 1)}가 구매를 완료했고, "
                 f"넘어가는 비율이 가장 낮은 단계는 {k['worst']}({F.pct(k['worst_rate'], 1)})입니다.")
        nums = [Number("구매 완료", F.pct(k["conv"], 1)), Number(k["worst"], F.pct(k["worst_rate"], 1), tone="down")]
        return Card(r.tags, concl, nums, _note(r))
    concl = (f"구매 전환율이 가장 높은 테마는 {k['best']}({F.pct(k['best_rate'], 1)})이고, "
             f"클릭률이 가장 높은 테마는 {k['click']}({F.pct(k['click_rate'], 1)})입니다.")
    nums = [Number(f"구매 전환율 1위 {k['best']}", F.pct(k["best_rate"], 1)),
            Number(f"클릭률 1위 {k['click']}", F.pct(k["click_rate"], 1))]
    return Card(r.tags, concl, nums, _note(r))


BUILDERS = {"status": _status, "rank": _rank, "trend": _trend, "candidates": _candidates,
            "levers": _levers, "promo": _promo, "funnel_theme": _funnel_theme}


def card(r: Result, why: bool = False) -> Card:
    """계산 결과 → 답변 카드. why=True는 '왜' 질문(변화 위치로 답할 때 고정 안내를 붙인다)."""
    c = _location(r, why) if r.intent == "location" else BUILDERS[r.intent](r)
    c.has_dashboard = r.table is not None or r.chart is not None
    c.title = r.title
    if why and r.intent != "location":
        c.lead = WHY_LEAD_PLAIN
    return c


def message(text: str, tags: list[str] | None = None) -> Card:
    """계산 없이 정해진 안내(데이터 없음·범위 밖 등)."""
    return Card(tags or [], text)

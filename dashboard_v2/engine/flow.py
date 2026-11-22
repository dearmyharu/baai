"""흐름 관리: '누구에게(어느 카테고리에) 무엇으로 밀까'를 찾아가는 상태와 다음 행동 버튼, Growth Lab 넘김.

원칙 (2026-11-22 결정)
- 대상 카테고리는 실무자가 '대상으로 정하기'를 눌러야만 정해진다(브리핑에서 들어왔다고 자동 지정하지 않음).
- 수단은 기본값 없이 실무자가 눌러야 정해진다. 지켜보기·묶음 할인은 선택지에 없다(묶음 할인은 상품 대상 전용).
- 가설 문장을 만들지 않는다. Growth Lab으로 넘기는 대상은 카테고리만.
- 다음 행동 버튼은 완성된 질의서를 들고 있어, 누르면 AI 없이 바로 계산한다.
이 파일은 streamlit을 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import basis as S
from . import compute as C
from .query import AXES, Query

STOP_PP = 8          # Growth Lab 중단 기준: 이익률이 시작 전보다 8%p 넘게 떨어지면
LEVERS = [           # (정책, 값, 이름) — Growth Lab(simulation) 수단 형식. 값: 판매가·쿠폰은 %, 무료배송은 기준 금액
    ("price", 5, "판매가 5% 할인"),
    ("price", 10, "판매가 10% 할인"),
    ("discount", 5, "주문 쿠폰 5%"),
    ("shipping", 20000, "무료배송 2만원 이상"),     # 현재 기준 3만원
]
STEP_NAMES = ["원인 좁히기", "어디를 밀까", "무엇으로 밀까", "확인 가능"]
NEXT_AXES = ["product", "customer_type", "daypart", "weekday", "path", "age_group", "gender", "region",
             "visitor_type", "signup_channel", "grade_at_order"]     # 다음 축 제안 순서


@dataclass
class Action:
    label: str
    kind: str                     # 'query' | 'set_target' | 'set_lever' | 'handoff'
    query: Query | None = None
    value: object = None


@dataclass
class Flow:
    target: str | None = None                                   # 대상 카테고리 (실무자가 정함)
    lever: dict | None = None                                   # {'policy','value','label'} (실무자가 정함)
    seen: dict[str, list[str]] = field(default_factory=dict)    # 카테고리 → 이미 본 축
    facts: dict[str, list[str]] = field(default_factory=dict)   # 카테고리 → 변화 위치 사실 문장(넘김 근거)
    question: str = ""                                          # 대상을 정한 시점의 질문

    # ---- 상태 바꾸기 -------------------------------------------------------
    def record(self, question: str, query: Query | None, result) -> None:
        """답이 나올 때마다 부른다. 변화 위치를 본 축과 사실 문장을 카테고리별로 기억한다."""
        if result is None or query is None or result.intent != "location" or not query.category:
            return
        cat, ax = query.category, result.key["axis_key"]
        self.seen.setdefault(cat, [])
        if ax not in self.seen[cat]:
            self.seen[cat].append(ax)
        self.facts.setdefault(cat, [])
        for f in result.facts[:2]:
            if f not in self.facts[cat]:
                self.facts[cat].append(f)
        self._last_question = question

    def set_target(self, category: str, question: str = "") -> None:
        if category != self.target:
            self.lever = None                   # 대상이 바뀌면 수단도 다시 고른다
        self.target = category
        self.question = question or getattr(self, "_last_question", "")

    def set_lever(self, policy: str, value: float) -> None:
        if not self.target:
            raise ValueError("대상 카테고리를 먼저 정해야 수단을 고를 수 있습니다.")
        label = next(lb for p, v, lb in LEVERS if p == policy and v == value)
        self.lever = {"policy": policy, "value": value, "label": label}

    def reset(self) -> None:
        self.__init__()

    # ---- 진행 상태 ---------------------------------------------------------
    def steps(self, m: dict, today) -> list[dict]:
        """진행 표시줄: [{'name','done','text'}]. 확인 가능은 대상이 정해진 뒤 계산."""
        t = self.target
        seen = [AXES[a] for a in self.seen.get(t, [])] if t else []
        testable, why = (None, "")
        if t:
            g = C.candidate_table(m, Query("candidates"), today)
            r = g.loc[t]
            testable = bool(r["testable"])
            why = "가능" if testable else f"어려움(하루 주문 {r['daily_orders']:.1f}건)"
        return [
            {"name": STEP_NAMES[0], "done": bool(seen), "text": "·".join(seen) if seen else "변화 위치를 아직 안 봄"},
            {"name": STEP_NAMES[1], "done": bool(t), "text": t or "대상 미정"},
            {"name": STEP_NAMES[2], "done": bool(self.lever), "text": self.lever["label"] if self.lever else "수단 미정"},
            {"name": STEP_NAMES[3], "done": bool(testable), "text": why or "대상 미정"},
        ]

    def ready(self, m: dict, today) -> bool:
        return all(s["done"] for s in self.steps(m, today))

    # ---- 다음 행동 버튼 ----------------------------------------------------
    def actions(self, query: Query | None, result) -> list[Action]:
        """답 아래에 보여 줄 버튼 (최대 4개)."""
        out: list[Action] = []
        if result is not None and query is not None:
            cat = query.category
            if result.intent == "location":
                left = [a for a in NEXT_AXES if a in result.axes_left and a not in self.seen.get(cat or "", [])]
                out += [Action(f"{AXES[a]}별로 보기", "query", replace(query, axis=a)) for a in left[:2]]
                if not cat and result.key["axis_key"] == "category":      # 쇼핑몰 전체 → 많이 변한 카테고리로 들어가기
                    out += [Action(f"{name} 변화 위치 보기", "query", Query("location", category=name))
                            for name, _, _ in result.key["top"][:2]]
            if result.intent == "candidates" and not cat:
                names = [c for kind in (C.KIND_DOWN, C.KIND_UP, C.KIND_MARGIN) for c in result.key["by_kind"][kind]]
                out += [Action(f"{c} 변화 위치 보기", "query", Query("location", category=c))
                        for c in list(dict.fromkeys(names))[:3]]
            if cat and cat != self.target and result.intent in ("status", "location", "candidates", "levers", "trend"):
                out.append(Action(f"{cat}{_josa(cat)} 대상으로 정하기", "set_target", value=cat))
        if self.target and not self.lever:
            if not (result is not None and result.intent == "levers" and query and query.category == self.target):
                out.append(Action(f"{self.target} 수단 참고 자료", "query", Query("levers", category=self.target)))
        return out[:4]

    def lever_actions(self) -> list[Action]:
        """대상이 정해졌을 때 고를 수 있는 수단 (기본값 없음)."""
        if not self.target:
            return []
        return [Action(lb, "set_lever", value=(p, v)) for p, v, lb in LEVERS]

    # ---- Growth Lab 넘김 ---------------------------------------------------
    def lab_request(self, m: dict, today) -> dict:
        """Growth Lab 요청 (docs/GrowthLab_인계.md 3-2 형식). 대상은 카테고리. 가설 문장은 넣지 않는다."""
        if not self.ready(m, today):
            raise ValueError("넘김 조건(원인 좁히기·대상·수단·확인 가능)이 다 갖춰지지 않았습니다.")
        t, lv = self.target, self.lever
        o, it = S.ledger(m)
        cb = S.compare_both(S.daily(o, it[it["category"].eq(t)].assign(_t=t), "상품매출", by="_t"), today).iloc[0]
        lab = S.window_labels(today)
        target_text = f"{t} 카테고리"
        return {
            "type": "plan",
            "question": self.question,
            "diagnosis": {"metric": f"{target_text} 상품매출",
                          "value": cb["7일_현재"], "base": cb["7일_평소"], "change": cb["7일_변화율"], "period": lab[7]["현재"],
                          "sales3": cb["3일_현재"], "base3": cb["3일_평소"], "change3": cb["3일_변화율"], "period3": lab[3]["현재"]},
            "target": {"type": "category", "value": t},
            "lever": {"policy": lv["policy"], "value": -lv["value"] if lv["policy"] == "price" else lv["value"]},
            "hypothesis": "",                  # 가설은 실무자가 세운다(시스템이 쓰지 않음)
            "cause_hypothesis": "",
            "primary_metric": f"{target_text} 일평균 매출",
            "guard_metric": f"{target_text} 이익률",
            "stop_rule": f"{target_text} 이익률이 시작 전보다 {STOP_PP}%p 넘게 떨어지면 중단",
            "evidence": list(self.facts.get(t, []))[:4],
        }


def _josa(word: str) -> str:
    ch = word[-1]
    code = ord(ch) - 0xAC00
    return ("을" if code % 28 else "를") if 0 <= code < 11172 else "을"


def summary(flow: Flow, m: dict, today) -> str:
    """진행 표시줄 한 줄 글자판 (기록·평가용)."""
    return " → ".join(f"{s['name']}: {'✓' if s['done'] else '·'} {s['text']}" for s in flow.steps(m, today))

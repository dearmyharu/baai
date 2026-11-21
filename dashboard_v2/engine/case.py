"""AI 분석가의 '분석 흐름': 진단 → 원인 → 가설 → 실험 → 판정 조건을 코드가 확인한다.

- 모델은 질문에 답하고 대상·수단 후보(campaign 칸)를 낼 뿐, 다음 단계로 넘어갈지는 이 파일이 정한다.
- 조건이 빠지면 빠진 조건을 선택지로 되묻는다(missing_question).
- 다섯 조건이 모두 갖춰져야 Growth Lab 요청(lab_request)을 만든다. 형식은 docs/GrowthLab_인계.md 3-2.
- 숫자는 모두 이 파일이 계산한다(진단 수치, 확인 가능성).
"""
from __future__ import annotations

import pandas as pd

from . import briefing as B

STEPS = ["진단", "원인", "가설", "실험", "판정"]
STOP_PP = 8                       # 기본 중단 기준: 이익률 8%p 넘게 하락
MIN_DAILY_ORDERS = 1.0            # 실험 가능: 대상 주문이 하루 평균 1건 이상
MIN_SALE_DAYS = 0.6               # 실험 가능: 최근 28일 중 60% 이상 판매가 있는 날

# Growth Lab(simulation.POLICIES)이 다루는 수단과 기본 선택지
LEVERS = {
    "price": {"label": "판매가 할인", "unit": "%", "choices": [5, 10, 15]},
    "discount": {"label": "주문 쿠폰(정률)", "unit": "%", "choices": [5, 10]},
    "shipping": {"label": "무료배송 기준 낮추기", "unit": "원", "choices": [20000, 10000]},   # 현재 기준 30,000원
    "bundle": {"label": "묶음 할인", "unit": "%", "choices": [5, 10]},
}


def new_case() -> dict:
    return {"question": "", "target": None, "lever": None, "hypothesis": "", "evidence": [], "candidates": []}


def lever_text(lever: dict | None) -> str:
    if not lever:
        return ""
    info = LEVERS.get(lever["policy"], {"label": lever["policy"], "unit": ""})
    v = lever["value"]
    val = f"{v:,.0f}원" if info["unit"] == "원" else f"{v:g}%"
    return f"{info['label']} {val}"


def target_text(target: dict | None) -> str:
    if not target:
        return ""
    return f"{target['value']} 카테고리" if target["type"] == "category" else target["value"]


# ---------------------------------------------------------------------------
# 진단·확인 가능성 (코드 계산)
# ---------------------------------------------------------------------------
def _target_items(it: pd.DataFrame, target: dict) -> pd.DataFrame:
    if target["type"] == "category":
        return it[it["category"].eq(target["value"])]
    return it[it["product_name"].eq(target["value"])]


def diagnose(m: dict, target: dict, today) -> dict | None:
    """대상의 최근 7일 일평균 매출 vs 직전 28일 일평균(요일 구성이 같음). 실험 가능 여부도 함께."""
    t = pd.Timestamp(today).normalize()
    y = t - pd.Timedelta(days=1)
    _, it = B.ledger(m)
    x = _target_items(it[it["date"] <= y], target)
    if x.empty:
        return None
    d = x.groupby("date").agg(sales=("net_sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
    idx = pd.date_range(y - pd.Timedelta(days=34), y, freq="D")
    d = d.reindex(idx, fill_value=0)
    cur, base = d.iloc[-7:], d.iloc[:-7]
    value, base_v = float(cur["sales"].mean()), float(base["sales"].mean())
    # 최근 3일 vs 지난 4주 같은 요일 3일 평균 (아침 브리핑과 같은 기준)
    v3 = float(d["sales"].iloc[-3:].sum())
    b3 = [float(d["sales"].reindex(pd.date_range(y - pd.Timedelta(days=7 * k + 2), y - pd.Timedelta(days=7 * k)),
                                   fill_value=0).sum()) for k in range(1, 5)]
    b3m = sum(b3) / 4
    margin = float(d["profit"].sum() / d["sales"].sum()) if d["sales"].sum() else None
    last28 = d.iloc[-28:]
    daily_orders = float(last28["orders"].mean())
    sale_days = float((last28["orders"] > 0).mean())
    name = target_text(target)
    return {"metric": f"{name} 일평균 매출", "value": value, "base": base_v,
            "sales3": v3, "base3": b3m, "change3": (v3 / b3m - 1) if b3m else None,
            "period3": [f"{y - pd.Timedelta(days=2):%Y-%m-%d}", f"{y:%Y-%m-%d}"],
            "change": (value / base_v - 1) if base_v else None,
            "period": [f"{y - pd.Timedelta(days=6):%Y-%m-%d}", f"{y:%Y-%m-%d}"],
            "base_period": [f"{idx[0]:%Y-%m-%d}", f"{y - pd.Timedelta(days=7):%Y-%m-%d}"],
            "margin": margin, "daily_orders": daily_orders, "sale_days": sale_days,
            "testable": daily_orders >= MIN_DAILY_ORDERS and sale_days >= MIN_SALE_DAYS}


def diag_text(diag: dict) -> str:
    s = f"최근 7일 일평균 {B._won(diag['value'])} · 직전 4주 {B._won(diag['base'])} ({diag['change']:+.0%})"
    if diag.get("change3") is not None:
        s += f" / 최근 3일 {B._won(diag['sales3'])} · 지난 4주 같은 요일 {B._won(diag['base3'])} ({diag['change3']:+.0%})"
    return s


def check(case: dict, diag: dict | None) -> list[dict]:
    """다섯 조건의 충족 여부와 한 줄 설명."""
    t, lv = case.get("target"), case.get("lever")
    out = []
    if diag and diag["change"] is not None:
        out.append({"step": "진단", "ok": True, "note": diag_text(diag)})
    else:
        out.append({"step": "진단", "ok": False, "note": "대상을 정하면 최근 7일 변화를 계산합니다"})
    out.append({"step": "원인", "ok": bool(t), "note": target_text(t) if t else "어디서 생긴 변화인지(대상) 미정"})
    out.append({"step": "가설", "ok": bool(t and lv),
                "note": f"{target_text(t)}에 {lever_text(lv)} → 매출 회복" if t and lv else "무엇으로 밀지(수단) 미정"})
    if diag:
        ok = diag["testable"]
        out.append({"step": "실험", "ok": ok,
                    "note": (f"최근 28일 하루 평균 주문 {diag['daily_orders']:.1f}건 · 판매일 {diag['sale_days']:.0%}"
                             + ("" if ok else " → 주문이 적어 효과 확인이 어렵습니다. 카테고리로 넓히는 것을 권합니다"))})
    else:
        out.append({"step": "실험", "ok": False, "note": "대상이 정해지면 확인합니다"})
    if t and diag:
        out.append({"step": "판정", "ok": True,
                    "note": f"주 지표 {diag['metric']} · 짝 지표 이익률(현재 {diag['margin']:.0%}) · 중단 기준 {STOP_PP}%p 하락"
                    if diag["margin"] is not None else f"주 지표 {diag['metric']} · 짝 지표 이익률"})
    else:
        out.append({"step": "판정", "ok": False, "note": "대상이 정해지면 주 지표·짝 지표를 정합니다"})
    return out


def ready(checks: list[dict]) -> bool:
    return all(c["ok"] for c in checks)


# ---------------------------------------------------------------------------
# 대화에서 대상·수단 받기
# ---------------------------------------------------------------------------
def _from_campaign(m: dict, camp: dict | None) -> tuple[list[dict], dict | None]:
    """모델의 campaign 칸 → 대상 후보 목록, 수단."""
    if not camp or not camp.get("target"):
        return [], None
    cats = set(m["raw"]["product"]["category"].unique())
    names = set(m["raw"]["product"]["product_name"].unique())
    cands = [{"type": "category", "value": c} for c in camp.get("categories", []) if c in cats]
    cands += [{"type": "product", "value": p} for p in camp.get("products", []) if p in names]
    lever = None
    pol, val = camp.get("policy"), camp.get("policy_value") or 0
    if pol in LEVERS and val:
        v = abs(float(val))
        if pol == "discount" and v > 100:     # 정액으로 답한 경우는 받지 않는다(정률 % 기준)
            v = 0
        lever = {"policy": pol, "value": v} if v else None
    return cands, lever


def _from_simulation(calls: list[dict]) -> dict | None:
    """대화 중 정책 손익 계산(simulate_policy)을 했다면 그 정책을 수단으로 받는다."""
    for c in reversed(calls or []):
        if c.get("tool") != "simulate_policy" or "result" not in c:
            continue
        pc = (c.get("params") or {}).get("policy_config") or {}
        pol = pc.get("policy")
        if pol == "price" and pc.get("price_change_pct"):
            return {"policy": "price", "value": abs(float(pc["price_change_pct"]))}
        if pol == "discount" and pc.get("discount_value") and pc.get("discount_type", "rate") == "rate":
            return {"policy": "discount", "value": float(pc["discount_value"])}
        if pol == "bundle" and pc.get("bundle_discount_pct"):
            return {"policy": "bundle", "value": float(pc["bundle_discount_pct"])}
        if pol == "shipping" and pc.get("free_shipping_threshold"):
            return {"policy": "shipping", "value": float(pc["free_shipping_threshold"])}
    return None


def update(case: dict, m: dict, answer: dict | None, question: str, calls: list[dict] | None = None) -> None:
    """답변 하나를 받은 뒤 분석 흐름을 갱신한다. 대상 후보가 하나뿐이면 자동으로 정하고, 여럿이면 되묻는다."""
    if not case.get("question"):
        case["question"] = question
    case.setdefault("asked", []).append(question)
    sim = _from_simulation(calls)
    if sim:
        case["lever"] = sim
    if not answer:
        return
    cands, lever = _from_campaign(m, answer.get("campaign"))
    if cands:
        case["candidates"] = cands
        if not case.get("target") and len(cands) == 1:
            case["target"] = cands[0]
    if lever and not case.get("lever"):
        case["lever"] = lever
    if answer.get("hypothesis") and not case.get("hypothesis"):
        case["hypothesis"] = answer["hypothesis"]
    for e in answer.get("evidence", []):
        if e not in case["evidence"]:
            case["evidence"].append(e)
    case["evidence"] = case["evidence"][-6:]


# ---------------------------------------------------------------------------
# 다음 단계: 빠진 조건 되묻기 + 원인 좁히기 질문 (코드가 정함)
# ---------------------------------------------------------------------------
def declining_categories(m: dict, today, n: int = 3) -> list[str]:
    t = pd.Timestamp(today).normalize()
    y = t - pd.Timedelta(days=1)
    _, it = B.ledger(m)
    x = it[(it["date"] > y - pd.Timedelta(days=35)) & (it["date"] <= y)]
    cur = x[x["date"] > y - pd.Timedelta(days=7)].groupby("category")["net_sales"].sum() / 7
    base = x[x["date"] <= y - pd.Timedelta(days=7)].groupby("category")["net_sales"].sum() / 28
    diff = (cur.reindex(base.index, fill_value=0) - base).sort_values()
    return [c for c, v in diff.items() if v < 0][:n]


def missing_question(case: dict, m: dict, today, checks: list[dict]) -> dict | None:
    """가장 먼저 빠진 조건 하나를 선택지로 묻는다. 반환: {step, text, choices: [{label, set: {...}}]}"""
    ok = {c["step"]: c["ok"] for c in checks}
    if not ok["원인"]:
        cands = case.get("candidates") or [{"type": "category", "value": c} for c in declining_categories(m, today)]
        if not cands:
            return None
        return {"step": "원인", "text": "Growth Lab으로 넘기려면 대상을 먼저 정해야 합니다. 어느 대상으로 진행할지 선택해 주십시오.",
                "choices": [{"label": target_text(c), "set": {"target": c}} for c in cands[:4]]}
    if not ok["실험"]:
        t = case["target"]
        if t["type"] == "product":
            cat = m["raw"]["product"].set_index("product_name")["category"].get(t["value"])
            if cat:
                return {"step": "실험", "text": f"{t['value']}는 주문이 적어 효과를 확인하기 어렵습니다. 범위를 넓힐지 선택해 주십시오.",
                        "choices": [{"label": f"{cat} 카테고리로 넓히기", "set": {"target": {"type": "category", "value": cat}}}]}
        return {"step": "실험", "text": "대상의 주문이 적어 효과를 확인하기 어렵습니다. 다른 대상을 선택해 주십시오.",
                "choices": [{"label": c, "set": {"target": {"type": "category", "value": c}}}
                            for c in declining_categories(m, today)]}
    if not ok["가설"]:
        opts = [("price", 5), ("price", 10), ("discount", 5), ("bundle", 5), ("shipping", 20000)]
        choices = [{"label": lever_text({"policy": p, "value": v}), "set": {"lever": {"policy": p, "value": v}}}
                   for p, v in opts]
        return {"step": "가설", "text": f"{target_text(case['target'])}에 어떤 수단을 쓸지 선택해 주십시오. "
                                        "효과는 Growth Lab에서 손익과 함께 확인합니다.", "choices": choices}
    return None


def next_questions(case: dict) -> list[str]:
    """원인 좁히기 질문(지금 데이터로 답할 수 있는 것만). 이미 물은 질문은 뺀다."""
    asked = case.get("asked", [])
    return [q for q in _next_questions(case) if not any(q.rstrip("?") in a for a in asked)][:3]


def _next_questions(case: dict) -> list[str]:
    t = case.get("target")
    if not t:
        return ["최근 7일 매출이 직전 7일보다 줄어든 카테고리는?", "최근 7일 매출이 직전 7일보다 늘어난 상품은?"]
    if t["type"] == "category":
        c = t["value"]
        return [f"최근 7일 {c} 카테고리에서 매출이 줄어든 상품은?",
                f"최근 7일 {c} 매출을 첫 구매 고객과 기존 고객으로 나눠 보면?",
                f"최근 7일 {c} 매출을 시간대별로 보면?",
                f"최근 7일 {c} 매출을 요일별로 보면?"]
    p = t["value"]
    return [f"최근 7일 {p} 구매 고객을 첫 구매 고객과 기존 고객으로 나눠 보면?",
            f"최근 7일 {p} 판매 수량을 요일별로 보면?"]


def context_text(case: dict, diag: dict | None = None) -> str:
    """모델에게 넘기는 현재 분석 상태(대상·진단·수단). 모델이 같은 대상을 이어서 보게 한다."""
    parts = []
    if case.get("target"):
        t = case["target"]
        parts.append(f"대상: {target_text(t)}" + (f" (도구에 category={t['value']})" if t["type"] == "category" else ""))
    if diag:
        parts.append(f"진단(계산 엔진): {target_text(case['target'])} {diag_text(diag)}")
    if case.get("lever"):
        parts.append(f"검토 중인 수단: {lever_text(case['lever'])}")
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# Growth Lab 요청 (docs/GrowthLab_인계.md 3-2)
# ---------------------------------------------------------------------------
def lab_request(case: dict, diag: dict) -> dict:
    t, lv = case["target"], case["lever"]
    lever = {"policy": lv["policy"], "value": -lv["value"] if lv["policy"] == "price" else lv["value"]}
    return {
        "type": "plan",
        "question": case.get("question", ""),
        "diagnosis": {k: diag.get(k) for k in ("metric", "value", "base", "change", "period",
                                                "sales3", "base3", "change3", "period3")},
        "target": {"type": t["type"], "value": t["value"]},
        "lever": lever,
        "hypothesis": f"{target_text(t)}에 {lever_text(lv)}를 적용하면 {diag['metric']}이 늘고 이익률은 중단 기준 안에 머문다",
        "cause_hypothesis": case.get("hypothesis", ""),     # 대화에서 나온 원인 가설(확인 전)
        "primary_metric": diag["metric"],
        "guard_metric": f"{target_text(t)} 이익률",
        "stop_rule": f"{target_text(t)} 이익률이 시작 전보다 {STOP_PP}%p 넘게 떨어지면 중단",
        "evidence": list(case.get("evidence", [])),
    }

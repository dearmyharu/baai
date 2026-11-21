"""Growth Lab 계산: 본전 · 이익 확률 · 효과 확인 기간 · 실행 계획 저장.

화면(views/growth_lab.py)은 이 파일의 함수 결과를 표시만 한다. UX/UI를 바꿀 때 이 파일은 그대로 쓴다.

원칙 (claude/재설계_2026-11-21.md, docs/GrowthLab_인계.md)
- AI로 주문 반응을 예측하지 않는다. 주문 반응은 사용자가 정하는 가정 범위이고 화면에 가정으로 표시한다.
- 이익 = 결제 금액 − 상품원가 − 배송 원가(주문당 SHIP_COST). 결제 수수료 등은 넣지 않는다.
- 판정 지표는 아침 브리핑(briefing.promo_status)과 같다: 대상 카테고리 일 매출 비중, 짝 지표 이익률.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from . import briefing as B
from . import simulation as S

SHIP_COST = B.SHIP_COST
BASE_DAYS = 28            # 손익 기준 기간: 기준일 전 28일(요일 구성 4주)
PRE_DAYS = 14             # 판정 시 비교하는 시작 전 기간 (briefing.PROMO["pre_days"]와 같음)
Z = 1.96 + 0.84           # 유의수준 5%(양쪽) + 검정력 80%
SHIPPING_FEE = 3000       # 무료배송 기준 미달 주문의 고객 배송비(현재 데이터)
LEVER_LABEL = {"price": "판매가 할인", "discount": "할인 쿠폰", "shipping": "무료배송 기준"}


# ---------------------------------------------------------------------------
# 입력 정리
# ---------------------------------------------------------------------------
def policy_config(lever: dict) -> dict:
    """요청의 lever({policy, value}) → simulation 설정. price는 가격 변화율(내리면 음수)."""
    pol, v = lever["policy"], float(lever["value"])
    if pol == "price":
        return {"policy": "price", "price_change_pct": -abs(v)}
    if pol == "discount":
        return {"policy": "discount", "discount_type": "rate", "discount_value": abs(v), "adoption_pct": 100}
    if pol == "shipping":
        return {"policy": "shipping", "shipping_fee": SHIPPING_FEE, "free_shipping_threshold": abs(v)}
    if pol == "bundle":
        return {"policy": "bundle", "bundle_discount_pct": abs(v)}
    raise ValueError(f"지원하지 않는 수단입니다: {pol}")


def lever_text(lever: dict) -> str:
    pol, v = lever["policy"], abs(float(lever["value"]))
    if pol == "shipping":
        return f"무료배송 기준 {v:,.0f}원"
    if pol == "discount" and lever.get("discount_type") == "fixed":
        return f"정액 쿠폰 {v:,.0f}원 할인"
    if pol == "discount":
        return f"정률 쿠폰 {v:g}% 할인"
    if pol == "price":
        return f"판매가 {v:g}% 할인"
    raise ValueError("지원하지 않는 프로모션입니다.")


def scope_of(target: dict, m: dict) -> dict:
    if target["type"] == "category":
        return {"categories": [target["value"]]}
    ids = m["raw"]["product"].loc[m["raw"]["product"]["product_name"].eq(target["value"]), "product_id"].tolist()
    if not ids:
        raise ValueError(f"상품을 찾지 못했습니다: {target['value']}")
    return {"product_ids": ids}


def base_period(today) -> tuple[pd.Timestamp, pd.Timestamp]:
    t = pd.Timestamp(today).normalize()
    return t - pd.Timedelta(days=BASE_DAYS), t


# ---------------------------------------------------------------------------
# 1. 본전
# ---------------------------------------------------------------------------
def breakeven(m: dict, target: dict, lever: dict, today) -> dict:
    """기준 기간(최근 28일) 대상 주문에 정책을 다시 계산. 주문 수가 그대로일 때의 이익 변화와 본전 주문 증가율.

    반환: orders, profit_before, profit_after0(주문 변화 0%), unit_profit_after, required(본전 주문 증가율, 소수),
          required_orders(28일 기준 추가 주문 수), table(비교표), notes
    """
    s, e = base_period(today)
    prep = S.prepare(m, s, e, scope_of(target, m), {"shipping_per_order": SHIP_COST, "fee_pct": 0, "other_per_order": 0})
    res = S.simulate(prep, policy_config(lever) | {"order_change_pct": 0})
    tb, tc = res["target_baseline"], res["target_changed"]
    req = res["required_order_change"]
    n = res["target_orders"]
    return {"period": (s, e - pd.Timedelta(days=1)), "orders": n, "buyers": res["target_buyers"],
            "revenue_before": tb["revenue"], "profit_before": tb["profit"],
            "revenue_after0": tc["revenue"], "profit_after0": tc["profit"],
            "unit_profit_after": res["unit_profit"], "required": req,
            "required_orders": (req * n) if req is not None else None,
            "table": S.comparison(res), "notes": res["notes"]}


# ---------------------------------------------------------------------------
# 2. 이익이 날 확률 (몬테카를로)
# ---------------------------------------------------------------------------
def _daily_target(m: dict, target: dict, today, days: int) -> pd.DataFrame:
    t = pd.Timestamp(today).normalize()
    _, it = B.ledger(m)
    it = it[(it["date"] >= t - pd.Timedelta(days=days)) & (it["date"] < t)]
    mask = it["category"].eq(target["value"]) if target["type"] == "category" else it["product_name"].eq(target["value"])
    idx = pd.date_range(t - pd.Timedelta(days=days), t - pd.Timedelta(days=1), freq="D")
    tgt = it[mask].groupby("date").agg(sales=("net_sales", "sum"), profit=("profit", "sum")).reindex(idx, fill_value=0)
    tot = it.groupby("date")["net_sales"].sum().reindex(idx, fill_value=0)
    tgt["total"] = tot
    tgt["share"] = (tgt["sales"] / tgt["total"].replace(0, np.nan)).fillna(0)
    return tgt


def profit_probability(be: dict, m: dict, target: dict, today, low: float, mode: float, high: float,
                       days: int = 14, n: int = 20000, seed: int = 0) -> dict:
    """주문 반응 x ~ 삼각분포(low, mode, high) (소수, 예: -0.05, 0.1, 0.3)와 기간 매출의 날마다 흔들림을 함께 뽑아
    '정책 기간 이익 > 정책을 안 했을 때 이익'이 될 확률.

    - 정책 이익 = 주문 변화 0%일 때 이익 × (1 + x) (대상 주문 수가 비례해 변한다는 simulation과 같은 가정)
    - 흔들림: 최근 56일 대상 일 이익에서 days일을 뽑아 평균을 낸 비율(정책 안 함·함 각각 따로 뽑음)
    """
    if not low <= mode <= high:
        raise ValueError("가정 범위는 최소 ≤ 가장 가능성 높음 ≤ 최대 순서여야 합니다.")
    rng = np.random.default_rng(seed)
    x = rng.triangular(low, mode, high, n) if high > low else np.full(n, mode)
    daily = _daily_target(m, target, today, 56)["profit"].values
    mu = daily.mean() if daily.mean() else 1.0
    noise = lambda: rng.choice(daily, (n, days)).mean(1) / mu
    per_day_before = be["profit_before"] / BASE_DAYS
    per_day_after0 = be["profit_after0"] / BASE_DAYS
    before = per_day_before * days * noise()
    after = per_day_after0 * days * (1 + x) * noise()
    diff = after - before
    return {"prob": float((diff > 0).mean()), "diff_p10": float(np.percentile(diff, 10)),
            "diff_p50": float(np.percentile(diff, 50)), "diff_p90": float(np.percentile(diff, 90)),
            "days": days, "assumption": (low, mode, high),
            "hist": pd.DataFrame({"이익 차이": diff[:4000]})}


# ---------------------------------------------------------------------------
# 3. 효과 확인에 필요한 기간
# ---------------------------------------------------------------------------
def detect_days(m: dict, target: dict, today, effect: float, max_days: int = 28) -> dict:
    """브리핑 판정과 같은 지표(대상 매출 비중, 일 단위)로, 주문이 effect(소수)만큼 늘었을 때 구분하는 데 필요한 일수.

    필요 일수 n: effect_share × 평균 비중 ≥ Z × 일 표준편차 × √(1/n + 1/PRE_DAYS)
    """
    d = _daily_target(m, target, today, 28)
    mu, sd = float(d["share"].mean()), float(d["share"].std(ddof=1))
    out = {"share_mean": mu, "share_sd": sd, "effect": effect, "max_days": max_days}
    if mu <= 0 or effect <= 0:
        return out | {"days": None, "status": "판단 불가", "note": "대상 매출이 없거나 기대 효과가 0 이하입니다."}
    eff_share = effect * (1 - mu) / (1 + effect * mu)      # 대상 주문이 늘면 비중은 이만큼 늘어난다
    rhs = (eff_share * mu / (Z * sd)) ** 2 - 1 / PRE_DAYS if sd > 0 else math.inf
    if rhs <= 0:
        return out | {"days": None, "status": "확인 어려움",
                      "note": f"하루 흔들림이 커서 {effect:+.0%} 정도의 변화는 기간을 늘려도 구분하기 어렵습니다. "
                              "효과가 더 큰 안을 쓰거나 대상을 넓히는 것을 권합니다."}
    n = math.ceil(1 / rhs)
    if n > max_days:
        return out | {"days": n, "status": "확인 어려움",
                      "note": f"{n}일이 필요해 한 달 안에 확인하기 어렵습니다. 대상을 넓히거나 기간을 길게 잡아야 합니다."}
    return out | {"days": max(n, 7), "status": "확인 가능",
                  "note": f"최소 {max(n, 7)}일 진행하면 {effect:+.0%} 수준의 변화를 구분할 수 있습니다(7일 미만은 판정하지 않음)."}


# ---------------------------------------------------------------------------
# 4. 실행 계획 저장 (promotion 테이블)
# ---------------------------------------------------------------------------
def next_promotion_id(promos: pd.DataFrame) -> str:
    nums = promos["promotion_id"].astype(str).str.extract(r"(\d+)")[0].dropna().astype(int) if len(promos) else []
    return f"PR{(max(nums) + 1 if len(nums) else 1):03d}"


def plan_row(promos: pd.DataFrame, target: dict, lever: dict, start: date, end: date, today,
             primary_metric: str, stop_pp: float, response=(-0.05, 0.10, 0.30)) -> dict:
    """Persist exact policy terms; do not conflate fixed coupons with percentages."""
    from . import growth_policy as GP
    if target["type"] != "category":
        raise ValueError("Growth Lab은 카테고리 단위만 지원합니다.")
    lv = GP.normalize_lever(lever)
    if end < start:
        raise ValueError("종료일이 시작일보다 빠릅니다.")
    if not 0 < stop_pp <= 100:
        raise ValueError("중단 기준은 0보다 큰 %p로 입력해 주십시오.")
    if len(response) != 3 or not -1 < response[0] <= response[1] <= response[2]:
        raise ValueError("주문 반응 기본 범위를 확인해 주십시오.")
    t = pd.Timestamp(today).normalize()
    cat = target["value"]
    v = lv["value"]
    pct = v if lv["policy"] == "price" or (lv["policy"] == "discount" and lv["discount_type"] == "rate") else 0
    return {"promotion_id": next_promotion_id(promos), "promotion_name": f"{cat} {lever_text(lv)}",
            "category": cat, "lever": lv["policy"], "discount_pct": pct,
            "discount_type": lv["discount_type"], "discount_value": v,
            "shipping_threshold": v if lv["policy"] == "shipping" else None,
            "order_response_low_pct": response[0] * 100,
            "order_response_mode_pct": response[1] * 100,
            "order_response_high_pct": response[2] * 100,
            "start_date": pd.Timestamp(start).strftime("%Y-%m-%d"),
            "end_date": pd.Timestamp(end).strftime("%Y-%m-%d"),
            "primary_metric": primary_metric, "guard_metric": f"{cat} 이익률",
            "stop_rule": f"{cat} 이익률이 시작 전보다 {stop_pp:g}%p 넘게 떨어지면 중단",
            "status": "RUNNING" if pd.Timestamp(start) <= t else "PLANNED",
            "is_simulated": "FALSE"}


def save_plan(row: dict) -> str:
    """로컬은 data/promotion.csv에 덧붙이고, DB 모드면 promotion 테이블에 넣는다. 반환: 저장 위치 설명."""
    from . import data as D
    if D.backend_name() == "db":
        from sqlalchemy import text
        from .db import get_engine
        cols = list(row)
        vals = {k: (v == "TRUE") if k == "is_simulated" else v for k, v in row.items()}
        with get_engine().begin() as c:
            c.execute(text(f"insert into promotion ({', '.join(cols)}) values ({', '.join(':' + k for k in cols)})"), vals)
        return "DB promotion 테이블"
    f = D.DEFAULT_DATA_DIR / "promotion.csv"
    df = pd.read_csv(f, encoding="utf-8-sig", dtype=str, keep_default_na=False) if f.exists() else pd.DataFrame(columns=list(row))
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(f, index=False, encoding="utf-8-sig", lineterminator="\r\n")
    return str(f)


# ---------------------------------------------------------------------------
# 5. 결과 보기 (등록된 프로모션)
# ---------------------------------------------------------------------------
def result_series(m: dict, promo: dict) -> pd.DataFrame:
    """시작 전 14일 ~ 기간(또는 기준일)까지 대상 카테고리 일 매출·이익률. 차트용."""
    _, it = B.ledger(m)
    s, e = promo["start"], promo["end"]
    lo = s - pd.Timedelta(days=PRE_DAYS)
    x = it[(it["date"] >= lo) & (it["date"] <= e) & it["category"].eq(promo["category"])]
    d = x.groupby("date").agg(매출=("net_sales", "sum"), 이익=("profit", "sum"))
    d = d.reindex(pd.date_range(lo, min(e, it["date"].max()), freq="D"), fill_value=0).reset_index(names="날짜")
    d["구간"] = np.where(d["날짜"] < s, "시작 전", "기간 중")
    return d

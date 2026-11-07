"""Policy replay on completed baskets, shared by Growth Lab and the AI tools."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import metrics as M

VERSION = 1
POLICIES = {
    "price": "판매가격 변경", "discount": "주문 쿠폰 변경", "shipping": "배송 정책",
    "benefit": "고객 추가 혜택", "bundle": "묶음 할인", "volume": "노출·전환 개선",
}
DEFAULT_COSTS = {"shipping_per_order": 0.0, "fee_pct": 0.0, "other_per_order": 0.0}
DEFAULT_CONFIG = {
    "policy": "price", "price_change_pct": 0.0, "discount_type": "rate", "discount_value": 0.0,
    "discount_cap": 0.0, "minimum_order": 0.0, "adoption_pct": 100.0,
    "shipping_fee": 0.0, "free_shipping_threshold": 0.0, "benefit_amount": 0.0,
    "bundle_discount_pct": 0.0, "order_change_pct": 0.0, "fixed_cost": 0.0,
}
LABELS = {
    "orders": "주문 수", "gross": "쿠폰 차감 전 상품금액", "discount": "쿠폰·묶음 할인 부담",
    "net_sales": "순상품매출", "shipping_income": "고객 배송비 수입", "revenue": "완료 매출",
    "product_cost": "상품원가", "shipping_cost": "배송 원가", "fee": "결제 수수료",
    "other_cost": "기타 주문 변동비", "benefit_cost": "추가 혜택 비용", "fixed_cost": "추가 실행비",
    "profit": "반영 비용 차감 이익",
}


def _number(value, name, low=0.0, high=1e12):
    try:
        v = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name}에 숫자를 입력해 주세요.") from None
    if not math.isfinite(v) or not low <= v <= high:
        raise ValueError(f"{name}은 {low:g}~{high:g} 범위의 유한한 숫자여야 합니다.")
    return v


def normalize_config(config):
    config = dict(config or {})
    unknown = set(config) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"지원하지 않는 정책 설정: {', '.join(sorted(unknown))}")
    out = DEFAULT_CONFIG | config
    if out["policy"] not in POLICIES:
        raise ValueError("지원하는 정책을 선택해 주세요.")
    if out["discount_type"] not in ("rate", "fixed"):
        raise ValueError("할인은 rate(정률) 또는 fixed(정액)로 지정해 주세요.")
    for key in set(DEFAULT_CONFIG) - {"policy", "discount_type"}:
        low = -100.0 if key in ("price_change_pct", "order_change_pct") else 0.0
        high = 100.0 if key in ("adoption_pct", "bundle_discount_pct") else 1000.0 if key.endswith("_pct") else 1e12
        out[key] = _number(out[key], key, low, high)
    if out["discount_type"] == "rate" and out["discount_value"] > 100:
        raise ValueError("정률 할인율은 100% 이하여야 합니다.")
    return out


def prepare(m, start, end, scope=None, costs=None):
    """Build an order-level ledger without changing the source mart."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start >= end:
        raise ValueError("시작일보다 끝 다음 날이 뒤여야 합니다.")
    scope = dict(scope or {})
    unknown = set(scope) - {"filters", "categories", "product_ids", "theme_id", "coupon_id"}
    if unknown:
        raise ValueError(f"지원하지 않는 대상 조건: {', '.join(sorted(unknown))}")
    costs = DEFAULT_COSTS | dict(costs or {})
    if set(costs) != set(DEFAULT_COSTS):
        raise ValueError("지원하지 않는 비용 항목입니다.")
    costs = {k: _number(v, k, high=100 if k == "fee_pct" else 1e12) for k, v in costs.items()}
    orders = M.completed_orders(m, start, end).copy()
    if orders.empty:
        raise ValueError("선택 기간에 완료 주문이 없습니다.")
    if orders["order_id"].duplicated().any():
        raise ValueError("중복 주문 ID가 있어 기준 매출을 계산할 수 없습니다.")
    items = m["items"][m["items"]["order_id"].isin(orders["order_id"])].copy()
    for col in ("sales_amount", "allocated_coupon_discount", "quantity", "cost_price"):
        items[col] = pd.to_numeric(items[col], errors="coerce")
        if items[col].isna().any() or not np.isfinite(items[col]).all() or items[col].lt(0).any():
            raise ValueError(f"{col}에 누락·음수·비정상 값이 있습니다. 기준 데이터를 확인해 주세요.")
    items["cost"] = items["quantity"] * items["cost_price"]
    agg = items.groupby("order_id").agg(gross=("sales_amount", "sum"), discount=("allocated_coupon_discount", "sum"),
                                         product_cost=("cost", "sum"))
    ledger = orders.set_index("order_id")[["customer_id", "total_amount"]].join(agg)
    ledger["total_amount"] = pd.to_numeric(ledger["total_amount"], errors="coerce")
    if ledger[["gross", "discount", "product_cost", "total_amount"]].isna().any().any():
        raise ValueError("주문별 상품 내역 또는 결제금액이 누락됐습니다.")
    if not np.isfinite(ledger[["gross", "discount", "product_cost", "total_amount"]]).all().all():
        raise ValueError("기준 주문금액에 비정상 값이 있습니다.")
    ledger["net_sales"] = ledger["gross"] - ledger["discount"]
    ledger["shipping_income"] = ledger["total_amount"] - ledger["net_sales"]
    if ledger["net_sales"].lt(-0.01).any() or ledger["shipping_income"].lt(-0.01).any():
        raise ValueError("주문 결제금액과 상품·쿠폰 금액이 일치하지 않습니다. 배송비 잔액을 확인해 주세요.")
    ledger["shipping_income"] = ledger["shipping_income"].clip(lower=0)
    target_orders = orders
    if scope.get("filters"):
        target_m = M.filter_mart(m, scope["filters"], (start, end))[0]
        target_orders = target_orders[target_orders["order_id"].isin(target_m["orders"]["order_id"])]
    if scope.get("theme_id"):
        target_orders = target_orders[target_orders["attributed_theme_id"].eq(scope["theme_id"])]
    if scope.get("coupon_id"):
        target_orders = target_orders[target_orders["coupon_id"].eq(scope["coupon_id"])]
    selected = items["order_id"].isin(target_orders["order_id"])
    if scope.get("categories"):
        selected &= items["category"].isin(scope["categories"])
    if scope.get("product_ids"):
        selected &= items["product_id"].isin(scope["product_ids"])
    selected_items = items[selected]
    selected_gross = selected_items.groupby("order_id")["sales_amount"].sum()
    ledger["selected_gross"] = selected_gross.reindex(ledger.index, fill_value=0)
    ledger["selected_products"] = selected_items.groupby("order_id")["product_id"].nunique().reindex(ledger.index, fill_value=0)
    ledger["target"] = ledger.index.isin(selected_gross.index)
    if not ledger["target"].any():
        raise ValueError("선택한 대상 조건에 완료 주문이 없습니다.")
    notes = ["배송비 수입은 완료 결제금액에서 쿠폰 차감 후 상품금액을 뺀 잔액입니다.",
             "고객 반응은 입력 가정입니다. 주문 구성·단가는 기준 기간과 같고 대상 주문 수만 비례 변화합니다.",
             "상품원가 외 비용은 입력한 항목만 반영합니다. 고정 운영비·세금·재고 제약은 별도입니다."]
    missing = [label for key, label in (("shipping_per_order", "배송 원가"), ("fee_pct", "결제 수수료"),
                                      ("other_per_order", "기타 주문 변동비")) if costs[key] == 0]
    if missing:
        notes.append("0으로 입력되어 추가 차감하지 않은 비용: " + ", ".join(missing))
    return {"ledger": ledger, "scope": scope, "costs": costs, "start": str(start.date()),
            "end": str(end.date()), "notes": notes}


def _totals(rows, weights, costs, benefit=None, fixed_cost=0.0):
    values = {k: float((rows[k] * weights).sum()) for k in ("gross", "discount", "product_cost", "shipping_income")}
    values["orders"] = float(weights.sum())
    values["net_sales"] = values["gross"] - values["discount"]
    values["revenue"] = values["net_sales"] + values["shipping_income"]
    values["shipping_cost"] = values["orders"] * costs["shipping_per_order"]
    values["fee"] = values["revenue"] * costs["fee_pct"] / 100
    values["other_cost"] = values["orders"] * costs["other_per_order"]
    values["benefit_cost"] = float((benefit * weights).sum()) if benefit is not None else 0.0
    values["fixed_cost"] = fixed_cost
    values["profit"] = values["revenue"] - sum(values[k] for k in (
        "product_cost", "shipping_cost", "fee", "other_cost", "benefit_cost", "fixed_cost"))
    return values


def simulate(prepared, config=None):
    c = normalize_config(config)
    base = prepared["ledger"]
    rows = base.copy()
    target = rows["target"].copy()
    policy = c["policy"]
    notes = list(prepared["notes"])
    if policy == "bundle":
        products = prepared["scope"].get("product_ids", [])
        if len(set(products)) < 2:
            raise ValueError("묶음 할인은 구성 상품을 2개 이상 선택해 주세요.")
        target &= rows["selected_products"].eq(len(set(products)))
        notes.append("구성 상품을 모두 담은 기존 주문의 선택 상품에 추가 할인을 적용합니다. 새 묶음 구매 전환은 주문 변화 가정에 포함됩니다.")
    if not target.any():
        raise ValueError("선택 정책을 적용할 대상 주문이 없습니다.")
    if policy == "price":
        rows.loc[target, "gross"] += rows.loc[target, "selected_gross"] * c["price_change_pct"] / 100
        rows["discount"] = rows["discount"].clip(upper=rows["gross"])
        notes.append("가격 변경은 선택 상품의 관측 판매금액을 증감합니다. 기존 쿠폰 할인액은 유지하되 상품금액을 상한으로 둡니다.")
    elif policy == "discount":
        eligible = target & rows["gross"].ge(c["minimum_order"])
        new = rows["gross"] * c["discount_value"] / 100 if c["discount_type"] == "rate" else pd.Series(c["discount_value"], index=rows.index)
        if c["discount_cap"] > 0:
            new = new.clip(upper=c["discount_cap"])
        new = new.clip(upper=rows["gross"]).where(eligible, 0)
        usage = c["adoption_pct"] / 100
        rows.loc[target, "discount"] = base.loc[target, "discount"] * (1 - usage) + new.loc[target] * usage
        notes.append("새 주문 쿠폰은 기존 주문 쿠폰을 교체합니다. 적용률은 대상 주문의 균등 비중 가정이며 최소금액 미달 주문의 새 할인은 0입니다.")
    elif policy == "shipping":
        net = rows["gross"] - rows["discount"]
        charge = pd.Series(c["shipping_fee"], index=rows.index).where(net < c["free_shipping_threshold"], 0)
        rows.loc[target, "shipping_income"] = charge[target]
        notes.append("무료배송 기준은 쿠폰 차감 후 주문 상품금액입니다. 기준 0원은 대상 주문 전체 무료배송입니다.")
    elif policy == "bundle":
        share = (rows["selected_gross"] / rows["gross"].replace(0, np.nan)).fillna(0)
        extra = (rows["gross"] - rows["discount"]) * share * c["bundle_discount_pct"] / 100
        rows.loc[target, "discount"] += extra[target]
    benefit = pd.Series(0.0, index=rows.index)
    if policy == "benefit":
        benefit.loc[target] = c["benefit_amount"] * c["adoption_pct"] / 100
        notes.append("추가 혜택은 주문당 판매자 부담 비용입니다. 쿠폰 변경과 별도로 적립금·사은품 등의 예상 소진 비용을 입력합니다.")
    weights = pd.Series(1.0, index=rows.index)
    weights.loc[target] = 1 + c["order_change_pct"] / 100
    costs = prepared["costs"]
    baseline = _totals(base, pd.Series(1.0, index=base.index), costs)
    changed = _totals(rows, weights, costs, benefit, c["fixed_cost"])
    unchanged = ~target
    outside = _totals(base[unchanged], pd.Series(1.0, index=base.index[unchanged]), costs)
    target_base = _totals(base[target], pd.Series(1.0, index=base.index[target]), costs)
    target_changed = _totals(rows[target], weights[target], costs, benefit[target])
    replay = _totals(rows[target], pd.Series(1.0, index=rows.index[target]), costs, benefit[target])
    unit_profit = replay["profit"] / int(target.sum())
    required = None
    if unit_profit > 0:
        required = (target_base["profit"] + c["fixed_cost"]) / replay["profit"] - 1
        required = max(-1.0, required)
    table = pd.DataFrame([{"지표": label, "현재": baseline[key], "변경안": changed[key],
                           "차이": changed[key] - baseline[key]} for key, label in LABELS.items()])
    return {"version": VERSION, "config": c, "baseline": baseline, "changed": changed,
            "target_baseline": target_base, "target_changed": target_changed, "outside": outside,
            "target_orders": int(target.sum()), "target_buyers": int(base.loc[target, "customer_id"].nunique()),
            "unit_profit": unit_profit, "required_order_change": required, "notes": notes, "table": table}


def sensitivity(prepared, config):
    center = normalize_config(config)["order_change_pct"]
    rates = sorted(set([max(-100.0, center - 10), center, min(1000.0, center + 10), 0.0]))
    return pd.DataFrame([{"주문 변화 가정 (%)": r, "반영 비용 차감 이익": simulate(prepared, dict(config, order_change_pct=r))["changed"]["profit"]}
                         for r in rates])


def evidence(prepared, result):
    """Exact numeric evidence for AI explanations and exports."""
    facts = [f"정책 {POLICIES[result['config']['policy']]} · 관측 대상 {result['target_orders']:,}주문, {result['target_buyers']:,}고객",
             f"사용자 가정: 대상 주문 수 {result['config']['order_change_pct']:+g}% 변화"]
    facts += [f"{LABELS[k]}: 현재 {result['baseline'][k]:,.0f}원 → 변경 {result['changed'][k]:,.0f}원, 차이 {result['changed'][k] - result['baseline'][k]:+,.0f}원"
              for k in ("revenue", "net_sales", "discount", "product_cost", "profit")]
    req = result["required_order_change"]
    facts.append(f"기존 이익 유지에 필요한 대상 주문 변화 {req * 100:+.2f}%" if req is not None
                 else "주문당 반영 비용 차감 이익이 0 이하이므로 주문 확대를 통한 손익 유지 조건을 계산하지 않습니다.")
    return facts

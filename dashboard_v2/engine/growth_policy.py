"""Growth Lab-only category promotion replay.

This intentionally does not change the shared AI analyst simulation engine.
Discounts apply once per basket to selected-category items only. Existing
coupon allocation on selected items is replaced; other-category discounts
remain. Shipping eligibility uses selected-category *post-coupon* subtotal,
never the whole basket. Orders not newly eligible keep their original fee.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import briefing as B
from . import simulation as S


def normalize_lever(lever: dict) -> dict:
    policy = str(lever.get("policy", ""))
    if policy not in ("price", "discount", "shipping"):
        raise ValueError("판매가 할인, 할인 쿠폰, 무료배송 중에서 선택해 주십시오.")
    try:
        value = float(lever.get("value", 0))
    except (TypeError, ValueError):
        raise ValueError("프로모션 조건에 올바른 숫자를 입력해 주십시오.") from None
    if not np.isfinite(value):
        raise ValueError("프로모션 조건은 유한한 숫자여야 합니다.")
    kind = str(lever.get("discount_type", "rate"))
    if policy == "discount" and kind not in ("rate", "fixed"):
        raise ValueError("쿠폰 할인 방식은 정률 또는 정액이어야 합니다.")
    max_value = 100000 if policy == "discount" and kind == "fixed" else 30000 if policy == "shipping" else 50
    if not 0 <= abs(value) <= max_value:
        raise ValueError(f"입력 가능한 범위는 0~{max_value:,}입니다.")
    # Coupon-only optional conditions: 0 means no minimum / no cap.
    # All eligibility amounts use the SELECTED category basket subtotal.
    minimum = 0.0
    cap = 0.0
    if policy == "discount":
        for key, label in (("minimum_order_amount", "최소주문금액"),
                           ("maximum_discount_amount", "최대 할인액")):
            try:
                amount = float(lever.get(key, 0) or 0)
            except (TypeError, ValueError):
                raise ValueError(f"{label}에 올바른 숫자를 입력해 주십시오.") from None
            if not np.isfinite(amount) or not 0 <= amount <= 100000000:
                raise ValueError(f"{label}은 0~100,000,000원이어야 합니다.")
            if key == "minimum_order_amount":
                minimum = amount
            else:
                cap = amount
    return {"policy": policy, "value": abs(value),
            "discount_type": kind if policy == "discount" else "none",
            "minimum_order_amount": minimum, "maximum_discount_amount": cap}


def _financial_rows(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["revenue"] = rows["gross"] - rows["discount"] + rows["shipping_income"]
    rows["profit"] = rows["revenue"] - rows["product_cost"] - B.SHIP_COST
    return rows


def replay(m: dict, category: str, lever: dict, start, end) -> dict:
    """Reprice actual completed category-containing baskets in [start, end).

    Scope is entire baskets containing the selected category; only selected
    lines receive discount. This makes order-level shipping & costs coherent.
    """
    lever = normalize_lever(lever)
    prep = S.prepare(m, start, end, {"categories": [category]},
                     {"shipping_per_order": B.SHIP_COST, "fee_pct": 0, "other_per_order": 0})
    led = prep["ledger"]
    original = led[led["target"]].copy()
    changed = original.copy()

    selected = prep["selected_items"]
    existing_category_coupon = selected.groupby("order_id")["allocated_coupon_discount"].sum()
    existing_category_coupon = existing_category_coupon.reindex(original.index, fill_value=0).clip(lower=0)
    existing_category_coupon = np.minimum(existing_category_coupon, original["discount"])
    selected_gross = original["selected_gross"].clip(lower=0)

    if lever["policy"] == "price":
        # Replace existing target-category coupon with new price markdown:
        # no stacked promotion on these selected-category product lines.
        changed["gross"] = original["gross"] - selected_gross * lever["value"] / 100
        changed["discount"] = original["discount"] - existing_category_coupon
    elif lever["policy"] == "discount":
        # Qualifying minimum: selected-category item subtotal ONLY (before
        # the new coupon). Products outside the category cannot fill the gap.
        qualified = selected_gross >= lever["minimum_order_amount"]
        if lever["discount_type"] == "fixed":
            new_coupon = np.minimum(selected_gross, lever["value"])
        else:
            new_coupon = selected_gross * lever["value"] / 100
        cap = lever["maximum_discount_amount"]
        if cap > 0:
            new_coupon = np.minimum(new_coupon, cap)
        new_coupon = np.minimum(new_coupon, selected_gross)
        # Ineligible orders retain their original category coupon instead of
        # erasing it. Eligible orders REPLACE the original coupon once/basket.
        applied_coupon = new_coupon.where(qualified, existing_category_coupon)
        changed["discount"] = original["discount"] - existing_category_coupon + applied_coupon
    else:
        # Threshold is based solely on items in the selected category.
        # Existing category coupons already reflected in that subtotal.
        selected_net = (selected_gross - existing_category_coupon).clip(lower=0)
        qualified = selected_net >= lever["value"]
        changed.loc[qualified, "shipping_income"] = 0.0
        # If not qualified, retain historical shipping fee, even if
        # the entire mixed basket crosses the threshold.

    changed["discount"] = changed["discount"].clip(lower=0)
    changed["discount"] = np.minimum(changed["discount"], changed["gross"])
    before = _financial_rows(original)
    after = _financial_rows(changed)

    # Same category-level margin definition as briefing.ledger():
    # category net product sales, less category COGS and its proportional
    # share of order shipping burden (shipping cost minus customer fee).
    selected_cost = selected.assign(
        item_cost=selected["quantity"] * selected["cost_price"]
    ).groupby("order_id")["item_cost"].sum().reindex(original.index, fill_value=0)
    selected_net_before = (selected_gross - existing_category_coupon).clip(lower=0)
    if lever["policy"] == "price":
        selected_net_after = (selected_gross * (1 - lever["value"] / 100)).clip(lower=0)
    elif lever["policy"] == "discount":
        selected_net_after = (selected_gross - applied_coupon).clip(lower=0)
    else:
        selected_net_after = selected_net_before.copy()
    for values, selected_net in ((before, selected_net_before), (after, selected_net_after)):
        net = (values["gross"] - values["discount"]).replace(0, np.nan)
        share = (selected_net / net).fillna(0).clip(0, 1)
        burden = B.SHIP_COST - values["shipping_income"]
        values["category_revenue"] = selected_net
        values["category_profit"] = selected_net - selected_cost - share * burden
    if (after[["revenue", "gross", "discount"]].lt(-0.001)).any().any():
        raise ValueError("정책 적용 후 상품 또는 결제금액이 음수가 되었습니다.")
    return {"before": before, "after": after, "lever": lever,
            "category": category, "start": pd.Timestamp(start), "end": pd.Timestamp(end)}


def totals(rows: pd.DataFrame) -> dict:
    # Main KPI scope: selected-category product sales and shipping-adjusted profit.
    revenue = float(rows["category_revenue"].sum())
    profit = float(rows["category_profit"].sum())
    return {"revenue": revenue, "profit": profit,
            "orders": int(len(rows)), "margin": profit / revenue if revenue else 0.0}


def daily_pair(m: dict, pair: dict, start, end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aligned daily basket-level historical baseline and policy outcome."""
    order_dates = (m["orders"].drop_duplicates("order_id").set_index("order_id")["order_time"]
                   .dt.normalize())
    calendar = pd.date_range(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1))
    result = []
    for key in ("before", "after"):
        rows = pair[key].copy()
        rows["date"] = order_dates.reindex(rows.index)
        day = rows.groupby("date")[["category_revenue", "category_profit"]].sum()
        day = day.rename(columns={"category_revenue": "revenue", "category_profit": "profit"})
        result.append(day.reindex(calendar, fill_value=0.0).astype(float))
    return result[0], result[1]


def break_even(pair: dict) -> dict:
    """Break-even basket growth for the same category-containing basket mix."""
    before, after = totals(pair["before"]), totals(pair["after"])
    required = (before["profit"] / after["profit"] - 1) if after["profit"] > 0 else None
    return {"before": before, "after": after,
            "required": required, "orders": len(pair["before"]),
            "required_orders": max(0, int(np.ceil(len(pair["before"]) * required)))
            if required is not None else None}


def monte_carlo(m: dict, category: str, lever: dict, today, days: int,
                low: float = -0.05, mode: float = 0.10, high: float = 0.30,
                n: int = 20000, seed: int = 42) -> dict:
    """Paired daily bootstrap + triangular order response for 20k scenarios.

    The same historical day is used for before/after to avoid counting normal
    day-to-day variation twice. Basket count changes proportionally while the
    observed mix/price/cost of category-containing baskets remains stable.
    Percentile bands are conditional scenario ranges, not forecasts trained on
    campaign response. Revenue is selected-category net product sales only; shipping burden is allocated proportionally as in Morning Briefing.
    """
    if not (-1 < low <= mode <= high) or high > 10:
        raise ValueError("주문 반응 기본 가정을 확인해 주십시오.")
    if not 1 <= days <= 60:
        raise ValueError("운영 기간은 1~60일 사이여야 합니다.")
    if n < 100:
        raise ValueError("시뮬레이션 반복 횟수는 100회 이상이어야 합니다.")
    end = pd.Timestamp(today).normalize()
    begin = end - pd.Timedelta(days=56)
    pair = replay(m, category, lever, begin, end)
    before, after = daily_pair(m, pair, begin, end)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(before), size=(n, days))
    growth = rng.triangular(low, mode, high, n) if high > low else np.full(n, mode)
    before_rev = before["revenue"].to_numpy()[idx].sum(axis=1)
    before_profit = before["profit"].to_numpy()[idx].sum(axis=1)
    before_margin = np.divide(before_profit, before_rev, out=np.full(n, np.nan), where=before_rev > 0)
    after_rev = after["revenue"].to_numpy()[idx].sum(axis=1) * (1 + growth)
    after_profit = after["profit"].to_numpy()[idx].sum(axis=1) * (1 + growth)
    margin = np.divide(after_profit, after_rev, out=np.full(n, np.nan), where=after_rev > 0)
    if not np.isfinite(margin).any():
        raise ValueError("선택 카테고리의 매출이 없어 이익률을 계산할 수 없습니다.")
    return {
        "days": days, "n": n, "assumption": (low, mode, high),
        "prob": float(np.mean(after_profit > before_profit)),
        "sales_p10": float(np.percentile(after_rev, 10)),
        "sales_p50": float(np.percentile(after_rev, 50)),
        "sales_p90": float(np.percentile(after_rev, 90)),
        "margin_p10": float(np.nanpercentile(margin, 10)),
        "margin_p50": float(np.nanpercentile(margin, 50)),
        "margin_p90": float(np.nanpercentile(margin, 90)),
        "baseline_sales_p50": float(np.percentile(before_rev, 50)),
        "baseline_margin_p50": float(np.nanpercentile(before_margin, 50)),
        "baseline_profit_p50": float(np.percentile(before_profit, 50)),
        "profit_delta_p10": float(np.percentile(after_profit - before_profit, 10)),
        "profit_delta_p50": float(np.percentile(after_profit - before_profit, 50)),
        "profit_delta_p90": float(np.percentile(after_profit - before_profit, 90)),
        "hist": pd.DataFrame({"이익 차이": (after_profit - before_profit)[:4000]})
    }

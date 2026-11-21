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
    return {"policy": policy, "value": abs(value),
            "discount_type": kind if policy == "discount" else "none"}


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
        if lever["discount_type"] == "fixed":
            new_coupon = np.minimum(selected_gross, lever["value"])
        else:
            new_coupon = selected_gross * lever["value"] / 100
        # One coupon per order, not one coupon per line.
        changed["discount"] = original["discount"] - existing_category_coupon + new_coupon
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
    if (after[["revenue", "gross", "discount"]].lt(-0.001)).any().any():
        raise ValueError("정책 적용 후 상품 또는 결제금액이 음수가 되었습니다.")
    return {"before": before, "after": after, "lever": lever,
            "category": category, "start": pd.Timestamp(start), "end": pd.Timestamp(end)}


def totals(rows: pd.DataFrame) -> dict:
    return {name: float(rows[name].sum()) for name in
            ("gross", "discount", "shipping_income", "revenue", "profit", "product_cost")} | {
                "orders": int(len(rows)), "margin": float(rows["profit"].sum()/rows["revenue"].sum())
                if rows["revenue"].sum() else 0.0}


def daily_pair(m: dict, pair: dict, start, end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aligned daily basket-level historical baseline and policy outcome."""
    order_dates = (m["orders"].drop_duplicates("order_id").set_index("order_id")["order_time"]
                   .dt.normalize())
    calendar = pd.date_range(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1))
    result = []
    for key in ("before", "after"):
        rows = pair[key].copy()
        rows["date"] = order_dates.reindex(rows.index)
        day = rows.groupby("date")[["revenue", "profit"]].sum()
        result.append(day.reindex(calendar, fill_value=0.0).astype(float))
    return result[0], result[1]

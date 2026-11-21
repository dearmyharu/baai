"""Regression tests for category-only promotions; run:
python -m unittest discover -s tests -p 'test_growth_policy.py'
"""
import unittest
from unittest.mock import patch

import pandas as pd

from engine import growth_policy as GP


def fake_prepared():
    # A mixed basket where other categories must NOT satisfy the threshold.
    ids = ["mixed", "meat_only", "meat_with_old_coupon", "already_free"]
    led = pd.DataFrame({
        "customer_id": ["A", "B", "C", "D"],
        "gross": [20000., 20000., 24000., 35000.],
        "discount": [0., 0., 1000., 0.],
        "product_cost": [12000., 12000., 15000., 21000.],
        "shipping_income": [3000., 3000., 3000., 0.],
        "selected_gross": [15000., 20000., 20000., 35000.],
        "target": [True] * 4,
    }, index=pd.Index(ids, name="order_id"))
    selected = pd.DataFrame({
        "order_id": ids, "allocated_coupon_discount": [0., 0., 1000., 0.]
    })
    return {"ledger": led, "selected_items": selected, "scope": {"categories": ["정육"]},
            "costs": {"shipping_per_order": 3000., "fee_pct": 0., "other_per_order": 0.},
            "notes": []}


class CategoryPromotionTests(unittest.TestCase):
    def replay(self, lever):
        with patch.object(GP.S, "prepare", return_value=fake_prepared()):
            return GP.replay({}, "정육", lever, "2026-09-01", "2026-10-01")

    def test_category_only_shipping_threshold(self):
        r = self.replay({"policy": "shipping", "value": 20000})
        # 15k meat + 5k other: remains paid shipping.
        self.assertEqual(r["after"].loc["mixed", "shipping_income"], 3000.)
        # 20k meat exactly: newly free shipping.
        self.assertEqual(r["after"].loc["meat_only", "shipping_income"], 0.)
        # 20k meat - 1k prior coupon: below post-coupon threshold.
        self.assertEqual(r["after"].loc["meat_with_old_coupon", "shipping_income"], 3000.)
        self.assertEqual(r["after"].loc["already_free", "shipping_income"], 0.)

    def test_fixed_coupon_once_per_order_and_no_stack(self):
        r = self.replay({"policy": "discount", "discount_type": "fixed", "value": 2000})
        self.assertEqual(r["after"].loc["mixed", "discount"], 2000.)
        self.assertEqual(r["after"].loc["meat_with_old_coupon", "discount"], 2000.)
        self.assertEqual(r["after"].loc["mixed", "gross"], 20000.)

    def test_percentage_coupon_selected_category_only(self):
        r = self.replay({"policy": "discount", "discount_type": "rate", "value": 10})
        # Gross 20k, selected meat 15k -> 1500, not 2000.
        self.assertEqual(r["after"].loc["mixed", "discount"], 1500.)

    def test_price_discount_does_not_stack_prior_category_coupon(self):
        r = self.replay({"policy": "price", "value": 10})
        self.assertEqual(r["after"].loc["meat_with_old_coupon", "gross"], 22000.)
        self.assertEqual(r["after"].loc["meat_with_old_coupon", "discount"], 0.)

    def test_break_even_and_totals_consistent(self):
        r = self.replay({"policy": "discount", "discount_type": "fixed", "value": 2000})
        be = GP.break_even(r)
        self.assertEqual(be["orders"], 4)
        self.assertGreater(be["before"]["profit"], be["after"]["profit"])
        self.assertGreater(be["required"], 0.0)


if __name__ == "__main__":
    unittest.main()

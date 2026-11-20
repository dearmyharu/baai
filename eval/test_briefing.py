"""아침 브리핑 규칙 테스트 (합성 데이터). python -m unittest eval.test_briefing -v"""
import unittest

import numpy as np
import pandas as pd

from core import briefing as B

DAY = pd.Timestamp("2026-09-29")          # 브리핑 대상 '어제' (화)
PRODUCTS = [  # id, 이름, 카테고리, 가격, 원가, 평소 하루 수량
    ("P1", "매운 떡볶이 밀키트", "야식", 12000, 6000, 12),
    ("P2", "순살 닭강정", "야식", 15000, 8000, 8),
    ("P3", "콜드브루 원액", "음료", 9000, 3000, 2),
    ("P4", "그릭요거트", "유제품", 6000, 2500, 10),
    ("P5", "샐러드 도시락", "간편식", 8000, 6700, 14),   # 원가가 높아 쿠폰을 쓰면 남는 게 적다
]


def make_mart(seed=0, spike=True, drop=True, cancels=True):
    rng = np.random.default_rng(seed)
    orders, items, oid = [], [], 0
    days = pd.date_range("2026-07-01", "2026-09-30", freq="D")
    for d in days:
        for pid, name, cat, price, cost, base in PRODUCTS:
            n = base
            if drop and cat == "야식" and DAY - pd.Timedelta(days=2) <= d <= DAY:
                n = base // 3
            if spike and pid == "P3" and d == DAY:
                n = 16
            n = max(0, int(rng.poisson(n)))
            for _ in range(n):
                oid += 1
                cust = f"C{rng.integers(0, 400)}"
                coupon = pid == "P5" and rng.random() < 0.8
                disc = round(price * 0.15) if coupon else 0
                first = 0.0
                if spike and pid == "P3" and d == DAY:
                    cust, first = f"NEW{oid}", 1.0
                t = d + pd.Timedelta(hours=int(rng.integers(9, 23)))
                if spike and pid == "P3" and d == DAY:
                    t = d + pd.Timedelta(hours=21)
                status = "COMPLETED"
                orders.append([f"O{oid}", cust, t, status, price - disc + 3000, coupon, first, disc])
                items.append([f"O{oid}", pid, name, cat, 1, price, disc, cost, cust, t, status])
    if cancels:
        for i in range(5):
            oid += 1
            t = DAY + pd.Timedelta(hours=10 + i)
            orders.append([f"O{oid}", "CX", t, "CANCELLED", 20000, False, 0.0, 0])
            items.append([f"O{oid}", "P4", "그릭요거트", "유제품", 1, 17000, 0, 2500, "CX", t, "CANCELLED"])
    o = pd.DataFrame(orders, columns=["order_id", "customer_id", "order_time", "order_status", "total_amount",
                                      "has_coupon", "is_first_purchase", "coupon_discount_amount"])
    it = pd.DataFrame(items, columns=["order_id", "product_id", "product_name", "category", "quantity",
                                      "sales_amount", "allocated_coupon_discount", "cost_price", "customer_id",
                                      "order_time", "order_status"])
    it["net_sales"] = it["sales_amount"] - it["allocated_coupon_discount"]
    cust = pd.DataFrame({"customer_id": o["customer_id"].unique()})
    cust["signup_channel"] = "INSTAGRAM"
    return {"orders": o, "items": it, "raw": {"customer": cust}}


class BriefingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = make_mart()
        cls.b = B.brief(cls.m, DAY)

    def test_profit_matches_formula(self):
        o, _ = B.ledger(self.m)
        r = o.iloc[0]
        self.assertAlmostEqual(r.profit, r.total_amount - r.cost - B.SHIP_COST)
        self.assertAlmostEqual(r.profit, r.net - r.cost - r.ship_burden)

    def test_item_profit_adds_up_to_order_profit(self):
        o, it = B.ledger(self.m)
        self.assertAlmostEqual(it["profit"].sum(), o["profit"].sum(), delta=1)

    def test_spike_found_first_with_viral_guess(self):
        top = self.b["todos"][0]
        self.assertEqual(top["kind"], "spike")
        self.assertIn("콜드브루", top["title"])
        self.assertEqual(top["profile"]["guess"], "바이럴·외부 소개 가능성")

    def test_category_drop_found(self):
        keys = {x["key"] for x in B.todos(self.m, DAY, {"max_items": 99})}
        self.assertIn("category:야식", keys)

    def test_low_margin_coupon_product_found(self):
        keys = {x["key"] for x in B.todos(self.m, DAY, {"max_items": 99})}
        self.assertIn("product:샐러드 도시락", keys)

    def test_cancel_found(self):
        kinds = {k for x in B.todos(self.m, DAY, {"max_items": 99}) for k in x["kinds"]}
        self.assertIn("cancel", kinds)

    def test_quiet_data_gives_no_problem_todos(self):
        m = make_mart(seed=1, spike=False, drop=False, cancels=False)
        items = B.todos(m, DAY, {"max_items": 99})
        self.assertFalse([x for x in items if x["kind"] in ("spike", "drop", "cancel")])

    def test_max_items_and_opportunity_kept(self):
        items = self.b["todos"]
        self.assertLessEqual(len(items), B.TH["max_items"])
        self.assertTrue(any(x["tone"] == "opportunity" for x in items))

    def test_same_weekday_baseline(self):
        y = self.b["yesterday"]
        self.assertTrue(all(d.dayofweek == DAY.dayofweek for d in y["base_days"]))
        self.assertEqual(len(y["base_days"]), 4)

    def test_month_pace_compares_same_day(self):
        p = self.b["pace"]
        self.assertEqual(p["day"], 29)
        self.assertIsNotNone(p["chg"])

    def test_summary_sentence(self):
        self.assertIn("어제(화) 매출은", self.b["summary"])


if __name__ == "__main__":
    unittest.main()

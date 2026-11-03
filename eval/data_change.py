"""데이터 변경 테스트: 데이터를 바꾸면 답도 바뀌는가 (하드코딩·캐시·조건 필터 확인).

dashboard 폴더에서:  python eval/data_change.py [데이터 폴더]
원본 데이터는 건드리지 않고 임시 복사본을 고친다.

시나리오: 6월에 '여성 고객'이 산 특정 상품(6월 여성 매출 10위)의 주문 금액만 10배로 올린다.
- 여성 고객 6월 상품 TOP1이 그 상품으로 바뀌어야 한다          (조건 + 데이터 반영)
- 조건 없는 6월 TOP1도 그 상품으로 바뀌어야 한다                (데이터 반영)
- 남성 고객 6월 TOP5와 5월 전체 TOP5는 그대로여야 한다           (건드리지 않은 곳은 그대로)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import tools as T  # noqa: E402
import os  # noqa: E402

from core.data import DEFAULT_DATA_DIR, build_all  # noqa: E402

JUN = dict(start="2026-06-01", end="2026-07-01")
MAY = dict(start="2026-05-01", end="2026-06-01")


def top(m, period, filters=None, n=5):
    return list(T.run(m, "rank_items", **period, target="product", n=n, filters=filters)["table"]["상품"])


def main(data_dir=None) -> int:
    src = Path(data_dir or os.getenv("DATA_DIR") or DEFAULT_DATA_DIR)
    A = build_all(src)
    women_top10 = top(A, JUN, {"gender": "F"}, 10)
    target = women_top10[9]
    pid = A["raw"]["product"].set_index("product_name").loc[target, "product_id"]
    before = {"여성 6월": top(A, JUN, {"gender": "F"}), "전체 6월": top(A, JUN), "남성 6월": top(A, JUN, {"gender": "M"}),
              "전체 5월": top(A, MAY)}

    tmp = Path(tempfile.mkdtemp(prefix="baai_dc_"))
    try:
        for f in src.glob("*.csv"):
            shutil.copy(f, tmp / f.name)
        o = pd.read_csv(tmp / "orders.csv", encoding="utf-8-sig")
        c = pd.read_csv(tmp / "customer.csv", encoding="utf-8-sig")
        it = pd.read_csv(tmp / "order_items.csv", encoding="utf-8-sig")
        women = set(c.loc[c["gender"].eq("F"), "customer_id"])
        june = o[(o["order_time"] >= JUN["start"]) & (o["order_time"] < JUN["end"]) & o["order_status"].eq("COMPLETED")
                 & o["customer_id"].isin(women)]["order_id"]
        mask = it["order_id"].isin(june) & it["product_id"].eq(pid)
        it.loc[mask, "sales_amount"] *= 10
        it.to_csv(tmp / "order_items.csv", index=False, encoding="utf-8-sig")
        B = build_all(tmp)
        after = {"여성 6월": top(B, JUN, {"gender": "F"}), "전체 6월": top(B, JUN), "남성 6월": top(B, JUN, {"gender": "M"}),
                 "전체 5월": top(B, MAY)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"변경: 6월 여성 고객 주문의 '{target}' 상품금액 ×10 ({int(mask.sum())}행)\n")
    checks = [("여성 6월 TOP1이 바뀐 상품", after["여성 6월"][0] == target),
              ("전체 6월 TOP1이 바뀐 상품", after["전체 6월"][0] == target),
              ("남성 6월 TOP5 그대로", after["남성 6월"] == before["남성 6월"]),
              ("전체 5월 TOP5 그대로", after["전체 5월"] == before["전체 5월"])]
    for k in before:
        print(f"{k}: {before[k][:3]} → {after[k][:3]}")
    print()
    for name, ok in checks:
        print(f"{'OK' if ok else 'NG'}  {name}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

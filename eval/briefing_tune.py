"""일일 브리핑 확인 사항 기준값 확인: 9월을 하루씩 돌려 하루에 할 일이 몇 개 나오는지 센다.

실행 (dashboard 폴더에서):  python -m eval.briefing_tune
기준값을 바꿔 보려면:        python -m eval.briefing_tune drop_pct=0.4 spike_x=4

목표: 하루 평균 2~4개. 매일 0개면 기준이 너무 엄격하고, 매일 4개를 꽉 채우면 너무 느슨하다.
max_items 제한 전(규칙에 걸린 전체) 개수와 종류별 개수를 같이 보여 준다.
"""
from __future__ import annotations

import sys
from collections import Counter

import pandas as pd

from core import briefing as B
from core.data import build_all


def run(m, days, th: dict) -> pd.DataFrame:
    rows = []
    for d in days:
        allx = B.todos(m, d, th | {"max_items": 99})
        kinds = Counter(k for x in allx for k in x["kinds"])
        rows.append({"날짜": f"{d:%m/%d}({B.DOW[d.dayofweek]})", "전체": len(allx),
                     "화면(최대 %d)" % B.TH["max_items"]: min(len(allx), B.TH["max_items"]),
                     **{k: kinds.get(k, 0) for k in ("spike", "drop", "rise", "margin", "coupon", "cancel")},
                     "1순위": allx[0]["title"] if allx else ""})
    return pd.DataFrame(rows)


def main(argv: list[str]) -> int:
    th = {}
    for a in argv:
        k, v = a.split("=", 1)
        th[k] = float(v) if "." in v else int(v)
    m = build_all()
    days = pd.date_range("2026-09-01", "2026-09-29", freq="D")
    df = run(m, days, th)
    pd.set_option("display.width", 200, "display.max_colwidth", 60, "display.max_rows", 100)
    print(df.to_string(index=False))
    print("\n하루 평균 (규칙에 걸린 전체):", round(df["전체"].mean(), 2),
          "· 0개인 날:", int((df["전체"] == 0).sum()), "· 4개 이상인 날:", int((df["전체"] >= 4).sum()))
    print("종류별 하루 평균:", {k: round(df[k].mean(), 2) for k in ("spike", "drop", "rise", "margin", "coupon", "cancel")})
    print("사용한 기준값:", B.TH | th)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

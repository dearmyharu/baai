"""공통 기준 — 아침 브리핑·AI 분석가·질문 대시보드가 모두 이 파일의 기준만 쓴다 (2026-11-22 결정).

- 비교: 최근 N일(3일·7일) 합계 vs 지난 4주 같은 요일 N일 합계의 평균. ±10% 밖이면 평소보다 높음·낮음.
- 기본 기간: 기간이 없는 순위·비중·구성 질문은 최근 28일(요일 구성이 4주로 같음). 추이는 전체 기간.
- 매출 정의(그대로 둠): 쇼핑몰 전체 = 완료 매출(완료 주문 결제 금액, 배송비 포함).
  카테고리·상품 단위 = 상품매출(쿠폰 차감 후 상품 금액, 배송비 제외). 카테고리를 더해도 완료 매출이 되지 않는다.
- 데이터는 기준일 전날까지(기준일 아침).

여기 있는 숫자를 바꾸면 모든 화면이 같이 바뀐다. 다른 파일에 같은 숫자를 다시 적지 않는다.
"""
from __future__ import annotations

import pandas as pd

from .data import PERIOD_START

BAND = 0.10          # 평소 범위 ±10% (근거: 9월 3일 매출 비율의 흔들림 약 ±8%, 2026-11-21 확인)
WEEKS = 4            # '평소' = 지난 4주 같은 요일
WINDOWS = (3, 7)     # 변화는 최근 3일과 최근 7일을 나란히 본다 (판단은 3~7일 흐름)
DEFAULT_DAYS = 28    # 기간 없는 순위·비중·구성 질문
SHIP_COST = 3000     # 판매자 배송 원가(주문당, 가정값). 이익 = 결제 금액 − 상품 원가 − 배송 원가

LEVEL_HIGH, LEVEL_NORMAL, LEVEL_LOW, LEVEL_NA = "평소보다 높음", "평소 수준", "평소보다 낮음", "비교 불가"

# 측정값: (이름, 단위, 계산 단위). 계산 단위 item = 주문 상품 장부, order = 주문 장부
MEASURES = {
    "완료 매출": ("won", "order"),
    "상품매출": ("won", "item"),
    "판매 수량": ("count", "item"),
    "주문 수": ("count", "both"),
    "구매 고객 수": ("count", "both"),
    "이익": ("won", "both"),
}


# ---------------------------------------------------------------------------
# 장부 (완료 주문만)
# ---------------------------------------------------------------------------
def ledger(m: dict, ship_cost: float = SHIP_COST) -> tuple[pd.DataFrame, pd.DataFrame]:
    """완료 주문 장부(o)와, 배송 부담을 상품금액 비율로 나눠 넣은 주문 상품 장부(it). 둘 다 date 열이 있다."""
    it = m["items"]
    it = it[it["order_status"].eq("COMPLETED")].copy()
    it["cost"] = it["quantity"] * it["cost_price"]
    o = m["orders"]
    o = o[o["order_status"].eq("COMPLETED")].copy()
    agg = it.groupby("order_id").agg(gross=("sales_amount", "sum"), discount=("allocated_coupon_discount", "sum"),
                                     net=("net_sales", "sum"), cost=("cost", "sum"))
    o = o.join(agg, on="order_id")
    o[["gross", "discount", "net", "cost"]] = o[["gross", "discount", "net", "cost"]].fillna(0)
    o["shipping_income"] = (o["total_amount"] - o["net"]).clip(lower=0)
    o["ship_burden"] = ship_cost - o["shipping_income"]
    o["profit"] = o["total_amount"] - o["cost"] - ship_cost
    o["date"] = o["order_time"].dt.normalize()
    share = it["net_sales"] / it["order_id"].map(o.set_index("order_id")["net"]).replace(0, pd.NA)
    it["ship_burden"] = share.fillna(0).astype(float) * it["order_id"].map(o.set_index("order_id")["ship_burden"])
    it["profit"] = it["net_sales"] - it["cost"] - it["ship_burden"]
    it["date"] = it["order_time"].dt.normalize()
    return o, it


# ---------------------------------------------------------------------------
# 날짜
# ---------------------------------------------------------------------------
def last_day(today) -> pd.Timestamp:
    """데이터가 있는 마지막 날 = 기준일 전날."""
    return pd.Timestamp(today).normalize() - pd.Timedelta(days=1)


def windows(today, length: int, weeks: int = WEEKS) -> tuple[list[pd.Timestamp], list[list[pd.Timestamp]]]:
    """최근 length일(어제까지)과, 지난 weeks주의 같은 요일 length일 묶음들."""
    y = last_day(today)
    cur = list(pd.date_range(y - pd.Timedelta(days=length - 1), y, freq="D"))
    base = [[d - pd.Timedelta(days=7 * k) for d in cur] for k in range(1, weeks + 1)]
    return cur, base


def default_period(today, kind: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """기간이 없는 질문의 기간 [start, end). kind: 'rank'(순위·비중·구성) | 'trend'(추이)."""
    t = pd.Timestamp(today).normalize()
    if kind == "rank":
        return t - pd.Timedelta(days=DEFAULT_DAYS), t
    if kind == "trend":
        return PERIOD_START, t
    raise ValueError(f"기본 기간 종류가 아닙니다: {kind}")


def span_label(days: list[pd.Timestamp]) -> str:
    return f"{days[0]:%m/%d}~{days[-1]:%m/%d}".replace("/0", "/").lstrip("0")


# ---------------------------------------------------------------------------
# 일별 표: 행 = 그룹, 열 = 날짜
# ---------------------------------------------------------------------------
def _item_agg(it: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return it.groupby(keys).agg(상품매출=("net_sales", "sum"), **{"판매 수량": ("quantity", "sum")},
                                **{"주문 수": ("order_id", "nunique")}, **{"구매 고객 수": ("customer_id", "nunique")},
                                이익=("profit", "sum"))


def _order_agg(o: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return o.groupby(keys).agg(**{"완료 매출": ("total_amount", "sum")}, **{"주문 수": ("order_id", "nunique")},
                               **{"구매 고객 수": ("customer_id", "nunique")}, 이익=("profit", "sum"))


def daily(o: pd.DataFrame, it: pd.DataFrame, measure: str, by: str | None = None) -> pd.DataFrame:
    """측정값의 일별 표. by가 없으면 쇼핑몰 전체 한 줄('전체'), 있으면 it의 그 열(category, product_name 등)별.

    - by가 없을 때 주문·고객·이익은 주문 장부로 센다(쇼핑몰 전체 기준).
    - by가 있으면 주문 상품 장부로 센다. 상품매출·판매 수량·이익은 그룹별 합이 전체와 맞고,
      주문 수·구매 고객 수는 한 주문이 여러 그룹에 걸치면 각 그룹에서 한 번씩 센다.
    """
    if measure not in MEASURES:
        raise ValueError(f"측정값이 아닙니다: {measure}. 가능한 값: {', '.join(MEASURES)}")
    unit = MEASURES[measure][1]
    if by is None:
        if unit == "item":
            g = _item_agg(it, ["date"])[measure]
        else:
            g = _order_agg(o, ["date"])[measure]
        return g.to_frame("전체").T
    if unit == "order":
        raise ValueError(f"{measure}은(는) 주문 단위라 {by}별로 나눌 수 없습니다. 상품매출을 쓰십시오.")
    if by not in it.columns:
        raise ValueError(f"나눌 수 없는 기준입니다: {by}")
    return _item_agg(it, [by, "date"])[measure].unstack("date", fill_value=0)


# ---------------------------------------------------------------------------
# 비교
# ---------------------------------------------------------------------------
def level(value: float | None, mean: float | None) -> str:
    if value is None or not mean:
        return LEVEL_NA
    if value < mean * (1 - BAND):
        return LEVEL_LOW
    if value > mean * (1 + BAND):
        return LEVEL_HIGH
    return LEVEL_NORMAL


def _sum(t: pd.DataFrame, days: list) -> pd.Series:
    return t.reindex(columns=days, fill_value=0).sum(axis=1)


def compare(t: pd.DataFrame, today, length: int, first_day=None) -> pd.DataFrame:
    """일별 표 t(행 = 그룹)의 최근 length일 합계 vs 지난 4주 같은 요일 length일 합계 평균.

    반환 열: 현재, 평소, 평소_최소, 평소_최대, 변화(금액·개수 차), 변화율, 판정.
    first_day보다 이른 평소 묶음은 뺀다(데이터 시작 전). 행 순서는 t 그대로.
    """
    first_day = pd.Timestamp(first_day) if first_day is not None else PERIOD_START
    cur, base = windows(today, length)
    base = [b for b in base if b[0] >= first_day]
    now = _sum(t, cur)
    if not base:
        out = pd.DataFrame({"현재": now})
        for c in ("평소", "평소_최소", "평소_최대", "변화", "변화율"):
            out[c] = float("nan")
        out["판정"] = LEVEL_NA
        return out
    bs = pd.concat([_sum(t, b) for b in base], axis=1)
    mean = bs.mean(axis=1)
    out = pd.DataFrame({"현재": now, "평소": mean, "평소_최소": bs.min(axis=1), "평소_최대": bs.max(axis=1)})
    out["변화"] = out["현재"] - out["평소"]
    out["변화율"] = (out["현재"] / out["평소"].where(out["평소"] > 0) - 1).astype(float)
    out["판정"] = [level(v, b) for v, b in zip(out["현재"], out["평소"])]
    return out


def compare_both(t: pd.DataFrame, today, first_day=None) -> pd.DataFrame:
    """최근 3일과 최근 7일을 나란히. 열 이름 앞에 '3일_', '7일_'."""
    parts = []
    for n in WINDOWS:
        c = compare(t, today, n, first_day)
        parts.append(c.add_prefix(f"{n}일_"))
    return pd.concat(parts, axis=1)


def window_labels(today) -> dict[int, dict[str, str]]:
    """{3: {'현재': '10/23~10/25', '평소': '지난 4주 같은 요일'}, 7: {...}}"""
    out = {}
    for n in WINDOWS:
        cur, _ = windows(today, n)
        out[n] = {"현재": span_label(cur), "평소": f"지난 {WEEKS}주 같은 요일"}
    return out

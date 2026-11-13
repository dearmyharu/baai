"""AI 분석가 전용 계산: 조립형 분석(analyze 도구).

대시보드 화면이 쓰는 core/metrics.py는 건드리지 않고(공동 작업 파일), 챗봇 기능은 이 파일에 둔다.
완료 주문·주문상품·방문·고객 속성 같은 기본 정의는 metrics의 함수를 그대로 써서 대시보드와 같은 숫자가 나온다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import AGE_GROUPS, completed_items, completed_orders, customer_attrs, in_period


def _grade_at(m: dict, df: pd.DataFrame, time_col: str) -> pd.Series:
    """df의 각 행(customer_id, time_col)의 그 시점 등급 (등급 변경 이력 as-of).
    metrics._grade_at과 같은 계산이지만, 그쪽은 인덱스가 어긋나 기간 앞쪽 일부 말고는 NaN이 되는 버그가 있어
    (2026-11-06 발견, 수정은 별도 PR) 여기서는 고친 판을 쓴다."""
    gh = m["raw"]["customer_grade_history"].sort_values("effective_from")
    x = df[["customer_id", time_col]].reset_index().sort_values(time_col)
    x = pd.merge_asof(x, gh[["customer_id", "effective_from", "effective_to", "membership_grade"]],
                      left_on=time_col, right_on="effective_from", by="customer_id", direction="backward")
    ok = x["effective_to"].isna() | (x[time_col] < x["effective_to"])
    return pd.Series(x["membership_grade"].where(ok.values).values, index=x["index"].values).reindex(df.index)


# 조립형 분석: 지표 × 기준(최대 2개) × 기간
# 지표마다 계산 단위(주문·주문상품·방문)가 정해져 있고, 기준은 그 단위에서 만들 수 있는 것만 쓴다.
# ---------------------------------------------------------------------------
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
DAYPARTS = ["심야(0-5시)", "아침(6-10시)", "점심(11-13시)", "오후(14-17시)", "저녁(18-21시)", "밤(22-23시)"]

# 지표: (계산 단위, 단위 표시, 설명)
SLICE_METRICS = {
    "매출": ("order", "won", "완료 매출(완료 주문 결제 금액 합, 배송비 포함)"),
    "상품매출": ("item", "won", "상품매출(완료 주문의 쿠폰 차감 후 상품금액, 배송비 제외)"),
    "판매수량": ("item", "count", "판매 수량(완료 주문 상품 개수)"),
    "주문수": ("order", "count", "완료 주문 수"),
    "구매고객수": ("order", "count", "구매 고객 수(완료 주문이 있는 고유 고객)"),
    "객단가": ("order", "won", "객단가(완료 매출 ÷ 완료 주문 수)"),
    "방문수": ("session", "count", "방문 세션 수(로그인 고객)"),
    "구매전환율": ("session", "rate", "세션 구매 전환율(구매 세션 ÷ 방문 세션)"),
    "장바구니율": ("session", "rate", "장바구니 담기율(장바구니 담은 세션 ÷ 방문 세션)"),
    "장바구니구매전환율": ("session", "rate", "장바구니→구매 전환율(상품 클릭 후 장바구니에 담은 세션 중 구매한 세션 비율, 구매 퍼널과 같은 기준)"),
}
# 기준: 표시 이름, 쓸 수 있는 단위, 순서가 있는 기준이면 순서
SLICE_DIMS = {
    "상품": ("product", {"item"}), "카테고리": ("category", {"item"}),
    "테마": ("theme", {"order", "item", "session"}), "경로": ("path", {"order", "item", "session"}),
    "요일": ("weekday", {"order", "item", "session"}), "평일주말": ("daytype", {"order", "item", "session"}),
    "시간대": ("daypart", {"order", "item", "session"}), "시각": ("hour", {"order", "item", "session"}),
    "일": ("date", {"order", "item", "session"}), "주": ("week", {"order", "item", "session"}),
    "월": ("month", {"order", "item", "session"}),
    "성별": ("gender", {"order", "item", "session"}), "연령대": ("age_group", {"order", "item", "session"}),
    "지역": ("region", {"order", "item", "session"}), "가입경로": ("signup_channel", {"order", "item", "session"}),
    "등급": ("grade", {"order", "item", "session"}), "첫구매기존": ("customer_type", {"order", "item"}),
    "신규재방문": ("visitor_type", {"order", "item", "session"}),
}
ORDERED_DIMS = {"요일": WEEKDAYS, "평일주말": ["평일", "주말"], "시간대": DAYPARTS, "시각": list(range(24)),
                "연령대": AGE_GROUPS}
TIME_DIMS = {"일", "주", "월"}
_LABELS = {"CURATION": "큐레이션 경유", "BROWSE": "일반 탐색", "NEW": "신규 방문", "RETURNING": "재방문", "UNKNOWN": "판정 불가",
           "F": "여성", "M": "남성"}


def _slice_frame(m: dict, unit: str, start, end, dims: list[str]) -> pd.DataFrame:
    """계산 단위의 행(완료 주문 / 완료 주문상품 / 방문)에 기준 열을 붙인다. 기준 열 이름 = 기준 표시 이름."""
    if unit == "session":
        df = in_period(m["sessions"], "start", start, end).copy()
        t = df["start"]
    elif unit == "item":
        df = completed_items(m, start, end).copy()
        t = df["order_time"]
    else:
        df = completed_orders(m, start, end).copy()
        t = df["order_time"]
    need_cust = {"성별", "연령대", "지역", "가입경로"} & set(dims)
    cust = customer_attrs(m) if need_cust else None
    for d in dims:
        if d == "상품":
            df[d] = df["product_name"]
        elif d == "카테고리":
            df[d] = df["category"]
        elif d == "테마":
            df[d] = df["theme_name"].fillna("테마 경유 아님")
        elif d == "경로":
            df[d] = df["path"].map(_LABELS).fillna("기타")
        elif d == "요일":
            df[d] = t.dt.dayofweek.map(dict(enumerate(WEEKDAYS)))
        elif d == "평일주말":
            df[d] = np.where(t.dt.dayofweek >= 5, "주말", "평일")
        elif d == "시간대":
            df[d] = pd.cut(t.dt.hour, bins=[-1, 5, 10, 13, 17, 21, 23], labels=DAYPARTS).astype(str)
        elif d == "시각":
            df[d] = t.dt.hour
        elif d in TIME_DIMS:
            df[d] = {"일": t.dt.normalize(), "주": t.dt.to_period("W-SUN").dt.start_time,
                     "월": t.dt.to_period("M").dt.start_time}[d]
        elif d in ("성별", "연령대", "지역", "가입경로"):
            col = {"성별": "gender", "연령대": "age_group", "지역": "region", "가입경로": "signup_channel"}[d]
            df[d] = df["customer_id"].map(cust[col]).map(lambda v: _LABELS.get(v, v)).fillna("정보 없음")
        elif d == "등급":
            if unit == "session":
                df[d] = _grade_at(m, df, "start")
            else:
                df[d] = df["order_id"].map(m["orders"].set_index("order_id")["grade_at_order"])
            df[d] = df[d].fillna("정보 없음")
        elif d == "첫구매기존":
            df[d] = df["customer_type"].fillna("정보 없음")
        elif d == "신규재방문":
            df[d] = df["visitor_type"].map(_LABELS).fillna("판정 불가")
    return df


def slice_metric(m: dict, start, end, metric: str, dims: list[str]) -> pd.DataFrame:
    """기준별 지표 값. 반환 열: 기준들…, 값, 표본(값을 만든 행 수: 주문·주문상품·세션)"""
    unit = SLICE_METRICS[metric][0]
    df = _slice_frame(m, unit, start, end, dims)
    if df.empty:
        return pd.DataFrame(columns=[*dims, "값", "표본"])
    g = df.groupby(dims, dropna=False, observed=True)
    if metric == "매출":
        out = g.agg(값=("total_amount", "sum"), 표본=("order_id", "nunique"))
    elif metric == "상품매출":
        out = g.agg(값=("net_sales", "sum"), 표본=("order_id", "nunique"))
    elif metric == "판매수량":
        out = g.agg(값=("quantity", "sum"), 표본=("order_id", "nunique"))
    elif metric == "주문수":
        out = g.agg(값=("order_id", "nunique"), 표본=("order_id", "nunique"))
    elif metric == "구매고객수":
        out = g.agg(값=("customer_id", "nunique"), 표본=("order_id", "nunique"))
    elif metric == "객단가":
        out = g.agg(매출=("total_amount", "sum"), 표본=("order_id", "nunique"))
        out["값"] = out["매출"] / out["표본"]
        out = out[["값", "표본"]]
    elif metric == "방문수":
        out = g.agg(값=("session_id", "size"), 표본=("session_id", "size"))
    elif metric == "구매전환율":
        out = g.agg(값=("has_purchase", "mean"), 표본=("session_id", "size"))
    elif metric == "장바구니율":
        out = g.agg(값=("has_cart", "mean"), 표본=("session_id", "size"))
    elif metric == "장바구니구매전환율":
        # 구매 퍼널(metrics.step_masks, ALL)과 같은 분모: 상품 클릭 + 장바구니까지 간 세션
        cart = df[df["has_product_click"] & df["has_cart"]]
        out = cart.groupby(dims, dropna=False, observed=True).agg(값=("has_purchase", "mean"), 표본=("session_id", "size"))
    else:
        raise ValueError(f"모르는 지표: {metric}")
    return out.reset_index()

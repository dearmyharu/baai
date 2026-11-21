"""Growth Lab v2: category-first promotion planning and briefing result review.

The chatbot integration is intentionally excluded from this UI revision.
Historical metrics are based on the app's frozen as-of date (2026-10-26).
"""
from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from engine import briefing as B
from engine import data as D
from engine import growth as G
from engine import growth_policy as GP
from engine import ui


ss = st.session_state
today = D.TODAY
mart = ui.get_mart()
assumed_response = (-0.05, 0.10, 0.30)  # fixed defaults; NOT a predicted promotion uplift

st.title("Growth Lab")
st.caption(
    f"데이터 기준일 {today:%Y-%m-%d} 아침 · 최근 28일 주문 기준 · "
    f"이익 = 결제금액 − 상품원가 − 배송 원가(주문당 {B.SHIP_COST:,}원), 기타 비용 제외"
)

# Open the existing promotion automatically when coming from Morning Briefing.
request = ss.get("lab_request") or {}
incoming = request.get("promotion_id") if request.get("type") == "lab" else None
if incoming and ss.get("gl_incoming_id") != incoming:
    ss["gl_incoming_id"] = incoming
    ss["gl_screen"] = "등록된 프로모션"
ss.setdefault("gl_screen", "새 프로모션 분석")
screen = st.segmented_control(
    "보기", ["새 프로모션 분석", "등록된 프로모션"], key="gl_screen",
    label_visibility="collapsed"
)


def show_result(pid: str):
    promos = mart["raw"].get("promotion", pd.DataFrame())
    row = promos[promos["promotion_id"].astype(str).eq(str(pid))]
    if row.empty:
        st.warning("등록된 프로모션을 찾지 못했습니다.")
        return
    saved = row.iloc[0]
    st.subheader(str(saved["promotion_name"]))
    st.caption(f"{pd.Timestamp(saved['start_date']):%Y-%m-%d} ~ "
               f"{pd.Timestamp(saved['end_date']):%Y-%m-%d} · {saved['category']} 카테고리")
    terms = {
        "대상": str(saved["category"]),
        "수단": str(saved["lever"]),
        "할인 방식": str(saved.get("discount_type", "") or "기존 등록 데이터"),
        "할인 조건": str(saved.get("discount_value", "") or saved.get("discount_pct", "")),
        "배송 기준": str(saved.get("shipping_threshold", "") or "—"),
        "주 지표": str(saved["primary_metric"]),
        "짝 지표": str(saved["guard_metric"]),
        "중단 기준": str(saved["stop_rule"]),
    }
    with st.expander("등록한 실행 계획", expanded=True):
        st.dataframe(pd.DataFrame(terms.items(), columns=["항목", "내용"]),
                     hide_index=True, width="stretch")
    status = next((p for p in B.promo_status(mart, today - pd.Timedelta(days=1))
                   if str(p["id"]) == str(pid)), None)
    if status is None:
        if pd.Timestamp(saved["start_date"]).normalize() >= today:
            st.info("아직 시작 전인 실행 계획입니다. 시작일 이후 실제 주문 데이터가 쌓이면 결과를 확인할 수 있습니다.")
        else:
            st.info("현재 데이터 기준일에서는 평가할 수 없는 프로모션입니다. 종료 후 14일이 지났거나 관측 데이터가 부족합니다.")
        return
    p = status
    st.markdown("#### 운영 성과")
    a, b, c = st.columns(3)
    a.metric("대상 일평균 매출", ui.won(p["sales_dur"]),
             f"{p['sales_chg']:+.1%}" if p["sales_chg"] is not None else None)
    b.metric("다른 카테고리 대비 매출 비중 변화",
             f"{p['effect']:+.1%}" if p["effect"] is not None else "—")
    c.metric("대상 이익률", ui.pct(p["margin_dur"]),
             f"{-p['margin_drop_pp']:+.1f}%p" if p["margin_drop_pp"] is not None else None)
    if p["status"] == "중단 검토":
        st.error(f"판정: {p['status']} · 이익률 중단 기준 점검이 필요합니다.")
    else:
        st.info(f"판정: {p['status']} · 운영 {p['days']}/{p['total_days']}일")
    series = G.result_series(mart, p)
    series = series[series["날짜"] < today]
    if len(series):
        chart = alt.Chart(series).mark_bar().encode(
            x=alt.X("날짜:T", title=None),
            y=alt.Y("매출:Q", title="일매출(원)"),
            color=alt.Color("구간:N", title=None),
            tooltip=["날짜:T", alt.Tooltip("매출:Q", format=",.0f")])
        st.altair_chart(chart.properties(height=240), width="stretch")
    st.caption("아침 브리핑과 동일한 판정을 사용합니다. 관측 전후 비교는 무작위 실험에 의한 인과적 검증이 아닙니다.")
    ss["growth_context"] = {"화면": "Growth Lab 프로모션 결과", "프로모션": p["name"],
                            "판정": p["status"], "카테고리": p["category"]}


def show_registered():
    st.subheader("등록된 프로모션")
    promos = mart["raw"].get("promotion", pd.DataFrame()).copy()
    if promos.empty:
        st.info("등록된 프로모션이 없습니다. 새 프로모션 분석에서 먼저 계획을 등록할 수 있습니다.")
        return
    current = {p["id"]: p["status"] for p in B.promo_status(mart, today - pd.Timedelta(days=1))}
    promos["평가 상태"] = promos["promotion_id"].map(current).fillna("시작 전 / 평가 기간 외")
    labels = promos["promotion_id"].astype(str) + " · " + promos["promotion_name"].astype(str)
    selection = st.selectbox("조회할 프로모션", list(promos["promotion_id"].astype(str)),
                             index=(list(promos["promotion_id"].astype(str)).index(str(incoming))
                                    if incoming and str(incoming) in list(promos["promotion_id"].astype(str)) else 0),
                             format_func=lambda pid: str(labels.loc[promos["promotion_id"].astype(str).eq(pid)].iloc[0]))
    show_result(selection)
    with st.expander("전체 프로모션 목록"):
        cols = ["promotion_id", "promotion_name", "start_date", "end_date", "평가 상태"]
        table = promos[cols].copy()
        table["start_date"] = pd.to_datetime(table["start_date"]).dt.strftime("%Y-%m-%d")
        table["end_date"] = pd.to_datetime(table["end_date"]).dt.strftime("%Y-%m-%d")
        st.dataframe(table, hide_index=True, width="stretch")


def show_planner():
    st.subheader("1. 프로모션 설정")
    cats = sorted(mart["raw"]["product"]["category"].dropna().astype(str).unique().tolist())
    if not cats:
        st.warning("선택할 카테고리가 없습니다.")
        return
    col1, col2 = st.columns(2)
    category = col1.selectbox("카테고리", cats, key="gl_cat")
    policy = col2.selectbox(
        "프로모션 종류", ["price", "discount", "shipping"],
        format_func=lambda p: {"price": "판매가 할인", "discount": "할인 쿠폰", "shipping": "무료배송 기준 변경"}[p],
        key="gl_policy"
    )
    coupon_type = "rate"
    if policy == "discount":
        coupon_type_label = st.segmented_control(
            "할인 방식", ["할인율 (%)", "할인액 (원)"], default="할인율 (%)",
            key="gl_coupon_mode"
        )
        coupon_type = "fixed" if coupon_type_label == "할인액 (원)" else "rate"
        if coupon_type == "fixed":
            value = st.number_input("주문당 할인액 (원)", min_value=0, max_value=100000,
                                    value=2000, step=500, key="gl_coupon_fixed")
        else:
            value = st.number_input("할인율 (%)", min_value=0.0, max_value=50.0,
                                    value=5.0, step=1.0, key="gl_coupon_pct")
        st.caption("선택 카테고리 상품금액에만 적용 · 주문당 1회 · 기존 해당 카테고리 쿠폰과 중복되지 않음")
    elif policy == "price":
        value = st.number_input("판매가 할인율 (%)", min_value=0.0, max_value=50.0,
                                value=5.0, step=1.0, key="gl_price_pct")
        st.caption("선택 카테고리 상품에 적용 · 기존 해당 카테고리 쿠폰 할인과 중복되지 않음")
    else:
        value = st.number_input("변경 후 무료배송 기준금액 (원)", min_value=0, max_value=30000,
                                value=20000, step=1000, key="gl_ship_threshold")
        st.caption(
            "기존 기준 30,000원 → 입력 금액으로 변경. "
            "선택 카테고리 상품금액만 기준을 충족해야 무료배송입니다. "
            "예: 정육 15,000원 + 과일 5,000원은 정육 20,000원 기준을 충족하지 않습니다."
        )

    lever = {"policy": policy, "value": value, "discount_type": coupon_type}
    try:
        normalized = GP.normalize_lever(lever)
    except ValueError as ex:
        st.error(str(ex))
        return
    st.caption(
        "기본 주문 반응 가정 자동 적용: 최소 −5% · 가장 가능성 높은 값 +10% · 최대 +30% "
        "(실제 고객 행동의 예측값은 아닙니다)."
    )
    params = {"category": category, "lever": normalized}
    if st.button("프로모션 분석하기", type="primary", use_container_width=True):
        ss["gl_analysis_params"] = params
    if ss.get("gl_analysis_params") != params:
        st.info("카테고리와 프로모션 조건을 입력한 후 '프로모션 분석하기'를 선택하십시오.")
        return

    try:
        s, e = G.base_period(today)
        pair = GP.replay(mart, category, normalized, s, e)
        be = GP.break_even(pair)
        # Detection uses the resulting category sales change, NOT order growth:
        # a 10% discount with 10% more orders need not increase sales.
        expected_sales_change = (
            (be["after"]["revenue"] / be["before"]["revenue"]) * (1 + assumed_response[1]) - 1
            if be["before"]["revenue"] > 0 else 0.0
        )
        detect = G.detect_days(mart, {"type": "category", "value": category},
                               today, effect=abs(expected_sales_change))
        suggested_days = (detect["days"] if detect["status"] == "확인 가능"
                          and detect["days"] is not None else 14)
        with st.expander("운영 기간 변경 (선택 사항)"):
            override = st.toggle("운영 기간 직접 지정", value=False, key="gl_days_override")
            if override:
                days = st.number_input("운영 기간(일)", min_value=7, max_value=60,
                                       value=14, step=1, key="gl_days_custom")
            else:
                days = suggested_days
        mc = GP.monte_carlo(mart, category, normalized, today, days=days,
                            low=assumed_response[0], mode=assumed_response[1],
                            high=assumed_response[2], n=20000)
    except (ValueError, KeyError) as ex:
        st.error(f"시뮬레이션을 실행하지 못했습니다: {ex}")
        return

    st.subheader("2. 분석 결과")
    st.caption(f"선택한 카테고리 상품 매출 기준 · 운영 {days}일 · 20,000회 몬테카를로")
    a, b, c = st.columns(3)
    a.metric("예상 매출", ui.won(mc["sales_p50"]),
             help="운영 기간 내 선택 카테고리 상품매출의 조건부 중앙값입니다. 다른 카테고리 매출은 제외합니다.")
    a.caption(f"예상 범위(10~90%): {ui.won(mc['sales_p10'])} ~ {ui.won(mc['sales_p90'])}")
    b.metric("예상 이익률", ui.pct(mc["margin_p50"]),
             help="선택 카테고리 상품원가와 주문별 배송 부담 배분액을 반영한 이익률 중앙값")
    b.caption(f"예상 범위(10~90%): {ui.pct(mc['margin_p10'])} ~ {ui.pct(mc['margin_p90'])}")
    if detect["days"] is not None:
        c.metric("효과 확인 기간", f"{detect['days']}일", help=detect["note"])
    else:
        c.metric("효과 확인 기간", "산출 어려움", help=detect["note"])
    c.caption(f"매출 변화 가정 {expected_sales_change:+.1%} · {detect['status']}")

    with st.container(border=True):
        if be["required"] is None:
            st.markdown("#### 기존 이익 유지: 주문 증가만으로 달성하기 어려움")
            st.caption("정책 적용 후 주문당 이익이 0 이하이므로 주문 수를 늘려도 본전 회복이 어렵습니다.")
        else:
            req = max(be["required"], 0.0)
            st.markdown(f"#### 기존 이익을 유지하려면 주문 **+{req:.1%}** 필요")
            st.caption(f"기준 28일 주문 {be['orders']:,}건 · 추가 주문 "
                       f"{max(0, be['required_orders']):,}건 · 카테고리 매출 구성·원가가 유지된다는 가정")
        st.metric("기존보다 이익이 증가할 확률", f"{mc['prob']:.1%}",
                  help="정책 미시행과 비교한 조건부 이익 증가 확률")
    with st.expander("시뮬레이션 상세 · 근거 및 가정"):
        st.markdown(
            f"**기본 주문 반응 가정:** {assumed_response[0]:+.0%} ~ "
            f"{assumed_response[2]:+.0%}, 가장 가능성 높은 값 {assumed_response[1]:+.0%}"
        )
        st.markdown(
            f"**이익 차이(10·50·90백분위수):** "
            f"{ui.won(mc['profit_delta_p10'])} / {ui.won(mc['profit_delta_p50'])} / "
            f"{ui.won(mc['profit_delta_p90'])}"
        )
        df = pd.DataFrame([{
            "구분": "정책 적용 전(기준 28일)", "매출": be["before"]["revenue"],
            "이익": be["before"]["profit"], "이익률": be["before"]["margin"]
        }, {
            "구분": "주문 수 동일 시 정책 적용 후(28일)", "매출": be["after"]["revenue"],
            "이익": be["after"]["profit"], "이익률": be["after"]["margin"]
        }])
        st.dataframe(df, hide_index=True, width="stretch")
        hist = alt.Chart(mc["hist"]).mark_bar(color=ui.C_MAIN).encode(
            x=alt.X("이익 차이:Q", bin=alt.Bin(maxbins=35), title="정책 시행−미시행 이익 차이(원)"),
            y=alt.Y("count()", title="시뮬레이션 횟수"))
        st.altair_chart(hist.properties(height=175), width="stretch")
        st.caption(
            "최근 56일 대상 주문의 일별 매출·이익을 재표본화하고, "
            "기본 주문 반응(삼각분포)을 적용한 조건부 결과입니다. "
            "실제 주문 증가율의 AI 예측이나 프로모션 효과의 인과 추정은 아닙니다."
        )
        st.caption(f"효과 확인 기간: {detect['note']}")

    st.subheader("3. 실행 계획")
    start = st.date_input("프로모션 시작일", value=today.date(), key="gl_start")
    end = start + timedelta(days=int(days)-1)
    with st.container(border=True):
        st.markdown(f"**{category} · {G.lever_text(normalized)}**")
        st.write(f"운영 기간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({days}일)")
        st.write(f"주 지표: {category} 일평균 매출")
        st.write(f"짝 지표: {category} 이익률")
        st.write("중단 기준: 이익률이 시작 전보다 8%p 초과 하락하면 중단 검토")
    st.caption("실행 계획 등록은 운영 정책을 저장하는 기능입니다. 실제 쇼핑몰 할인이나 쿠폰을 발행하지는 않습니다.")
    if st.button("실행 계획 등록", type="primary", use_container_width=True):
        try:
            row = G.plan_row(mart["raw"]["promotion"],
                             {"type": "category", "value": category}, normalized,
                             start, end, today, f"{category} 일평균 매출", 8.0,
                             response=assumed_response)
            location = G.save_plan(row)
        except Exception as ex:
            st.error(f"계획 등록에 실패했습니다: {ex}")
        else:
            ui.get_mart.clear()
            st.success(f"{row['promotion_id']} 실행 계획을 등록했습니다. 저장 위치: {location}. "
                       "등록된 프로모션 화면에서 확인할 수 있습니다.")
    ss["growth_context"] = {
        "화면": "Growth Lab 프로모션 검토", "카테고리": category,
        "프로모션": G.lever_text(normalized), "손익 기준": "최근 28일",
        "주문 반응 가정": assumed_response, "운영 일수": int(days),
        "예상 매출 중앙값": round(mc["sales_p50"]),
        "예상 이익률 중앙값": round(mc["margin_p50"], 4),
        "이익 증가 확률": round(mc["prob"], 4),
        "본전 주문 증가율": be["required"], "효과 확인 기간": detect["days"]
    }


if screen == "등록된 프로모션":
    show_registered()
else:
    show_planner()

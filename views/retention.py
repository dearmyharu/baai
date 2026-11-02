"""④ 고객·리텐션: 어떤 고객이 돌아오고, 어떤 고객이 떠나는가?"""
import altair as alt
import pandas as pd
import streamlit as st

from core import ui
from core.metrics import (GAP_LABELS, RFM_ORDER, RFM_RULES, cohort_retention, customer_mix, repeat_gaps, repeat_rates,
                          rfm_preference, rfm_segments, rfm_summary)

m = ui.get_mart()
cur, prev = ui.period_controls()

st.title("고객·리텐션")
st.caption(f"분석 {ui.period_label(cur)} · 비교 {ui.period_label(prev)}")

# ---------------- 고객 구성 ----------------
st.subheader("구매 고객 구성")
mix = customer_mix(m, *cur)
cols = st.columns(4)
cols[0].metric("첫 구매 고객", ui.num(mix.loc["첫 구매 고객", "고객수"]), border=True,
               help="이 기간에 생애 첫 완료 주문을 한 고객 (과거 구매 0회)")
cols[1].metric("첫 구매 고객 매출 비중", ui.pct(mix.loc["첫 구매 고객", "매출 비중"]), border=True)
cols[2].metric("기존 구매 고객", ui.num(mix.loc["기존 구매 고객", "고객수"]), border=True,
               help="과거 구매 이력이 있거나 이 기간 안에 이미 첫 구매를 한 고객")
cols[3].metric("기존 구매 고객 매출 비중", ui.pct(mix.loc["기존 구매 고객", "매출 비중"]), border=True)
ui.note("한 고객이 기간 중 첫 구매 후 다시 구매하면 두 구분에 모두 잡혀 고객 수 합이 전체 구매 고객 수보다 클 수 있습니다.")

tab_co, tab_re, tab_rfm = st.tabs(["코호트", "재구매", "RFM 고객군"])

# =====================================================================
# 코호트
# =====================================================================
with tab_co:
    basis = st.segmented_control("코호트 기준", ["생애 첫 구매 고객", "관측 기간 첫 주문 고객 (기존 고객 포함)"],
                                 default="생애 첫 구매 고객", key="co_basis") or "생애 첫 구매 고객"
    ret, size = cohort_retention(m, "lifetime" if basis == "생애 첫 구매 고객" else "observed")
    heat = alt.Chart(ret).mark_rect().encode(
        x=alt.X("경과:N", title=None, sort=[f"{i}개월 후" for i in range(1, 6)], axis=alt.Axis(orient="top", labelAngle=0)),
        y=alt.Y("코호트:N", title=None),
        color=alt.Color("유지율:Q", scale=alt.Scale(scheme="greens", domain=[0, max(0.01, ret["유지율"].max())]), legend=None),
        tooltip=["코호트", "경과", alt.Tooltip("유지율:Q", format=".1%"), alt.Tooltip("고객:Q", title="재구매 고객")])
    txt = alt.Chart(ret).mark_text(fontSize=12).encode(
        x=alt.X("경과:N", sort=[f"{i}개월 후" for i in range(1, 6)]), y="코호트:N", text=alt.Text("유지율:Q", format=".0%"),
        color=alt.condition("datum.유지율 > 0.3", alt.value("white"), alt.value("#374151")))
    st.altair_chart((heat + txt).properties(height=46 * len(size) + 40), width="stretch")
    ui.note("유지율 = 코호트 고객 중 해당 월에 완료 주문이 1건 이상 있는 비율. 관찰 기간이 9월까지라 "
            "최근 코호트일수록 볼 수 있는 칸이 적고, 빈칸은 아직 관찰할 수 없는 시점입니다(0%가 아님).")

# =====================================================================
# 재구매
# =====================================================================
with tab_re:
    st.markdown("**첫 주문 후 N일 안에 다시 구매한 비율** (관측 기간의 첫 완료 주문 기준)")
    rr = repeat_rates(m)
    sel = st.segmented_control("재구매 기준", ["7일 재구매율", "30일 재구매율", "60일 재구매율"], default="30일 재구매율",
                               key="re_win") or "30일 재구매율"
    sub = rr[rr["기준"].eq(sel)]
    a, b = st.columns([3, 2], gap="large")
    with a:
        ch = alt.Chart(sub).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("첫 주문 월:N", title=None, axis=alt.Axis(labelAngle=0)),
            xOffset="구분:N",
            y=alt.Y("재구매율:Q", axis=alt.Axis(format=".0%"), title=sel),
            color=alt.Color("구분:N", scale=alt.Scale(domain=["생애 첫 구매 고객", "기존 구매 고객"], range=[ui.C_ACCENT, ui.C_MAIN]),
                            legend=alt.Legend(title=None)),
            tooltip=["첫 주문 월", "구분", alt.Tooltip("재구매율:Q", format=".1%"), alt.Tooltip("대상 고객:Q", format=",")])
        st.altair_chart(ch.properties(height=280), width="stretch")
    with b:
        st.dataframe(sub.pivot_table(index="첫 주문 월", columns="구분", values=["재구매율", "대상 고객"]).round(3),
                     width="stretch")
    win_n = int(sel.split("일")[0])
    ui.note(f"재구매 정의: 관측 기간(4/1~9/30)의 첫 완료 주문 이후 {win_n}일 안에 완료 주문이 또 있으면 재구매. "
            f"첫 주문 후 {win_n}일이 9/30 안에 끝나는 고객만 대상이라, 최근 월은 대상이 적거나 빠집니다.")

    st.markdown("**재구매까지 걸린 기간** (연속된 두 완료 주문 사이 간격, 전체 관측 기간)")
    rg = repeat_gaps(m)
    gd, labels = rg["dist"], GAP_LABELS
    c1, c2 = st.columns([3, 1])
    c1.altair_chart(alt.Chart(gd).mark_bar(color=ui.C_MAIN, cornerRadiusEnd=3).encode(
        x=alt.X("간격:N", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("비중:Q", axis=alt.Axis(format=".0%"), title=None),
        tooltip=["간격", alt.Tooltip("건수:Q", format=","), alt.Tooltip("비중:Q", format=".1%")]).properties(height=240),
        width="stretch")
    c2.metric("재구매 간격 중앙값", f"{rg['median_days']:.0f}일" if pd.notna(rg["median_days"]) else "–", border=True)
    c2.metric("구매 고객당 완료 주문", f"{rg['orders_per_buyer']:.2f}건", border=True)

# =====================================================================
# RFM
# =====================================================================
with tab_rfm:
    ref = cur[1]
    st.caption(f"기준일 {ui.d(ref - pd.Timedelta(days=1))} (분석 기간 종료일). 예측 모델이 아니라 구매 이력 규칙으로 나눈 고객군입니다.")
    r = rfm_segments(m, ref)
    rules, order_seg = RFM_RULES, RFM_ORDER
    summ = rfm_summary(m, *cur, r=r)

    a, b = st.columns([3, 2], gap="large")
    with a:
        long = summ.melt(id_vars="고객군", value_vars=["고객 비중", "매출 비중"], var_name="구분", value_name="비중")
        st.altair_chart(alt.Chart(long).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("고객군:N", sort=order_seg, title=None), x=alt.X("비중:Q", axis=alt.Axis(format=".0%"), title=None),
            yOffset="구분:N",
            color=alt.Color("구분:N", scale=alt.Scale(domain=["고객 비중", "매출 비중"], range=[ui.C_PREV, ui.C_MAIN]),
                            legend=alt.Legend(title=None)),
            tooltip=["고객군", "구분", alt.Tooltip("비중:Q", format=".1%")]).properties(height=340), width="stretch")
    with b:
        st.dataframe(summ[["고객군", "고객수", "평균주문", "경과일중앙값", "분석 기간 매출"]], hide_index=True, width="stretch",
                     column_config={"평균주문": st.column_config.NumberColumn(format="%.1f"),
                                    "분석 기간 매출": st.column_config.NumberColumn(format="localized")})
    with st.expander("고객군 분류 기준 보기"):
        st.dataframe(rules, hide_index=True, width="stretch")
        ui.note("주문 수(F)와 금액(M)은 관측 기간(4/1~) 기준, 최근성(R)은 4/1 이전 마지막 구매일도 반영합니다. "
                "'휴면 추정'은 구매 이력만으로 본 규칙 분류이며 이탈 확률이 아닙니다.")

    st.markdown("**고객군별 선호** (분석 기간 완료 주문 기준)")
    pref_dim = st.segmented_control("선호 기준", ["카테고리", "큐레이션 테마"], default="카테고리", key="rfm_pref") or "카테고리"
    col = "category" if pref_dim == "카테고리" else "theme_name"
    pv = rfm_preference(m, *cur, dim=col, r=r)
    st.altair_chart((alt.Chart(pv).mark_rect().encode(
        x=alt.X(f"{col}:N", title=None, axis=alt.Axis(labelAngle=-30)), y=alt.Y("고객군:N", sort=order_seg, title=None),
        color=alt.Color("비중:Q", scale=alt.Scale(scheme="greens"), legend=None),
        tooltip=["고객군", f"{col}:N", alt.Tooltip("비중:Q", format=".1%")]) +
        alt.Chart(pv).mark_text(fontSize=10).encode(x=f"{col}:N", y=alt.Y("고객군:N", sort=order_seg),
                                                    text=alt.Text("비중:Q", format=".0%"),
                                                    color=alt.condition("datum.비중 > 0.25", alt.value("white"), alt.value("#374151")))
        ).properties(height=320), width="stretch")
    ui.note("행마다 합이 100%입니다. 테마 기준은 큐레이션을 거친 주문만 포함합니다.")

    st.markdown("**고객군을 Growth Lab 과제로 저장**")
    pick = st.selectbox("고객군", [s_ for s_ in order_seg if s_ in set(summ["고객군"])], key="rfm_pick")
    row = summ.set_index("고객군").loc[pick]
    cand = {"kind": "segment", "title": f"RFM '{pick}' 고객군 관리", "metric": "고객군 규모·매출 비중", "segment": pick,
            "current": row["매출 비중"], "previous": None, "unit": "rate", "n_current": int(row["고객수"]), "n_previous": 0,
            "p_value": None,
            "definition": f"{rules.set_index('고객군').loc[pick, '분류 기준']} · 고객 {int(row['고객수']):,}명, "
                          f"분석 기간 매출 비중 {ui.pct(row['매출 비중'])}, 경과일 중앙값 {row['경과일중앙값']:.0f}일"}
    ui.save_to_lab_button(cand, "고객·리텐션", cur, prev, key=f"rfm_save_{pick}")

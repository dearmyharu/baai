"""④ 고객·리텐션: 어떤 고객이 돌아오고, 어떤 고객이 떠나는가?"""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from core import ui
from core.data import AS_OF, PERIOD_START
from core.metrics import in_period

m = ui.get_mart()
cur, prev = ui.period_controls()

st.title("고객·리텐션")
st.caption(f"분석 {ui.period_label(cur)} · 비교 {ui.period_label(prev)}")

orders = m["orders"]
comp = orders[orders["order_status"].eq("COMPLETED")].sort_values("order_time")
OBS_END = AS_OF.normalize() + pd.Timedelta(days=1)          # 2026-10-01

# ---------------- 고객 구성 ----------------
st.subheader("구매 고객 구성")
cc = in_period(comp, "order_time", *cur)
mix = cc.groupby("customer_type").agg(고객수=("customer_id", "nunique"), 매출=("total_amount", "sum"),
                                      주문수=("order_id", "nunique")).reindex(["첫 구매 고객", "기존 구매 고객"])
mix["매출 비중"] = mix["매출"] / mix["매출"].sum()
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
    if basis == "생애 첫 구매 고객":
        first = comp[comp["is_first_purchase"].eq(1)].groupby("customer_id")["month"].min()
    else:
        first = comp.groupby("customer_id")["month"].min()
    act = comp[["customer_id", "month"]].drop_duplicates()
    act = act[act["customer_id"].isin(first.index)]
    act["cohort"] = act["customer_id"].map(first)
    act["k"] = ((act["month"].dt.year - act["cohort"].dt.year) * 12 + act["month"].dt.month - act["cohort"].dt.month)
    size = first.value_counts().sort_index()
    ret = act[act["k"] >= 1].groupby(["cohort", "k"])["customer_id"].nunique().reset_index(name="고객")
    grid = pd.MultiIndex.from_product([size.index, range(1, 6)], names=["cohort", "k"]).to_frame(index=False)
    grid = grid[grid["cohort"].dt.year * 12 + grid["cohort"].dt.month + grid["k"] <= OBS_END.year * 12 + OBS_END.month - 1]
    ret = grid.merge(ret, how="left").fillna({"고객": 0})
    ret["유지율"] = ret["고객"] / ret["cohort"].map(size)
    ret["코호트"] = ret["cohort"].dt.strftime("%Y-%m") + " (n=" + ret["cohort"].map(size).astype(str) + ")"
    ret["경과"] = ret["k"].astype(str) + "개월 후"
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
    seq = comp[["customer_id", "order_time", "is_first_purchase"]].copy()
    seq["next_time"] = seq.groupby("customer_id")["order_time"].shift(-1)
    seq["gap_days"] = (seq["next_time"] - seq["order_time"]).dt.total_seconds() / 86400
    firsts = seq.groupby("customer_id").head(1).copy()
    firsts["month"] = firsts["order_time"].dt.to_period("M").dt.start_time
    firsts["구분"] = np.where(firsts["is_first_purchase"].eq(1), "생애 첫 구매 고객", "기존 구매 고객")
    rows = []
    for win in (7, 30, 60):
        elig = firsts[firsts["order_time"] + pd.Timedelta(days=win) <= OBS_END]
        for (mon, grp_), g in elig.groupby(["month", "구분"]):
            rows.append({"첫 주문 월": mon.strftime("%Y-%m"), "구분": grp_, "기준": f"{win}일 재구매율",
                         "대상 고객": len(g), "재구매율": (g["gap_days"] <= win).mean()})
    rr = pd.DataFrame(rows)
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
    gaps = seq["gap_days"].dropna()
    bins = [0, 3, 7, 14, 21, 30, 45, 60, 90, 200]
    labels = ["0-3일", "4-7일", "8-14일", "15-21일", "22-30일", "31-45일", "46-60일", "61-90일", "91일+"]
    gd = pd.cut(gaps, bins=bins, labels=labels, include_lowest=True).value_counts().reindex(labels).reset_index()
    gd.columns = ["간격", "건수"]
    gd["비중"] = gd["건수"] / gd["건수"].sum()
    c1, c2 = st.columns([3, 1])
    c1.altair_chart(alt.Chart(gd).mark_bar(color=ui.C_MAIN, cornerRadiusEnd=3).encode(
        x=alt.X("간격:N", sort=labels, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("비중:Q", axis=alt.Axis(format=".0%"), title=None),
        tooltip=["간격", alt.Tooltip("건수:Q", format=","), alt.Tooltip("비중:Q", format=".1%")]).properties(height=240),
        width="stretch")
    c2.metric("재구매 간격 중앙값", f"{gaps.median():.0f}일" if len(gaps) else "–", border=True)
    c2.metric("구매 고객당 완료 주문", f"{comp.groupby('customer_id').size().mean():.2f}건", border=True)

# =====================================================================
# RFM
# =====================================================================
with tab_rfm:
    ref = cur[1]
    st.caption(f"기준일 {ui.d(ref - pd.Timedelta(days=1))} (분석 기간 종료일). 예측 모델이 아니라 구매 이력 규칙으로 나눈 고객군입니다.")
    hist = comp[comp["order_time"] < ref]
    g = hist.groupby("customer_id").agg(last=("order_time", "max"), F=("order_id", "nunique"), M=("total_amount", "sum"))
    snap = m["raw"]["customer_initial_snapshot"].set_index("customer_id")
    prior_last = snap["last_purchase_date"].dropna()
    allc = g.index.union(prior_last.index)
    r = pd.DataFrame(index=allc)
    r["last"] = g["last"].reindex(allc).fillna(prior_last.reindex(allc))
    r["F"] = g["F"].reindex(allc).fillna(0).astype(int)
    r["M"] = g["M"].reindex(allc).fillna(0)
    r["recency"] = (ref - r["last"]).dt.days
    first_new = comp[comp["is_first_purchase"].eq(1)].groupby("customer_id")["order_time"].min()
    r["first_purchase"] = first_new.reindex(allc)

    def seg(x):
        if pd.notna(x.first_purchase) and x.first_purchase < ref and (ref - x.first_purchase).days <= 30 and x.F <= 1:
            return "신규 구매"
        if x.recency <= 30 and x.F >= 4:
            return "핵심"
        if x.recency <= 60 and x.F >= 2:
            return "충성"
        if x.recency <= 30:
            return "성장 가능"
        if x.recency <= 60:
            return "관심 필요"
        if x.F >= 2:
            return "이탈 우려"
        return "휴면 추정"

    r["고객군"] = r.apply(seg, axis=1)
    rules = pd.DataFrame([
        ("신규 구매", "생애 첫 구매가 최근 30일 안이고 관측 기간 완료 주문 1건 이하", "첫 구매 경험 강화, 두 번째 구매 유도"),
        ("핵심", "마지막 구매 30일 이내 · 관측 기간 주문 4건 이상", "이탈 방지, 혜택 유지"),
        ("충성", "마지막 구매 60일 이내 · 주문 2건 이상", "구매 빈도 높이기, 교차 판매"),
        ("성장 가능", "마지막 구매 30일 이내 · 주문 1건 이하", "재구매 유도"),
        ("관심 필요", "마지막 구매 31~60일 · 주문 1건 이하", "리마인드"),
        ("이탈 우려", "마지막 구매 60일 초과 · 주문 2건 이상", "복귀 유도"),
        ("휴면 추정", "마지막 구매 60일 초과 · 주문 1건 이하 (4/1 이전 마지막 구매 포함)", "저비용 재활성화 시도"),
    ], columns=["고객군", "분류 기준", "활용 방향 (가설)"])
    order_seg = list(rules["고객군"])

    cur_orders = in_period(comp, "order_time", *cur)
    summ = r.groupby("고객군").agg(고객수=("F", "size"), 평균주문=("F", "mean"), 경과일중앙값=("recency", "median"))
    cur_rev = cur_orders.assign(seg=cur_orders["customer_id"].map(r["고객군"])).groupby("seg")["total_amount"].sum()
    summ["분석 기간 매출"] = cur_rev.reindex(summ.index).fillna(0)
    summ["매출 비중"] = summ["분석 기간 매출"] / max(summ["분석 기간 매출"].sum(), 1)
    summ["고객 비중"] = summ["고객수"] / summ["고객수"].sum()
    summ = summ.reindex(order_seg).dropna(how="all").reset_index()

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
    it = in_period(m["items"], "order_time", *cur)
    it = it[it["order_status"].eq("COMPLETED")].assign(고객군=lambda x: x["customer_id"].map(r["고객군"]))
    col = "category" if pref_dim == "카테고리" else "theme_name"
    if col == "theme_name":
        it = it.dropna(subset=["theme_name"])
    pv = it.groupby(["고객군", col])["net_sales"].sum().reset_index()
    pv["비중"] = pv["net_sales"] / pv.groupby("고객군")["net_sales"].transform("sum")
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

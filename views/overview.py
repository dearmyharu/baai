"""① 통합 현황: 지금 무엇이 달라졌고, 무엇부터 확인해야 하는가?"""
import altair as alt
import pandas as pd
import streamlit as st

from core import ui
from core.metrics import detect_changes, in_period, kpis, theme_table

m = ui.get_mart()
cur, prev = ui.period_controls()
has_prev = prev is not None

st.title("통합 현황")
st.caption(f"분석 {ui.period_label(cur)} · 비교 {ui.period_label(prev)}")

k = kpis(m, *cur)
kp = kpis(m, *prev) if has_prev else {}
g = kp.get
ui.kpi_row([
    ("완료 매출", k["revenue"], g("revenue"), "won", "COMPLETED 주문의 total_amount 합 (배송비 포함, 회계 순매출 아님)"),
    ("완료 주문 수", k["orders"], g("orders"), "count", "COMPLETED 주문 수"),
    ("구매 고객 수", k["buyers"], g("buyers"), "count", "완료 주문이 있는 고유 고객 수"),
    ("객단가", k["aov"], g("aov"), "won", "완료 매출 ÷ 완료 주문 수"),
    ("세션 구매 전환율", k["cvr"], g("cvr"), "rate",
     "구매 세션 ÷ 전체 세션(큐레이션+일반 탐색). 쇼핑몰 전체 방문 전환율과 다름. 변화는 %p"),
    ("재구매 고객 비중", k["repeat_rate"], g("repeat_rate"), "rate",
     "기간 안에서 완료 주문이 2건 이상인 고객 ÷ 구매 고객. 기간이 짧을수록 낮게 나옴"),
], has_prev)
if has_prev and cur[1] - cur[0] != prev[1] - prev[0]:
    ui.note(f"분석 기간({(cur[1]-cur[0]).days}일)과 비교 기간({(prev[1]-prev[0]).days}일)의 일수가 달라 "
            "합계 지표(매출·주문·고객 수)는 일수 차이의 영향을 받습니다.")

# 매출 변화 분해: 주문 수 vs 객단가
if has_prev and kp["orders"] and k["orders"]:
    rev_ch = k["revenue"] - kp["revenue"]
    ord_eff = (k["orders"] - kp["orders"]) * kp["aov"]
    aov_eff = (k["aov"] - kp["aov"]) * k["orders"]
    st.markdown(
        f"**매출 변화 나눠 보기** · 완료 매출 {ui.won(rev_ch)} 변화 = "
        f"주문 수 변화 효과 **{ui.won(ord_eff)}** + 객단가 변화 효과 **{ui.won(aov_eff)}**")

st.write("")
left, right = st.columns([3, 2], gap="large")

# ---------------- 성과 추이 ----------------
with left:
    st.subheader("성과 추이")
    grain = st.segmented_control("단위", ["일별", "주별"], default="일별", key="ov_grain", label_visibility="collapsed") or "일별"
    col = "date" if grain == "일별" else "week"
    lo = prev[0] if has_prev else cur[0]
    o = in_period(m["orders"], "order_time", lo, cur[1])
    o = o[o["order_status"].eq("COMPLETED")]
    t = o.groupby(col).agg(매출=("total_amount", "sum"), 주문수=("order_id", "nunique")).reset_index()
    t["기간"] = (t[col] >= cur[0]).map({True: "분석 기간", False: "비교 기간"})
    base = alt.Chart(t).encode(x=alt.X(f"{col}:T", title=None, axis=alt.Axis(format="%m/%d")))
    bars = base.mark_bar(opacity=0.9).encode(
        y=alt.Y("매출:Q", title="완료 매출(원)", axis=alt.Axis(format="~s")),
        color=alt.Color("기간:N", scale=alt.Scale(domain=["분석 기간", "비교 기간"], range=[ui.C_MAIN, ui.C_PREV]),
                        legend=alt.Legend(title=None)),
        tooltip=[alt.Tooltip(f"{col}:T", title="날짜"), alt.Tooltip("매출:Q", format=",.0f"), alt.Tooltip("주문수:Q")])
    line = base.mark_line(color=ui.C_ACCENT, strokeWidth=2).encode(
        y=alt.Y("주문수:Q", title="완료 주문 수", axis=alt.Axis(titleColor=ui.C_ACCENT)))
    st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent").properties(height=280), width="stretch")
    ui.note("막대 = 완료 매출, 주황 선 = 완료 주문 수")

# ---------------- 성장 지표 요약 ----------------
with right:
    st.subheader("성장 지표 요약")
    c = m["raw"]["customer"]
    new_sign = c[(c["signup_date"] >= cur[0]) & (c["signup_date"] < cur[1])]
    s = in_period(m["sessions"], "start", *cur)
    rows = [
        ("Acquisition", "신규 가입 고객 수", len(new_sign), "count",
         None if not has_prev else len(c[(c["signup_date"] >= prev[0]) & (c["signup_date"] < prev[1])])),
        ("Activation", "첫 구매 주문 수", k["first_purchases"], "count", g("first_purchases")),
        ("Activation", "세션 구매 전환율", k["cvr"], "rate", g("cvr")),
        ("Retention", "재구매 고객 비중", k["repeat_rate"], "rate", g("repeat_rate")),
        ("Revenue", "객단가", k["aov"], "won", g("aov")),
        ("Revenue", "쿠폰 사용 주문 비중", k["coupon_order_share"], "rate", g("coupon_order_share")),
        ("품질", "취소·환불 비중", k["cancel_refund_rate"], "rate", g("cancel_refund_rate")),
    ]
    tbl = pd.DataFrame([{"단계": r[0], "지표": r[1], "현재": ui.fmt_value(r[2], r[3]),
                         "변화": ui.fmt_delta(r[2], r[4], r[3]) if has_prev else "–"} for r in rows])
    st.dataframe(tbl, hide_index=True, width="stretch")
    ui.note("Acquisition은 유입 채널별 방문 데이터가 없어 '신규 가입 수'로 대신 봅니다. "
            "Referral 지표는 데이터가 없어 제외했습니다.")

st.divider()

# ---------------- 확인할 변화 ----------------
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("확인할 변화")
    if not has_prev:
        st.info("이전 기간과 비교해야 변화를 찾을 수 있습니다. 사이드바에서 비교를 켜거나 5월 이후 기간을 선택하세요.")
    else:
        mode = st.segmented_control("탐지 기준", ["엄격 (p<0.05)", "탐색 (p<0.20)"], default="엄격 (p<0.05)",
                                    key="ov_sens", help="탐색 기준은 방향만 관측된 약한 변화까지 보여줍니다.") or "엄격 (p<0.05)"
        alpha = 0.05 if mode.startswith("엄격") else 0.20
        cands = detect_changes(m, cur, prev, alpha=alpha)
        st.caption(f"비교 기간과 비교해 달라진 비율 지표(p<{alpha:.2f}, 차이 1%p 이상, 분모 100 이상)와 "
                   f"15% 이상 달라진 금액 지표 {len(cands)}개. 아직 원인이 검토되지 않은 **문제·기회 후보**입니다."
                   + (" 탐색 기준의 후보는 우연일 가능성이 더 큽니다." if alpha > 0.05 else ""))
        if not cands:
            st.success("기준을 넘는 큰 변화가 없습니다.")
        page_map = {"journey": ("views/journey.py", "고객 여정에서 보기"),
                    "curation": ("views/curation.py", "상품·큐레이션에서 보기"),
                    "overview": (None, None)}
        for i, cnd in enumerate(cands[:6]):
            down = cnd["direction"] == "하락"
            with st.container(border=True):
                a, b = st.columns([5, 2])
                a.markdown(f"{'🔻' if down else '🔺'} **{cnd['title']}**")
                val = f"{ui.fmt_value(cnd['previous'], cnd['unit'])} → {ui.fmt_value(cnd['current'], cnd['unit'])}"
                delta = ui.fmt_delta(cnd["current"], cnd["previous"], cnd["unit"])
                a.markdown(f"관찰된 변화: {val} (**{delta}**) · 영향 범위: {cnd['segment']}")
                ev = f"근거: 분석 n={cnd['n_current']:,} / 비교 n={cnd['n_previous']:,}"
                if pd.notna(cnd.get("p_value")):
                    ev += f" · p={cnd['p_value']:.3f}"
                a.caption(f"{ev} · 정의: {cnd['definition']}")
                with b:
                    target, label = page_map.get(cnd["page"], (None, None))
                    if target:
                        st.page_link(target, label=label, icon=":material/arrow_forward:")
                    ui.save_to_lab_button(cnd, "통합 현황", cur, prev, key=f"ov_save_{i}")
        if len(cands) > 6:
            with st.expander(f"나머지 {len(cands) - 6}개 보기"):
                st.dataframe(pd.DataFrame([{
                    "변화": c_["title"], "비교": ui.fmt_value(c_["previous"], c_["unit"]),
                    "현재": ui.fmt_value(c_["current"], c_["unit"]),
                    "차이": ui.fmt_delta(c_["current"], c_["previous"], c_["unit"]),
                    "p값": None if pd.isna(c_.get("p_value")) else round(c_["p_value"], 4)} for c_ in cands[6:]]),
                    hide_index=True, width="stretch")

# ---------------- 매출 구성 ----------------
with right:
    st.subheader("카테고리별 매출")
    it = in_period(m["items"], "order_time", *cur)
    it = it[it["order_status"].eq("COMPLETED")]
    cat = it.groupby("category")["net_sales"].sum().sort_values(ascending=False).reset_index()
    cat["비중"] = cat["net_sales"] / cat["net_sales"].sum()
    if has_prev:
        ip = in_period(m["items"], "order_time", *prev)
        cp = ip[ip["order_status"].eq("COMPLETED")].groupby("category")["net_sales"].sum()
        cat["변화"] = [ui.fmt_delta(v, cp.get(c_), "won") for c_, v in zip(cat["category"], cat["net_sales"])]
    ch = alt.Chart(cat).mark_bar(color=ui.C_MAIN, cornerRadiusEnd=3).encode(
        x=alt.X("net_sales:Q", title=None, axis=alt.Axis(format="~s")),
        y=alt.Y("category:N", sort="-x", title=None),
        tooltip=[alt.Tooltip("category", title="카테고리"), alt.Tooltip("net_sales:Q", title="상품매출", format=",.0f"),
                 alt.Tooltip("비중:Q", format=".1%")])
    st.altair_chart(ch.properties(height=max(200, 26 * len(cat))), width="stretch")
    ui.note("완료 주문의 쿠폰 차감 후 상품금액(배송비 제외)이라 KPI 카드의 완료 매출과 합계가 다릅니다.")

st.divider()

# ---------------- 상품·테마 요약 ----------------
a, b = st.columns(2, gap="large")
with a:
    st.subheader("인기 상품 TOP 5")
    top = (it.groupby(["product_name", "category"])
           .agg(상품매출=("net_sales", "sum"), 구매고객=("customer_id", "nunique"), 수량=("quantity", "sum"))
           .sort_values("상품매출", ascending=False).head(5).reset_index())
    top["상품매출"] = top["상품매출"].map(ui.won)
    st.dataframe(top.rename(columns={"product_name": "상품", "category": "카테고리"}), hide_index=True, width="stretch")
with b:
    st.subheader("큐레이션 테마 TOP 5")
    tt = theme_table(m, *cur).sort_values("경유매출", ascending=False).head(5)
    view = pd.DataFrame({"테마": tt["테마"], "경유 매출": tt["경유매출"].map(ui.won),
                         "클릭률": tt["클릭률"].map(ui.pct), "구매 전환율": tt["구매전환율"].map(ui.pct)})
    st.dataframe(view, hide_index=True, width="stretch")
    ui.note("경유 매출 = 해당 테마 화면을 거쳐 발생한 완료 주문 금액(경로 귀속). 테마가 만들어낸 증분 매출은 아닙니다.")
    st.page_link("views/curation.py", label="상품·큐레이션 자세히 보기", icon=":material/arrow_forward:")

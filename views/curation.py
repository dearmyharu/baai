"""② 상품·큐레이션: 어떤 상품과 테마가 누구에게 잘 작동하는가?"""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from core import ui
from core.metrics import (POTENTIAL_HINT, QUADRANT_HINT, category_performance, product_performance, product_potential,
                          rising_products, segment_category_mix, theme_lineup, theme_quadrant, theme_segments,
                          theme_table, theme_weekly)

m = ui.get_mart()
cur, prev = ui.period_controls()
has_prev = prev is not None

st.title("상품·큐레이션")
st.caption(f"분석 {ui.period_label(cur)} · 비교 {ui.period_label(prev)}")

tab_c, tab_p = st.tabs(["큐레이션 테마", "상품·카테고리"])

# =====================================================================
# 큐레이션
# =====================================================================
with tab_c:
    tt, mx, my = theme_quadrant(m, *cur)
    if has_prev:
        tp = theme_table(m, *prev).set_index("theme_id")
        tt["클릭률 변화"] = tt.apply(lambda r: ui.fmt_delta(r["클릭률"], tp["클릭률"].get(r["theme_id"]), "rate"), axis=1)
        tt["구매전환율 변화"] = tt.apply(lambda r: ui.fmt_delta(r["구매전환율"], tp["구매전환율"].get(r["theme_id"]), "rate"), axis=1)

    st.subheader("테마별 성과")
    show = pd.DataFrame({
        "테마": tt["테마"], "노출 세션": tt["노출세션"], "클릭률": tt["클릭률"],
        "상품 클릭률": tt["상품클릭률"], "장바구니율": tt["장바구니율"], "장바구니→구매": tt["장바구니→구매"],
        "구매 전환율": tt["구매전환율"], "완료 주문": tt["완료주문"].astype(int), "경유 매출": tt["경유매출"],
        "객단가": tt["객단가"]})
    if has_prev:
        show.insert(3, "클릭률 변화", tt["클릭률 변화"])
        show.insert(8, "구매전환율 변화", tt["구매전환율 변화"])
    pcfg = st.column_config.NumberColumn(format="percent")
    st.dataframe(show.sort_values("경유 매출", ascending=False), hide_index=True, width="stretch",
                 column_config={c: pcfg for c in ["클릭률", "상품 클릭률", "장바구니율", "장바구니→구매", "구매 전환율"]} | {
                     "경유 매출": st.column_config.NumberColumn(format="localized"),
                     "객단가": st.column_config.NumberColumn(format="localized")})
    ui.note("모든 비율은 DISTINCT 세션 기준. 클릭률 = 테마 클릭 세션 ÷ 노출 세션, 상품 클릭률 = 상품 클릭 ÷ 테마 클릭, "
            "장바구니율 = 장바구니 ÷ 상품 클릭, 구매 전환율 = 구매 세션 ÷ 노출 세션. "
            "경유 매출은 테마를 거친 완료 주문 금액(경로 귀속)이며 테마의 증분 효과가 아닙니다.")

    # ------------- 관심 vs 구매 -------------
    st.subheader("관심과 구매의 차이")
    qcolor = alt.Scale(domain=["관심↑ 구매↓", "관심↓ 구매↑", "관심↑ 구매↑", "관심↓ 구매↓"],
                       range=[ui.C_DOWN, ui.C_UP, ui.C_MAIN, ui.C_PREV])
    left, right = st.columns([3, 2], gap="large")
    with left:
        pts = alt.Chart(tt).mark_circle(opacity=0.85, stroke="white", strokeWidth=1).encode(
            x=alt.X("클릭률:Q", title="관심: 테마 클릭률", axis=alt.Axis(format=".0%"), scale=alt.Scale(zero=False)),
            y=alt.Y("클릭후구매율:Q", title="구매: 클릭 후 구매율", axis=alt.Axis(format=".0%"), scale=alt.Scale(zero=False)),
            size=alt.Size("노출세션:Q", legend=None, scale=alt.Scale(range=[80, 900])),
            color=alt.Color("구분:N", scale=qcolor, legend=alt.Legend(title=None)),
            tooltip=["테마", alt.Tooltip("노출세션:Q", format=","), alt.Tooltip("클릭률:Q", format=".1%"),
                     alt.Tooltip("클릭후구매율:Q", format=".1%"), alt.Tooltip("경유매출:Q", format=",.0f")])
        labels = alt.Chart(tt).mark_text(dy=-14, fontSize=11, color="#374151").encode(x="클릭률:Q", y="클릭후구매율:Q", text="테마")
        rx = alt.Chart(pd.DataFrame({"v": [mx]})).mark_rule(strokeDash=[4, 4], color="#9CA3AF").encode(x="v:Q")
        ry = alt.Chart(pd.DataFrame({"v": [my]})).mark_rule(strokeDash=[4, 4], color="#9CA3AF").encode(y="v:Q")
        st.altair_chart((pts + labels + rx + ry).properties(height=380), width="stretch")
        ui.note("점선은 테마 중앙값, 원 크기는 노출 세션 수. 클릭 후 구매율 = 구매 세션 ÷ 테마 클릭 세션.")
    with right:
        st.markdown("**검토할 가설** (원인을 확정한 것이 아닙니다)")
        for q, msg in QUADRANT_HINT.items():
            sub = tt[tt["구분"].eq(q)]
            if sub.empty:
                continue
            with st.container(border=True):
                st.markdown(f"**{q}** · {', '.join(sub['테마'])}")
                st.caption(msg)
                for _, r in sub.iterrows():
                    cand = {"kind": "theme", "title": f"'{r['테마']}' 테마: {q}", "metric": "클릭률 / 클릭 후 구매율",
                            "segment": r["테마"], "theme_id": r["theme_id"], "current": r["클릭후구매율"],
                            "previous": my, "unit": "rate", "n_current": int(r["클릭세션"]), "n_previous": 0,
                            "p_value": None, "direction": "하락" if q == "관심↑ 구매↓" else "상승",
                            "definition": f"클릭률 {ui.pct(r['클릭률'])} (중앙값 {ui.pct(mx)}), "
                                          f"클릭 후 구매율 {ui.pct(r['클릭후구매율'])} (중앙값 {ui.pct(my)})",
                            "hypothesis_hint": msg}
                    ui.save_to_lab_button(cand, "상품·큐레이션", cur, prev, key=f"q_{r['theme_id']}",
                                          label=f"{r['테마']} 저장")

    st.divider()

    # ------------- 테마 상세 -------------
    st.subheader("테마 상세 보기")
    opts = tt.sort_values("경유매출", ascending=False)
    tid = st.selectbox("테마 선택", opts["theme_id"], format_func=lambda x: opts.set_index("theme_id").loc[x, "테마"],
                       key="cur_theme")
    tname = opts.set_index("theme_id").loc[tid, "테마"]

    a, b = st.columns(2, gap="large")
    with a:
        st.markdown(f"**'{tname}' 주별 추이** (전체 관측 기간)")
        w = theme_weekly(m, tid)
        long = w.melt(id_vars=["week", "노출"], value_vars=["클릭률", "장바구니→구매", "구매 전환율"], var_name="지표", value_name="값")
        band = alt.Chart(pd.DataFrame({"s": [cur[0]], "e": [cur[1]]})).mark_rect(color=ui.C_MAIN, opacity=0.07).encode(x="s:T", x2="e:T")
        line = alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("week:T", title=None, axis=alt.Axis(format="%m/%d")),
            y=alt.Y("값:Q", title=None, axis=alt.Axis(format=".0%")),
            color=alt.Color("지표:N", legend=alt.Legend(title=None)),
            tooltip=[alt.Tooltip("week:T", title="주 시작"), "지표", alt.Tooltip("값:Q", format=".1%"), alt.Tooltip("노출:Q", title="노출 세션")])
        st.altair_chart((band + line).properties(height=280), width="stretch")
        ui.note("옅은 초록 구간이 현재 분석 기간입니다. 주 단위 표본이 작으면 변동이 커 보일 수 있습니다.")
    with b:
        st.markdown(f"**'{tname}' 고객별 반응** (분석 기간)")
        dim = st.segmented_control("나눠 볼 기준", ["방문 유형", "가입 시기", "평일/주말", "시간대"], default="방문 유형",
                                   key="cur_dim") or "방문 유형"
        col = {"방문 유형": "visitor_type", "가입 시기": "is_new_signup", "평일/주말": "day_type", "시간대": "daypart"}[dim]
        grp = theme_segments(m, tid, *cur, by=col)
        grp[col] = grp[col].map(lambda v: ui.LABELS.get(v, v))
        grp["표본"] = np.where(grp["노출세션"] < 30, "⚠️ 30 미만", "")
        st.dataframe(grp.rename(columns={col: dim}), hide_index=True, width="stretch",
                     column_config={c: pcfg for c in ["클릭률", "장바구니→구매", "구매 전환율"]})
        ui.note("표본 30 미만 그룹은 순위·비교 결론을 내리지 마세요.")

    st.markdown(f"**'{tname}' 구성 상품별 성과** (분석 기간)")
    lineup, extra = theme_lineup(m, tid, *cur)
    st.dataframe(lineup[["display_rank", "product_name", "category", "상품 클릭 세션", "장바구니 세션", "클릭→장바구니",
                         "판매수량", "경유상품매출", "매출 비중"]].rename(columns={"display_rank": "노출 순서", "product_name": "상품",
                                                                       "category": "카테고리"}),
                 hide_index=True, width="stretch",
                 column_config={"클릭→장바구니": pcfg, "매출 비중": pcfg,
                                "경유상품매출": st.column_config.NumberColumn(format="localized")})
    ui.note(f"경유상품매출 = 이 테마를 거친 완료 주문에 담긴 해당 상품의 쿠폰 후 상품금액. "
            f"같은 주문에 함께 담긴 편성 외 상품 매출 {ui.won(extra)}은 표에서 제외했습니다.")

# =====================================================================
# 상품·카테고리
# =====================================================================
with tab_p:
    st.subheader("카테고리별 성과")
    cat = category_performance(m, *cur)
    if has_prev:
        cp = category_performance(m, *prev)["상품매출"]
        cat["매출 변화"] = [ui.fmt_delta(v, cp.get(c), "won") for c, v in cat["상품매출"].items()]
    cat = cat.sort_values("상품매출", ascending=False).reset_index().rename(columns={"category": "카테고리"})
    st.dataframe(cat, hide_index=True, width="stretch",
                 column_config={"매출 비중": pcfg, "큐레이션 경유 비중": pcfg, "공헌이익률": pcfg,
                                "상품매출": st.column_config.NumberColumn(format="localized"),
                                "공헌이익": st.column_config.NumberColumn(format="localized")})
    ui.note("상품매출 = 쿠폰 차감 후 상품금액(배송비 제외). 공헌이익 = 상품매출 − 원가(광고·배송·운영비 차감 전).")

    st.subheader("상품별 성과")
    f1, f2 = st.columns([2, 1])
    cats = ["전체"] + sorted(cat["카테고리"].dropna().unique())
    sel = f1.selectbox("카테고리", cats, key="prod_cat")
    n_top = f2.number_input("표시 개수", 5, 100, 20, step=5, key="prod_n")
    pr = product_performance(m, *cur, category=sel).head(int(n_top))
    st.dataframe(pr.drop(columns=["product_id", "공헌이익"]).rename(columns={"product_name": "상품", "category": "카테고리"}),
                 hide_index=True, width="stretch",
                 column_config={"재구매 고객 비중": pcfg, "큐레이션 경유 비중": pcfg, "공헌이익률": pcfg,
                                "상품매출": st.column_config.NumberColumn(format="localized")})
    ui.note("재구매 고객 비중 = 이 상품을 기간 안에 2번 이상 다른 주문으로 산 고객 ÷ 구매 고객.")

    # ------------- 성장 잠재력 -------------
    st.subheader("성장 잠재력")
    st.caption("지금 매출은 낮지만 관심·구매 의향·전환·성장 지표가 좋은 상품을 찾습니다. "
               "규칙 기반 탐색 점수이며 미래 매출 예측이 아닙니다.")
    pp = product_potential(m, *cur, prev=prev)
    ok = pp[pp["구분"].ne("표본 부족")].copy()
    if ok.empty:
        st.info(f"상품 클릭 세션이 {pp.attrs['min_clicks']}개 이상인 상품이 없습니다. 분석 기간을 늘려 주세요.")
    else:
        pcolor = alt.Scale(domain=["키울 후보", "주력", "점검 필요", "관망"], range=[ui.C_UP, ui.C_MAIN, ui.C_DOWN, ui.C_PREV])
        a, b = st.columns([3, 2], gap="large")
        with a:
            pts = alt.Chart(ok[ok["상품매출"] > 0]).mark_circle(opacity=0.8, size=70).encode(
                x=alt.X("상품매출:Q", title="현재 상품매출(원, 로그)", scale=alt.Scale(type="log"), axis=alt.Axis(format="~s")),
                y=alt.Y("잠재력 점수:Q", title="잠재력 점수 (0~100)", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("구분:N", scale=pcolor, legend=alt.Legend(title=None)),
                tooltip=[alt.Tooltip("product_name:N", title="상품"), alt.Tooltip("category:N", title="카테고리"),
                         alt.Tooltip("잠재력 점수:Q", format=".0f"), alt.Tooltip("상품매출:Q", format=",.0f"),
                         alt.Tooltip("클릭세션:Q", format=","), alt.Tooltip("장바구니율:Q", format=".1%"),
                         alt.Tooltip("클릭당 주문:Q", format=".1%")]
                + ([alt.Tooltip("매출 증가율:Q", format="+.0%")] if has_prev else []))
            rx = alt.Chart(pd.DataFrame({"v": [pp.attrs["sales_median"]]})).mark_rule(strokeDash=[4, 4], color="#9CA3AF").encode(x="v:Q")
            ry = alt.Chart(pd.DataFrame({"v": [pp.attrs["score_median"]]})).mark_rule(strokeDash=[4, 4], color="#9CA3AF").encode(y="v:Q")
            st.altair_chart((pts + rx + ry).properties(height=360), width="stretch")
            parts = " · ".join(pp.attrs["parts"])
            ui.note(f"점수 = {parts} 지표를 상품끼리 비교한 백분위의 평균. 점선은 중앙값. "
                    f"상품 클릭 세션 {pp.attrs['min_clicks']}개 미만 상품 {int((pp['구분'] == '표본 부족').sum())}개는 제외."
                    + ("" if has_prev else " 비교 기간이 없어 '성장' 지표는 빠졌습니다."))
        with b:
            st.markdown("**키울 후보**")
            st.caption(POTENTIAL_HINT["키울 후보"])
            cand_df = ok[ok["구분"].eq("키울 후보")].head(10)
            cols_ = ["product_name", "category", "잠재력 점수", "상품매출", "장바구니율", "클릭당 주문"] + (["매출 증가율"] if has_prev else [])
            st.dataframe(cand_df[cols_].rename(columns={"product_name": "상품", "category": "카테고리"}), hide_index=True,
                         width="stretch",
                         column_config={"잠재력 점수": st.column_config.NumberColumn(format="%.0f"),
                                        "상품매출": st.column_config.NumberColumn(format="localized"),
                                        "장바구니율": pcfg, "클릭당 주문": pcfg, "매출 증가율": pcfg})
            for _, r in cand_df.head(3).iterrows():
                cand = {"kind": "product", "title": f"'{r['product_name']}' 상품 키우기", "metric": "상품 클릭 → 장바구니율",
                        "segment": r["product_name"], "product_id": r["product_id"], "current": r["장바구니율"],
                        "previous": None, "unit": "rate", "n_current": int(r["클릭세션"]), "n_previous": 0, "p_value": None,
                        "definition": f"잠재력 점수 {r['잠재력 점수']:.0f}(중앙값 {pp.attrs['score_median']:.0f}), "
                                      f"상품매출 {ui.won(r['상품매출'])}(중앙값 {ui.won(pp.attrs['sales_median'])}), "
                                      f"클릭 세션 {int(r['클릭세션']):,}",
                        "hypothesis_hint": POTENTIAL_HINT["키울 후보"]}
                ui.save_to_lab_button(cand, "상품·큐레이션", cur, prev, key=f"pot_{r['product_id']}",
                                      label=f"{r['product_name']} 저장")
        if has_prev:
            st.markdown("**요즘 뜨는 상품** (비교 기간 대비 상품매출 증가율, 비교 기간 주문 10건 이상)")
            rp = rising_products(m, cur, prev, n=10)
            st.dataframe(rp[["product_name", "category", "매출 증가율", "상품매출", "이전 상품매출", "클릭 증가율"]]
                         .rename(columns={"product_name": "상품", "category": "카테고리"}), hide_index=True, width="stretch",
                         column_config={"매출 증가율": pcfg, "클릭 증가율": pcfg,
                                        "상품매출": st.column_config.NumberColumn(format="localized"),
                                        "이전 상품매출": st.column_config.NumberColumn(format="localized")})

    st.subheader("고객군별 선호 카테고리")
    grp = st.segmented_control("고객 구분", ["첫 구매 / 기존 구매", "주문 당시 등급", "방문 유형"], default="첫 구매 / 기존 구매",
                               key="prod_grp") or "첫 구매 / 기존 구매"
    col = {"첫 구매 / 기존 구매": "customer_type", "주문 당시 등급": "grade_at_order", "방문 유형": "visitor_type"}[grp]
    mix = segment_category_mix(m, *cur, by=col)
    mix[col] = mix[col].map(lambda v: ui.LABELS.get(v, v))
    heat = alt.Chart(mix).mark_rect().encode(
        x=alt.X("category:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{col}:N", title=None),
        color=alt.Color("비중:Q", scale=alt.Scale(scheme="greens"), legend=alt.Legend(format=".0%", title="매출 비중")),
        tooltip=[alt.Tooltip(f"{col}:N", title=grp), alt.Tooltip("category:N", title="카테고리"),
                 alt.Tooltip("비중:Q", format=".1%"), alt.Tooltip("net_sales:Q", title="상품매출", format=",.0f")])
    txt = alt.Chart(mix).mark_text(fontSize=11).encode(x="category:N", y=f"{col}:N", text=alt.Text("비중:Q", format=".0%"),
                                                       color=alt.condition("datum.비중 > 0.2", alt.value("white"), alt.value("#374151")))
    st.altair_chart((heat + txt).properties(height=60 + 34 * mix[col].nunique()), width="stretch")
    ui.note("각 행의 합이 100%입니다. 등급은 현재 등급이 아니라 주문 당시 등급입니다.")

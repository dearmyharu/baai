"""③ 고객 여정·전환: 고객이 어디에서 구매를 포기하는가?"""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from core import ui
from core.metrics import FUNNEL_STEPS, funnel, in_period, step_rate, two_prop_test

m = ui.get_mart()
cur, prev = ui.period_controls()
has_prev = prev is not None

st.title("고객 여정·전환")
st.caption(f"분석 {ui.period_label(cur)} · 비교 {ui.period_label(prev)}")

s_cur = in_period(m["sessions"], "start", *cur)
s_prev = in_period(m["sessions"], "start", *prev) if has_prev else None

path_label = {"ALL": "전체", "CURATION": "큐레이션 경유", "BROWSE": "일반 탐색"}
path = st.segmented_control("세션 경로", list(path_label), default="ALL", format_func=path_label.get, key="jr_path") or "ALL"

# ---------------- 요약 ----------------
sc = s_cur if path == "ALL" else s_cur[s_cur["path"].eq(path)]
sp = None if not has_prev else (s_prev if path == "ALL" else s_prev[s_prev["path"].eq(path)])
c1, c2, c3, c4 = st.columns(4)
c1.metric("세션 수", ui.num(len(sc)), ui.fmt_delta(len(sc), len(sp), "count") if has_prev else None, border=True)
c2.metric("세션 고객 수", ui.num(sc["customer_id"].nunique()),
          ui.fmt_delta(sc["customer_id"].nunique(), sp["customer_id"].nunique(), "count") if has_prev else None, border=True)
cv, pv = sc["has_purchase"].mean(), (sp["has_purchase"].mean() if has_prev else None)
c3.metric("세션 구매 전환율", ui.pct(cv), ui.fmt_delta(cv, pv, "rate") if has_prev else None, border=True,
          help="구매 세션 ÷ 세션 (해당 경로)")
nv = sc["visitor_type"].eq("NEW").mean()
c4.metric("신규 방문 세션 비중", ui.pct(nv), ui.fmt_delta(nv, sp["visitor_type"].eq("NEW").mean(), "rate") if has_prev else None,
          border=True, help="고객의 첫 방문(과거 방문 0회)인 세션 비중")
ui.note("방문은 로그인 고객의 큐레이션·검색·카테고리 진입 세션만 기록되어 있어 쇼핑몰 전체 방문과 다릅니다. "
        "'결제 진입' 단계 이벤트는 데이터에 없어 장바구니 다음 단계가 바로 구매입니다.")

# ---------------- 퍼널 ----------------
st.subheader("구매 퍼널")
fc = funnel(s_cur, path)
fc["기간"] = "분석 기간"
frames = [fc]
if has_prev:
    fp = funnel(s_prev, path)
    fp["기간"] = "비교 기간"
    frames.append(fp)
f = pd.concat(frames)
order = [lab for lab, _ in FUNNEL_STEPS[path]]

left, right = st.columns([3, 2], gap="large")
with left:
    bars = alt.Chart(f).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("단계:N", sort=order, title=None),
        x=alt.X("첫 단계 대비:Q", title="첫 단계 대비 남은 비율", axis=alt.Axis(format=".0%")),
        yOffset=alt.YOffset("기간:N", sort=["분석 기간", "비교 기간"]),
        color=alt.Color("기간:N", scale=alt.Scale(domain=["분석 기간", "비교 기간"], range=[ui.C_MAIN, ui.C_PREV]),
                        legend=alt.Legend(title=None)),
        tooltip=["기간", "단계", alt.Tooltip("세션 수:Q", format=","), alt.Tooltip("첫 단계 대비:Q", format=".1%"),
                 alt.Tooltip("직전 단계 대비 전환율:Q", format=".1%")])
    st.altair_chart(bars.properties(height=60 * len(order)), width="stretch")
with right:
    rows = []
    for i in range(1, len(order)):
        n1, d1, r1 = step_rate(s_cur, path, i)
        row = {"구간": f"{order[i-1]} → {order[i]}", "분석 기간": r1, "이탈 세션": d1 - n1}
        if has_prev:
            n0, d0, r0 = step_rate(s_prev, path, i)
            _, p = two_prop_test(n1, d1, n0, d0)
            row.update({"비교 기간": r0, "변화(%p)": (r1 - r0) * 100 if pd.notna(r0) else np.nan,
                        "유의": "●" if (pd.notna(p) and p < 0.05) else ""})
        rows.append(row)
    step_tbl = pd.DataFrame(rows)
    st.dataframe(step_tbl, hide_index=True, width="stretch",
                 column_config={"분석 기간": st.column_config.NumberColumn(format="percent"),
                                "비교 기간": st.column_config.NumberColumn(format="percent"),
                                "변화(%p)": st.column_config.NumberColumn(format="%+.1f"),
                                "이탈 세션": st.column_config.NumberColumn(format="localized")})
    ui.note("구간 전환율 분모 = 직전 단계에 도달한 세션. ● = 비교 기간과의 차이가 p<0.05 (두 비율 z-검정).")

st.divider()

# ---------------- 선택 구간 세분화 ----------------
st.subheader("구간 자세히 보기")
choices = list(range(1, len(order)))
default_step = int(step_tbl["이탈 세션"].iloc[:-1].idxmax()) + 1 if len(step_tbl) > 1 else 1
step_idx = st.selectbox("살펴볼 구간", choices, index=choices.index(default_step),
                        format_func=lambda i: f"{order[i-1]} → {order[i]}", key="jr_step")
step_name = f"{order[step_idx-1]} → {order[step_idx]}"

dims = {"방문 유형": "visitor_type", "가입 시기": "is_new_signup", "평일/주말": "day_type", "시간대": "daypart",
        "첫 클릭 상품 카테고리": "first_category"}
if path != "BROWSE":
    dims = {"테마": "theme_name", **dims}
dim = st.segmented_control("나눠 볼 기준", list(dims), default=list(dims)[0], key="jr_dim") or list(dims)[0]
col = dims[dim]
if col == "first_category" and step_idx < 2 + (path == "CURATION"):
    st.info("첫 클릭 상품 카테고리는 상품 클릭 이후 구간에서만 정해집니다. 다른 기준이나 구간을 골라주세요.")
else:
    gc = step_rate(s_cur, path, step_idx, by=col).rename(columns={"rate": "분석 기간"})
    if has_prev:
        gp = step_rate(s_prev, path, step_idx, by=col)
        gc = gc.join(gp.rename(columns={"num": "num_p", "den": "den_p", "rate": "비교 기간"}), how="left")
        gc["변화(%p)"] = (gc["분석 기간"] - gc["비교 기간"]) * 100
        gc["p값"] = [two_prop_test(r.num, r.den, r.num_p, r.den_p)[1] if pd.notna(r.den_p) and r.den_p > 0 else np.nan
                    for r in gc.itertuples()]
        # 전체 변화에 대한 기여: 그룹 분모 비중 × 그룹 전환율 변화
        gc["전체 변화 기여(%p)"] = (gc["den"] / gc["den"].sum()) * gc["변화(%p)"]
    gc = gc[gc.index != "nan"].reset_index().rename(columns={"grp": dim, "den": "분모 세션", "num": "전환 세션"})
    gc[dim] = gc[dim].map(lambda v: ui.LABELS.get(v, {"True": "신규 가입(4/1 이후)", "False": "기존 가입"}.get(v, v)))
    gc["표본"] = np.where(gc["분모 세션"] < 30, "⚠️ 30 미만", "")
    keep = [dim, "분모 세션", "분석 기간"] + (["비교 기간", "변화(%p)", "p값", "전체 변화 기여(%p)"] if has_prev else []) + ["표본"]
    a, b = st.columns([3, 2], gap="large")
    with a:
        st.dataframe(gc[keep].sort_values("분모 세션", ascending=False), hide_index=True, width="stretch",
                     column_config={"분석 기간": st.column_config.NumberColumn(format="percent"),
                                    "비교 기간": st.column_config.NumberColumn(format="percent"),
                                    "변화(%p)": st.column_config.NumberColumn(format="%+.1f"),
                                    "전체 변화 기여(%p)": st.column_config.NumberColumn(format="%+.2f"),
                                    "p값": st.column_config.NumberColumn(format="%.3f")})
        ui.note("전체 변화 기여 = 그룹의 분모 비중 × 그룹 전환율 변화. 어느 그룹이 전체 변화를 끌고 있는지 빠르게 보는 근사치입니다.")
    with b:
        ch_df = gc[gc["분모 세션"] >= 30]
        if has_prev and not ch_df.empty:
            dot = alt.Chart(ch_df).transform_fold(["분석 기간", "비교 기간"], as_=["기간", "전환율"]).mark_circle(size=110).encode(
                y=alt.Y(f"{dim}:N", title=None, sort="-x"), x=alt.X("전환율:Q", axis=alt.Axis(format=".0%"), title=step_name),
                color=alt.Color("기간:N", scale=alt.Scale(domain=["분석 기간", "비교 기간"], range=[ui.C_MAIN, ui.C_PREV]),
                                legend=alt.Legend(title=None)),
                tooltip=[f"{dim}:N", "기간:N", alt.Tooltip("전환율:Q", format=".1%")])
            rule = alt.Chart(ch_df).mark_rule(color="#D1D5DB").encode(y=f"{dim}:N", x="분석 기간:Q", x2="비교 기간:Q")
            st.altair_chart((rule + dot).properties(height=36 * len(ch_df) + 40), width="stretch")

    # 저장
    n1, d1, r1 = step_rate(s_cur, path, step_idx)
    cand = {"kind": "funnel", "title": f"{path_label[path]} {step_name} 전환율", "metric": step_name, "segment": path_label[path],
            "current": r1, "previous": step_rate(s_prev, path, step_idx)[2] if has_prev else None, "unit": "rate",
            "n_current": d1, "n_previous": step_rate(s_prev, path, step_idx)[1] if has_prev else 0, "p_value": None,
            "path": path, "step_idx": step_idx,
            "definition": f"DISTINCT 세션 기준, {order[step_idx-1]} 도달 세션 중 {order[step_idx]} 도달 비율 ({dim}별로 확인)"}
    if has_prev and cand["previous"] is not None:
        cand["delta"] = r1 - cand["previous"]
        cand["direction"] = "하락" if cand["delta"] < 0 else "상승"
    ui.save_to_lab_button(cand, "고객 여정·전환", cur, prev, key=f"jr_save_{path}_{step_idx}", label="이 구간을 Growth Lab에 저장")

st.divider()

# ---------------- 기간별 변화 ----------------
st.subheader("구간 전환율 주별 추이")
ss = m["sessions"] if path == "ALL" else m["sessions"][m["sessions"]["path"].eq(path)]
weeks = []
for wk, g in ss.groupby("week"):
    row = {"week": wk}
    for i in range(1, len(order)):
        if order[i] == "구매 완료":
            continue
        n, dd, r = step_rate(g, path, i)
        row[f"{order[i-1]}→{order[i]}"] = r
    weeks.append(row)
wdf = pd.DataFrame(weeks).melt(id_vars="week", var_name="구간", value_name="전환율")
band = alt.Chart(pd.DataFrame({"s": [cur[0]], "e": [cur[1]]})).mark_rect(color=ui.C_MAIN, opacity=0.07).encode(x="s:T", x2="e:T")
line = alt.Chart(wdf).mark_line(point=alt.OverlayMarkDef(size=25)).encode(
    x=alt.X("week:T", title=None, axis=alt.Axis(format="%m/%d")),
    y=alt.Y("전환율:Q", axis=alt.Axis(format=".0%"), title=None, scale=alt.Scale(zero=False)),
    color=alt.Color("구간:N", legend=alt.Legend(title=None)),
    tooltip=[alt.Tooltip("week:T", title="주 시작"), "구간", alt.Tooltip("전환율:Q", format=".1%")])
st.altair_chart((band + line).properties(height=300), width="stretch")
ui.note("전체 관측 기간(4~9월)의 주별 값입니다. 옅은 초록 구간이 현재 분석 기간입니다. "
        "주 단위는 표본이 작아 흔들릴 수 있으니 여러 주에 걸친 흐름으로 보세요. "
        "큐레이션 경유 세션의 구매율이 높더라도 그 자체로 큐레이션의 효과라고 볼 수는 없습니다(고객 구성 차이 가능).")

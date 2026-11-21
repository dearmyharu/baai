"""Growth Lab: 해도 되는가(손익) · 확인할 수 있는가(기간) · 어떻게 실행하는가(계획).

계산은 engine/growth.py, 판정은 engine/briefing.promo_status. 이 파일은 표시만 한다.
※ 기능 우선 버전(2026-11-21). UX/UI는 이후 개편 예정 — 화면 구성만 바꾸고 engine/growth.py는 그대로 쓰면 된다.

입력: st.session_state["lab_request"]  (docs/GrowthLab_인계.md 3장)
  - {"type": "plan", ...}             AI 분석가에서 넘어온 새 계획
  - {"type": "lab", "promotion_id"}   아침 브리핑에서 넘어온 프로모션 결과 보기
  - 없음                               등록된 프로모션 목록
"""
import altair as alt
import pandas as pd
import streamlit as st

from engine import briefing as B
from engine import case as C
from engine import data as D
from engine import growth as G
from engine import ui

ss = st.session_state
today = D.TODAY                  # 기준일 고정(10/26 아침)
day_str = f"{today:%Y-%m-%d}"
req = ss.get("lab_request")
mt = ui.get_mart()               # 기준일 이전 데이터만 들어 있음
ss["growth_context"] = None      # 화면이 계산을 마치면 아래에서 채운다(오른쪽 AI 분석가가 참고)

st.title("Growth Lab")
st.caption(f"기준일 {day_str} 아침 · 손익 기준: 최근 {G.BASE_DAYS}일 · "
           f"이익 = 결제 금액 − 상품원가 − 배송 원가(주문당 {G.SHIP_COST:,}원), 기타 비용 제외")


# ======================================================================= 결과 보기
def show_result(pid: str):
    promos = B.promo_status(ui.get_mart(), today - pd.Timedelta(days=1))
    p = next((x for x in promos if x["id"] == pid), None)
    raw = ui.get_mart()["raw"]["promotion"]
    if p is None:
        row = raw[raw["promotion_id"].eq(pid)]
        st.warning(f"{pid}: 기준일 기준으로 판정할 수 있는 기간이 아닙니다(시작 전이거나 종료 후 14일이 지남)."
                   if len(row) else f"{pid}: 등록된 프로모션이 없습니다.")
        return
    st.subheader(f"{p['name']} 결과")
    st.caption(f"{ui.md(p['start'])}~{ui.md(p['end'])} · {p['phase']} {p['days']}/{p['total_days']}일"
               + (" · 모의 데이터" if p["is_simulated"] else ""))
    a, b, c, d = st.columns(4)
    a.metric("판정", p["status"])
    a.caption("7일 미만은 판단 이름")
    b.metric(f"{p['category']} 일평균 매출", ui.won(p["sales_dur"]),
             f"{p['sales_chg']:+.0%} 시작 전 14일 대비" if p["sales_chg"] is not None else None)
    eff = "–" if p["effect"] is None else f"{p['effect']:+.0%}"
    c.metric("다른 카테고리 대비 효과", eff,
             None if p["effect_lo"] is None else f"95% 구간 {p['effect_lo']:+.0%} ~ {p['effect_hi']:+.0%}", delta_color="off")
    d.metric("이익률", ui.pct(p["margin_dur"]),
             f"{-p['margin_drop_pp']:+.1f}%p" if p["margin_drop_pp"] is not None else None)
    ss["growth_context"] = {"화면": "Growth Lab 프로모션 결과", **{k: p[k] for k in (
        "name", "category", "phase", "days", "total_days", "sales_chg", "effect", "effect_lo", "effect_hi",
        "margin_pre", "margin_dur", "status", "stop_rule")}}
    ss["page_context"] = f"Growth Lab에서 {p['name']} 결과(판정 {p['status']})를 보고 있음"
    s = G.result_series(ui.get_mart(), p)
    s = s[s["날짜"] < today]
    chart = alt.Chart(s).mark_bar().encode(
        x=alt.X("날짜:T", title=None), y=alt.Y("매출:Q", title="대상 카테고리 일 매출(원)", axis=alt.Axis(format="~s")),
        color=alt.Color("구간:N", scale=alt.Scale(domain=["시작 전", "기간 중"], range=[ui.C_PREV, ui.C_MAIN]), title=None),
        tooltip=["날짜:T", alt.Tooltip("매출:Q", format=","), alt.Tooltip("이익:Q", format=",")])
    st.altair_chart(chart.properties(height=260), width="stretch")
    st.caption(f"중단 기준: {p['stop_rule']} · 효과 = 대상 카테고리 매출 비중의 변화(같은 기간 다른 카테고리 변화를 뺌), "
               "일 단위 재추출 95% 구간. 구간이 0을 넘으면 '효과 있음'.")
    with st.expander("판정 방법"):
        st.markdown("- 7일 미만: 판단 이름\n- 이익률 하락이 중단 기준 초과(3일 이상): 중단 검토\n"
                    "- 효과 95% 구간 하한 > 0: 효과 있음 / 상한 < 0: 효과 없음(감소) / 그 외: 효과 불분명")


# ======================================================================= 새 계획
def show_plan(r: dict):
    target = r["target"]
    st.subheader(f"계획: {C.target_text(target)}")
    dg = r.get("diagnosis") or {}
    with st.container(border=True):
        st.markdown(f"**출발 질문** {r.get('question', '')}")
        if dg:
            st.markdown(f"**진단** {dg.get('metric', '')}: 최근 7일 {ui.won(dg.get('value'))} · 직전 4주 {ui.won(dg.get('base'))}"
                        + (f" ({dg['change']:+.0%})" if dg.get("change") is not None else "")
                        + (f" / 최근 3일 {dg['change3']:+.0%}" if dg.get("change3") is not None else ""))
        if r.get("cause_hypothesis"):
            st.caption(f"원인 가설(확인 전): {r['cause_hypothesis']}")
        for e in r.get("evidence", [])[:4]:
            st.caption(f"근거: {e}")

    # ---------------- 수단 조정
    st.markdown("#### 수단")
    lv = dict(r["lever"])
    pols = [p for p in G.LEVER_LABEL if not (p == "bundle" and target["type"] == "category")]
    c1, c2 = st.columns([1, 1])
    pol = c1.selectbox("수단", pols, index=pols.index(lv["policy"]) if lv["policy"] in pols else 0,
                       format_func=lambda p: G.LEVER_LABEL[p], key="gl_policy")
    if pol == "shipping":
        val = c2.number_input("무료배송 기준(원, 현재 30,000원)", 0, 100000,
                              int(abs(lv["value"])) if lv["policy"] == "shipping" else 20000, 5000, key="gl_value_ship")
    else:
        val = c2.number_input("할인율(%)", 1.0, 50.0, float(abs(lv["value"])) if lv["policy"] == pol else 5.0, 1.0,
                              key="gl_value_pct")
    lever = {"policy": pol, "value": val}
    if lv["policy"] == "bundle" and target["type"] == "category":
        st.caption("묶음 할인은 상품 2개 이상을 지정해야 계산할 수 있어 카테고리 대상에서는 다른 수단으로 바꿨습니다.")

    # ---------------- 1. 본전
    try:
        be = G.breakeven(mt, target, lever, today)
    except ValueError as ex:
        st.error(f"손익을 계산할 수 없습니다: {ex}")
        return
    st.markdown("#### 1. 본전에 필요한 추가 주문")
    a, b, c = st.columns(3)
    a.metric(f"최근 {G.BASE_DAYS}일 대상 주문", f"{be['orders']:,}건", help="대상 상품이 들어 있는 완료 주문")
    b.metric("주문 수가 그대로면 이익", ui.won(be["profit_after0"]),
             f"{be['profit_after0'] - be['profit_before']:+,.0f}원 (현재 {ui.won(be['profit_before'])})")
    if be["required"] is None:
        c.metric("본전 주문 증가율", "계산 불가", help="정책 후 주문당 이익이 0 이하입니다.")
    else:
        c.metric("본전 주문 증가율", f"{be['required']:+.1%}", f"28일 기준 약 {be['required_orders']:+,.0f}건", delta_color="off")
    st.caption("확정 계산입니다. 주문 구성·단가는 최근 28일과 같고 대상 주문 수만 비례해 변한다고 봅니다.")
    with st.expander("손익 비교표"):
        tb = be["table"].copy()
        for col in ("현재", "변경안", "차이"):
            tb[col] = tb[col].map(lambda v: f"{v:,.0f}")
        st.dataframe(tb, hide_index=True, width="stretch")
        for n in be["notes"]:
            st.caption(n)

    # ---------------- 2. 이익 확률
    st.markdown("#### 2. 이익이 날 확률")
    req_pct = (be["required"] or 0) * 100
    a, b, c, d = st.columns(4)
    low = a.number_input("주문 반응 최소(%)", -50.0, 200.0, -5.0, 1.0, key="gl_low")
    mode = b.number_input("가장 가능성 높음(%)", -50.0, 200.0, round(max(req_pct, 0) + 5, 0), 1.0, key="gl_mode")
    high = c.number_input("최대(%)", -50.0, 200.0, round(max(req_pct * 2, 30), 0), 1.0, key="gl_high")
    days = d.number_input("진행 일수", 7, 60, 14, 1, key="gl_days")
    try:
        pp = G.profit_probability(be, mt, target, today, low / 100, mode / 100, high / 100, int(days))
    except ValueError as ex:
        st.error(str(ex))
        return
    a, b = st.columns([1, 2])
    a.metric("이익이 늘어날 확률", f"{pp['prob']:.0%}")
    a.caption(f"{int(days)}일 이익 차이: 하위 10% {pp['diff_p10']:+,.0f}원 · 중간 {pp['diff_p50']:+,.0f}원 · "
              f"상위 10% {pp['diff_p90']:+,.0f}원")
    hist = alt.Chart(pp["hist"]).mark_bar(color=ui.C_MAIN).encode(
        x=alt.X("이익 차이:Q", bin=alt.Bin(maxbins=40), title=f"{int(days)}일 이익 차이(원)"),
        y=alt.Y("count()", title=None))
    rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=ui.C_DOWN).encode(x="x:Q")
    b.altair_chart((hist + rule).properties(height=180), width="stretch")
    st.caption(f"가정: 주문 반응 {low:+.0f}% ~ {high:+.0f}% (가장 가능성 높음 {mode:+.0f}%). AI가 예측한 값이 아니라 입력한 가정입니다. "
               "날마다의 매출 흔들림(최근 56일)을 함께 반영한 2만 번 모의 계산입니다.")

    # ---------------- 3. 확인 기간
    st.markdown("#### 3. 효과 확인에 필요한 기간")
    eff = max(mode / 100, (be["required"] or 0))
    dd = G.detect_days(mt, target, today, eff)
    a, b = st.columns([1, 3])
    a.metric("필요 일수", "–" if dd["days"] is None else f"{dd['days']}일", dd["status"], delta_color="off")
    b.markdown(dd["note"])
    b.caption(f"기준: 대상 매출 비중(평균 {dd['share_mean']:.1%}, 하루 흔들림 {dd['share_sd']:.1%}p) · "
              f"기대 효과 {eff:+.0%}(가장 가능성 높은 반응과 본전 중 큰 값) · 유의수준 5%, 검정력 80% · 시작 전 {G.PRE_DAYS}일과 비교")

    # ---------------- 4. 실행 계획
    st.markdown("#### 4. 실행 계획")
    rec_days = dd["days"] if dd["days"] and dd["status"] == "확인 가능" else 14
    a, b, c = st.columns(3)
    start = a.date_input("시작일", today.date(), key="gl_start")
    end = b.date_input("종료일(포함)", (pd.Timestamp(start) + pd.Timedelta(days=rec_days - 1)).date(), key="gl_end")
    stop_pp = c.number_input("중단 기준: 이익률 하락(%p)", 1.0, 30.0, 8.0, 1.0, key="gl_stop")
    plan_tbl = pd.DataFrame([
        ("대상", C.target_text(target)), ("수단", G.lever_text(lever)),
        ("기간", f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({(pd.Timestamp(end) - pd.Timestamp(start)).days + 1}일)"),
        ("주 지표", r.get("primary_metric") or f"{C.target_text(target)} 일평균 매출"),
        ("짝 지표", f"{C.target_text(target)} 이익률"),
        ("중단 기준", f"이익률이 시작 전보다 {stop_pp:g}%p 넘게 떨어지면 중단"),
        ("본전 주문 증가율", "–" if be["required"] is None else f"{be['required']:+.1%}"),
        ("이익 확률(가정)", f"{pp['prob']:.0%}"), ("확인 가능성", f"{dd['status']}" + (f" ({dd['days']}일)" if dd["days"] else "")),
    ], columns=["항목", "내용"])
    st.dataframe(plan_tbl, hide_index=True, width="stretch")
    ss["growth_context"] = {
        "화면": "Growth Lab 새 계획", "대상": C.target_text(target), "수단": G.lever_text(lever),
        "손익 기준 기간": f"{be['period'][0]:%Y-%m-%d} ~ {be['period'][1]:%Y-%m-%d}",
        "simulate_policy 범위": {"categories": [target["value"]]} if target["type"] == "category" else {"product": target["value"]},
        "대상 주문": be["orders"], "현재 이익": round(be["profit_before"]), "주문 그대로일 때 이익": round(be["profit_after0"]),
        "본전 주문 증가율": None if be["required"] is None else round(be["required"], 4),
        "주문 반응 가정(%)": {"최소": low, "가장 가능성 높음": mode, "최대": high}, "진행 일수": int(days),
        "이익이 늘어날 확률": round(pp["prob"], 3), "확인 가능성": dd["status"], "필요 일수": dd["days"],
        "배송 원가(주문당)": G.SHIP_COST}
    ss["page_context"] = f"Growth Lab에서 {C.target_text(target)} {G.lever_text(lever)} 계획을 검토 중"
    if pd.Timestamp(end) >= D.PERIOD_END:
        st.caption("데이터가 10/31까지라 그 이후 기간의 결과는 아침 브리핑에 나오지 않습니다(가상 데이터 한계).")
    if st.button("실행 계획 등록", type="primary"):
        try:
            row = G.plan_row(ui.get_mart()["raw"]["promotion"], target, lever, start, end, today,
                             r.get("primary_metric") or f"{C.target_text(target)} 일평균 매출", stop_pp)
            where = G.save_plan(row)
        except Exception as ex:  # noqa: BLE001
            st.error(f"등록하지 못했습니다: {ex}")
        else:
            ui.get_mart.clear()
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success(f"{row['promotion_id']} {row['promotion_name']} 등록 완료({where}). "
                       "시작일부터 아침 브리핑의 프로모션 점검에 나옵니다.")


# ======================================================================= 목록
def show_list():
    st.info("AI 분석가에서 '계획 세우기'로 넘어오거나, 아침 브리핑의 '결과 보기'로 넘어오면 이 화면이 채워집니다.")
    promos = ui.get_mart()["raw"]["promotion"].copy()
    if promos.empty:
        st.caption("등록된 프로모션이 없습니다.")
        return
    st.markdown("#### 등록된 프로모션")
    status = {p["id"]: p["status"] for p in B.promo_status(ui.get_mart(), today - pd.Timedelta(days=1))}
    promos["판정(기준일)"] = promos["promotion_id"].map(status).fillna("–")
    show = promos[["promotion_id", "promotion_name", "start_date", "end_date", "status", "판정(기준일)"]].copy()
    show.columns = ["ID", "이름", "시작", "종료", "상태", "판정(기준일)"]
    for col in ("시작", "종료"):
        show[col] = pd.to_datetime(show[col]).dt.strftime("%Y-%m-%d")
    st.dataframe(show, hide_index=True, width="stretch")
    pid = st.selectbox("결과 볼 프로모션", promos["promotion_id"], key="gl_pick")
    if st.button("결과 보기"):
        ss.lab_request = {"type": "lab", "promotion_id": pid}
        st.rerun()


if not req:
    show_list()
elif req.get("type") == "plan":
    show_plan(req)
elif req.get("type") == "lab" and req.get("promotion_id"):
    show_result(req["promotion_id"])
else:
    show_list()
if req:
    if st.button("목록으로"):
        ss.pop("lab_request", None)
        st.rerun()

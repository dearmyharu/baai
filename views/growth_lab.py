"""⑤ Growth Lab: 어떤 문제를 해결하고, 어떻게 검증할 것인가?"""
import math

import pandas as pd
import streamlit as st

from core import llm, store, tools, ui
from core.metrics import sample_size_per_group, two_prop_test

m = ui.get_mart()
cur, prev = ui.period_controls()

st.title("Growth Lab")
st.caption("다른 화면에서 저장한 변화를 문제 → 가설 → 전략 → 실험 설계로 정리하는 작업 공간입니다. "
           + ("저장 위치: 공유 DB (팀원 모두에게 보입니다)" if store.backend() == "db"
              else "저장 위치: 이 PC의 dashboard/growth_lab/store.json (나만 보입니다)"))
if store.current_author() == "익명":
    st.info("왼쪽 사이드바 아래 '내 이름'을 적으면 누가 저장·수정했는지 함께 기록됩니다.", icon=":material/person:")

data = store.load()
problems = data["problems"]

# ---------------- 문제 목록 ----------------
with st.expander("직접 문제 후보 추가", icon=":material/add:"):
    with st.form("new_problem", clear_on_submit=True):
        t = st.text_input("문제 제목", placeholder="예: 7월 야식 테마 장바구니 이탈 증가")
        obs = st.text_area("관찰된 변화와 근거", placeholder="어떤 지표가 어느 기간에 얼마나 변했는지")
        if st.form_submit_button("추가") and t:
            store.add_problem({"kind": "manual", "title": t, "definition": obs, "unit": "rate"}, "직접 입력",
                              {"page": "Growth Lab", "period": ui.period_label(cur), "compare": ui.period_label(prev)})
            st.rerun()

if not problems:
    st.info("아직 저장된 문제 후보가 없습니다. 통합 현황의 '확인할 변화', 상품·큐레이션의 '관심과 구매의 차이', "
            "고객 여정의 '구간 자세히 보기', 리텐션의 'RFM 고객군'에서 **Growth Lab에 저장**을 눌러 가져오세요.")
    st.page_link("views/overview.py", label="통합 현황으로 가기", icon=":material/arrow_forward:")
    st.stop()

lst = pd.DataFrame([{"ID": p["id"], "상태": p["status"], "문제": p["title"], "출처": p["source_page"],
                     "분석 기간": p.get("context", {}).get("period", ""), "작성": p.get("created_by", ""),
                     "최근 수정": f"{p.get('updated_at', p['created_at'])} {p.get('updated_by', '')}".strip()}
                    for p in problems])
st.dataframe(lst.iloc[::-1], hide_index=True, width="stretch")

ids = [p["id"] for p in problems][::-1]
titles = {p["id"]: p["title"] for p in problems}
pid = st.selectbox("작업할 문제", ids, format_func=lambda i: f"{i} · {titles.get(i, '')}", key="gl_pid")
P = store.get_problem(pid)
if P is None:
    st.warning("다른 팀원이 이 문제를 삭제했습니다.")
    st.stop()
obs = P.get("observed", {})
unit = obs.get("unit", "rate")

st.divider()
h1, h2, h3 = st.columns([4, 2, 1])
h1.subheader(P["title"])
skey = f"st_{pid}_{P['status']}"     # 다른 곳에서 상태가 바뀌면 위젯도 새로 그려지도록 상태를 키에 포함
h2.selectbox("상태", store.STATUSES, index=store.STATUSES.index(P["status"]), key=skey,
             on_change=lambda: store.update_problem(pid, status=st.session_state[skey]))
with h3:
    st.write("")
    if st.button("삭제", key=f"del_{pid}", icon=":material/delete:"):
        store.delete_problem(pid)
        st.rerun()

with st.container(border=True):
    ctx = P.get("context", {})
    st.markdown(f"**관찰된 근거** · 출처: {P['source_page']} · 분석 {ctx.get('period', '–')} / 비교 {ctx.get('compare', '–')}")
    if obs.get("current") is not None:
        line = f"{obs.get('metric', '')}: "
        if obs.get("previous") is not None:
            line += f"{ui.fmt_value(obs['previous'], unit)} → "
        line += f"**{ui.fmt_value(obs['current'], unit)}**"
        if obs.get("previous") is not None:
            line += f" ({ui.fmt_delta(obs['current'], obs['previous'], unit)})"
        st.markdown(line + f" · 영향 범위: {obs.get('segment', '–')}")
    st.caption(f"정의: {obs.get('definition', '–')} · 표본 n={obs.get('n_current', '–')}"
               + (f" · p={obs['p_value']:.3f}" if obs.get("p_value") is not None else ""))

# ---------------- AI 초안 ----------------
AKEY = llm.api_key()
dkey = f"ai_draft_{pid}"
with st.container(border=True):
    a1, a2 = st.columns([3, 1])
    a1.markdown("**AI 초안** · AI가 데이터 도구로 근거를 확인한 뒤 가설·전략(ICE)·실험 설계 초안을 씁니다.")
    if not AKEY:
        a1.caption("Secrets에 OPENAI_API_KEY를 넣으면 쓸 수 있습니다.")
    elif a2.button("AI 초안 만들기", key=f"mk_{pid}", icon=":material/auto_awesome:", use_container_width=True):
        try:
            with st.spinner("근거 데이터를 확인하고 초안을 쓰는 중... (20~40초)"):
                st.session_state[dkey] = llm.draft(AKEY, P, lambda name, p_: tools.run(m, name, **p_))
        except Exception as e:  # API 오류·시간 초과: 화면은 계속
            st.error(str(e) if isinstance(e, llm.LLMError) else f"AI 초안을 만들지 못했습니다({type(e).__name__}). 다시 시도해 주세요.")
    if P.get("ai_draft"):
        a1.caption(f"마지막 반영: {P['ai_draft'].get('at', '')} · 모델 {P['ai_draft'].get('model', '')}")

    D = st.session_state.get(dkey)
    if D:
        st.markdown(D["summary"])
        if D["warnings"]:
            st.warning(f"근거 데이터에서 찾지 못한 숫자가 {len(D['warnings'])}개 있습니다: {', '.join(D['warnings'])}. "
                       "해당 칸에 '⚠️ 확인 필요'를 붙였으니 반영 전에 확인하세요.")
        with st.expander(f"AI가 확인한 근거 데이터 ({sum('result' in c for c in D['calls'])}개)"):
            for c in D["calls"]:
                if "result" in c:
                    st.markdown(f"**{c['result']['title']}** · {c['result']['period']}")
                    for f in c["result"]["facts"]:
                        st.markdown(f"- {f}")
        st.markdown("**가설 초안**")
        st.dataframe(pd.DataFrame(D["hypotheses"]).drop(columns=["작성"]), hide_index=True, width="stretch")
        st.markdown("**전략 초안 (ICE 순)**")
        st.dataframe(pd.DataFrame(D["strategies"])[["선택", "개선 액션", "연결 가설", "기대 영향", "Impact", "Confidence",
                                                    "Ease", "ICE", "ICE 근거"]], hide_index=True, width="stretch")
        e = D["experiment"]
        st.markdown(f"**실험 초안** · {e['name']}  \n실험군(B): {e['treatment']}  \n대조군(A): {e['control']}  \n"
                    f"주요 지표: {e['metric']} · 대상: {e['target']} · 배정: {e['unit']} · 최소 검출 효과 {e['mde']:.0f}%  \n"
                    f"중단 기준: {e['stop']}")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("초안 반영", key=f"ap_{pid}", type="primary", icon=":material/check:"):
            keep_h = [h for h in (P.get("hypotheses") or []) if str(h.get("가설", "")).strip()
                      and (h.get("작성") == "분석가" or (h.get("작성") == "템플릿 초안" and h.get("채택")))]
            keep_s = [x for x in (P.get("strategies") or []) if str(x.get("개선 액션", "")).strip()]
            for x in keep_s:
                x["선택"] = False
            old = P.get("experiment") or {}
            exp = {**{k: v for k, v in old.items() if v not in ("", None, [])},
                   **{k: v for k, v in e.items() if not old.get(k)}}
            store.update_problem(
                pid, hypotheses=keep_h + D["hypotheses"], strategies=D["strategies"] + keep_s, experiment=exp,
                ai_draft={"at": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"), "model": D["model"],
                          "summary": D["summary"], "evidence": [c["result"]["title"] for c in D["calls"] if "result" in c]},
                status="가설 검토" if P["status"] in ("문제 후보", "문제 정의") else P["status"])
            for k in (f"hy_{pid}", f"stg_{pid}", dkey):
                st.session_state.pop(k, None)
            st.toast("AI 초안을 가설·전략·실험 설계에 반영했습니다. 각 탭에서 검토하고 고쳐 주세요.")
            st.rerun()
        if b2.button("버리기", key=f"dc_{pid}"):
            st.session_state.pop(dkey, None)
            st.rerun()
        ui.note("AI 초안은 출발점입니다. 숫자는 데이터 도구 결과에서만 가져오도록 했지만, 원인·전략은 검증 전 가설입니다. "
                "반영하면 이전 AI 초안과 채택하지 않은 템플릿 초안 대신 새 AI 초안이 들어가고, 분석가가 쓴 가설과 기존 전략은 유지됩니다. 실험 설계는 비어 있는 칸만 채웁니다.")

tabs = st.tabs(["1. 문제 정의", "2. 가설 검토", "3. 전략 비교", "4. 실험 설계", "5. 결과 검토"])

# ---------------- 1. 문제 정의 ----------------
with tabs[0]:
    dfn = P.get("definition") or {}
    default_stmt = (f"{ctx.get('period', '')} 기간에 {obs.get('segment', '')}의 {obs.get('metric', '')}이(가) "
                    + (f"{ui.fmt_value(obs.get('previous'), unit)}에서 {ui.fmt_value(obs.get('current'), unit)}로 "
                       f"{obs.get('direction', '변화')}했다." if obs.get("previous") is not None else "확인이 필요한 수준이다."))
    with st.form(f"def_{pid}"):
        c1, c2 = st.columns(2)
        target = c1.text_input("대상 고객", dfn.get("target", obs.get("segment", "")))
        period = c2.text_input("발생 기간", dfn.get("period", ctx.get("period", "")))
        metric = c1.text_input("문제 지표", dfn.get("metric", obs.get("metric", "")))
        scope = c2.text_input("영향 범위 (규모)", dfn.get("scope", f"분모 {obs.get('n_current', '–')}"))
        stmt = st.text_area("문제 문장", dfn.get("statement", default_stmt))
        why = st.text_area("왜 중요한가 (비즈니스 영향)", dfn.get("impact", ""),
                           placeholder="예: 이 구간 전환율이 이전 수준이면 월 완료 주문이 약 N건 더 많았을 것")
        if st.form_submit_button("문제 정의 저장"):
            store.update_problem(pid, definition={"target": target, "period": period, "metric": metric, "scope": scope,
                                                  "statement": stmt, "impact": why},
                                 status="문제 정의" if P["status"] == "문제 후보" else P["status"])
            st.toast("문제 정의를 저장했습니다.")
            st.rerun()
    if obs.get("previous") is not None and obs.get("n_current") and unit == "rate":
        lost = (obs["previous"] - obs["current"]) * obs["n_current"]
        ui.note(f"참고 계산: 비교 기간 수준이었다면 전환이 약 {lost:+,.0f}건 {'더 많았을' if lost > 0 else '더 적었을'} 것입니다 "
                f"(분모 {obs['n_current']:,} × 차이).")

# ---------------- 2. 가설 ----------------
TEMPLATES = {
    "funnel": [("배송비·최소 주문 금액 부담으로 결제를 포기했다", "장바구니 금액 3만원 미만 세션의 구매율 비교"),
               ("특정 테마·시간대에 이탈이 몰려 있다", "구간 자세히 보기에서 테마·시간대별 변화 기여 확인"),
               ("쿠폰 조건이 맞지 않아 결제를 미뤘다", "쿠폰 사용 주문 비중 변화, 쿠폰 기간과 겹치는지 확인"),
               ("가격 변동(할인 종료)으로 구매 매력이 낮아졌다", "구성 상품 가격 이력 확인")],
    "theme": [("배너 메시지가 기대하게 만든 것과 상품 구성이 다르다", "테마 내 상품 클릭→장바구니율 비교"),
              ("구성 상품의 가격대가 테마 타깃 고객에게 높다", "객단가와 고객군별 구매 전환 비교"),
              ("상위 노출 상품의 성과가 낮아 테마 전체가 끌려 내려간다", "구성 상품별 성과 표에서 노출 순서별 확인"),
              ("노출 위치가 바뀌거나 노출 대상 고객이 달라졌다", "방문 유형·시간대별 노출 비중 변화")],
    "segment": [("첫 구매 경험(배송·품질)이 다음 구매로 이어지지 못한다", "첫 구매 고객 30일 재구매율 추이"),
                ("재구매를 떠올리게 하는 접점(리마인드)이 없다", "재구매 간격 중앙값 시점 전후 방문 여부"),
                ("선호 카테고리와 추천 테마가 맞지 않는다", "고객군별 선호 카테고리·테마 비교")],
    "product": [("노출이 적어 관심 대비 매출 규모가 작다", "큐레이션 편성 여부, 노출 위치별 클릭 세션 비교"),
                ("가격·용량 구성이 첫 구매 장벽이다", "가격 이력, 첫 구매 고객 비중 비교"),
                ("관련 상품과 함께 노출되면 구매가 늘어난다", "같은 테마 안 상품들의 클릭→장바구니율 비교")],
    "category": [("가격 인상·할인 종료로 수요가 줄었다", "가격 이력과 판매량 비교"),
                 ("계절성으로 수요가 이동했다", "월별 카테고리 비중 추이")],
}
with tabs[1]:
    hyps = P.get("hypotheses") or []
    if not hyps:
        tpl = TEMPLATES.get(obs.get("kind"), TEMPLATES["funnel"])
        hyps = [{"채택": False, "가설": h, "근거": "", "반대 근거": "", "추가 확인": chk, "작성": "템플릿 초안"} for h, chk in tpl]
    st.caption("템플릿 초안은 출발점일 뿐입니다. 근거와 반대 근거를 데이터로 채운 뒤 검토할 가설을 '채택'하세요. "
               "위의 'AI 초안 만들기'로 데이터 근거가 붙은 초안을 받을 수도 있습니다.")
    ed = st.data_editor(pd.DataFrame(hyps), num_rows="dynamic", width="stretch", key=f"hy_{pid}",
                        column_config={"채택": st.column_config.CheckboxColumn(width="small"),
                                       "가설": st.column_config.TextColumn(width="large"),
                                       "작성": st.column_config.SelectboxColumn(options=["템플릿 초안", "AI 초안", "분석가"], width="small")})
    if st.button("가설 저장", key=f"hys_{pid}"):
        rows = ed.fillna("").to_dict("records")
        store.update_problem(pid, hypotheses=rows,
                             status="가설 검토" if P["status"] in ("문제 후보", "문제 정의") else P["status"])
        st.toast("가설을 저장했습니다.")
        st.rerun()

# ---------------- 3. 전략 ----------------
with tabs[2]:
    chosen = [h["가설"] for h in (P.get("hypotheses") or []) if h.get("채택")]
    if not chosen:
        st.info("2단계에서 채택한 가설이 없습니다. 먼저 검토할 가설을 고르세요.")
    strat = P.get("strategies") or [{"선택": False, "개선 액션": "", "연결 가설": chosen[0] if chosen else "",
                                    "기대 영향": "", "Impact": 5, "Confidence": 5, "Ease": 5, "ICE 근거": ""}]
    sdf = pd.DataFrame(strat)
    ed = st.data_editor(sdf.drop(columns=["ICE"], errors="ignore"), num_rows="dynamic", width="stretch", key=f"stg_{pid}",
                        column_config={
                            "선택": st.column_config.CheckboxColumn(width="small"),
                            "연결 가설": st.column_config.SelectboxColumn(options=chosen or [""]),
                            "Impact": st.column_config.NumberColumn(min_value=1, max_value=10, step=1, width="small"),
                            "Confidence": st.column_config.NumberColumn(min_value=1, max_value=10, step=1, width="small"),
                            "Ease": st.column_config.NumberColumn(min_value=1, max_value=10, step=1, width="small")})
    ice = ed.copy()
    for c in ["Impact", "Confidence", "Ease"]:
        ice[c] = pd.to_numeric(ice[c], errors="coerce")
    ice["ICE"] = (ice["Impact"] * ice["Confidence"] * ice["Ease"]).round(0)
    if ice["개선 액션"].fillna("").str.len().sum():
        st.markdown("**ICE 순위** (Impact × Confidence × Ease, 각 1~10)")
        st.dataframe(ice[ice["개선 액션"].fillna("") != ""].sort_values("ICE", ascending=False)[
            ["개선 액션", "연결 가설", "Impact", "Confidence", "Ease", "ICE", "ICE 근거"]], hide_index=True, width="stretch")
    if st.button("전략 저장", key=f"sts_{pid}"):
        store.update_problem(pid, strategies=ice.fillna("").to_dict("records"),
                             status="전략 선정" if P["status"] in ("문제 후보", "문제 정의", "가설 검토") else P["status"])
        st.toast("전략을 저장했습니다.")
        st.rerun()
    ui.note("ICE 점수는 판단을 정리하는 도구일 뿐입니다. 점수마다 근거를 적어 두세요.")

# ---------------- 4. 실험 설계 ----------------
with tabs[3]:
    ex = P.get("experiment") or {}
    picked = [s for s in (P.get("strategies") or []) if s.get("선택")]
    if not picked:
        st.info("3단계에서 실행 후보(선택)를 고르면 실험 설계로 이어집니다. 지금도 직접 입력할 수 있습니다.")
    base_rate = obs.get("current") if unit == "rate" and obs.get("current") is not None else 0.2
    try:
        a_, b_ = [pd.Timestamp(x) for x in ctx.get("period", "").split(" ~ ")]
        days = (b_ - a_).days + 1
    except Exception:
        days = 30
    daily_default = max(1, int((obs.get("n_current") or 300) / days))

    with st.form(f"exp_{pid}"):
        c1, c2 = st.columns(2)
        name = c1.text_input("실험명", ex.get("name", picked[0]["개선 액션"] if picked else ""))
        hyp = c2.text_input("검증할 가설", ex.get("hypothesis", picked[0]["연결 가설"] if picked else ""))
        treat = c1.text_area("실험군 (B) 변경 내용", ex.get("treatment", ""))
        control = c2.text_area("대조군 (A)", ex.get("control", "현재 화면·정책 유지"))
        unit_ = c1.selectbox("배정 단위", ["고객", "세션"], index=["고객", "세션"].index(ex.get("unit", "고객")),
                             help="같은 고객이 두 조건을 모두 보지 않도록 보통 고객 단위로 배정합니다.")
        target = c2.text_input("실험 대상", ex.get("target", obs.get("segment", "")))
        metric = c1.text_input("주요 지표 (1개)", ex.get("metric", obs.get("metric", "")))
        guard = c2.multiselect("가드레일 지표", ["객단가", "취소·환불 비중", "쿠폰 할인액", "공헌이익률", "전체 세션 구매 전환율"],
                               default=ex.get("guardrails", ["객단가", "취소·환불 비중"]))
        st.markdown("**표본·기간 산정**")
        d1, d2, d3, d4 = st.columns(4)
        p0 = d1.number_input("기준 전환율", 0.001, 0.999, float(ex.get("baseline", round(base_rate, 4))), format="%.4f",
                             help="대조군에서 예상되는 주요 지표 값. 근거 데이터의 현재 값으로 채워집니다.")
        mde = d2.number_input("최소 검출 효과 (상대 %)", 1.0, 200.0, float(ex.get("mde", 10.0)), step=1.0)
        alpha = d3.selectbox("유의수준", [0.05, 0.1, 0.01], index=[0.05, 0.1, 0.01].index(ex.get("alpha", 0.05)))
        power = d4.selectbox("검정력", [0.8, 0.9], index=[0.8, 0.9].index(ex.get("power", 0.8)))
        e1, e2 = st.columns(2)
        daily = e1.number_input("일 평균 실험 대상 수", 1, 1_000_000, int(ex.get("daily", daily_default)),
                                help=f"근거 데이터의 분모를 기간 일수로 나눈 값({daily_default:,}/일)으로 채워집니다.")
        stop = e2.text_input("중단 기준", ex.get("stop", "가드레일 지표가 대조군보다 유의하게 악화되면 중단"))
        submitted = st.form_submit_button("실험 설계 저장")

    n = sample_size_per_group(p0, mde / 100, alpha, power)
    if pd.notna(n):
        total = n * 2
        dur = math.ceil(total / daily)
        k1, k2, k3 = st.columns(3)
        k1.metric("그룹당 필요 표본", f"{n:,}", border=True)
        k2.metric("총 필요 표본", f"{total:,}", border=True)
        k3.metric("예상 기간", f"{dur}일" + (" (최소 7일 권장)" if dur < 7 else ""), border=True)
        ui.note(f"기준 {p0:.1%} → 목표 {p0 * (1 + mde / 100):.1%} 변화를 유의수준 {alpha}, 검정력 {power:.0%}로 찾기 위한 "
                "두 비율 비교(정규근사) 표본입니다. 요일 효과를 고려해 1주 단위로 운영하세요.")
        if dur > 60:
            st.warning("예상 기간이 60일을 넘습니다. 최소 검출 효과를 키우거나 대상을 넓히는 것을 검토하세요.")
    else:
        st.warning("기준 전환율과 최소 검출 효과 조합이 0~100% 범위를 벗어납니다.")
    if submitted:
        store.update_problem(pid, experiment={
            "name": name, "hypothesis": hyp, "treatment": treat, "control": control, "unit": unit_, "target": target,
            "metric": metric, "guardrails": guard, "baseline": p0, "mde": mde, "alpha": alpha, "power": power,
            "daily": daily, "stop": stop, "n_per_group": n, "duration_days": None if pd.isna(n) else math.ceil(n * 2 / daily)},
            status="실험 설계 완료")
        st.toast("실험 설계를 저장했습니다. 상태: 실험 설계 완료")
        st.rerun()

# ---------------- 5. 결과 검토 ----------------
with tabs[4]:
    st.info("실제 실험 결과 데이터가 없어 기본 상태는 '실험 설계 완료'입니다. 결과 수치가 생기면 아래에 입력해 효과와 불확실성을 확인할 수 있습니다.")
    res = (P.get("experiment") or {}).get("result", {})
    with st.form(f"res_{pid}"):
        mock = st.checkbox("모의 결과입니다 (실제 실험 아님)", value=res.get("mock", True))
        r1, r2, r3, r4 = st.columns(4)
        na = r1.number_input("대조군 대상 수", 0, 10_000_000, int(res.get("na", 0)))
        xa = r2.number_input("대조군 전환 수", 0, 10_000_000, int(res.get("xa", 0)))
        nb = r3.number_input("실험군 대상 수", 0, 10_000_000, int(res.get("nb", 0)))
        xb = r4.number_input("실험군 전환 수", 0, 10_000_000, int(res.get("xb", 0)))
        decision = st.selectbox("판단", ["미정", "도입", "수정 후 재실험", "중단"],
                                index=["미정", "도입", "수정 후 재실험", "중단"].index(res.get("decision", "미정")))
        ok = st.form_submit_button("결과 저장")
    if na and nb and xa <= na and xb <= nb:
        pa, pb = xa / na, xb / nb
        z, p = two_prop_test(xb, nb, xa, na)
        se = math.sqrt(pa * (1 - pa) / na + pb * (1 - pb) / nb)
        lo, hi = (pb - pa) - 1.96 * se, (pb - pa) + 1.96 * se
        c1, c2, c3 = st.columns(3)
        c1.metric("대조군 → 실험군", f"{pa:.2%} → {pb:.2%}", f"{(pb - pa) * 100:+.2f}%p", border=True)
        c2.metric("상대 변화", f"{(pb / pa - 1) * 100:+.1f}%" if pa else "–", border=True)
        c3.metric("p값", f"{p:.4f}", border=True)
        st.markdown(f"차이의 95% 신뢰구간: **{lo * 100:+.2f}%p ~ {hi * 100:+.2f}%p**"
                    + (" · 0을 포함하므로 효과가 있다고 말하기 어렵습니다." if lo <= 0 <= hi else ""))
        if mock:
            st.caption("⚠️ 모의 결과입니다.")
    if ok:
        ex = P.get("experiment") or {}
        ex["result"] = {"mock": mock, "na": na, "xa": xa, "nb": nb, "xb": xb, "decision": decision}
        store.update_problem(pid, experiment=ex)
        st.toast("결과를 저장했습니다.")
        st.rerun()

# ---------------- 내보내기 ----------------
st.divider()
P = store.get_problem(pid)


def to_md(p):
    dfn, ex = p.get("definition") or {}, p.get("experiment") or {}
    lines = [f"# {p['title']}", f"- ID: {p['id']} · 상태: {p['status']} · 출처: {p['source_page']}", "",
             "## 문제 정의", dfn.get("statement", "(미작성)"), f"- 대상: {dfn.get('target', '')}",
             f"- 기간: {dfn.get('period', '')}", f"- 지표: {dfn.get('metric', '')}", f"- 영향: {dfn.get('impact', '')}", "",
             "## 가설"]
    if p.get("ai_draft"):
        a = p["ai_draft"]
        lines[-1:-1] = ["## AI 근거 요약", a.get("summary", ""), f"- 확인한 데이터: {', '.join(a.get('evidence', []))} "
                        f"({a.get('at', '')}, {a.get('model', '')})", ""]
    for h in p.get("hypotheses") or []:
        lines.append(f"- [{'x' if h.get('채택') else ' '}] {h.get('가설', '')} (근거: {h.get('근거', '')} / 반대 근거: "
                     f"{h.get('반대 근거', '')} / 추가 확인: {h.get('추가 확인', '')}) _{h.get('작성', '')}_")
    lines += ["", "## 전략 (ICE)"]
    for s in sorted(p.get("strategies") or [], key=lambda s: -(s.get("ICE") or 0)):
        lines.append(f"- {'★ ' if s.get('선택') else ''}{s.get('개선 액션', '')} · ICE {s.get('ICE', '')} · {s.get('ICE 근거', '')}")
    lines += ["", "## 실험 설계"]
    for k, lab in [("name", "실험명"), ("hypothesis", "가설"), ("treatment", "실험군"), ("control", "대조군"), ("unit", "배정 단위"),
                   ("target", "대상"), ("metric", "주요 지표"), ("guardrails", "가드레일"), ("baseline", "기준 전환율"),
                   ("mde", "최소 검출 효과(%)"), ("n_per_group", "그룹당 표본"), ("duration_days", "예상 기간(일)"), ("stop", "중단 기준")]:
        lines.append(f"- {lab}: {ex.get(k, '')}")
    return "\n".join(lines)


st.download_button("이 문제의 계획서 내려받기 (.md)", to_md(P), file_name=f"{pid}.md", icon=":material/download:")

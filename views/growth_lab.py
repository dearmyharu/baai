"""Growth Lab — product, policy, current/new conditions, results."""

from __future__ import annotations

import hashlib
import json

import altair as alt
import pandas as pd
import streamlit as st

from core import growth_experiment, metrics as M, simulation as S, store, ui


def price_table(prepared):
    items = prepared["selected_items"].copy()
    items = items[items.quantity.gt(0)]
    items["unit_price"] = items.sales_amount / items.quantity
    recent = items.sort_values("order_time").drop_duplicates("product_id", keep="last")
    bounds = items.groupby("product_id").unit_price.agg(["min", "max"])
    out = (
        recent[["product_id", "product_name", "unit_price", "cost_price"]]
        .set_index("product_id")
        .join(bounds)
    )
    return out.rename(
        columns={
            "product_name": "상품",
            "unit_price": "최근 판매가격 (원)",
            "cost_price": "상품원가 (원)",
            "min": "최저 판매가격 (원)",
            "max": "최고 판매가격 (원)",
        }
    )


def policy_inputs(config, prefix, prepared, policy):
    default = S.normalize_config(config)
    cfg = dict(default, policy=policy)
    st.caption("기준은 선택 기간의 완료 주문입니다. 현재 정보와 바꿀 값을 확인하세요.")
    a, b = st.columns(2)
    with a:
        st.markdown("**현재 정보**")
        ledger = prepared["ledger"].loc[prepared["ledger"].target]
        if policy == "price":
            st.caption(
                "쿠폰 차감 전 단가입니다. 여러 가격에 판매됐다면 최근 가격과 범위를 함께 표시합니다."
            )
        elif policy == "discount":
            rate = (
                ledger.discount.sum() / ledger.gross.sum() * 100
                if ledger.gross.sum()
                else 0
            )
            st.metric("관측된 실질 쿠폰 할인율", f"{rate:.2f}%")
            st.caption(
                "대상 주문의 상품금액 대비 쿠폰 할인액 비율입니다. 쿠폰 상한·최소금액에 따라 설정 할인율과 다를 수 있습니다."
            )
        elif policy == "shipping":
            st.metric(
                "관측된 평균 고객 배송비",
                ui.won(ledger.shipping_income.mean(), short=False),
            )
            st.caption(
                "현재 무료배송 기준은 주문 내역만으로 확정할 수 없습니다. 변경할 기준을 오른쪽에 입력하세요."
            )
        elif policy in ("benefit", "bundle"):
            st.metric("대상 완료 주문", f"{len(ledger):,}건")
            st.caption(
                "현재 주문금액에 추가로 적용할 혜택 또는 묶음 할인을 입력합니다."
            )
        else:
            st.metric("대상 완료 주문", f"{len(ledger):,}건")
            st.caption("노출·전환 개선에 따른 주문 반응을 직접 가정합니다.")
    with b:
        st.markdown("**변경할 정책**")
        if policy == "discount":
            cfg["discount_type"] = st.selectbox(
                "할인 방식",
                ["rate", "fixed"],
                index=["rate", "fixed"].index(default["discount_type"]),
                format_func=lambda x: "할인율 (%)" if x == "rate" else "할인액 (원)",
                key=f"{prefix}_discount_type",
            )
            cfg["discount_value"] = st.number_input(
                (
                    "변경 할인율 (%)"
                    if cfg["discount_type"] == "rate"
                    else "변경 할인액 (원)"
                ),
                0.0,
                100.0 if cfg["discount_type"] == "rate" else 1e8,
                (
                    min(float(default["discount_value"]), 100.0)
                    if cfg["discount_type"] == "rate"
                    else float(default["discount_value"])
                ),
                key=f"{prefix}_discount_value",
            )
            st.caption("선택한 주문의 기존 쿠폰을 새 쿠폰으로 교체합니다.")
        elif policy == "shipping":
            cfg["shipping_fee"] = st.number_input(
                "변경 고객 배송비 (원)",
                0.0,
                1e8,
                float(default["shipping_fee"]),
                key=f"{prefix}_shipping_fee",
            )
            cfg["free_shipping_threshold"] = st.number_input(
                "변경 무료배송 기준 (원)",
                0.0,
                1e8,
                float(default["free_shipping_threshold"]),
                key=f"{prefix}_free_shipping_threshold",
                help="쿠폰 차감 후 상품금액 기준. 0원은 전체 무료배송입니다.",
            )
        elif policy == "benefit":
            cfg["benefit_amount"] = st.number_input(
                "추가 혜택 원가 (원/사용 주문)",
                0.0,
                1e8,
                float(default["benefit_amount"]),
                key=f"{prefix}_benefit_amount",
            )
        elif policy == "bundle":
            cfg["bundle_discount_pct"] = st.number_input(
                "묶음 추가 할인율 (%)",
                0.0,
                100.0,
                float(default["bundle_discount_pct"]),
                key=f"{prefix}_bundle_discount_pct",
            )
            st.caption(
                "1단계에서 구성 상품을 2개 이상 선택하세요. 모두 담은 주문에 적용합니다."
            )
    if policy == "price":
        prices = price_table(prepared)
        prices["변경 가격 (원)"] = [
            default["price_overrides"].get(
                str(k), v * (1 + default["price_change_pct"] / 100)
            )
            for k, v in zip(prices.index, prices["최근 판매가격 (원)"])
        ]
        prices = prices.reset_index()
        target_key = hashlib.sha256(
            prices[["product_id", "최근 판매가격 (원)"]].to_json().encode()
        ).hexdigest()[:10]
        edited = st.data_editor(
            prices,
            hide_index=True,
            width="stretch",
            key=f"{prefix}_prices_{target_key}",
            disabled=[c for c in prices.columns if c != "변경 가격 (원)"],
            column_config={
                "product_id": None,
                "변경 가격 (원)": st.column_config.NumberColumn(
                    min_value=0, format="%.0f"
                ),
            },
        )
        cfg["price_overrides"] = {
            str(r["product_id"]): float(r["변경 가격 (원)"])
            for _, r in edited.iterrows()
            if pd.notna(r["변경 가격 (원)"])
            and r["변경 가격 (원)"] != r["최근 판매가격 (원)"]
        }
        cfg["price_change_pct"] = 0.0
        expected = prices["변경 가격 (원)"].reset_index(drop=True)
        if default["price_change_pct"] and edited["변경 가격 (원)"].reset_index(
            drop=True
        ).equals(expected):
            cfg["price_overrides"] = {}
            with st.expander("이전 기록·AI의 가격 변화율 사용"):
                cfg["price_change_pct"] = st.number_input(
                    "가격 변화율 (%)",
                    -100.0,
                    1000.0,
                    float(default["price_change_pct"]),
                    key=f"{prefix}_price_change_pct",
                )
    with st.expander("고객 반응·할인 조건·추가 실행비 설정"):
        st.caption(
            "기본 결과는 주문 수 유지 가정입니다. 반응을 가정할 때만 수정하세요."
        )
        cfg["order_change_pct"] = st.number_input(
            "대상 주문 수 변화 가정 (%)",
            -100.0,
            1000.0,
            float(default["order_change_pct"]),
            key=f"{prefix}_order_change_pct",
        )
        cfg["fixed_cost"] = st.number_input(
            "추가 실행비 (원)",
            0.0,
            1e8,
            float(default["fixed_cost"]),
            key=f"{prefix}_fixed_cost",
        )
        if policy == "discount":
            cfg["minimum_order"] = st.number_input(
                "최소 주문 상품금액 (원)",
                0.0,
                1e8,
                float(default["minimum_order"]),
                key=f"{prefix}_minimum_order",
            )
            cfg["discount_cap"] = st.number_input(
                "최대 할인액 (원, 0은 상한 없음)",
                0.0,
                1e8,
                float(default["discount_cap"]),
                key=f"{prefix}_discount_cap",
            )
        if policy in ("discount", "benefit"):
            cfg["adoption_pct"] = st.number_input(
                "적용 주문 비중 (%)",
                0.0,
                100.0,
                float(default["adoption_pct"]),
                key=f"{prefix}_adoption_pct",
            )
    return cfg


def main():
    st.session_state.pop("growth_context", None)
    m = ui.get_mart()
    cur, _ = ui.period_controls()
    st.title("Growth Lab")
    st.caption("상품을 고르고, 정책을 바꿔 현재와 비교해 보세요.")
    if store.db_error():
        st.warning("공유 저장이 연결되지 않아 현재 실행 환경에 저장합니다.")
    records = {p["id"]: p for p in reversed(store.load()["problems"])}
    pending = st.session_state.pop("growth_open_id", None)
    if pending in records:
        st.session_state.sim_record = pending
    if st.session_state.get("sim_record") not in [None, "new", *records]:
        st.session_state.sim_record = "new"
    with st.expander("저장한 비교·분석 근거 불러오기"):
        selected = st.selectbox(
            "불러올 기록",
            ["new", *records],
            key="sim_record",
            format_func=lambda x: "새로 시작" if x == "new" else records[x]["title"],
        )
        record = records.get(selected)
        saved = (record or {}).get("simulation") or {}
        if record:
            st.write(record.get("observed", {}))
            for field in ("definition", "hypotheses", "strategies"):
                if record.get(field):
                    st.write(record[field])
            if saved:
                st.caption(
                    f"저장 기간 {saved['start']} ~ {saved['end']} (끝 다음 날 미포함)"
                )
                st.button("저장 기간 적용", on_click=restore_period, args=(saved,))
            st.download_button(
                "이전 기록 내려받기",
                json.dumps(record, ensure_ascii=False, indent=2),
                file_name="growth_record.json",
            )
    prefix = f"sim_{selected}"
    source = saved.get("scope") or {}
    if not saved and record:
        obs = record.get("observed") or {}
        source = {k: obs[k] for k in ("theme_id", "coupon_id") if obs.get(k)}
        if obs.get("product_id"):
            source["product_ids"] = [obs["product_id"]]
        calls = obs.get("calls") or []
        if calls:
            source["filters"] = calls[0].get("params", {}).get("filters", {})
    st.subheader("1. 어떤 상품을 개선할까요?")
    st.caption("분석 기간 · " + ui.period_label(cur))
    products = m["raw"]["product"]
    cats = sorted(products.category.dropna().unique())
    categories = st.multiselect(
        "상품군 선택 (비우면 전체 상품군)",
        cats,
        default=[c for c in source.get("categories", []) if c in cats],
        key=f"{prefix}_categories",
    )
    available = products[products.category.isin(categories)] if categories else products
    names = available.set_index("product_id").product_name.to_dict()
    id_key = f"{prefix}_products"
    if id_key in st.session_state:
        st.session_state[id_key] = [x for x in st.session_state[id_key] if x in names]
    ids = st.multiselect(
        "세부 상품 선택 (비우면 선택 상품군 전체)",
        list(names),
        default=[x for x in source.get("product_ids", []) if x in names],
        format_func=lambda x: names[x],
        key=id_key,
    )
    filters = dict(source.get("filters") or {})
    with st.expander("대상을 더 구체적으로 선택"):
        themes = m["raw"]["curation_theme"].set_index("theme_id").theme_name.to_dict()
        theme_options = ["", *themes]
        theme = st.selectbox(
            "테마",
            theme_options,
            index=(
                theme_options.index(source.get("theme_id", ""))
                if source.get("theme_id", "") in theme_options
                else 0
            ),
            format_func=lambda x: themes.get(x, "전체"),
            key=f"{prefix}_theme",
        )
        opts = ["", "F", "M"]
        gender = st.selectbox(
            "고객 성별",
            opts,
            index=opts.index(filters.get("gender", "")),
            format_func=lambda x: {"": "전체", "F": "여성", "M": "남성"}[x],
            key=f"{prefix}_gender",
        )
        grades = st.multiselect(
            "주문 당시 등급",
            ["BRONZE", "SILVER", "GOLD", "VIP"],
            default=filters.get("grades", []),
            key=f"{prefix}_grades",
        )
        filters = {
            k: v
            for k, v in filters.items()
            if k not in ("gender", "grades", "grade_basis")
        }
        if gender:
            filters["gender"] = gender
        if grades:
            filters.update(grades=grades, grade_basis="당시")
        if filters:
            st.caption(M.describe_filters(M.clean_filters(filters), cur))
    scope = dict(
        categories=categories,
        product_ids=ids,
        theme_id=theme,
        filters=filters,
        coupon_id=source.get("coupon_id", ""),
    )
    costs = S.DEFAULT_COSTS | saved.get("costs", {})
    try:
        initial = S.prepare(m, *cur, scope, costs)
    except (ValueError, KeyError) as exc:
        st.info(
            "이 기간·대상에 계산할 판매 내역이 없습니다. 상품이나 기간을 다시 선택해 주세요."
        )
        with st.expander("상세 사유"):
            st.write(str(exc))
        return
    items = initial["selected_items"]
    a, b, c = st.columns(3)
    a.metric("선택 상품 판매수량", f"{items.quantity.sum():,.0f}개")
    b.metric(
        "선택 상품매출",
        ui.won(
            (items.sales_amount - items.allocated_coupon_discount).sum(), short=False
        ),
    )
    c.metric("포함된 완료 주문", f"{int(initial['ledger'].target.sum()):,}건")
    st.subheader("2. 무엇을 바꿀까요?")
    configs = (saved.get("scenarios", []) + [{}, {}])[:2]
    default = S.normalize_config(configs[0])
    policy = st.selectbox(
        "바꿀 정책",
        list(S.POLICIES),
        index=list(S.POLICIES).index(default["policy"]),
        format_func=S.POLICIES.get,
        key=f"{prefix}_a_policy",
    )
    if policy == "discount":
        orders = M.completed_orders(m, *cur)
        target_ids = initial["ledger"].index[initial["ledger"].target]
        seen = orders[orders.order_id.isin(target_ids)].coupon_id.unique()
        names = m["raw"]["coupon"].set_index("coupon_id").coupon_name.to_dict()
        options = ["", *sorted(seen)]
        current = scope["coupon_id"]
        scope["coupon_id"] = st.selectbox(
            "변경할 기존 쿠폰",
            options,
            index=options.index(current) if current in options else 0,
            format_func=lambda x: names.get(
                x, "쿠폰 미사용 주문" if x == "NO_COUPON" else "모든 대상 주문"
            ),
            key=f"{prefix}_coupon",
        )
        raw = m["raw"]["coupon"]
        columns = [
            x
            for x in [
                "coupon_name",
                "discount_type",
                "discount_value",
                "max_discount_amount",
                "min_order_amount",
            ]
            if x in raw.columns
        ]
        shown = (
            raw[raw.coupon_id.eq(scope["coupon_id"])]
            if scope["coupon_id"]
            else raw[raw.coupon_id.isin(seen)]
        )
        st.dataframe(
            shown[columns].rename(
                columns={
                    "coupon_name": "쿠폰",
                    "discount_type": "할인 방식",
                    "discount_value": "설정 할인값",
                    "max_discount_amount": "최대 할인액",
                    "min_order_amount": "최소 주문금액",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    with st.expander("비용 상세 설정"):
        st.caption(
            "상품원가는 자동 반영합니다. 추가 비용을 모르면 0으로 두고, 반영 범위와 함께 결과를 보세요."
        )
        a, b, c = st.columns(3)
        costs = dict(
            shipping_per_order=a.number_input(
                "주문당 배송 원가 (원)",
                0.0,
                1e7,
                float(costs["shipping_per_order"]),
                key=f"{prefix}_shipping_cost",
            ),
            fee_pct=b.number_input(
                "결제 수수료율 (%)",
                0.0,
                100.0,
                float(costs["fee_pct"]),
                key=f"{prefix}_fee",
            ),
            other_per_order=c.number_input(
                "기타 주문당 비용 (원)",
                0.0,
                1e7,
                float(costs["other_per_order"]),
                key=f"{prefix}_other",
            ),
        )
    try:
        prepared = S.prepare(m, *cur, scope, costs)
    except (ValueError, KeyError) as exc:
        st.info(str(exc))
        return
    st.subheader("3. 현재값을 확인하고 변경값을 입력하세요")
    config_a = policy_inputs(configs[0], f"{prefix}_a", prepared, policy)
    extra = st.toggle(
        "다른 변경안도 함께 비교",
        value=len(saved.get("scenarios", [])) > 1,
        key=f"{prefix}_extra",
    )
    config_b = {}
    if extra:
        with st.expander("추가 변경안 B", expanded=True):
            bp = st.selectbox(
                "추가안 정책",
                list(S.POLICIES),
                index=list(S.POLICIES).index(S.normalize_config(configs[1])["policy"]),
                format_func=S.POLICIES.get,
                key=f"{prefix}_b_policy",
            )
            config_b = policy_inputs(configs[1], f"{prefix}_b", prepared, bp)
    try:
        results = [S.simulate(prepared, config_a)]
        if extra:
            results.append(S.simulate(prepared, config_b))
    except (ValueError, KeyError) as exc:
        st.info(str(exc))
        return
    baseline = results[0]["baseline"]
    st.subheader("4. 결과 비교")
    labels = (
        ["현재"]
        + ["변경안 A" if extra else "변경 후"]
        + (["변경안 B"] if extra else [])
    )
    values = [baseline] + [r["changed"] for r in results]
    for box, label, value in zip(st.columns(len(labels)), labels, values):
        with box.container(border=True):
            st.markdown(f"**{label}**")
            st.metric(
                "완료 매출",
                ui.won(value["revenue"], short=False),
                (
                    None
                    if label == "현재"
                    else ui.won(value["revenue"] - baseline["revenue"], short=False)
                ),
            )
            st.metric(
                "반영 비용 차감 이익",
                ui.won(value["profit"], short=False),
                (
                    None
                    if label == "현재"
                    else ui.won(value["profit"] - baseline["profit"], short=False)
                ),
            )
            st.caption(f"주문 수 {value['orders']:,.1f}건")
    table = results[0]["table"][["지표", "현재"]].copy()
    for label, result in zip(["A", "B"][: len(results)], results):
        table[f"변경안 {label}"] = result["table"]["변경안"]
        table[f"{label} 차이"] = result["table"]["차이"]
    with st.expander("매출·할인·원가·비용 상세 보기"):
        st.dataframe(table, hide_index=True, width="stretch")
    chosen = (
        st.radio("검토할 안", ["A", "B"], horizontal=True,
                 index=0 if saved.get("selected", "A") == "A" else 1, key=f"{prefix}_selected")
        if extra
        else "A"
    )
    result = results[0 if chosen == "A" else 1]
    st.caption(
        f"전체 쇼핑몰 결과입니다. 선택안 적용 대상 {result['target_orders']:,}주문 · {result['target_buyers']:,}고객"
    )
    required = result["required_order_change"]
    if required is None:
        st.warning(
            "변경 후 대상 주문당 이익이 0 이하입니다. 정책·비용 구조를 먼저 검토하세요."
        )
    else:
        st.info(
            f"기존 이익 유지에 필요한 대상 주문 변화 {required*100:+.2f}% · 입력한 가정 {result['config']['order_change_pct']:+g}%"
        )
    with st.expander("대상·비용별 상세와 계산 기준"):
        st.dataframe(
            pd.DataFrame(
                [
                    {"범위": "대상 현재", **result["target_baseline"]},
                    {
                        "범위": "대상 변경 (추가 실행비 제외)",
                        **result["target_changed"],
                    },
                    {"범위": "대상 밖 공통", **result["outside"]},
                ]
            ).rename(columns=S.LABELS),
            hide_index=True,
            width="stretch",
        )
        for note in result["notes"]:
            st.caption(note)
        st.caption(
            "추가 실행비는 전체에서 한 번 차감합니다. 주문 수는 기대값이므로 소수일 수 있습니다."
        )
    with st.expander("판매가 더 늘거나 줄어든다면?"):
        sensitivity = S.sensitivity(prepared, result["config"])
        st.altair_chart(
            alt.Chart(sensitivity)
            .mark_line(point=True, color=ui.C_MAIN)
            .encode(
                x=alt.X("주문 변화 가정 (%):Q"),
                y=alt.Y("반영 비용 차감 이익:Q", axis=alt.Axis(format="~s")),
                tooltip=list(sensitivity.columns),
            ),
            width="stretch",
        )
        st.caption(
            "현재 가정의 전후 10%p와 변화 0% 비교입니다. 시나리오 민감도이며 통계적 신뢰구간과 구분합니다."
        )
    snapshot = dict(
        version=S.VERSION,
        start=prepared["start"],
        end=prepared["end"],
        scope=scope,
        costs=costs,
        scenarios=[config_a] + ([config_b] if extra else []),
        selected=chosen,
        facts=S.evidence(prepared, result),
        notes=result["notes"],
        comparison=table.to_dict("records"),
    )
    st.session_state.growth_context = snapshot
    st.caption("결과가 궁금하면 AI 분석가를 열고 “왜 이익이 달라졌어?”라고 물어보세요.")
    with st.form(f"{prefix}_save"):
        title = st.text_input(
            "비교 기록 이름", (record or {}).get("title", "정책 시뮬레이션 비교")
        )
        reason = st.text_area("선택 이유·다음 행동", saved.get("decision", ""))
        save = st.form_submit_button("비교안과 판단 저장", type="primary")
    if save:
        payload = {**snapshot, "decision": reason}
        pid = selected
        if record is None:
            pid = store.add_problem(
                {
                    "kind": "simulation",
                    "title": title or "정책 비교",
                    "facts": snapshot["facts"],
                },
                "Growth Lab",
                {"period": ui.period_label(cur)},
                simulation=payload,
                status="전략 선정",
            )
        else:
            store.update_problem(
                pid, title=title or "정책 비교", simulation=payload, status="전략 선정"
            )
        st.session_state.growth_open_id = pid
        st.rerun()
    st.download_button(
        "현재 비교 JSON 내려받기",
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        file_name="growth_simulation.json",
        mime="application/json",
    )
    with st.expander("선택 기능 · 실험 설계와 결과 검토"):
        if record:
            sessions = M.in_period(m["sessions"], "start", *cur)
            growth_experiment.render(record, sessions, (cur[1] - cur[0]).days)
        else:
            st.info("비교안을 저장하면 실험 설계를 이어서 작성할 수 있습니다.")


def restore_period(saved):
    st.session_state.period_mode = "직접 선택"
    st.session_state.period_range = (
        pd.Timestamp(saved["start"]).date(),
        (pd.Timestamp(saved["end"]) - pd.Timedelta(days=1)).date(),
    )


main()

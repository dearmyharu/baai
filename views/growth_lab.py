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
    ledger = prepared["ledger"].loc[prepared["ledger"].target]

    def number(field, label, maximum=1e8, minimum=0.0, help=None):
        cfg[field] = st.number_input(
            label, float(minimum), float(maximum),
            min(float(maximum), float(default[field])),
            key=f"{prefix}_{field}", help=help,
        )

    if policy == "price":
        prices = price_table(prepared)
        st.caption("선택 기간에 실제 판매된 쿠폰 차감 전 가격입니다. 새 가격은 직접 입력하세요.")
        target_key = hashlib.sha256(prices.to_json().encode()).hexdigest()[:10]
        if len(prices) == 1:
            pid = str(prices.index[0])
            row = prices.iloc[0]
            st.markdown(f"**{row['상품']}**")
            st.metric("최근 판매가격", ui.won(row["최근 판매가격 (원)"], short=False))
            value = st.number_input(
                "변경할 판매가격 (원)", 0.0, 1e8,
                float(default["price_overrides"].get(pid, row["최근 판매가격 (원)"] * (1 + default["price_change_pct"] / 100))),
                key=f"{prefix}_price_{target_key}",
            )
            # An untouched latest-price field must preserve historical price variation.
            cfg["price_overrides"] = {pid: value} if value != row["최근 판매가격 (원)"] else {}
            cfg["price_change_pct"] = 0.0
            if default["price_change_pct"] and value == row["최근 판매가격 (원)"] * (1 + default["price_change_pct"] / 100):
                cfg["price_overrides"] = {}
                cfg["price_change_pct"] = default["price_change_pct"]
        else:
            mode = st.radio("가격 입력 방법", ["전체 같은 비율로 변경", "상품별 가격 입력"],
                            index=1 if default["price_overrides"] else 0,
                            key=f"{prefix}_price_mode", horizontal=True)
            if mode == "전체 같은 비율로 변경":
                cfg["price_overrides"] = {}
                number("price_change_pct", "선택 상품 가격 변화 (%)", 1000, -100,
                       "예: 5는 5% 인상, -5는 5% 인하입니다.")
            else:
                prices["변경 가격 (원)"] = [default["price_overrides"].get(str(k), v)
                                            for k, v in zip(prices.index, prices["최근 판매가격 (원)"])]
                edited = st.data_editor(
                    prices.reset_index()[["product_id", "상품", "최근 판매가격 (원)", "변경 가격 (원)"]],
                    hide_index=True, width="stretch", key=f"{prefix}_prices_{target_key}",
                    disabled=["product_id", "상품", "최근 판매가격 (원)"],
                    column_config={"product_id": None,
                        "상품": st.column_config.TextColumn(width="small"),
                        "변경 가격 (원)": st.column_config.NumberColumn(min_value=0, format="%.0f", required=True)},
                )
                cfg["price_overrides"] = {str(r["product_id"]): float(r["변경 가격 (원)"])
                    for _, r in edited.iterrows() if pd.notna(r["변경 가격 (원)"])
                    and r["변경 가격 (원)"] != r["최근 판매가격 (원)"]}
                cfg["price_change_pct"] = 0.0
        with st.expander("현재 상품원가·판매가격 범위 확인"):
            st.dataframe(prices.drop(columns=["변경 가격 (원)"], errors="ignore"), width="stretch")
    elif policy == "discount":
        rate = ledger.discount.sum() / ledger.gross.sum() * 100 if ledger.gross.sum() else 0
        st.metric("현재 대상 주문의 실질 쿠폰 할인율", f"{rate:.2f}%")
        st.caption("위 비율은 실제 차감된 할인액 비중입니다. 쿠폰에 설정된 할인율과 다를 수 있습니다.")
        st.info("주문 쿠폰은 선택 상품을 포함한 주문의 상품금액 전체에 적용합니다. 기존 쿠폰을 교체합니다.")
        cfg["discount_type"] = st.selectbox("할인 방식", ["rate", "fixed"],
            index=["rate", "fixed"].index(default["discount_type"]),
            format_func=lambda x: "할인율 (%)" if x == "rate" else "할인액 (원)", key=f"{prefix}_discount_type")
        cfg["discount_value"] = st.number_input(
            "변경 할인율 (%)" if cfg["discount_type"] == "rate" else "변경 할인액 (원)",
            0.0, 100.0 if cfg["discount_type"] == "rate" else 1e8,
            min(float(default["discount_value"]), 100.0) if cfg["discount_type"] == "rate" else float(default["discount_value"]),
            key=f"{prefix}_discount_value_{cfg['discount_type']}",
        )
        number("minimum_order", "쿠폰 최소 주문금액 (원)", help="0원은 최소금액 제한 없음입니다.")
        number("discount_cap", "최대 할인액 (원)", help="0원은 최대 할인액 제한 없음입니다.")
        number("adoption_pct", "쿠폰 적용 주문 비중 (%)", 100,
               help="100%는 대상 주문 모두에 적용한다는 가정입니다.")
        st.caption("0%·0원 할인은 기존 쿠폰 제거입니다. 최소금액 미달 주문은 새 할인이 0원입니다.")
    elif policy == "shipping":
        st.metric("현재 주문당 평균 고객 부담 배송비", ui.won(ledger.shipping_income.mean(), short=False))
        st.caption("현재 무료배송 기준은 주문 이력만으로 확정할 수 없습니다.")
        number("shipping_fee", "변경 고객 부담 배송비 (원)")
        number("free_shipping_threshold", "변경 무료배송 기준 (원)",
               help="쿠폰 차감 후 주문 상품금액 기준입니다.")
        st.caption("무료배송 기준 0원 = 대상 주문 모두 무료배송. 배송비 수입과 판매자의 배송 원가는 별개입니다.")
    elif policy == "benefit":
        st.caption("적립금·사은품 등 현재 정책에 더할 판매자 부담 비용을 입력하세요.")
        number("benefit_amount", "추가 혜택 원가 (원/사용 주문)")
        number("adoption_pct", "혜택 사용 주문 비중 (%)", 100)
    elif policy == "bundle":
        st.caption("선택한 구성 상품을 모두 담은 기존 주문에 추가 할인을 적용합니다.")
        number("bundle_discount_pct", "묶음 추가 할인율 (%)", 100)
    else:
        st.caption("상세페이지·노출 개선 등으로 주문 수가 달라지는 상황을 아래에서 가정하세요.")

    st.markdown("**판매량은 어떻게 가정할까요?**")
    st.caption("할인이나 가격 변경으로 실제 주문이 얼마나 달라질지는 아직 알 수 없습니다.")
    number("order_change_pct", "대상 주문 수 변화 가정 (%)", 1000, -100,
           "모르면 0으로 두세요. 0%는 주문 수 유지, 10%는 10% 증가, -10%는 10% 감소 가정입니다.")
    st.caption(S.assumption_text(cfg))
    with st.expander("추가 실행비 입력 (선택)"):
        number("fixed_cost", "추가 실행비 (원)", help="분석 기간 전체에서 한 번 차감하는 제작·캠페인 비용입니다.")
    return cfg


def reset_comparison():
    for key in list(st.session_state):
        if key.startswith("sim_new") or key in ("sim_record", "growth_context", "growth_open_id"):
            del st.session_state[key]
    st.session_state.sim_record = "new"


def request_signature(start, end, scope, costs, configs):
    return hashlib.sha256(json.dumps([str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date()),
        scope, costs, [S.normalize_config(c) for c in configs]], sort_keys=True, default=str).encode()).hexdigest()


def render_cards(results, whole_shop=False):
    tables = [S.comparison(r, whole_shop) for r in results]
    labels = ["현재", "변경안 A" if len(results) > 1 else "변경 후"] + (["변경안 B"] if len(results) > 1 else [])
    values = [tables[0].set_index("지표")["현재"]] + [t.set_index("지표")["변경안"] for t in tables]
    for box, label, value in zip(st.columns(len(labels)), labels, values):
        with box.container(border=True):
            st.markdown(f"**{label}**")
            for key, title in (("revenue", "매출 (배송비 포함)"), ("profit", "입력한 비용 차감 후 이익")):
                metric = S.LABELS[key]
                st.metric(title, ui.won(value[metric], short=False),
                    None if label == "현재" else ui.won(value[metric] - values[0][metric], short=False))
            st.caption(f"주문 수 {value[S.LABELS['orders']]:,.1f}건")
    table = tables[0][["지표", "현재"]].copy()
    for label, t in zip(["A", "B"], tables):
        table[f"변경안 {label}"] = t["변경안"]
        table[f"{label} 차이"] = t["차이"]
    return table


def main():
    st.session_state.pop("growth_context", None)
    m = ui.get_mart()
    cur, _ = ui.period_controls()
    st.title("Growth Lab")
    st.caption("정책을 실행하기 전에, 입력한 가정에 따른 매출·비용·이익을 비교하는 곳입니다.")
    st.button("새 비교 시작", on_click=reset_comparison)
    if st.session_state.pop("growth_saved", False):
        st.success("비교 기록을 저장했습니다. 위의 ‘저장한 비교’에서 다시 열 수 있습니다.")
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
            st.markdown(f"**{record.get('title', '저장한 비교')}**")
            observed = record.get("observed") or {}
            for fact in observed.get("facts", [])[:5]:
                st.write("• " + str(fact))
            for field in ("definition", "hypotheses", "strategies"):
                if record.get(field):
                    with st.expander({"definition": "기존 문제 정의", "hypotheses": "기존 가설", "strategies": "기존 전략"}[field]):
                        value = record[field]
                        if isinstance(value, list):
                            st.dataframe(pd.DataFrame(value), hide_index=True, width="stretch")
                        else:
                            st.write(value)
            if saved:
                saved_label = ui.period_label((pd.Timestamp(saved['start']), pd.Timestamp(saved['end'])))
                st.caption("저장한 분석 기간 · " + saved_label)
                st.caption("저장한 정책 · " + " / ".join(S.POLICIES.get(c.get('policy'), '정책') for c in saved.get('scenarios', [])))
                if saved.get("decision"):
                    st.write("메모: " + saved["decision"])
                if (pd.Timestamp(saved['start']), pd.Timestamp(saved['end'])) != cur:
                    st.warning("현재 조회 기간과 저장한 기간이 다릅니다. 저장한 결과를 재현하려면 기간도 적용하세요.")
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
    sold = M.completed_orders(m, *cur)
    sales = m["items"][m["items"].order_id.isin(sold.order_id)]
    counts = sales.groupby("product_id").order_id.nunique().to_dict()
    available = available.copy()
    available["_orders"] = available.product_id.map(counts).fillna(0)
    available = available.sort_values(["_orders", "product_name"], ascending=[False, True])
    names = available.set_index("product_id").product_name.to_dict()
    id_key = f"{prefix}_products"
    if id_key not in st.session_state:
        st.session_state[id_key] = [x for x in source.get("product_ids", []) if x in names]
    else:
        st.session_state[id_key] = [x for x in st.session_state[id_key] if x in names]
    ids = st.multiselect(
        "세부 상품 선택 (비우면 선택 상품군 전체)",
        list(names),
        format_func=lambda x: f"{names[x]} · {counts.get(x, 0):,}주문",
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
        if "완료 주문이 없습니다" not in str(exc):
            st.error("기준 데이터에 문제가 있어 계산할 수 없습니다. 아래 내용을 확인해 주세요.")
            st.caption(str(exc))
            return
        st.info(
            "이 기간·대상에 계산할 판매 내역이 없습니다. 상품이나 기간을 다시 선택해 주세요."
        )
        st.caption(str(exc))
        candidates = available[available._orders.gt(0)].head(3)
        if not candidates.empty:
            st.write("이 기간에 판매 내역이 있는 상품으로 다시 시작해 보세요.")
            for _, row in candidates.iterrows():
                st.button(f"{row.product_name} · {int(row._orders):,}주문 선택",
                    key=f"{prefix}_suggest_{row.product_id}", on_click=select_product,
                    args=(id_key, row.product_id))
        st.caption("또는 왼쪽 ‘분석 월’을 바꿔 주세요.")
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
    if initial['ledger'].target.sum() < 30:
        st.warning("선택 대상의 완료 주문이 30건 미만입니다. 계산은 가능하지만 고객 반응의 근거로 쓰기에는 적습니다.")
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
        shown = shown[columns].copy()
        if "discount_type" in shown:
            shown["discount_type"] = shown["discount_type"].replace({"FIXED": "정액 할인", "RATE": "정률 할인", "PERCENT": "정률 할인", "fixed": "정액 할인", "rate": "정률 할인"})
        st.dataframe(
            shown.rename(
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
    config_a = policy_inputs(configs[0], f"{prefix}_a_{policy}", prepared, policy)
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
            config_b = policy_inputs(configs[1], f"{prefix}_b_{bp}", prepared, bp)
    configs_now = [config_a] + ([config_b] if extra else [])
    signature = request_signature(*cur, scope, costs, configs_now)
    calculate = st.button("결과 확인", type="primary", key=f"{prefix}_calculate")
    st.subheader("4. 결과 비교")
    if calculate:
        st.session_state[f"{prefix}_calculated"] = signature
    if st.session_state.get(f"{prefix}_calculated") != signature:
        st.info("변경값과 주문 수 가정을 확인한 뒤 ‘결과 확인’을 눌러 주세요. 입력을 바꾸면 다시 계산해야 합니다.")
        return
    try:
        results = [S.simulate(prepared, c) for c in configs_now]
    except (ValueError, KeyError) as exc:
        st.warning(str(exc))
        return
    st.markdown("**선택 상품이 포함된 주문의 결과**")
    st.caption("함께 구매한 다른 상품과 고객 부담 배송비를 포함합니다. 선택 상품만의 매출은 1단계에서 확인할 수 있습니다.")
    for label, cfg in zip(["A", "B"], configs_now):
        st.info((f"변경안 {label} · " if extra else "") + S.assumption_text(cfg))
    missing = [label for key, label in (("shipping_per_order", "배송 원가"), ("fee_pct", "결제 수수료"),
               ("other_per_order", "기타 주문당 비용")) if costs[key] == 0]
    if missing:
        st.warning("0원으로 두어 차감하지 않은 비용: " + ", ".join(missing) + ". 실제 순이익과 다를 수 있습니다.")
    st.caption("상품원가는 자동 반영합니다. 고정 운영비·세금·재고 제약은 포함하지 않습니다.")
    table = render_cards(results)
    with st.expander("대상 주문의 매출·할인·비용 상세"):
        st.dataframe(table, hide_index=True, width="stretch")
    with st.expander("전체 쇼핑몰에 미치는 영향 보기"):
        st.caption("선택 대상 밖의 주문은 그대로 유지한 전체 쇼핑몰 합계입니다.")
        shop_table = render_cards(results, whole_shop=True)
        st.dataframe(shop_table, hide_index=True, width="stretch")
    chosen = (
        st.radio("검토할 안", ["A", "B"], horizontal=True,
                 index=0 if saved.get("selected", "A") == "A" else 1, key=f"{prefix}_selected")
        if extra
        else "A"
    )
    result = results[0 if chosen == "A" else 1]
    st.caption(
        f"선택 범위 {int(result['scope_baseline']['orders']):,}주문 · 선택안 적용 대상 {result['target_orders']:,}주문 · {result['target_buyers']:,}고객"
    )
    required = result["required_order_change"]
    if required is None:
        st.warning(
            "변경 후 대상 주문당 이익이 0 이하입니다. 정책·비용 구조를 먼저 검토하세요."
        )
    else:
        if abs(required) < 0.00005:
            st.info("입력한 비용 기준으로 주문 수가 유지되면 현재 이익을 유지합니다.")
        elif required > 0:
            st.info(f"현재 이익을 유지하려면 대상 주문이 {required*100:.2f}% 이상 늘어야 합니다. 실제로 늘어날지는 별도 확인이 필요합니다.")
        else:
            st.info(f"계산상 대상 주문이 최대 {abs(required)*100:.2f}% 줄어도 현재 이익을 유지합니다. 실제 고객 반응을 예측한 값은 아닙니다.")
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
        display_scope="target_orders",
    )
    st.session_state.growth_context = snapshot
    st.caption("결과가 궁금하면 AI 분석가를 열고 “왜 이익이 달라졌어?”라고 물어보세요.")
    with st.form(f"{prefix}_save"):
        title = st.text_input(
            "비교 기록 이름", (record or {}).get("title", "정책 시뮬레이션 비교")
        )
        reason = st.text_area("선택 이유·다음 행동", saved.get("decision", ""))
        copy_record = st.checkbox("원본을 유지하고 새 비교 기록으로 저장", value=True) if record else False
        save = st.form_submit_button("비교안과 판단 저장", type="primary")
    if save:
        payload = {**snapshot, "decision": reason}
        pid = selected
        if record is None or copy_record:
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
        st.session_state.growth_saved = True
        st.session_state[f"sim_{pid}_calculated"] = signature
        st.rerun()
    with st.expander("계산 기준·개발용 파일 내려받기"):
        st.download_button("현재 비교 파일 내려받기", json.dumps(snapshot, ensure_ascii=False, indent=2),
                           file_name="growth_simulation.json", mime="application/json")
    with st.expander("선택 기능 · 실험 설계와 결과 검토"):
        if record:
            sessions = M.in_period(m["sessions"], "start", *cur)
            growth_experiment.render(record, sessions, (cur[1] - cur[0]).days)
        else:
            st.info("비교안을 저장하면 실험 설계를 이어서 작성할 수 있습니다.")


def select_product(key, product_id):
    st.session_state[key] = [product_id]


def restore_period(saved):
    st.session_state.period_mode = "직접 선택"
    st.session_state.period_range = (
        pd.Timestamp(saved["start"]).date(),
        (pd.Timestamp(saved["end"]) - pd.Timedelta(days=1)).date(),
    )


main()

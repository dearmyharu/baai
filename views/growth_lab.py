"""Growth Lab: policy scenarios with optional experiment planning."""
from __future__ import annotations

import json

import altair as alt
import pandas as pd
import streamlit as st

from core import growth_experiment, metrics as M, simulation as S, store, ui


def policy_inputs(config, prefix):
    default = S.normalize_config(config)
    cfg = dict(default)
    cfg['policy'] = st.selectbox('정책', list(S.POLICIES), index=list(S.POLICIES).index(default['policy']),
                                 format_func=S.POLICIES.get, key=f'{prefix}_policy')

    def number(key, label, low=0.0, high=1e8, help=None):
        cfg[key] = st.number_input(label, float(low), float(high), min(float(high), float(default[key])),
                                    key=f'{prefix}_{key}', help=help)

    policy = cfg['policy']
    if policy == 'price':
        number('price_change_pct', '선택 상품 가격 변화 (%)', -100, 1000,
               '관측된 쿠폰 차감 전 상품금액을 증감합니다. 0%는 현재 가격입니다.')
    elif policy == 'discount':
        cfg['discount_type'] = st.selectbox('새 쿠폰 방식', ['rate', 'fixed'],
            index=['rate', 'fixed'].index(default['discount_type']),
            format_func=lambda x: '정률 (%)' if x == 'rate' else '정액 (원)', key=f'{prefix}_discount_type')
        number('discount_value', '새 할인율 (%)' if cfg['discount_type'] == 'rate' else '새 할인액 (원)',
               high=100 if cfg['discount_type'] == 'rate' else 1e8)
        number('minimum_order', '최소 주문 상품금액 (원)')
        number('discount_cap', '최대 할인액 (원, 0은 상한 없음)')
        number('adoption_pct', '새 쿠폰 적용 주문 비중 (%)', high=100,
               help='대상 주문의 해당 비중에서 기존 주문 쿠폰을 새 쿠폰으로 교체합니다.')
    elif policy == 'shipping':
        number('shipping_fee', '고객 부담 배송비 (원)')
        number('free_shipping_threshold', '무료배송 기준 (원)', help='쿠폰 차감 후 상품금액 기준. 0원은 전체 무료배송입니다.')
    elif policy == 'benefit':
        number('benefit_amount', '사용 주문당 추가 혜택 원가 (원)', help='적립금·사은품 등의 판매자 부담 비용입니다.')
        number('adoption_pct', '혜택 사용 주문 비중 (%)', high=100)
    elif policy == 'bundle':
        number('bundle_discount_pct', '선택 상품 묶음 추가 할인율 (%)', high=100)
        st.caption('대상 상품을 2개 이상 고르세요. 구성 상품을 모두 담은 기존 주문에 적용합니다.')
    else:
        st.caption('노출·클릭·상세페이지 개선을 대상 주문 변화 가정과 추가 실행비로 비교합니다.')
    number('order_change_pct', '대상 주문 수 변화 가정 (%)', -100, 1000,
           '구매 행동에 대한 직접 입력 가정입니다. 다른 전환율을 추가로 곱하지 않습니다.')
    number('fixed_cost', '추가 실행비 (원)', help='분석 기간 전체에서 한 번 차감하는 제작·캠페인 비용입니다.')
    return cfg


def main():
    m = ui.get_mart()
    cur, _ = ui.period_controls()
    st.title('Growth Lab')
    st.caption('정책을 바꾸고 매출·비용·이익을 비교하세요. 고객 반응은 직접 조정하는 가정입니다.')
    if store.db_error():
        st.warning('공유 저장소에 연결하지 못해 현재 실행 환경의 파일에 저장합니다. ' + store.db_error())
    st.caption('저장 위치 · ' + ('팀 공유 DB' if store.backend() == 'db' else '현재 실행 환경 파일'))
    records = {p['id']: p for p in reversed(store.load()['problems'])}
    pending = st.session_state.pop('growth_open_id', None)
    if pending in records:
        st.session_state.sim_record = pending
    if st.session_state.get('sim_record') not in [None, 'new', *records]:
        st.session_state.sim_record = 'new'
    selected = st.selectbox('분석 근거·저장한 비교 불러오기', ['new', *records], key='sim_record',
        format_func=lambda x: '새 정책 비교 시작' if x == 'new' else f"{records[x]['title']} · {records[x]['status']}")
    record = records.get(selected)
    saved = (record or {}).get('simulation') or {}
    prefix = f'sim_{selected}'
    st.caption('분석 기간 · ' + ui.period_label(cur))
    if record:
        with st.expander('저장한 분석 근거·이전 가설·전략 기록'):
            st.write(record.get('observed', {}))
            for field, label in [('definition', '문제 정의'), ('hypotheses', '가설'), ('strategies', '전략·ICE')]:
                if record.get(field):
                    st.markdown(f'**{label}**')
                    st.write(record[field])
            if saved:
                st.caption(f"저장 기간 {saved.get('start')} ~ {saved.get('end')} (끝 다음 날 미포함). 현재 결과는 사이드바 기간으로 재계산합니다.")
                st.button('저장 기간 적용', key=f'restore_{selected}', on_click=restore_period, args=(saved,))
            st.download_button('기존 기록 JSON 내려받기', json.dumps(record, ensure_ascii=False, indent=2),
                               file_name=f'growth_{selected}.json', mime='application/json')
    source = saved.get('scope') or {}
    if not saved and record:
        observed = record.get('observed') or {}
        source = {k: observed[k] for k in ('theme_id', 'coupon_id') if observed.get(k)}
        if observed.get('product_id'):
            source['product_ids'] = [observed['product_id']]
        calls = observed.get('calls') or []
        if calls and calls[0].get('params', {}).get('filters'):
            source['filters'] = calls[0]['params']['filters']
    with st.expander('적용 대상·반영 비용', expanded=True):
        a, b = st.columns(2)
        products = m['raw']['product']
        cats = sorted(products.category.dropna().unique())
        names = products.set_index('product_id').product_name.to_dict()
        categories = a.multiselect('대상 카테고리 (비우면 전체)', cats,
            default=[x for x in source.get('categories', []) if x in cats], key=f'{prefix}_categories')
        ids = b.multiselect('대상 상품·묶음 구성 (비우면 전체)', list(names),
            default=[x for x in source.get('product_ids', []) if x in names],
            format_func=lambda x: f'{x} · {names[x]}', key=f'{prefix}_products')
        themes = m['raw']['curation_theme'].set_index('theme_id').theme_name.to_dict()
        coupons = m['raw']['coupon'].set_index('coupon_id').coupon_name.to_dict()
        theme_options, coupon_options = ['', *themes], ['', 'NO_COUPON', *coupons]
        theme = a.selectbox('대상 테마', theme_options,
            index=theme_options.index(source.get('theme_id', '')) if source.get('theme_id', '') in theme_options else 0,
            format_func=lambda x: themes.get(x, '전체'), key=f'{prefix}_theme')
        coupon = b.selectbox('기존 사용 쿠폰으로 대상 제한', coupon_options,
            index=coupon_options.index(source.get('coupon_id', '')) if source.get('coupon_id', '') in coupon_options else 0,
            format_func=lambda x: coupons.get(x, '쿠폰 미사용' if x == 'NO_COUPON' else '전체'), key=f'{prefix}_coupon')
        original_filters = source.get('filters') or {}
        gender_options = ['', 'F', 'M']
        gender = a.selectbox('고객 성별', gender_options, index=gender_options.index(original_filters.get('gender', '')),
            format_func=lambda x: {'': '전체', 'F': '여성', 'M': '남성'}[x], key=f'{prefix}_gender')
        grades = b.multiselect('주문 당시 고객 등급', ['BRONZE', 'SILVER', 'GOLD', 'VIP'],
                               default=original_filters.get('grades', []), key=f'{prefix}_grades')
        filters = {k: v for k, v in original_filters.items() if k not in ('gender', 'grades', 'grade_basis')}
        if gender:
            filters['gender'] = gender
        if grades:
            filters.update(grades=grades, grade_basis='당시')
        if filters:
            st.caption('고객 조건 · ' + M.describe_filters(M.clean_filters(filters), cur))
        scope = dict(categories=categories, product_ids=ids, theme_id=theme, coupon_id=coupon, filters=filters)
        c = S.DEFAULT_COSTS | saved.get('costs', {})
        a, b, d = st.columns(3)
        costs = dict(
            shipping_per_order=a.number_input('주문당 배송 원가 (원)', 0.0, 1e7, float(c['shipping_per_order']), key=f'{prefix}_shipping_cost'),
            fee_pct=b.number_input('결제 수수료율 (%)', 0.0, 100.0, float(c['fee_pct']), key=f'{prefix}_fee'),
            other_per_order=d.number_input('기타 주문당 변동비 (원)', 0.0, 1e7, float(c['other_per_order']), key=f'{prefix}_other'))
        st.caption('0인 비용은 추가 차감하지 않습니다. 비용 기준은 현재와 변경안에 동일하게 적용합니다.')
    configs = (saved.get('scenarios', []) + [{}, {}])[:2]
    pending = st.session_state.pop('growth_pending_scenario', None)
    if pending:
        for key, value in S.normalize_config(pending).items():
            st.session_state[f'{prefix}_a_{key}'] = value
        st.info('AI가 계산한 정책을 변경안 A에 불러왔습니다. 대상·기간·비용도 확인하세요.')
    st.subheader('정책과 고객 반응 가정')
    left, right = st.columns(2)
    with left:
        st.markdown('**변경안 A**')
        config_a = policy_inputs(configs[0], f'{prefix}_a')
    with right:
        st.markdown('**변경안 B**')
        config_b = policy_inputs(configs[1], f'{prefix}_b')
    try:
        prepared = S.prepare(m, *cur, scope, costs)
        results = [S.simulate(prepared, config_a), S.simulate(prepared, config_b)]
    except (ValueError, KeyError) as exc:
        st.session_state.pop('growth_context', None)
        st.warning(str(exc))
        return
    baseline = results[0]['baseline']
    st.subheader('현재와 비교')
    for box, label, value in zip(st.columns(3), ['현재', '변경안 A', '변경안 B'], [baseline, results[0]['changed'], results[1]['changed']]):
        with box.container(border=True):
            st.markdown(f'**{label}**')
            st.metric('완료 매출', ui.won(value['revenue'], short=False),
                      None if label == '현재' else ui.won(value['revenue']-baseline['revenue'], short=False))
            st.metric('반영 비용 차감 이익', ui.won(value['profit'], short=False),
                      None if label == '현재' else ui.won(value['profit']-baseline['profit'], short=False))
            st.caption(f"주문 수 {value['orders']:,.1f}건")
    table = results[0]['table'][['지표', '현재']].copy()
    for label, result in zip(['A', 'B'], results):
        table[f'변경안 {label}'] = result['table']['변경안']
        table[f'{label} 차이'] = result['table']['차이']
    st.dataframe(table, hide_index=True, width='stretch')
    chosen = st.radio('검토할 안', ['A', 'B'], horizontal=True,
                       index=0 if saved.get('selected', 'A') == 'A' else 1, key=f'{prefix}_selected')
    result = results[0 if chosen == 'A' else 1]
    st.caption(f"전체 쇼핑몰 결과입니다. 선택안 적용 대상 {result['target_orders']:,}주문 · {result['target_buyers']:,}고객")
    required = result['required_order_change']
    if required is None:
        st.warning('변경 후 대상 주문당 이익이 0 이하입니다. 정책·비용 구조를 먼저 검토하세요.')
    else:
        st.info(f"기존 이익 유지에 필요한 대상 주문 변화 {required*100:+.2f}% · 입력한 가정 {result['config']['order_change_pct']:+g}%")
    with st.expander('대상·비용별 상세와 계산 기준'):
        st.dataframe(pd.DataFrame([{'범위': '대상 현재', **result['target_baseline']},
            {'범위': '대상 변경 (추가 실행비 제외)', **result['target_changed']},
            {'범위': '대상 밖 공통', **result['outside']}]).rename(columns=S.LABELS), hide_index=True, width='stretch')
        for note in result['notes']:
            st.caption(note)
        st.caption('추가 실행비는 전체에서 한 번 차감합니다. 주문 수는 기대값이므로 소수일 수 있습니다.')
    with st.expander('주문 반응에 따른 민감도', expanded=True):
        sensitivity = S.sensitivity(prepared, result['config'])
        st.altair_chart(alt.Chart(sensitivity).mark_line(point=True, color=ui.C_MAIN).encode(
            x=alt.X('주문 변화 가정 (%):Q'), y=alt.Y('반영 비용 차감 이익:Q', axis=alt.Axis(format='~s')),
            tooltip=list(sensitivity.columns)), width='stretch')
        st.caption('현재 가정의 전후 10%p와 변화 0% 비교입니다. 시나리오 민감도이며 통계적 신뢰구간과 구분합니다.')
    snapshot = dict(version=S.VERSION, start=prepared['start'], end=prepared['end'], scope=scope, costs=costs,
        scenarios=[config_a, config_b], selected=chosen, facts=S.evidence(prepared, result), notes=result['notes'],
        comparison=table.to_dict('records'))
    st.session_state.growth_context = snapshot
    st.subheader('AI와 검토하기')
    st.caption('AI는 정책 후보·확인할 가정을 제안하고 계산 결과를 설명합니다. 정책값을 검토한 뒤 적용하세요.')
    if st.button('이 비교안의 손익과 확인할 가정 설명', key=f'{prefix}_ai'):
        st.session_state.pending_q = '현재 Growth Lab 비교안을 설명하고 손익 유지 조건과 실행 전에 확인할 가정을 알려줘.'
        st.session_state.active_dash = None
        st.rerun()
    with st.form(f'{prefix}_save'):
        title = st.text_input('비교 기록 이름', (record or {}).get('title', '정책 시뮬레이션 비교'))
        reason = st.text_area('선택 이유·다음 행동', saved.get('decision', ''))
        save = st.form_submit_button('비교안과 판단 저장', type='primary')
    if save:
        payload = {**snapshot, 'decision': reason}
        pid = selected
        if record is None:
            pid = store.add_problem({'kind': 'simulation', 'title': title or '정책 비교', 'facts': snapshot['facts']},
                                     'Growth Lab', {'period': ui.period_label(cur)}, simulation=payload, status='전략 선정')
        else:
            store.update_problem(pid, title=title or '정책 비교', simulation=payload, status='전략 선정')
        st.session_state.growth_open_id = pid
        st.rerun()
    st.download_button('현재 비교 JSON 내려받기', json.dumps(snapshot, ensure_ascii=False, indent=2),
                       file_name='growth_simulation.json', mime='application/json')
    with st.expander('선택 기능 · 실험 설계와 결과 검토'):
        if record:
            sessions = M.in_period(m['sessions'], 'start', *cur)
            growth_experiment.render(record, sessions, (cur[1]-cur[0]).days)
        else:
            st.info('비교안을 저장하면 실험 설계를 이어서 작성할 수 있습니다.')


def restore_period(saved):
    st.session_state.period_mode = '직접 선택'
    st.session_state.period_range = (pd.Timestamp(saved['start']).date(), (pd.Timestamp(saved['end']) - pd.Timedelta(days=1)).date())


main()

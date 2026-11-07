"""Optional conversion experiment planning after a policy comparison."""
import math

import pandas as pd
import streamlit as st

from . import metrics as M, store


def render(record, sessions, days):
    pid = record['id']
    ex = record.get('experiment') or {}
    st.caption('표본 계산은 세션 구매 전환율 기준입니다. 매출·이익 실험은 별도 설계가 필요합니다.')
    st.caption('기본 전환율·유입 규모는 기간 내 전체 로그인 세션입니다. 실제 실험 대상에 맞게 수정하세요.')
    with st.form(f'plan_{pid}'):
        name = st.text_input('실험명', ex.get('name', '선택 정책 검증'))
        treatment = st.text_area('실험군 변경 내용', ex.get('treatment', ''))
        control = st.text_area('대조군 정책', ex.get('control', '현재 정책 유지'))
        a, b = st.columns(2)
        rate = float(sessions.has_purchase.mean()) if len(sessions) else 0.2
        p0 = a.number_input('기준 구매 전환율 (%)', 0.01, 99.99,
                            min(99.99, max(0.01, float(ex.get('baseline', rate)) * 100))) / 100
        lift = b.number_input('최소 검출 효과 (상대 %)', 0.1, 200.0, float(ex.get('mde', 10)))
        daily = a.number_input('일평균 실험 대상 세션', 0.0, 1e7, float(ex.get('daily', len(sessions) / max(days, 1))))
        alpha = b.selectbox('유의수준', [0.05, 0.1, 0.01], index=[0.05, 0.1, 0.01].index(ex.get('alpha', 0.05)))
        power = a.selectbox('검정력', [0.8, 0.9], index=[0.8, 0.9].index(ex.get('power', 0.8)))
        stop = st.text_input('함께 확인할 지표·중단 기준', ex.get('stop', '주문당 이익·취소환불·고객 불만 확인'))
        save = st.form_submit_button('실험 설계 저장')
    n = M.sample_size_per_group(p0, lift / 100, alpha, power)
    valid = pd.notna(n) and daily > 0
    duration = math.ceil(n * 2 / daily) if valid else None
    if valid:
        st.info(f'그룹당 {n:,}세션 · 총 {2*n:,}세션 · 약 {duration:,}일 (두 그룹에 반씩 배정)')
        if duration > 60:
            st.warning('60일이 넘습니다. 대상 확대·검출 효과·실험안을 검토하세요.')
    else:
        st.warning('전환율·개선폭·일평균 대상을 확인하세요.')
    if save and valid:
        store.update_problem(pid, experiment={**ex, 'name': name, 'treatment': treatment, 'control': control,
            'baseline': p0, 'mde': lift, 'daily': daily, 'alpha': alpha, 'power': power,
            'metric': '세션 구매 전환율', 'unit': '세션', 'stop': stop, 'n_per_group': n, 'duration_days': duration},
            status='실험 설계 완료')
        st.success('실험 설계를 저장했습니다.')
    with st.expander('실험 결과·기존 결과 확인'):
        res = ex.get('result') or {}
        with st.form(f'result_{pid}'):
            mock = st.checkbox('모의 결과', value=res.get('mock', True))
            a, b = st.columns(2)
            na = a.number_input('대조군 대상 수', 0, 10_000_000, int(res.get('na', 0)))
            xa = a.number_input('대조군 구매 수', 0, 10_000_000, int(res.get('xa', 0)))
            nb = b.number_input('실험군 대상 수', 0, 10_000_000, int(res.get('nb', 0)))
            xb = b.number_input('실험군 구매 수', 0, 10_000_000, int(res.get('xb', 0)))
            options = ['미정', '도입', '수정 후 재실험', '중단']
            decision = st.selectbox('판단', options, index=options.index(res.get('decision', '미정')))
            save = st.form_submit_button('결과 저장')
        valid = na > 0 and nb > 0 and xa <= na and xb <= nb
        if valid:
            pa, pb = xa / na, xb / nb
            _, p = M.two_prop_test(xb, nb, xa, na)
            se = math.sqrt(pa * (1-pa) / na + pb * (1-pb) / nb)
            st.write(f"{'모의' if mock else '입력된 실험'} 결과 · {pa:.2%} → {pb:.2%} · p={p:.4f}")
            st.caption(f'차이의 95% 신뢰구간 {(pb-pa-1.96*se)*100:+.2f}%p ~ {(pb-pa+1.96*se)*100:+.2f}%p. 비용·이익도 함께 확인하세요.')
        if save:
            if not valid:
                st.error('대상 수는 양수, 구매 수는 대상 수 이하여야 합니다.')
            else:
                current = store.get_problem(pid)
                if current:
                    store.update_problem(pid, experiment={**(current.get('experiment') or {}), 'result': {
                        'mock': mock, 'na': na, 'xa': xa, 'nb': nb, 'xb': xb, 'decision': decision}})
                    st.success('결과를 저장했습니다.')

"""Policy replay regressions. Run python -m unittest eval.test_simulation -v."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core import metrics as M, simulation as S, store, tools, llm

START, END = pd.Timestamp('2026-09-01'), pd.Timestamp('2026-10-01')


def mart():
    orders = pd.DataFrame([
        ['O1', 'C1', '2026-09-05', 'COMPLETED', 21000, 'VIP', 'T1', 'K1', '첫 구매 고객'],
        ['O2', 'C2', '2026-09-07', 'COMPLETED', 23000, 'BRONZE', 'T2', 'NO_COUPON', '기존 구매 고객'],
        ['O3', 'C2', '2026-09-09', 'CANCELLED', 99999, 'BRONZE', 'T2', 'NO_COUPON', None],
    ], columns=['order_id', 'customer_id', 'order_time', 'order_status', 'total_amount', 'grade_at_order',
                'attributed_theme_id', 'coupon_id', 'customer_type'])
    orders.order_time = pd.to_datetime(orders.order_time)
    items = pd.DataFrame([
        ['O1', 'P1', '식빵', '빵', 1, 30000, 9000, 12000],
        ['O2', 'P2', '우유', '음료', 1, 12000, 0, 5000],
        ['O2', 'P3', '치즈', '유제품', 1, 8000, 0, 3000],
        ['O3', 'P1', '식빵', '빵', 1, 99999, 0, 12000],
    ], columns=['order_id', 'product_id', 'product_name', 'category', 'quantity', 'sales_amount',
                'allocated_coupon_discount', 'cost_price'])
    items = items.merge(orders[['order_id', 'order_time', 'order_status', 'customer_id']], on='order_id')
    items['net_sales'] = items.sales_amount - items.allocated_coupon_discount
    items['contribution'] = items.net_sales - items.quantity * items.cost_price
    customers = pd.DataFrame([
        ['C1', 'F', 1995, '서울특별시', 'DIRECT', 'VIP', pd.Timestamp('2026-04-02')],
        ['C2', 'M', 1985, '경기도', 'EMAIL', 'BRONZE', pd.Timestamp('2026-04-03')],
    ], columns=['customer_id', 'gender', 'birth_year', 'region', 'signup_channel', 'membership_grade', 'signup_date'])
    sessions = pd.DataFrame({'session_id': ['S1', 'S2'], 'customer_id': ['C1', 'C2'],
        'start': pd.to_datetime(['2026-09-05', '2026-09-07']), 'has_purchase': [True, False]})
    history = pd.DataFrame({'customer_id': ['C1', 'C2'], 'effective_from': pd.to_datetime(['2026-04-01']*2),
        'effective_to': pd.to_datetime([None, None]), 'membership_grade': ['VIP', 'BRONZE']})
    return dict(orders=orders, items=items, sessions=sessions, raw={
        'product': items[['product_id', 'product_name', 'category', 'cost_price']].drop_duplicates('product_id'),
        'customer': customers, 'customer_grade_history': history,
        'curation_theme': pd.DataFrame({'theme_id': ['T1', 'T2'], 'theme_name': ['아침', '간식']}),
        'coupon': pd.DataFrame({'coupon_id': ['K1'], 'coupon_name': ['30% 쿠폰']}),
        'event_log': pd.DataFrame({'session_id': ['S1', 'S2']})})


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.m = mart()
        self.base = S.prepare(self.m, START, END)

    def test_identity_matches_completed_order_revenue(self):
        for policy in ['price', 'volume']:
            r = S.simulate(self.base, {'policy': policy})
            self.assertEqual(r['changed'], r['baseline'])
            self.assertEqual(r['baseline']['revenue'], 44000)
            self.assertEqual(r['baseline']['orders'], 2)
            self.assertEqual(r['baseline']['profit'], 24000)

    def test_discount_break_even_and_unchanged_outside(self):
        base = S.prepare(self.m, START, END, {'coupon_id': 'K1'})
        r = S.simulate(base, {'policy': 'discount', 'discount_value': 35})
        self.assertEqual(r['changed']['revenue'], 42500)
        self.assertAlmostEqual(r['required_order_change'], 0.2)
        r = S.simulate(base, {'policy': 'discount', 'discount_value': 35, 'order_change_pct': 20})
        self.assertAlmostEqual(r['changed']['profit'], r['baseline']['profit'])
        self.assertEqual(r['outside']['revenue'], 23000)

    def test_absolute_price_and_no_double_percentage(self):
        prepared = S.prepare(self.m, START, END, {'product_ids': ['P2']})
        result = S.simulate(prepared, {'policy': 'price', 'price_overrides': {'P2': 10000}})
        self.assertEqual(result['changed']['revenue'], 42000)
        self.assertEqual(result['changed']['product_cost'], 20000)
        with self.assertRaises(ValueError):
            S.simulate(prepared, {'policy': 'price', 'price_overrides': {'P2': 10000}, 'price_change_pct': 5})

    def test_minimum_cap_and_adoption(self):
        r = S.simulate(self.base, {'policy': 'discount', 'discount_value': 50, 'discount_cap': 6000,
                                  'minimum_order': 25000, 'adoption_pct': 50})
        self.assertEqual(r['changed']['discount'], 7500)
        r = S.simulate(self.base, {'policy': 'discount', 'discount_type': 'fixed', 'discount_value': 1e6})
        self.assertEqual(r['changed']['net_sales'], 0)

    def test_shipping_and_costs_charged_once(self):
        base = S.prepare(self.m, START, END, costs={'shipping_per_order': 3000, 'fee_pct': 10})
        r = S.simulate(base, {'policy': 'shipping', 'shipping_fee': 3000, 'free_shipping_threshold': 22000, 'fixed_cost': 1000})
        self.assertEqual(r['changed']['shipping_income'], 6000)
        self.assertEqual(r['changed']['shipping_cost'], 6000)
        self.assertEqual(r['changed']['fee'], 4700)
        self.assertEqual(r['changed']['profit'], 15300)

    def test_benefit_usage_and_order_volume(self):
        r = S.simulate(self.base, {'policy': 'benefit', 'benefit_amount': 2000, 'adoption_pct': 50,
                                  'order_change_pct': 20, 'fixed_cost': 1000})
        self.assertEqual(r['changed']['benefit_cost'], 2400)
        self.assertAlmostEqual(r['changed']['profit'], 25400)

    def test_price_target_affects_selected_items_only(self):
        base = S.prepare(self.m, START, END, {'product_ids': ['P2']})
        r = S.simulate(base, {'policy': 'price', 'price_change_pct': 10})
        self.assertEqual(r['changed']['revenue'], 45200)
        self.assertEqual(r['changed']['product_cost'], 20000)

    def test_bundle_requires_all_products(self):
        base = S.prepare(self.m, START, END, {'product_ids': ['P2', 'P3']})
        r = S.simulate(base, {'policy': 'bundle', 'bundle_discount_pct': 10})
        self.assertEqual(r['target_orders'], 1)
        self.assertEqual(r['changed']['revenue'], 42000)
        with self.assertRaises(ValueError):
            S.simulate(self.base, {'policy': 'bundle'})

    def test_zero_orders_loss_and_invalid_values(self):
        r = S.simulate(self.base, {'policy': 'volume', 'order_change_pct': -100})
        self.assertEqual(r['changed']['revenue'], 0)
        r = S.simulate(self.base, {'policy': 'discount', 'discount_value': 100})
        self.assertIsNone(r['required_order_change'])
        for value in [float('nan'), float('inf'), -101]:
            with self.assertRaises(ValueError):
                S.simulate(self.base, {'order_change_pct': value})
        with self.assertRaises(ValueError):
            S.prepare(self.m, '2026-08-01', '2026-09-01')

    def test_incomplete_money_rejected(self):
        self.m['items'].loc[0, 'cost_price'] = float('nan')
        with self.assertRaises(ValueError):
            S.prepare(self.m, START, END)

    def test_tool_uses_same_engine_and_serializable_payload(self):
        cfg = dict(policy='price', price_change_pct=10)
        res = tools.run(self.m, 'simulate_policy', start=str(START.date()), end=str(END.date()), policy_config=cfg)
        direct = S.simulate(self.base, cfg)
        pd.testing.assert_frame_equal(res['table'], direct['table'])
        json.dumps(res['simulation'], allow_nan=False)
        schema = next(t for t in llm.function_declarations() if t['name'] == 'simulate_policy')
        self.assertIn('policy_config', schema['parameters']['required'])
        with self.assertRaises(ValueError):
            tools.run(self.m, 'simulate_policy', start=str(START.date()), end=str(END.date()), policy_config={'policy': 'discount'})

    def test_target_comparison_fixed_cost_and_shop_reconciliation(self):
        prepared = S.prepare(self.m, START, END, {'product_ids': ['P2']})
        r = S.simulate(prepared, {'policy': 'price', 'price_overrides': {'P2': 10000}, 'fixed_cost': 1000})
        target = S.comparison(r).set_index('지표')
        shop = S.comparison(r, whole_shop=True).set_index('지표')
        self.assertEqual(target.loc['반영 비용 차감 이익', '변경안'], 12000)
        self.assertEqual(shop.loc['반영 비용 차감 이익', '변경안'], 21000)
        self.assertEqual(target.loc['반영 비용 차감 이익', '차이'], shop.loc['반영 비용 차감 이익', '차이'])

    def test_bundle_and_price_compare_on_same_selected_scope(self):
        # Only O2 has both products. O1 must still appear unchanged in the
        # selected-scope comparison so A/B share the same baseline.
        prepared = S.prepare(self.m, START, END, {'product_ids': ['P1', 'P2', 'P3']})
        # Bundle of P2/P3, but add an existing selected basket lacking P3.
        self.m['items'].loc[self.m['items'].product_id.eq('P1'), 'product_id'] = 'P2'
        prepared = S.prepare(self.m, START, END, {'product_ids': ['P2', 'P3']})
        a = S.simulate(prepared, {'policy': 'price', 'price_change_pct': 5})
        b = S.simulate(prepared, {'policy': 'bundle', 'bundle_discount_pct': 10})
        self.assertEqual(b['target_orders'], 1)
        pd.testing.assert_series_equal(S.comparison(a)['현재'], S.comparison(b)['현재'])
        self.assertEqual(b['scope_baseline']['orders'], 2)

    def test_input_numbers_are_evidence_but_invented_numbers_are_rejected(self):
        result = tools.simulate_policy(self.m, str(START.date()), str(END.date()),
            {'policy': 'discount', 'discount_value': 10, 'minimum_order': 25000, 'discount_cap': 5000})
        calls = [{'tool': 'simulate_policy', 'result': result}]
        self.assertEqual(llm.unsupported_in_answer('10% 할인, 최소금액 25,000원, 최대 5,000원', calls), [])
        self.assertIn('77%', llm.unsupported_in_answer('주문은 77% 늘어납니다.', calls))

    def test_ai_demand_question_cannot_present_assumption_as_prediction(self):
        result = tools.simulate_policy(self.m, str(START.date()), str(END.date()),
            {'policy': 'discount', 'discount_value': 10})
        answer = {'conclusion': '10% 할인해도 더 팔리지 않는 것으로 나왔습니다.',
                  'evidence': [], 'hypothesis': '할인 효과가 없습니다.', 'notice': '', 'next_questions': []}
        raw = dict(text=json.dumps(answer, ensure_ascii=False),
                   calls=[{'tool': 'simulate_policy', 'result': result}], model='test', usage={})
        with patch.object(llm, '_tool_loop', return_value=raw):
            reply = llm.ask('test-key', '10% 할인하면 얼마나 더 팔려?', lambda *a: {}, model='test')
        self.assertEqual(reply['answer']['conclusion'], '실제 판매량이 얼마나 늘어날지는 아직 알 수 없습니다.')
        self.assertEqual(reply['answer']['hypothesis'], '')
        self.assertIn('주문 수가 그대로 유지', reply['answer']['notice'])

    def test_grade_filter_with_noncontiguous_index(self):
        frame = self.m['sessions'].copy()
        frame.index = [41, 93]
        self.assertEqual(list(M._grade_at(self.m, frame, 'start')), ['VIP', 'BRONZE'])
        base = S.prepare(self.m, START, END, {'filters': {'grades': ['VIP'], 'grade_basis': '당시'}})
        self.assertEqual(base['ledger'].target.sum(), 1)

    def test_ai_tool_call_round_trip(self):
        from core import llm_openai
        params = {'start': '2026-09-01', 'end': '2026-10-01',
                  'policy_config': {'policy': 'discount', 'discount_value': 35},
                  'simulation_scope': {'coupon_id': 'K1'}}
        first = {'choices': [{'message': {'tool_calls': [{'id': 'sim1', 'type': 'function', 'function': {
            'name': 'simulate_policy', 'arguments': json.dumps(params)}}]}}]}
        last = {'choices': [{'message': {'content': json.dumps({'conclusion': '입력한 조건의 비교입니다.',
            'evidence': [], 'hypothesis': '', 'notice': '주문 반응은 가정입니다.', 'next_questions': []})}}]}
        with patch.object(llm_openai, '_chat_any', side_effect=[(first, 'test'), (last, 'test')]):
            result = llm.ask('sk-test', '쿠폰을 35%로 바꾸면?', lambda name, p: tools.run(self.m, name, **p), model='test')
        self.assertEqual(result['calls'][0]['result']['simulation']['scenarios'][0]['discount_value'], 35)
        self.assertEqual(result['calls'][0]['result']['table'].iloc[-1]['변경안'], 7500)

    def test_no_mutation_and_sensitivity(self):
        old = copy.deepcopy(self.m)
        S.simulate(self.base, {'policy': 'discount', 'discount_value': 100})
        pd.testing.assert_frame_equal(self.m['items'], old['items'])
        sens = S.sensitivity(self.base, {'policy': 'price'})
        self.assertEqual(list(sens['주문 변화 가정 (%)']), [-10, 0, 10])

    def test_legacy_and_new_storage(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'STORE_PATH', Path(tmp)/'store.json'), patch.object(store, 'backend', return_value='json'):
            store._invalidate()
            pid = store.add_problem({'title': '기존 문제'}, 'test', {})
            store.update_problem(pid, hypotheses=[{'가설': '기존 가설'}], experiment={'result': {'mock': True}})
            store.update_problem(pid, simulation={'version': 1})
            current = store.get_problem(pid)
            self.assertEqual(current['hypotheses'][0]['가설'], '기존 가설')
            self.assertTrue(current['experiment']['result']['mock'])
            new = store.add_problem({'title': '새 비교'}, 'test', {}, simulation={'version': 1}, status='전략 선정')
            self.assertEqual(store.get_problem(new)['simulation']['version'], 1)
            store._invalidate()


class GrowthUiTests(unittest.TestCase):
    def setUp(self):
        from core import ui
        from streamlit.testing.v1 import AppTest
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [patch.object(ui, 'get_mart', return_value=mart()),
                        patch.object(store, 'STORE_PATH', Path(self.tmp.name)/'store.json'),
                        patch.object(store, 'backend', return_value='json')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        store._invalidate()
        self.at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'views/growth_lab.py'), default_timeout=20).run()

    def assert_clean(self):
        self.assertFalse(list(self.at.exception), [e.message for e in self.at.exception])

    def calculate(self):
        next(b for b in self.at.button if b.label == '결과 확인').click().run()
        self.assert_clean()

    def test_direct_entry_and_all_policy_controls(self):
        self.assert_clean()
        self.assertNotIn('growth_context', self.at.session_state)
        self.assertFalse(any(m.label == '입력한 비용 차감 후 이익' for m in self.at.metric))
        for policy in S.POLICIES:
            if policy == 'bundle':
                self.at.multiselect(key='sim_new_products').set_value(['P2', 'P3']).run()
            self.at.selectbox(key='sim_new_a_policy').set_value(policy).run()
            self.assert_clean()
            self.assertNotIn('growth_context', self.at.session_state)
            self.calculate()
            self.assertEqual(self.at.session_state.growth_context['scenarios'][0]['policy'], policy)
            self.assertTrue(any('실제 판매량 증가를 예측한 결과가 아닙니다' in i.value for i in self.at.info))

    def test_save_reload_and_old_record_compatibility(self):
        self.at.number_input(key='sim_new_a_price_order_change_pct').set_value(10).run()
        self.calculate()
        next(b for b in self.at.button if b.label == '비교안과 판단 저장').click().run()
        self.assert_clean()
        record = store.load()['problems'][0]
        self.assertEqual(record['simulation']['scenarios'][0]['order_change_pct'], 10)
        self.assertIn('growth_context', self.at.session_state)
        store.update_problem(record['id'], hypotheses=[{'가설': '이전 가설'}], experiment={'name': '기존 실험'})
        self.at.run()
        self.assert_clean()
        self.assertEqual(store.get_problem(record['id'])['experiment']['name'], '기존 실험')
        next(b for b in self.at.button if b.label == '저장 기간 적용').click().run()
        self.assert_clean()
        # New-record saving is the default when reviewing an existing comparison.
        next(b for b in self.at.button if b.label == '비교안과 판단 저장').click().run()
        self.assert_clean()
        self.assertEqual(len(store.load()['problems']), 2)
        self.assertEqual(store.get_problem(record['id'])['experiment']['name'], '기존 실험')

    def test_ai_tool_imports_full_scope_and_period(self):
        from core import chat
        payload = tools.simulate_policy(mart(), '2026-09-01', '2026-10-01',
            {'policy': 'shipping', 'shipping_fee': 3000, 'free_shipping_threshold': 30000},
            {'product_ids': ['P2']}, {'shipping_per_order': 2500})['simulation']
        with patch.object(chat.st, 'session_state', self.at.session_state):
            chat.open_simulation(payload)
        self.at.run()
        self.assert_clean()
        self.assertEqual(self.at.multiselect(key=f"sim_{self.at.session_state.sim_record}_products").value, ['P2'])
        self.calculate()
        ctx = self.at.session_state.growth_context
        self.assertEqual(ctx['scenarios'][0]['policy'], 'shipping')
        self.assertEqual(ctx['costs']['shipping_per_order'], 2500)
        self.assertEqual(len(ctx['scenarios']), 1)

    def test_category_selection_limits_products(self):
        self.at.multiselect(key='sim_new_products').set_value(['P2']).run()
        self.at.multiselect(key='sim_new_categories').set_value(['빵']).run()
        self.assert_clean()
        self.assertEqual(self.at.multiselect(key='sim_new_products').value, [])
        self.assertFalse(any('우유' in s for s in self.at.multiselect(key='sim_new_products').options))

    def test_second_scenario_and_stale_results(self):
        self.calculate()
        self.assertEqual(len(self.at.session_state.growth_context['scenarios']), 1)
        self.at.toggle(key='sim_new_extra').set_value(True).run()
        self.assertNotIn('growth_context', self.at.session_state)
        self.calculate()
        self.assertEqual(len(self.at.session_state.growth_context['scenarios']), 2)
        self.at.number_input(key='sim_new_a_price_order_change_pct').set_value(10).run()
        self.assertNotIn('growth_context', self.at.session_state)
        self.assertFalse(any(m.label == '입력한 비용 차감 후 이익' for m in self.at.metric))

    def test_single_product_input_and_target_basket_result(self):
        self.at.multiselect(key='sim_new_products').set_value(['P2']).run()
        price = next(n for n in self.at.number_input if n.label == '변경할 판매가격 (원)')
        price.set_value(10000).run()
        self.calculate()
        ctx = self.at.session_state.growth_context
        self.assertEqual(ctx['scenarios'][0]['price_overrides'], {'P2': 10000})
        self.assertEqual(ctx['display_scope'], 'target_orders')
        rows = {r['지표']: r for r in ctx['comparison']}
        self.assertEqual(rows['완료 매출']['현재'], 23000)  # Milk basket includes cheese + shipping.
        self.assertEqual(rows['완료 매출']['변경안 A'], 21000)
        self.assertTrue(any('차감하지 않은 비용' in w.value for w in self.at.warning))
        next(b for b in self.at.button if b.label == '새 비교 시작').click().run()
        self.assert_clean()
        self.assertEqual(self.at.multiselect(key='sim_new_products').value, [])
        self.assertNotIn('growth_context', self.at.session_state)

    def test_missing_sales_recovery_and_clear_coupon_units(self):
        self.at.selectbox(key='period_month').set_value(4).run()  # August has no orders in fixture.
        self.assert_clean()
        self.assertTrue(any('판매 내역이 없습니다' in i.value for i in self.at.info))
        self.at.selectbox(key='period_month').set_value(5).run()
        self.at.selectbox(key='sim_new_a_policy').set_value('discount').run()
        self.at.number_input(key='sim_new_a_discount_discount_value_rate').set_value(10).run()
        self.calculate()
        self.assertEqual(self.at.session_state.growth_context['scenarios'][0]['discount_value'], 10)
        self.assertTrue(any('최소 주문금액' in n.label for n in self.at.number_input))
        self.at.selectbox(key='sim_new_a_discount_discount_type').set_value('fixed').run()
        self.at.number_input(key='sim_new_a_discount_discount_value_fixed').set_value(2000).run()
        self.at.selectbox(key='sim_new_a_discount_discount_type').set_value('rate').run()
        self.assert_clean()
        self.assertLessEqual(self.at.number_input(key='sim_new_a_discount_discount_value_rate').value, 100)

    def test_unsold_product_can_recover_without_leaving_page(self):
        from core import ui
        m = ui.get_mart()
        m['raw']['product'] = pd.concat([m['raw']['product'], pd.DataFrame([
            {'product_id': 'P4', 'product_name': '신상품', 'category': '음료', 'cost_price': 1000}])], ignore_index=True)
        self.at.run()
        self.at.multiselect(key='sim_new_products').set_value(['P4']).run()
        self.assert_clean()
        next(b for b in self.at.button if '주문 선택' in b.label).click().run()
        self.assert_clean()
        self.assertNotEqual(self.at.multiselect(key='sim_new_products').value, ['P4'])
        self.calculate()

    def test_draft_chat_never_uses_old_comparison(self):
        from core import chat
        self.calculate()
        self.at.number_input(key='sim_new_a_price_order_change_pct').set_value(5).run()
        self.at.session_state.growth_active = True
        log = []
        with patch.object(chat.st, 'session_state', self.at.session_state), patch.object(llm, 'ask') as ask:
            chat._answer(mart(), 'test-key', log, '지금 결과를 설명해줘')
        ask.assert_not_called()
        self.assertIn('아직 계산하지 않았습니다', log[0]['a'])

    def test_ai_context_instructions_keep_actual_inputs(self):
        context = dict(start='2026-09-01', end='2026-10-01', selected='A',
            scenarios=[{'policy': 'price', 'price_change_pct': 10}], scope={'product_ids': ['P2']})
        raw = dict(text='설정한 가정을 기준으로 비교합니다.', calls=[], model='test', usage={})
        with patch.object(llm, '_tool_loop', return_value=raw) as run:
            llm.ask('test-key', '현재 비교를 설명해줘', lambda *args: {}, model='test', growth_context=context)
        self.assertIn('현재 Growth Lab 비교 화면', run.call_args.args[1])
        self.assertIn('P2', run.call_args.args[1])


if __name__ == '__main__':
    unittest.main()

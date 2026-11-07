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
        self.assertEqual(result['calls'][0]['result']['table'].iloc[-1]['변경안'], 22500)

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

    def test_direct_entry_and_all_policy_controls(self):
        self.assert_clean()
        for policy in S.POLICIES:
            if policy == 'bundle':
                self.at.multiselect(key='sim_new_products').set_value(['P2', 'P3']).run()
            self.at.selectbox(key='sim_new_a_policy').set_value(policy).run()
            self.assert_clean()
            self.assertEqual(len(self.at.metric), 6)

    def test_save_reload_and_old_record_compatibility(self):
        self.at.number_input(key='sim_new_a_price_change_pct').set_value(10).run()
        save = next(b for b in self.at.button if b.label == '비교안과 판단 저장')
        save.click().run()
        self.assert_clean()
        record = store.load()['problems'][0]
        self.assertEqual(record['simulation']['scenarios'][0]['price_change_pct'], 10)
        self.assertEqual(len(self.at.metric), 6)
        store.update_problem(record['id'], hypotheses=[{'가설': '이전 가설'}], experiment={'name': '기존 실험'})
        self.at.run()
        self.assert_clean()
        self.assertEqual(store.get_problem(record['id'])['experiment']['name'], '기존 실험')
        next(b for b in self.at.button if b.label == '저장 기간 적용').click().run()
        self.assert_clean()

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
        ctx = self.at.session_state.growth_context
        self.assertEqual(ctx['scenarios'][0]['policy'], 'shipping')
        self.assertEqual(ctx['costs']['shipping_per_order'], 2500)

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

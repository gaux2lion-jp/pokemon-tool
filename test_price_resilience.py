import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
import price_resilience as resilience

T1 = '2026-10-14T12:00:00+00:00'
T2 = '2026-10-14T13:00:00+00:00'
T3 = '2026-10-14T14:00:00+00:00'


def row(site='A', product='P', price=10000, **extra):
    return dict(site=site, product_name=product, product_display_name=product,
                product_name_on_site=product, price=price, variant='BOX',
                url='https://example.com/', **extra)


def previous(rows):
    sites = {r['site']: dict(status='ok', count=1, last_success_at=T1) for r in rows}
    return dict(updated_at=T1, sites=sites, results=[dict(r, fetched_at=T1, stale=False) for r in rows])


class ResilienceTests(unittest.TestCase):
    def reconcile(self, fresh, states, old, checked=T2, products=None):
        return resilience.reconcile_prices(fresh, states, old, 'product_name', checked, products)

    def test_one_failed_shop_retains_its_prices_and_timestamp(self):
        old = previous([row('A'), row('B', price=9000)])
        rows, status = self.reconcile([row('B', price=9500)], {'A': {'status':'error'}, 'B': {'status':'ok'}}, old)
        by_site = {r['site']:r for r in rows}
        self.assertTrue(by_site['A']['stale']); self.assertEqual(by_site['A']['fetched_at'], T1)
        self.assertFalse(by_site['B']['stale']); self.assertEqual(by_site['B']['fetched_at'], T2)
        self.assertEqual(status['A']['checked_at'], T2)
        self.assertEqual(status['A']['last_success_at'], T1)
        self.assertEqual(status['B']['last_success_at'], T2)
        self.assertEqual(status['A']['cached_count'], 1)

    def test_all_fail_repeatedly_preserves_original_observation(self):
        old = previous([row('A'), row('B')])
        states = {'A': {'status':'error'}, 'B': {'status':'unexpected_empty'}}
        rows, status = self.reconcile([], states, old)
        payload = resilience.report_payload(rows, status, 'test', T2)
        rows, status = self.reconcile([], states, payload, checked=T3)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['stale'] and r['fetched_at']==T1 for r in rows))
        self.assertEqual(resilience.report_payload(rows, status, 'test', T3)['updated_at'], T1)

    def test_zero_unclassified_rows_are_failure(self):
        rows, status = self.reconcile([], {'A': {'status':'ok','count':0}}, previous([row()]))
        self.assertTrue(rows[0]['stale']); self.assertEqual(status['A']['status'], 'unexpected_empty')

    def test_successful_shop_missing_one_product_does_not_resurrect_it(self):
        rows, status = self.reconcile([row(product='P')], {'A': {'status':'ok'}}, previous([row(product='P'),row(product='Q')]))
        self.assertEqual([r['product_name'] for r in rows], ['P'])
        self.assertFalse(rows[0]['stale'])

    def test_successful_source_with_no_config_matches_retires_old_rows(self):
        rows, status = self.reconcile([], {'A': {'status':'ok','source_count':10}}, previous([row()]))
        self.assertEqual(rows, [])
        self.assertEqual(status['A']['status'], 'ok')

    def test_partial_source_retains_only_missing_rows(self):
        rows, status = self.reconcile([row(product='P',price=8000)], {'A': {'status':'partial'}}, previous([row(product='P'),row(product='Q')]))
        self.assertEqual(len(rows),2)
        self.assertEqual([(r['product_name'],r['stale']) for r in rows], [('P',False),('Q',True)])

    def test_recovery_removes_stale_and_replaces_prior_value(self):
        old = previous([row()]); old['results'][0]['stale']=True
        rows, status = self.reconcile([row(price=8000)], {'A': {'status':'ok'}}, old)
        self.assertEqual(len(rows),1); self.assertFalse(rows[0]['stale'])
        self.assertEqual(rows[0]['price'],8000); self.assertEqual(rows[0]['fetched_at'],T2)

    def test_no_cache_never_invents_a_price_or_time(self):
        rows, status = self.reconcile([], {'A': {'status':'error'}}, {})
        self.assertEqual(rows, []); self.assertEqual(status['A']['cached_count'],0)
        self.assertNotIn('last_success_at',status['A'])
        self.assertIsNone(resilience.report_payload(rows,status,'test',T2)['updated_at'])

    def test_legacy_cache_requires_successful_shop_and_real_timestamp(self):
        old = dict(updated_at=T1, results=[row()], sites={'A': {'status':'ok'}})
        rows, _ = self.reconcile([], {'A': {'status':'error'}}, old)
        self.assertEqual(rows[0]['fetched_at'], T1)
        old['sites']['A']['status']='error'
        self.assertEqual(self.reconcile([], {'A': {'status':'error'}},old)[0],[])
        old['sites']['A']['status']='ok'; old['updated_at']=None
        self.assertEqual(self.reconcile([], {'A': {'status':'error'}},old)[0],[])

    def test_removed_config_products_and_shops_not_restored(self):
        rows, _ = self.reconcile([], {'A': {'status':'error'}}, previous([row('A','P'),row('A','Q'),row('B','Q')]), products={'Q'})
        self.assertEqual([(r['site'],r['product_name']) for r in rows],[('A','Q')])

    def test_confirmed_empty_review_or_unconfigured_do_not_restore(self):
        for state in ('empty','review','unconfigured'):
            with self.subTest(state=state):
                self.assertEqual(self.reconcile([], {'A': {'status':state}}, previous([row()]))[0], [])

    def test_x_cache_cannot_outlive_original_24_hour_window(self):
        for published, count in [('2026-10-13T12:59:59+00:00',0), (T1,1)]:
            rows, _ = self.reconcile([], {'A': {'status':'error'}}, previous([row(published_at=published)]))
            self.assertEqual(len(rows),count)

    def test_json_serialization_and_newest_real_observation(self):
        rows, status = self.reconcile([row('B',cost_price=5)], {'A': {'status':'error'}, 'B': {'status':'ok'}}, previous([row()]))
        payload=resilience.report_payload(rows,status,'test',T2)
        self.assertEqual(payload['updated_at'],T2)
        self.assertFalse(any('cost_price' in r for r in payload['results']))
        with tempfile.TemporaryDirectory() as directory:
            resilience.atomic_json(str(Path(directory,'prices.json')),payload)
            self.assertEqual(resilience.load_previous(directory),payload)

    def test_malformed_and_future_dated_cache_is_not_adopted(self):
        for old in ({'results':None}, {'results':{},'sites':None}, previous([row(price=float('nan'))]), previous([row(price=True)])):
            with self.subTest(old=old):
                self.assertEqual(self.reconcile([], {'A':{'status':'error'}},old)[0], [])
        old=previous([row()]); old['results'][0]['fetched_at']=T3
        self.assertEqual(self.reconcile([], {'A':{'status':'error'}},old)[0], [])

    def test_confirmed_empty_records_successful_check_without_prices(self):
        rows, status=self.reconcile([], {'A':{'status':'empty'}},previous([row()]))
        self.assertEqual(rows,[]); self.assertEqual(status['A']['last_success_at'],T2)

    def test_timestamp_selection_is_chronological_across_offsets(self):
        rows=[dict(row('A'),fetched_at='2026-10-14T20:00:00+09:00'),dict(row('B'),fetched_at=T2)]
        self.assertEqual(resilience.report_payload(rows,{},'test',T3)['updated_at'],T2)

    def test_guarantee_snapshot_remains_on_its_original_row(self):
        rows, _ = self.reconcile([], {'A': {'status':'error'}}, previous([row(guarantee_displayed=True, shop_condition_prices={'b':None})]))
        self.assertTrue(rows[0]['guarantee_displayed']); self.assertIsNone(rows[0]['shop_condition_prices']['b'])
        self.assertTrue(rows[0]['stale'])


try:
    import onepiece_scraper as s
    ONEPIECE=True
except ImportError:
    import pokemon_scraper as s
    ONEPIECE=False


class IntegrationTests(unittest.TestCase):
    def tearDown(self):
        s.SITE_STATUS.clear()

    def test_mixed_rows_ui_does_not_award_stale_winner_or_live_guarantee(self):
        fresh=dict(row('B',price=8000),fetched_at=T2,stale=False,diff_from_prev=0,prev_price=8000)
        stale=dict(row('A',price=20000,guarantee_displayed=True,condition_badge='満額保証'),fetched_at=T1,stale=True,diff_from_prev=None,prev_price=None)
        s.SITE_STATUS.update(A={'status':'error','count':0,'cached_count':1})
        with tempfile.TemporaryDirectory() as directory, patch.object(s,'REPORT_DIR',directory):
            s.generate_html_report([stale,fresh],updated_at=T2)
            doc=BeautifulSoup(Path(directory,'index.html').read_text(),'html.parser')
            self.assertIn('8,000円',doc.select_one('.best').get_text())
            self.assertNotIn('20,000円',doc.select_one('.best').get_text())
            self.assertIn('前回取得価格',doc.select_one('.stale-row').get_text())
            self.assertIn('前回掲載',doc.select_one('.stale-row').get_text())
            self.assertIn('2026-10-14 21:00',doc.select_one('.stale-row').get_text())
            self.assertNotIn('初回',doc.select_one('.stale-row').get_text())
            self.assertEqual(doc.select('td.price')[0].get_text().split('円')[0], '8,000')
            payload=json.loads(Path(directory,'prices.json').read_text())
            self.assertEqual(payload['updated_at'],T2)
            self.assertEqual(resilience.timestamp(payload['checked_at']),resilience.timestamp(T2))

    def test_all_stale_ui_has_no_current_highest(self):
        stale=dict(row(),fetched_at=T1,stale=True,diff_from_prev=None,prev_price=None)
        with tempfile.TemporaryDirectory() as directory, patch.object(s,'REPORT_DIR',directory):
            s.generate_html_report([stale],updated_at=T2)
            doc=BeautifulSoup(Path(directory,'index.html').read_text(),'html.parser')
            self.assertEqual(doc.select_one('.best').get_text(),'今回取得できた価格なし')
            self.assertEqual(json.loads(Path(directory,'prices.json').read_text())['updated_at'],T1)

    @unittest.skipUnless(ONEPIECE, 'ONE PIECE comparisons API')
    def test_stale_does_not_mutate_history_or_notify_then_recovery_compares_real_price(self):
        key='A|P|BOX'; history={key:10000}
        stale=dict(row(price=30000),stale=True,diff_from_prev=20000)
        compared, saved=s.attach_comparisons([stale],history)
        self.assertEqual(saved,history); self.assertIsNone(compared[0]['diff_from_prev'])
        stale['diff_from_prev']=20000
        self.assertFalse(s.has_price_changes([stale])); self.assertEqual(s.build_discord_messages([stale]),[])
        compared,saved=s.attach_comparisons([row(price=11000)],history)
        self.assertEqual(compared[0]['diff_from_prev'],1000); self.assertEqual(saved[key],11000)

    @unittest.skipUnless(ONEPIECE, 'ONE PIECE run_once API')
    def test_all_fail_run_once_publishes_failure_without_rewriting_history_or_notifying(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(s,'REPORT_DIR',directory), patch.object(s,'run_all',return_value=[]), patch.object(s,'load_history',return_value={'A|P|BOX':10000}), patch.object(s,'save_history') as save, patch.object(s,'send_discord_notification') as send:
            resilience.atomic_json(str(Path(directory,'prices.json')),previous([row()]))
            s.SITE_STATUS.update(A={'status':'error'})
            s.run_once({'products':[{'display_name':'P'}]},notify=False)
            save.assert_not_called(); send.assert_not_called()
            data=json.loads(Path(directory,'prices.json').read_text())
            self.assertTrue(data['results'][0]['stale']); self.assertEqual(data['results'][0]['fetched_at'],T1)

    @unittest.skipIf(ONEPIECE, 'Pokémon run_all API')
    def test_pokemon_failure_keeps_history_then_recovery_compares_real_price(self):
        from contextlib import ExitStack
        functions=('scrape_base','scrape_runto','scrape_newenoking','scrape_homura','scrape_mobile_ichiban','scrape_kaitori_itchome','scrape_rudeya','scrape_toreca_lounge','scrape_toreca_masai','scrape_torecabank','scrape_somurie','scrape_shinsoku','scrape_x_api')
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(s,'REPORT_DIR',directory))
            stack.enter_context(patch.object(s,'now_jst',return_value=resilience.timestamp(T2)))
            stack.enter_context(patch.object(s,'load_history',return_value={'P_買取ホムラ':10000}))
            save=stack.enter_context(patch.object(s,'save_history'))
            send=stack.enter_context(patch.object(s,'send_discord_notification'))
            mocks={f:stack.enter_context(patch.object(s,f,return_value=[])) for f in functions}
            resilience.atomic_json(str(Path(directory,'prices.json')),previous([row('買取ホムラ')]))
            s.run_all({'products':[{'display_name':'P'}]})
            save.assert_not_called(); self.assertEqual(send.call_args.args[1],[])
            data=json.loads(Path(directory,'prices.json').read_text())
            self.assertEqual(data['results'][0]['fetched_at'],T1); self.assertTrue(data['results'][0]['stale'])
            mocks['scrape_homura'].return_value=[row('買取ホムラ',price=11000)]
            s.run_all({'products':[{'display_name':'P'}]})
            self.assertEqual(save.call_args.args[0]['P_買取ホムラ'],11000)
            self.assertEqual(send.call_args.args[1][0]['diff'],1000)
            data=json.loads(Path(directory,'prices.json').read_text())
            self.assertFalse(data['results'][0]['stale']); self.assertEqual(data['results'][0]['fetched_at'],T2)


if __name__=='__main__': unittest.main()

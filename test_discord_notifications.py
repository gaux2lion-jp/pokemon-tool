import contextlib
import importlib
import io
import json
import os
import random
import unittest
from unittest.mock import Mock, patch

import requests
import discord_notifications as d

DATE = '2026-10-15 00:01'
URL = 'https://example.invalid/prices/'


def change(index=0, **extra):
    row = dict(product=f'日本語商品番号{index:05d}📦', site='買取テスト店', price=12800,
               diff=500, variant='未開封BOX')
    row.update(extra)
    return row


def response(status=200, retry=None, header=None):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps({'id':'123456789012345678'} if retry is None else {'retry_after': retry}).encode()
    if header is not None:
        r.headers['Retry-After'] = header
    return r


class FormattingTests(unittest.TestCase):
    def build(self, rows):
        return d.build_change_messages(rows, DATE, URL)

    def test_zero_one_thirty_thirtyone_eighty_hundreds_complete(self):
        for count in (0, 1, 30, 31, 80, 500):
            with self.subTest(count=count):
                rows = [change(i) for i in range(count)]
                messages = self.build(rows)
                text = ''.join(messages)
                self.assertEqual(text.count('円 → '), count)
                for row in rows:
                    self.assertEqual(text.count(row['product']), 1)
                for page, message in enumerate(messages, 1):
                    self.assertLessEqual(d.discord_length(message), 1900)
                    self.assertIn(f'（{page}/{len(messages)}）', message)
                    self.assertIn(DATE + ' 日本時間', message)
                    self.assertTrue(message.endswith(URL))
                self.assertNotIn('件の変動あり', text)
                if count == 0:
                    self.assertEqual(messages, [])
                if count >= 80:
                    self.assertGreater(len(messages), 1)

    def test_old_new_and_signed_delta_for_both_directions(self):
        text = ''.join(self.build([change(0), change(1, diff=-300)]))
        self.assertIn('12,300円 → 12,800円 （買取テスト店） +500円', text)
        self.assertIn('13,100円 → 12,800円 （買取テスト店） -300円', text)
        self.assertIn('📈', text)
        self.assertIn('📉', text)
        self.assertIn('[未開封BOX]', text)

    def test_unchanged_initial_and_stale_are_excluded(self):
        rows = [change(0, diff=None), change(1, diff=0), change(2, stale=True), change(3)]
        text = ''.join(self.build(rows))
        for row in rows[:3]:
            self.assertNotIn(row['product'], text)
        self.assertIn(rows[3]['product'], text)
        self.assertIn('商品：1件', text)

    def test_stable_order_including_variants(self):
        rows = [change(0, variant=x) for x in ('未開封', 'カートン', 'BOX')]
        rows += [change(1, site='B'), change(1, site='A'), change(1, site='A', price=30000)]
        expected = self.build(rows)
        random.Random(1).shuffle(rows)
        self.assertEqual(self.build(rows), expected)

    def test_astral_unicode_never_exceeds_budget(self):
        rows = [change(i, product=f'商品{i:04d}' + '𠮷🧑🏽\u200d💻' * 45) for i in range(80)]
        messages = self.build(rows)
        self.assertTrue(all(d.discord_length(m) <= 1900 for m in messages))
        for row in rows:
            self.assertEqual(''.join(messages).count(row['product']), 1)
        self.assertEqual(d.discord_length('𠮷📦'), 4)

    def test_single_oversized_name_is_continued_without_data_loss(self):
        product = '𠮷📦全角' * 2000
        messages = self.build([change(0, product=product)])
        bodies = [m.split('\n\n', 1)[1].rsplit('\n📋', 1)[0] for m in messages]
        rebuilt = ''.join(body.removeprefix('↪ 続き: ').rstrip('\n') for body in bodies)
        self.assertIn(product, rebuilt)
        self.assertIn('12,300円 → 12,800円', rebuilt)
        self.assertTrue(all(d.discord_length(m) <= 1900 for m in messages))
        self.assertGreater(len(messages), 1)

    def test_page_count_digit_transitions(self):
        # Each long-but-valid record occupies a page, exercising 9/10 and 99/100.
        for count in (9, 10, 99, 100):
            rows = [change(i, product=f'番号{i:04d}' + '全' * 1000) for i in range(count)]
            messages = self.build(rows)
            self.assertEqual(len(messages), count)
            self.assertIn(f'（{count}/{count}）', messages[-1])
            self.assertTrue(all(d.discord_length(m) <= 1900 for m in messages))
            for row in rows:
                self.assertEqual(''.join(messages).count(row['product']), 1)

    def test_very_long_report_url_fails_instead_of_truncating_changes(self):
        with self.assertRaises(ValueError):
            d.build_change_messages([change()], DATE, URL + 'x' * 1900)

    def test_newlines_cannot_forge_extra_rows(self):
        text = ''.join(self.build([change(product='商品\r\n次の行', site='店舗\n名称')]))
        self.assertIn('商品  次の行', text)
        self.assertIn('店舗 名称', text)


class TransportTests(unittest.TestCase):
    def send(self, messages=('一通目', '二通目'), replies=None):
        post = Mock(side_effect=replies or [response() for _ in messages])
        sleep = Mock()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = d.send_messages('https://example.invalid/webhook/SECRET', messages,
                                     post=post, sleep=sleep)
        return result, post, sleep, output.getvalue()

    def test_every_page_sent_in_order_with_mentions_disabled_and_confirmation(self):
        result, post, sleep, _ = self.send(messages=('@everyone <@123>', '次'))
        self.assertEqual(result, {'total': 2, 'sent': 2, 'status': 'sent'})
        self.assertEqual([x.kwargs['json']['content'] for x in post.call_args_list], ['@everyone <@123>', '次'])
        for call in post.call_args_list:
            self.assertEqual(call.kwargs['json']['allowed_mentions'], {'parse': []})
            self.assertEqual(call.kwargs['params'], {'wait': 'true'})
            self.assertEqual(call.kwargs['timeout'], 15)
            self.assertFalse(call.kwargs['allow_redirects'])
        sleep.assert_called_once_with(1)

    def test_explicit_429_retries_only_the_rejected_page(self):
        result, post, sleep, _ = self.send(replies=[response(), response(429, retry=2.5), response()])
        self.assertEqual(result['sent'], 2)
        self.assertEqual([x.kwargs['json']['content'] for x in post.call_args_list], ['一通目', '二通目', '二通目'])
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [1, 2.5])

    def test_retry_after_respects_larger_header_or_body_cooldown(self):
        result, post, sleep, _ = self.send(messages=('一',), replies=[response(429, retry=1.25, header='2.5'), response()])
        self.assertEqual(result['status'], 'sent')
        sleep.assert_called_once_with(2.5)

    def test_larger_body_cooldown_cannot_be_shortened_by_header(self):
        result, post, sleep, _ = self.send(messages=('一',), replies=[response(429, retry=99, header='1.25')])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_long_retry_after_stops_instead_of_sleeping_or_retrying_early(self):
        result, post, sleep, _ = self.send(messages=('一',), replies=[response(429, retry=86400)])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_aggregate_retry_wait_is_bounded(self):
        result, post, sleep, _ = self.send(messages=('一',), replies=[response(429, retry=20), response(429, retry=20)])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(20)

    def test_zero_wait_429_retries_are_bounded(self):
        result, post, sleep, _ = self.send(messages=('一',), replies=[response(429, retry=0)] * 4)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(post.call_count, 4)

    def test_malformed_retry_after_is_not_retried(self):
        for retry in ('bad', -1, float('nan'), float('inf'), True):
            with self.subTest(retry=retry):
                result, post, sleep, _ = self.send(messages=('一',), replies=[response(429, retry=retry)])
                self.assertEqual(post.call_count, 1)
                self.assertEqual(result['status'], 'failed')
                sleep.assert_not_called()

    def test_partial_failure_stops_batch_without_retry_or_false_success(self):
        result, post, _, output = self.send(messages=('一', '二', '三'), replies=[response(), response(400)])
        self.assertEqual(result, {'total': 3, 'sent': 1, 'status': 'failed', 'stopped_at': 2, 'http_status': 400})
        self.assertEqual(post.call_count, 2)
        self.assertIn('確認済み 1通、未送信 2通', output)

    def test_ambiguous_timeout_is_never_retried_and_secret_is_not_logged(self):
        result, post, _, output = self.send(messages=('一', '二', '三'), replies=[response(), requests.Timeout('SECRET webhook https://secret')])
        self.assertEqual(result, {'total': 3, 'sent': 1, 'status': 'unknown', 'stopped_at': 2})
        self.assertEqual(post.call_count, 2)
        self.assertNotIn('SECRET', output)
        self.assertNotIn('https://secret', output)

    def test_non_429_error_is_not_retried(self):
        result, post, _, output = self.send(messages=('一',), replies=[response(500)])
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('未確認', output)
        self.assertEqual(post.call_count, 1)

    def test_unconfirmed_2xx_is_unknown_and_not_retried(self):
        for code, body in ((204, ''), (200, '{}'), (200, 'not json'), (200, '{"id":null}'), (200, '{"id":"bad"}')):
            with self.subTest(code=code, body=body):
                r = response(code)
                r._content = body.encode()
                result, post, _, _ = self.send(messages=('一',), replies=[r])
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['sent'], 0)
                self.assertEqual(post.call_count, 1)

    def test_existing_query_preserves_thread_but_cannot_disable_wait(self):
        post = Mock(return_value=response())
        d.send_messages(URL + '?thread_id=123&wait=false', ['test'], post=post, sleep=Mock())
        self.assertIn('thread_id=123', post.call_args.args[0])
        self.assertNotIn('wait=false', post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs['params'], {'wait': 'true'})

    def test_validate_entire_batch_before_first_post(self):
        post = Mock()
        with self.assertRaises(ValueError):
            d.send_messages(URL, ['valid', '𠮷' * 951], post=post)
        post.assert_not_called()

    def test_no_url_or_no_messages_does_not_post(self):
        post = Mock()
        self.assertEqual(d.send_messages('', ['test'], post=post)['status'], 'skipped')
        self.assertEqual(d.send_messages(URL, [], post=post)['status'], 'skipped')
        post.assert_not_called()


class ScraperIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.onepiece = os.path.exists(os.path.join(os.path.dirname(__file__), 'onepiece_scraper.py'))
        cls.scraper = importlib.import_module('onepiece_scraper' if cls.onepiece else 'pokemon_scraper')

    def rows(self, count=80):
        if self.onepiece:
            return [dict(product_display_name=f'統合商品{i:03d}', site='テスト店', price=12000,
                         diff_from_prev=1000, variant='未開封BOX') for i in range(count)]
        return [dict(product=f'統合商品{i:03d}', site='テスト店', price=12000, diff=1000) for i in range(count)]

    def test_scraper_formats_all_changes(self):
        messages = self.scraper.build_discord_messages(self.rows())
        self.assertGreater(len(messages), 1)
        combined = ''.join(messages)
        for index in range(80):
            self.assertEqual(combined.count(f'統合商品{index:03d}'), 1)
        self.assertTrue(all(d.discord_length(m) <= 1900 for m in messages))

    def test_scraper_send_delegates_batch_without_using_retrying_scrape_session(self):
        with patch.object(self.scraper, 'send_messages', return_value={'status':'sent'}) as send:
            if self.onepiece:
                messages = self.scraper.build_discord_messages(self.rows())
                result = self.scraper.send_discord_notification(URL, messages)
            else:
                with patch.dict(os.environ, {}, clear=True):
                    result = self.scraper.send_discord_notification({'discord_webhook_url': URL}, self.rows())
            self.assertEqual(result['status'], 'sent')
            self.assertEqual(send.call_args.args[0], URL)
            self.assertGreater(len(send.call_args.args[1]), 1)

    def test_no_notify_never_calls_transport(self):
        s = self.scraper
        with contextlib.ExitStack() as stack:
            prior = {'テスト店|商品|BOX': 10000} if self.onepiece else {'商品_テスト店': 10000}
            stack.enter_context(patch.object(s, 'load_history', return_value=prior))
            stack.enter_context(patch.object(s, 'load_previous', return_value={}))
            stack.enter_context(patch.object(s, 'save_history'))
            stack.enter_context(patch.object(s, 'generate_html_report'))
            send = stack.enter_context(patch.object(s, 'send_messages'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if self.onepiece:
                row = dict(site='テスト店', product_display_name='商品', variant='BOX', price=11000)
                stack.enter_context(patch.object(s, 'run_all', return_value=[row]))
                s.run_once({}, notify=False)
            else:
                names = ('scrape_base', 'scrape_runto', 'scrape_newenoking', 'scrape_homura',
                         'scrape_mobile_ichiban', 'scrape_kaitori_itchome', 'scrape_rudeya',
                         'scrape_toreca_lounge', 'scrape_toreca_masai', 'scrape_torecabank',
                         'scrape_somurie', 'scrape_shinsoku', 'scrape_x_api')
                for name in names:
                    rows = [dict(site='テスト店', product_name='商品', price=11000)] if name == 'scrape_homura' else []
                    stack.enter_context(patch.object(s, name, return_value=rows))
                stack.enter_context(patch('sys.argv', ['pokemon_scraper.py', '--no-notify']))
                s.run_all({'products':[{'display_name':'商品'}]})
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()

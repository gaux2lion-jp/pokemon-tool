import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock
import pokemon_scraper as s


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.config = {'products': [{'display_name': 'テストBOX', 'keywords': ['テストBOX']}]}
        self.now = datetime.now(timezone.utc).isoformat()

    def rows(self, value):
        return s._x_cached_results({'prices': {'買取EXPO': {'テストBOX': value}}}, self.config)

    def test_old_and_undated_prices_rejected(self):
        self.assertEqual(self.rows(10000), [])
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.assertEqual(self.rows({'price': 10000, 'published_at': old}), [])
        self.assertEqual(self.rows({'price': 10000, 'published_at': 'bad'}), [])

    def test_fresh_price_accepted(self):
        self.assertEqual(self.rows({'price': 10000, 'published_at': self.now})[0]['price'], 10000)

    def run_api(self, response, state=None):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'state.json')
            if state:
                with open(path, 'w') as f:
                    json.dump(state, f)
            with patch.object(s, 'X_API_STATE_PATH', path), patch.dict(os.environ, {'X_BEARER_TOKEN': 'test'}), patch.object(s.requests, 'get', return_value=response):
                return s.scrape_x_api(self.config)

    def cached(self):
        return {'version': 2, 'prices': {'買取EXPO': {'テストBOX': {'price': 10000, 'published_at': self.now}}}, 'newest_ids': {}}

    def test_http_error_does_not_reuse_cache(self):
        self.assertEqual(self.run_api(Mock(status_code=401), self.cached()), [])

    def test_fresh_text_post(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'id': '123', 'created_at': self.now, 'text': 'テストBOX 10000円'}]}
        self.assertEqual(len(self.run_api(response)), 2)

    def test_image_only_invalidates_previous_price(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'id': '123', 'created_at': self.now, 'text': '価格更新', 'attachments': {'media_keys': ['photo']}}]}
        self.assertEqual(self.run_api(response, self.cached()), [])

    def test_multiple_prices_not_guessed(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'id': '123', 'created_at': self.now, 'text': 'テストBOX 10000円 12000円'}]}
        self.assertEqual(self.run_api(response, self.cached()), [])

    def test_incomplete_page_not_used(self):
        response = Mock(status_code=200)
        response.json.return_value = {'meta': {'next_token': 'next'}, 'data': []}
        self.assertEqual(self.run_api(response, self.cached()), [])


if __name__ == '__main__':
    unittest.main()

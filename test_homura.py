import copy
import unittest
from unittest.mock import MagicMock, patch

import pokemon_scraper as s


def product(pid=1, name="【BOX】30th CELEBRATION", price=11000, sub_id=128, sub_name="シュリンク有り",
            guarantee=False, jan=""):
    return {"id": pid, "name": name, "price": price,
            "full_price_guarantee": guarantee, "jan_code": jan,
            "product_sub_category": {"id": sub_id, "name": sub_name,
                                     "product_category": {"id": 14, "name": "トレカ"}}}


def page(rows, current=1, pages=1, total=None):
    return {"data": rows, "meta": {"current_page": current,
            "total_pages": pages, "total_count": len(rows) if total is None else total}}


class HomuraApiTests(unittest.TestCase):
    def fetch(self, payloads, errors=None):
        session = MagicMock()
        responses = []
        for index, payload in enumerate(payloads):
            response = MagicMock()
            response.json.return_value = payload
            if errors and index in errors:
                response.raise_for_status.side_effect = RuntimeError("HTTP 503")
            responses.append(response)
        session.get.side_effect = responses
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        with patch.object(s.requests, "Session", factory), patch.object(s.time, "sleep"):
            result = s.fetch_homura_products(128)
        return result, session

    def test_paginates_and_binds_each_product(self):
        rows, session = self.fetch([page([product(1)], 1, 2, 2),
                                    page([product(2, price=12000)], 2, 2, 2)])
        self.assertEqual([(r["id"], r["price"]) for r in rows], [(1, 11000), (2, 12000)])
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["page"], 2)
        self.assertEqual(session.get.call_args_list[0].kwargs["params"]["product_sub_category_id"], 128)

    def test_partial_failure_raises(self):
        with self.assertRaises(RuntimeError):
            self.fetch([page([product()], 1, 2, 2), {}], {1})

    def test_missing_or_changed_schema_raises(self):
        for payload in ({}, {"data": {}, "meta": {}}, {"data": [], "meta": None},
                        {"data": [], "meta": {"total_pages": 1}},
                        page([{"id": True}])):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.fetch([payload])

    def test_counts_pages_and_duplicates_fail_closed(self):
        invalid = [
            [page([product()], 1, 0, 1)],
            [page([product()], 1, 1, 2)],
            [page([product()], 1, 21, 21)],
            [page([product()], 2, 2, 2)],
            [page([product()], 1, 2, 2), page([product()], 2, 2, 2)],
            [page([product()], 1, 2, 2), page([product(2)], 2, 2, 3)],
            [page([], 1, 2, 2)],
        ]
        for payloads in invalid:
            with self.subTest(payloads=payloads), self.assertRaises(ValueError):
                self.fetch(payloads)

    def test_valid_empty_response(self):
        rows, _ = self.fetch([page([], 1, 0, 0)])
        self.assertEqual(rows, [])

    def test_malformed_product_fields_fail_instead_of_clearing_prices(self):
        invalid = []
        for field in ("price", "name", "product_sub_category"):
            row = product()
            del row[field]
            invalid.append(row)
        for field, value in (("price", None), ("price", "11000"),
                             ("price", -1), ("name", ""), ("product_sub_category", [])):
            row = product()
            row[field] = value
            invalid.append(row)
        renamed = product()
        renamed["product_sub_category"]["name"] = "unknown"
        invalid.append(renamed)
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.fetch([page([row])])


class HomuraParserTests(unittest.TestCase):
    def setUp(self):
        self.config = {"exclude_variant_keywords": ["カートン", "バラパック", "シュリンク無し"],
                       "products": [
                           {"display_name": "30th CELEBRATION", "keywords": ["30th CELEBRATION"],
                            "jan_codes": ["4521329462424"],
                            "exclude_keywords": ["FUTURISTIC", "フューチャリスティック"]},
                           {"display_name": "30th CELEBRATION FUTURISTIC BOX",
                            "keywords": ["FUTURISTIC BOX"], "jan_codes": ["4521329463872"]},
                           {"display_name": "ロケット団の栄光",
                            "keywords": ["ロケット団の栄光"], "jan_codes": ["4521329374659"]},
                       ]}

    def test_pokemon_box_and_real_guarantee_flag(self):
        rows = s.parse_homura_products([product(guarantee=True)], self.config)
        self.assertEqual(rows[0]["product_name"], "30th CELEBRATION")
        self.assertEqual(rows[0]["price"], 11000)
        self.assertEqual(rows[0]["condition_badge"], "満額保証")

    def test_special_set_exact_jan_and_no_booster_substring_match(self):
        rows = s.parse_homura_products([
            product(1, name="【BOX】30th CELEBRATION", price=26000, jan="4521329462424"),
            product(2, name="30th CELEBRATION フューチャリスティック BOX", price=62000,
                    sub_id=130, sub_name="スペシャルセット", jan="4521329463872"),
            product(3, name="【BOX】ロケット団の栄光", price=23000, jan="4521329374659"),
            product(4, name="ロケット団の栄光 アタッシュケースセット ※輸送箱未開封", price=25000,
                    sub_id=130, sub_name="スペシャルセット", jan="4521329374628"),
        ], self.config)
        self.assertEqual({r["product_name"]: r["price"] for r in rows},
                         {"30th CELEBRATION": 26000,
                          "30th CELEBRATION FUTURISTIC BOX": 62000,
                          "ロケット団の栄光": 23000})

    def test_wrong_unit_category_and_invalid_prices_excluded(self):
        invalid = [
            product(sub_id=129, sub_name="シュリンク無し"),
            product(sub_id=131, sub_name="未開封カートン"),
            product(sub_id=183, sub_name="バラパック"),
            product(sub_id=132, sub_name="ワンピース 未開封BOX"),
            product(sub_id=157, sub_name="シングルカード"),
            product(sub_name="unknown"), product(name="30th CELEBRATION"),
            product(name="【BOX】30th CELEBRATION カートン"),
            product(price=0), product(price=True), product(price="11000"),
            product(price=None), product(price=2999), product(price=5000001),
        ]
        self.assertEqual(s.parse_homura_products(invalid, self.config), [])

    def test_empty_jan_safe_and_notes_do_not_imply_guarantee(self):
        self.config["products"][0]["jan_codes"] = []
        source = product()
        source.update(notes="満額保証", promoted=True, homura_premium=True)
        source["full_price_guarantee"] = "true"
        rows = s.parse_homura_products([source], self.config)
        self.assertIsNone(rows[0]["jan_code"])
        self.assertIsNone(rows[0]["condition_badge"])

    def test_ambiguous_alias_is_not_assigned_arbitrarily(self):
        self.config["products"].append({"display_name": "another", "keywords": ["30th CELEBRATION"],
                                        "jan_codes": []})
        self.assertEqual(s.parse_homura_products([product()], self.config), [])

    def test_second_category_failure_propagates(self):
        with patch.object(s, "fetch_homura_products", side_effect=[[product()], RuntimeError("HTTP 503")]):
            with self.assertRaises(RuntimeError):
                s.scrape_homura(self.config)

    def test_mega_dream_kana_alias_does_not_require_guessing_jan_suffix(self):
        config = {"products": [{"display_name": "MEGAドリームex",
                               "keywords": ["MEGAドリームex"],
                               "jan_codes": ["4521329431932"]}]}
        rows = s.parse_homura_products([product(name="【BOX】メガドリームex",
                                               price=12800, jan="114521329431932")], config)
        self.assertEqual([(r["product_name"], r["price"]) for r in rows],
                         [("MEGAドリームex", 12800)])


if __name__ == "__main__":
    unittest.main()


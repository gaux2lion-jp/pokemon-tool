import unittest

from pokemon_scraper import extract_x_prices, matches_product, x_post_closes_product


class XPriceParserTests(unittest.TestCase):
    def setUp(self):
        self.excludes = ["カートン", "シュリンクなし", "バラ"]

    def product(self, name, keywords=None, excludes=None):
        return {
            "display_name": name,
            "keywords": keywords or [name],
            "exclude_keywords": excludes or [],
        }

    def test_rise_slash_format(self):
        text = "30th CELEBRATION/22000円\nストームエメラルダ/11500円\nOP-17/13000円"
        prices = extract_x_prices(text, self.product("ストームエメラルダ"), self.excludes)
        self.assertEqual(prices, [11500])

    def test_expo_space_format_and_alias(self):
        text = "ポケモン151 43000円\nシャイニートレジャー 5600円"
        product = self.product("ポケモンカード151", ["ポケモンカード151", "ポケモン151"])
        self.assertEqual(extract_x_prices(text, product, self.excludes), [43000])

    def test_does_not_take_previous_lines_price(self):
        text = "別の商品 23000円\nストームエメラルダ 10200円"
        prices = extract_x_prices(text, self.product("ストームエメラルダ"), self.excludes)
        self.assertEqual(prices, [10200])

    def test_variant_exclusion_is_line_scoped(self):
        text = "別の商品 シュリンクなし 5000円\nストームエメラルダ 11500円"
        prices = extract_x_prices(text, self.product("ストームエメラルダ"), self.excludes)
        self.assertEqual(prices, [11500])

    def test_closing_post_removes_product(self):
        text = "リミックスバウト\n買取受付〆切となりました"
        self.assertTrue(x_post_closes_product(text, self.product("リミックスバウト")))

    def test_unrelated_closing_post_does_not_remove_product(self):
        text = "別の商品\n買取受付〆切となりました"
        self.assertFalse(x_post_closes_product(text, self.product("リミックスバウト")))

    def test_short_carton_code_does_not_exclude_collection(self):
        product = self.product("25th ANNIVERSARY COLLECTION")
        self.assertTrue(matches_product(
            "拡張パック 25th ANNIVERSARY COLLECTION",
            product,
            ["ct", "cs"],
        ))


if __name__ == "__main__":
    unittest.main()

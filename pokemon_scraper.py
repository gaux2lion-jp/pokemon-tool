# -*- coding: utf-8 -*-
"""
ポケモンカード買取価格チェッカー（全14店舗完全対応 ＆ X検索ダイレクトアクセス版）
"""

import os
import re
import json
import time
import sys
import unicodedata
import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

TEST_MODE = False

logging.basicConfig(level=logging.WARNING)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "price_history.json")
REPORT_DIR = os.path.join(BASE_DIR, "docs")
LOG_FILE_PATH = os.path.join(BASE_DIR, "latest_run.log")
X_STATE_PATH = os.path.join(BASE_DIR, "x_state.json")

JST = timezone(timedelta(hours=9))

class AutoLogger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def now_jst():
    return datetime.now(JST)

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def fetch_soup(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")

def normalize_str(s):
    if not s:
        return ""
    return unicodedata.normalize('NFKC', str(s)).lower()

def matches_product(text, product, global_exclude_keywords):
    norm_text = normalize_str(text)

    for g_kw in global_exclude_keywords:
        if not g_kw: continue
        kw_norm = normalize_str(g_kw)
        
        if kw_norm == "開封" and "未開封" in norm_text:
            if "開封済" in norm_text or "開封品" in norm_text:
                return False
            continue
            
        if kw_norm == "パック" and ("拡張パック" in norm_text or "ハイクラスパック" in norm_text):
            if "バラパック" in norm_text or "パック販売" in norm_text:
                return False
            continue

        if kw_norm in norm_text:
            return False

    for ex_kw in product.get("exclude_keywords", []):
        if ex_kw and normalize_str(ex_kw) in norm_text:
            return False

    keywords = product.get("keywords", [])
    if not keywords:
        keywords = [product.get("display_name", "")]

    for kw in keywords:
        if kw and normalize_str(kw) in norm_text:
            return True

    return False

def add_or_update_result(results, site_name, product_name, price, jan_code):
    for r in results:
        if r["site"] == site_name and r["product_name"] == product_name:
            if price > r["price"]:
                r["price"] = price
            return
    results.append({
        "product_name": product_name,
        "site": site_name,
        "price": price,
        "jan_code": jan_code
    })

# 1. 買取BASE
def scrape_base(config):
    site_name = "買取BASE"
    url = "https://kaitori-base.com/?p=9534"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        soup = fetch_soup(url)
        tables = soup.find_all("table")

        for table in reversed(tables):
            rows = table.find_all("tr")
            if len(rows) > 10:
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        name = cells[0].get_text(strip=True)
                        price_text = cells[-1].get_text(strip=True)

                        for product in products_config:
                            if matches_product(name, product, global_exclude):
                                try:
                                    prices = re.findall(r"[\d,]+", price_text)
                                    valid_prices = [int(p.replace(",", "")) for p in prices if len(p.replace(",", "")) >= 4]
                                    if valid_prices:
                                        price = valid_prices[-1]
                                        if 3000 <= price <= 5000000:
                                            add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                                except Exception:
                                    pass
                                break
                if results:
                    break

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 2. Runto買取
def scrape_runto(config):
    site_name = "Runto買取"
    base_url = "https://runto666.com/product-category/card/"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        max_pages = 2 if TEST_MODE else 15
        target_items = []

        for page in range(1, max_pages + 1):
            url = base_url if page == 1 else f"{base_url}page/{page}/"
            try:
                soup = fetch_soup(url)
                product_links = soup.find_all("a", class_="woocommerce-LoopProduct-link")

                if not product_links:
                    break

                for link in product_links:
                    product_url = link.get("href")
                    product_name_elem = link.find("h2") or link.find("h3")

                    if product_name_elem and product_url:
                        name = product_name_elem.get_text(strip=True)
                        for product in products_config:
                            if matches_product(name, product, global_exclude):
                                target_items.append((product_url, product))
                                break
                time.sleep(0.2)
            except Exception:
                break

        for product_url, product in target_items:
            try:
                detail_soup = fetch_soup(product_url)
                summary = detail_soup.find("div", class_="summary entry-summary")
                price_area = summary.find("p", class_="price") if summary else detail_soup.find("p", class_="price")

                if price_area:
                    price_text = price_area.get_text(strip=True)
                    prices = re.findall(r"[\d,]+", price_text)
                    valid_prices = [int(p.replace(",", "")) for p in prices if len(p.replace(",", "")) >= 4]

                    if valid_prices:
                        price = max(valid_prices)
                        if 3000 <= price <= 5000000:
                            add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                time.sleep(0.2)
            except Exception:
                pass

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 3. 買取エノキング
def scrape_newenoking(config):
    site_name = "買取エノキング"
    base_url = "https://newenoking-kaitori.com/products?q=%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        max_pages = 2 if TEST_MODE else 10 
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        for page in range(1, max_pages + 1):
            url = f"{base_url}&page={page}"
            resp = requests.get(url, headers=headers, timeout=15)
            html = resp.text

            rsc_matches = re.findall(r'self\.__next_f\.push\(\[(.*?)\]\s*\)', html, re.DOTALL)
            if not rsc_matches and page > 1:
                break

            for rsc in rsc_matches:
                name_match = re.search(r'\\"name\\":\\"([^\\]+)\\"', rsc) or re.search(r'"name":"([^"]+)"', rsc)
                alt_match = re.search(r'"alt":"([^"]+)"', rsc)
                price_match = re.search(r'"referencePrice":(\d+)', rsc) or re.search(r'\\"referencePrice\\":(\d+)', rsc)
                
                name = (name_match.group(1) if name_match else '') or (alt_match.group(1) if alt_match else '')
                price = int(price_match.group(1)) if price_match else None
                
                if name and price and 3000 <= price <= 5000000:
                    for product in products_config:
                        if matches_product(name, product, global_exclude):
                            add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                            break
            time.sleep(0.2)

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 4. 買取ホムラ
def scrape_homura(config):
    site_name = "買取ホムラ"
    base_url = "https://kaitori-homura.com/products?q%5Bproduct_sub_category_product_category_id_eq%5D=14"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        max_pages = 2 if TEST_MODE else 20

        for page in range(1, max_pages + 1):
            url = f"{base_url}&page={page}"
            soup = fetch_soup(url)
            cards = soup.find_all("div", class_=re.compile(r"product|card|item", re.I))

            if not cards:
                break

            for card in cards:
                text = card.get_text(strip=True)
                for product in products_config:
                    if matches_product(text, product, global_exclude):
                        price_match = re.search(r"買取金額[^\d]*¥?\s*([\d,]{4,8})", text) or re.search(r"¥\s*([\d,]{4,8})", text)
                        if price_match:
                            clean_price = price_match.group(1).replace(",", "")
                            if clean_price.isdigit():
                                price = int(clean_price)
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                                    break
            time.sleep(0.2)

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 5. モバイル一番
def scrape_mobile_ichiban(config):
    site_name = "モバイル一番"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        max_pages = 2 if TEST_MODE else 10

        for page in range(1, max_pages + 1):
            url = "https://www.mobile-ichiban.com/Prod/3/04" if page == 1 else f"https://www.mobile-ichiban.com/G01_ProdutShow/Index/{page}?kid=3&bid=04"
            soup = fetch_soup(url)
            items = soup.find_all("div", class_=re.compile(r"card|item|prod|list", re.I)) or soup.find_all("tr")

            if not items:
                break

            for item in items:
                text = item.get_text(strip=True)
                for product in products_config:
                    if matches_product(text, product, global_exclude):
                        price_match = re.search(r"([\d,]+)\s*円", text) or re.search(r"¥\s*([\d,]+)", text)
                        if price_match:
                            clean_price = price_match.group(1).replace(",", "")
                            if clean_price.isdigit():
                                price = int(clean_price)
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                                    break
            time.sleep(0.3)

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 6. 買取1丁目
def scrape_kaitori_itchome(config):
    site_name = "買取１丁目"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.1-chome.com/tradeCards",
        }
        max_pages = 2 if TEST_MODE else 10

        for page in range(1, max_pages + 1):
            params = {
                "accCode": "", "page": str(page), "size": "50",
                "keyword": "", "isImpo": "false", "isCampaign": "false",
                "cateCode": "IIzyMdayU5wp7T4G", "kbNames": "", "cateName": ""
            }
            url = "https://www.1-chome.com/api/goods/listPage?" + urllib.parse.urlencode(params)
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            
            content = data.get("data", {}).get("content", [])
            if not content:
                break

            for item in content:
                name = item.get("title", "")
                item_jan = str(item.get("jan", "")).strip()
                
                for product in products_config:
                    p_name = product.get("display_name")
                    jan_codes = [str(j).strip() for j in product.get("jan_codes", []) if j]
                    
                    is_match = False
                    if item_jan and item_jan in jan_codes:
                        is_match = True
                    elif matches_product(name, product, global_exclude):
                        is_match = True

                    if is_match:
                        for kd in item.get("goodsKbDetails", []):
                            cond_name = kd.get("kbDetailName", "")
                            price = kd.get("kbDetailPrice")
                            
                            if price and 3000 <= price <= 5000000:
                                full_text = f"{name} {cond_name}"
                                if matches_product(full_text, product, global_exclude):
                                    add_or_update_result(results, site_name, p_name, price, jan_codes[0] if jan_codes else None)
                                    break
            time.sleep(0.2)

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 7. 買取ルデヤ
def scrape_rudeya(config):
    site_name = "買取ルデヤ"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        target_products = products_config[:5] if TEST_MODE else products_config

        for product in target_products:
            jan_codes = product.get("jan_codes", [])
            url = f"https://kaitori-rudeya.com/search/index/-/{jan_codes[0]}/-/-" if jan_codes else f"https://kaitori-rudeya.com/search/index/{urllib.parse.quote(product.get('display_name', ''))}/-/-/-"

            try:
                soup = fetch_soup(url)
                cards = soup.find_all("article", class_=re.compile(r"card", re.I)) or soup.find_all("div", class_=re.compile(r"item|product|box", re.I))

                for card in cards:
                    text = card.get_text(strip=True)
                    if matches_product(text, product, global_exclude):
                        price_match = re.search(r"買取価格\s*([\d,]+)\s*円", text) or re.search(r"([\d,]+)\s*円", text)
                        if price_match:
                            clean_price = price_match.group(1).replace(",", "")
                            if clean_price.isdigit():
                                price = int(clean_price)
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(results, site_name, product.get("display_name"), price, jan_codes[0] if jan_codes else None)
                                    break
                time.sleep(0.2)
            except Exception:
                pass

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 8. トレカラウンジ
def scrape_toreca_lounge(config):
    site_name = "トレカラウンジ"
    base_url = "https://kaitori.toreca-lounge.com/products?keyword="
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        target_products = products_config[:5] if TEST_MODE else products_config

        for product in target_products:
            search_word = urllib.parse.quote(product.get("display_name", ""))
            url = f"{base_url}{search_word}"
            
            try:
                soup = fetch_soup(url)
                items = soup.find_all("div", class_=re.compile(r"product|card|item_box", re.I)) or soup.find_all("tr")

                for item in items:
                    text = item.get_text(strip=True)
                    norm_item = normalize_str(text)
                    if any(ck in norm_item for ck in ["カートン", "carton", "1c/s", "1cs", "ケース"]):
                        continue

                    if matches_product(text, product, global_exclude):
                        price_match = re.search(r"買取価格\s*:\s*¥?\s*([\d,]+)", text) or re.search(r"¥\s*([\d,]+)", text) or re.search(r"([\d,]+)\s*円", text)
                        if price_match:
                            clean_price = price_match.group(1).replace(",", "")
                            if clean_price.isdigit():
                                price = int(clean_price)
                                p_display = product.get("display_name", "")
                                if price > 400000 and "20th" not in p_display and "best of" not in p_display.lower():
                                    continue
                                    
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(results, site_name, p_display, price, product.get("jan_codes", [None])[0])
                                    break
                time.sleep(0.2)
            except Exception:
                pass

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 9. トレカマサイ
def scrape_toreca_masai(config):
    site_name = "トレカマサイ"
    url = "https://www.masai-tcg.com/products"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    TOP_PRICE_RE = re.compile(r"買取価格\s*[¥￥]\s*([0-9,]+)")
    CONDITION_PRICE_RE = re.compile(
        r"(シュリンク付き|シュリンク有り|シュリンク有|シュリンク無し|シュリンクなし|"
        r"ペリペリ無し|ぺりぺり無し|ペリペリ無|ぺりぺり無|統一パック|"
        r"テープ付き|テープカット|カートン|未開封|通常)"
        r"\s*[¥￥]\s*([0-9,]+)"
    )

    try:
        soup = fetch_soup(url)
        cards = soup.select('a[href^="/products/"]')
        seen_slugs = set()

        for card in cards:
            href = card.get("href", "")
            if not href or href in seen_slugs:
                continue
            seen_slugs.add(href)

            name = ""
            img = card.find("img")
            if img and img.get("alt") and "ロゴ" not in img.get("alt"):
                name = img["alt"].strip()
            
            if not name:
                heading = card.find(["h2", "h3", "h4"])
                if heading:
                    name = heading.get_text(" ", strip=True)
            
            if not name:
                continue

            card_text = card.get_text(" ", strip=True)

            for product in products_config:
                if matches_product(name, product, global_exclude) or matches_product(card_text, product, global_exclude):
                    price = None
                    m_top = TOP_PRICE_RE.search(card_text)
                    if m_top:
                        price = int(m_top.group(1).replace(",", ""))
                    else:
                        prices = [int(p_str.replace(",", "")) for _, p_str in CONDITION_PRICE_RE.findall(card_text)]
                        if prices:
                            price = max(prices)
                    
                    if price and 3000 <= price <= 5000000:
                        add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                        break

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 10. トレカバンク
def scrape_torecabank(config):
    site_name = "トレカバンク"
    base_url = "https://store.torecabank.com/mail_buy_list"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        target_products = products_config[:5] if TEST_MODE else products_config

        for product in target_products:
            search_word = product.get("display_name", "")
            params = {"keyword": search_word, "types[]": "5", "sort": "price_desc", "recruiting_only": "1"}
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = requests.get(base_url, params=params, headers=headers, timeout=15)
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select("div.product-card, div.buy-item") or soup.find_all("tr")

                for card in cards:
                    text = card.get_text(strip=True)
                    if matches_product(text, product, global_exclude):
                        price_match = re.search(r"([\d,]+)\s*円", text) or re.search(r"¥\s*([\d,]+)", text)
                        if price_match:
                            clean_price = price_match.group(1).replace(",", "")
                            if clean_price.isdigit():
                                price = int(clean_price)
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                                    break
                time.sleep(0.2)
            except Exception:
                pass

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 11. 買取ソムリエ
def scrape_somurie(config):
    site_name = "買取ソムリエ"
    base_url = "https://somurie-kaitori.com/products?q="
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        target_products = products_config[:5] if TEST_MODE else products_config

        for product in target_products:
            search_word = urllib.parse.quote(product.get("display_name", ""))
            url = f"{base_url}{search_word}"
            try:
                soup = fetch_soup(url)
                cards = soup.select("div.product-card, li.product-item") or soup.find_all("div", class_=re.compile(r"product|card", re.I))

                for card in cards:
                    text = card.get_text(strip=True)
                    if matches_product(text, product, global_exclude):
                        price_match = re.search(r"買取価格\s*:\s*¥?\s*([\d,]+)", text) or re.search(r"¥\s*([\d,]+)", text) or re.search(r"([\d,]+)\s*円", text)
                        if price_match:
                            clean_price = price_match.group(1).replace(",", "")
                            if clean_price.isdigit():
                                price = int(clean_price)
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(results, site_name, product.get("display_name"), price, product.get("jan_codes", [None])[0])
                                    break
                time.sleep(0.2)
            except Exception:
                pass

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 12. シンソク
def scrape_shinsoku(config):
    site_name = "シンソク"
    url = "https://shinsoku-tcg.com/yuso-kaitori"
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    try:
        soup = fetch_soup(url)
        items = soup.find_all("tr") or soup.select("li.product, div.product-card")

        for item in items:
            text = item.get_text(strip=True)
            if not text:
                continue

            for product in products_config:
                if matches_product(text, product, global_exclude):
                    price_match = re.search(r"¥\s*([\d,]+)", text) or re.search(r"([\d,]+)\s*円", text)
                    if price_match:
                        clean_price = price_match.group(1).replace(",", "")
                        if clean_price.isdigit():
                            price = int(clean_price)
                            if 3000 <= price <= 5000000:
                                add_or_update_result(
                                    results, 
                                    site_name, 
                                    product.get("display_name"), 
                                    price, 
                                    product.get("jan_codes", [None])[0]
                                )
                                break

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# X(旧Twitter)共通スクレイピング（最新検索画面アクセス版）
def scrape_x_shop(config, site_name, search_url):
    results = []
    products_config = config.get("products", [])
    global_exclude = config.get("exclude_variant_keywords", [])

    if not os.path.exists(X_STATE_PATH) or os.path.getsize(X_STATE_PATH) == 0:
        print(f" ⚠️ [{site_name:15}] x_state.json が存在しないためスキップします。")
        return results

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f" ⚠️ [{site_name:15}] Playwright がインストールされていないためスキップします。")
        return results

    try:
        print(f" ⏳ [{site_name:15}] X検索タイムライン確認中...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, timeout=30000)
            try:
                context = browser.new_context(
                    storage_state=X_STATE_PATH,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.route("**/*", lambda route, req: route.abort() if req.resource_type in ("media", "font") else route.continue_())
                
                # 検索画面（最新タブ）に直接アクセス
                page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                
                # 最新ツイート群の描画を確実に待機し、スクロール
                try:
                    page.wait_for_selector('[data-testid="tweet"]', timeout=20000)
                except Exception:
                    pass

                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(1.5)

                html = page.content()
            finally:
                browser.close()

        soup = BeautifulSoup(html, "html.parser")
        tweets = soup.select("article[data-testid='tweet']")

        for tweet in tweets:
            tweet_text = tweet.get_text(separator="\n", strip=True)
            lines = tweet_text.split("\n")

            for line in lines:
                if not line.strip():
                    continue

                for product in products_config:
                    if matches_product(line, product, global_exclude):
                        price_match = re.search(r"[¥￥]\s*([\d,]+)|([\d,]+)\s*円", line)
                        if price_match:
                            raw_price = (price_match.group(1) or price_match.group(2)).replace(",", "")
                            if raw_price.isdigit():
                                price = int(raw_price)
                                if 3000 <= price <= 5000000:
                                    add_or_update_result(
                                        results, 
                                        site_name, 
                                        product.get("display_name"), 
                                        price, 
                                        product.get("jan_codes", [None])[0]
                                    )

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# 13. 買取EXPO (最新検索URL)
def scrape_kaitoriexpo(config):
    return scrape_x_shop(config, "買取EXPO", "https://x.com/search?q=from%3Akaitoriexpo&f=live")

# 14. 買取RISE (最新検索URL)
def scrape_kaitoririse(config):
    return scrape_x_shop(config, "買取RISE", "https://x.com/risekaitori&f=live")

def generate_html_report(results):
    os.makedirs(REPORT_DIR, exist_ok=True)
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_name"], []).append(r)

    rows_html = []
    sorted_product_names = sorted(grouped.keys(), key=lambda x: unicodedata.normalize('NFKC', str(x)).lower())
    
    for product_name in sorted_product_names:
        rows = grouped[product_name]
        rows_sorted = sorted(rows, key=lambda x: x["price"], reverse=True)
        best = rows_sorted[0]

        rows_html.append(
            f'<tr class="product-row"><td colspan="3"><strong>{product_name}</strong> '
            f'<span class="best">最高値 {best["price"]:,}円 ({best["site"]})</span></td></tr>'
        )

        for r in rows_sorted:
            diff_html = '<span style="color:#999; font-size:12px; margin-left:8px; font-weight:normal;">(変動なし)</span>'
            if r.get("prev_price") is not None:
                diff = r["price"] - r["prev_price"]
                if diff > 0:
                    diff_html = f'<span style="color:#ef4444; font-size:12px; margin-left:8px; font-weight:bold;">(▲ +{diff:,}円)</span>'
                elif diff < 0:
                    diff_html = f'<span style="color:#3b82f6; font-size:12px; margin-left:8px; font-weight:bold;">(▼ {diff:,}円)</span>'
            else:
                diff_html = '<span style="color:#999; font-size:12px; margin-left:8px; font-weight:normal;">(初回)</span>'

            rows_html.append(
                f'<tr><td style="padding-left: 20px;">{r["site"]}</td><td>―</td>'
                f'<td class="price">{r["price"]:,}円{diff_html}</td></tr>'
            )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>買取価格一覧</title>
<style>
body {{ font-family: -apple-system, sans-serif; background:#f5f5f7; margin:0; padding:16px; color:#333; }}
.container {{ max-width: 800px; margin: 0 auto; }}
h1 {{ font-size: 20px; }}
.updated {{ color:#666; font-size: 13px; margin-bottom: 16px; }}
table {{ width:100%; border-collapse: collapse; background:#fff; border-radius:8px; overflow:hidden; }}
td {{ padding:10px 12px; border-bottom:1px solid #eee; font-size:14px; }}
.product-row td {{ background:#eef2ff; font-weight:500; }}
.best {{ color:#2563eb; font-size:12px; margin-left:8px; }}
.price {{ text-align:right; font-weight:600; white-space: nowrap; }}
</style>
</head>
<body>
<div class="container">
<h1>📊 買取価格一覧（ポケモンカード）</h1>
<div class="updated">最終更新: {now_jst().strftime('%Y-%m-%d %H:%M (日本時間)')}</div>
<table>
{"".join(rows_html)}
</table>
</div>
</body>
</html>"""

    filepath = os.path.join(REPORT_DIR, "index.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f" 📄 HTMLレポートを更新しました: {filepath}")

def send_discord_notification(config, changed_items):
    if not changed_items:
        print("\n ℹ️ 前回実行時から価格の変化がなかったため、Discord通知はスキップしました。")
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL") or config.get("discord_webhook_url")
    if not webhook_url:
        print(" ⚠️ DiscordのWebhook URLが設定されていないため、通知をスキップします。")
        return

    report_url = config.get("report_url", "https://gaux2lion-jp.github.io/pokemon-tool/")
    now_str = now_jst().strftime('%Y-%m-%d %H:%M')

    content = f"📦 **買取価格チェック（{now_str}）**\n\n"
    content += "🔔 **価格が変わった商品**\n"
    
    max_display = 30
    for i, item in enumerate(changed_items):
        if i >= max_display:
            content += f"など、他 {len(changed_items) - max_display} 件の変動あり\n"
            break
        
        icon = "📈" if item['diff'] > 0 else "📉"
        sign = "+" if item['diff'] > 0 else ""
        content += f"{icon} {item['product']}：{item['price']:,}円 （{item['site']}） {sign}{item['diff']:,}円\n"

    content += f"\n📋 **全商品・全サイトの詳細一覧はこちら**\n{report_url}"

    if len(content) > 1900:
        content = content[:1900] + f"...\n\n📋 **続き・詳細一覧はこちら**\n{report_url}"

    payload = {"content": content}
    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        print(" ✓ Discordへ更新完了の通知を送信しました！")
    except Exception as e:
        print(f" ❌ Discord通知エラー: {e}")

def run_all(config):
    print(f"\n{'='*60}")
    mode_label = "【🚀 テストモード（検証）】" if TEST_MODE else "【✅ 本番モード（全件取得）】"
    print(f"ポケモンカード買取価格チェック {mode_label}")
    print(f"実行時刻: {now_jst().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    scraper_funcs = [
        scrape_base, scrape_runto, scrape_newenoking, scrape_homura,
        scrape_mobile_ichiban, scrape_kaitori_itchome, scrape_rudeya,
        scrape_toreca_lounge, scrape_toreca_masai, scrape_torecabank,
        scrape_somurie, scrape_shinsoku, scrape_kaitoriexpo, scrape_kaitoririse
    ]

    all_results = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_func = {executor.submit(func, config): func for func in scraper_funcs}
        for future in as_completed(future_to_func):
            try:
                res = future.result()
                if res:
                    all_results.extend(res)
            except Exception as e:
                print(f" ❌ スレッド実行エラー: {e}")

    print(f"\n{'='*60}")
    print(f"スクレイピング完了！ 合計 {len(all_results)} 件のデータを取得")
    print(f"{'='*60}\n")

    if not all_results:
        print(" ⚠️ データが取得できませんでした。")
        return

    history = load_history()
    grouped = {}
    changed_items = []

    for result in all_results:
        product_name = result["product_name"]
        grouped.setdefault(product_name, []).append(result)

        hist_key = f"{product_name}_{result['site']}"
        prev_price = history.get(hist_key)
        result["prev_price"] = prev_price
        history[hist_key] = result["price"]

        if prev_price is not None and prev_price != result["price"]:
            diff = result["price"] - prev_price
            changed_items.append({
                "product": product_name,
                "site": result["site"],
                "price": result["price"],
                "diff": diff
            })

    save_history(history)

    for product_name in sorted(grouped.keys()):
        rows = sorted(grouped[product_name], key=lambda x: x["price"], reverse=True)
        print(f"📦 {product_name}")
        print("─" * 60)
        for r in rows:
            diff_str = "初回"
            if r["prev_price"] is not None:
                diff = r["price"] - r["prev_price"]
                diff_str = f"{diff:+,}円" if diff != 0 else "変動なし"
            print(f"  [{r['site']:12}] {r['price']:,}円 ({diff_str})")
        print()

    generate_html_report(all_results)
    send_discord_notification(config, changed_items)

if __name__ == "__main__":
    sys.stdout = AutoLogger(LOG_FILE_PATH)
    config = load_config()
    run_all(config)

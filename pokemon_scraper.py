# -*- coding: utf-8 -*-
"""
ポケモンカード買取価格チェッカー（爆速化 ＆ Discord通知詳細化 ＆ HTML差額表示 ＆ 通知スキップ機能 最終形態）
"""

import os
import re
import json
import time
import sys
import unicodedata
import logging
import urllib.parse
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────
# 🚀 運用設定
#   False : 全ページ・全件取得（本番用）
#   True  : ページ巡回数を制限（テスト用）
# ──────────────────────────────────────────────────
TEST_MODE = False

logging.basicConfig(level=logging.WARNING)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "price_history.json")
REPORT_DIR = os.path.join(BASE_DIR, "docs")
LOG_FILE_PATH = os.path.join(BASE_DIR, "latest_run.log")

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
    """ブラウザを使わず、HTMLを直接爆速で取得する"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def normalize_str(s):
    """全角英数・記号を半角に変換し、小文字化する"""
    if not s:
        return ""
    return unicodedata.normalize('NFKC', str(s)).lower()

def matches_product(text, product, global_exclude_keywords):
    norm_text = normalize_str(text)

    # 1. 全体除外キーワードの判定
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

    # 2. 個別除外キーワードの判定
    for ex_kw in product.get("exclude_keywords", []):
        if ex_kw and normalize_str(ex_kw) in norm_text:
            return False

    # 3. マッチキーワードの判定
    keywords = product.get("keywords", [])
    if not keywords:
        keywords = [product.get("display_name", "")]

    for kw in keywords:
        if kw and normalize_str(kw) in norm_text:
            return True

    return False

def add_or_update_result(results, site_name, product_name, price, jan_code):
    """同一商品が見つかった場合、より高い金額で上書きする"""
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
        print(f" ⏳ [{site_name:15}] アクセス中...")
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
        print(f" ⏳ [{site_name:15}] 全ページ巡回中...")
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
                time.sleep(0.3)
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
                time.sleep(0.3)
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
        print(f" ⏳ [{site_name:15}] RSC直接解析中...")
        max_pages = 2 if TEST_MODE else 10 
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

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
            time.sleep(0.3)

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
        print(f" ⏳ [{site_name:15}] 全カテゴリ巡回中...")
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
            time.sleep(0.3)

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
        print(f" ⏳ [{site_name:15}] 全ページ巡回中...")
        max_pages = 2 if TEST_MODE else 10

        for page in range(1, max_pages + 1):
            if page == 1:
                url = "https://www.mobile-ichiban.com/Prod/3/04"
            else:
                url = f"https://www.mobile-ichiban.com/G01_ProdutShow/Index/{page}?kid=3&bid=04"
            
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
            time.sleep(0.5)

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
        print(f" ⏳ [{site_name:15}] API全ページ巡回中...")
        
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
            time.sleep(0.3)

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
        print(f" ⏳ [{site_name:15}] 個別検索中...")
        target_products = products_config[:5] if TEST_MODE else products_config

        for product in target_products:
            jan_codes = product.get("jan_codes", [])
            
            if jan_codes:
                url = f"https://kaitori-rudeya.com/search/index/-/{jan_codes[0]}/-/-"
            else:
                search_word = urllib.parse.quote(product.get("display_name", ""))
                url = f"https://kaitori-rudeya.com/search/index/{search_word}/-/-/-"

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
                time.sleep(0.3)
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
        print(f" ⏳ [{site_name:15}] 個別検索中...")
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
                time.sleep(0.3)
            except Exception:
                pass

        print(f" ✓ [{site_name:15}] {len(results):3}件取得")
        return results

    except Exception as e:
        print(f" ✗ [{site_name:15}] エラー: {str(e)[:50]}")
        return results

# HTMLレポートの生成処理（差額カラー表示＆ソート機能）
def generate_html_report(results):
    os.makedirs(REPORT_DIR, exist_ok=True)
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_name"], []).append(r)

    rows_html = []
    
    # 辞書順（数字 → アルファベット → カナ → 漢字）にソート
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
            # 差額の計算とカラー装飾
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
/* white-space:nowrap を追加して価格と差額が改行されないように調整 */
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
    # 変更がない場合はここで処理を終了（スキップ）する
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

    # 2000文字制限の回避
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

    all_results = []

    try:
        all_results.extend(scrape_base(config))
        all_results.extend(scrape_runto(config))
        all_results.extend(scrape_newenoking(config))
        all_results.extend(scrape_homura(config))
        all_results.extend(scrape_mobile_ichiban(config))
        all_results.extend(scrape_kaitori_itchome(config))
        all_results.extend(scrape_rudeya(config))
        all_results.extend(scrape_toreca_lounge(config))

    except Exception as e:
        print(f"\n ❌ エラー: {e}")

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

    # 変更点を保持した状態でHTMLを生成
    generate_html_report(all_results)
    send_discord_notification(config, changed_items)

if __name__ == "__main__":
    sys.stdout = AutoLogger(LOG_FILE_PATH)
    config = load_config()
    run_all(config)

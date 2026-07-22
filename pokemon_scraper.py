# -*- coding: utf-8 -*-
"""
買取価格比較ツール
==================

事前に設定した商品（例：ワンピースカード 決戦の刻）について、
複数の買取サイトの価格を一括取得し、一覧表示・CSV保存するツールです。

■できること
  - 買取ホムラ / 買取BASE / Runto買取 の3サイトを横断して価格を確認
  - 前回実行時との価格差（値上がり/値下がり）を表示
  - config.json に設定した仕入れ値との差額（利益）を表示
  - 結果を results/ フォルダにCSVで保存

■使い方
  1) 商品情報は config.json で設定します（商品名・検索キーワード・仕入れ値）
  2) ターミナルで下記を実行します
       python kaitori_scraper.py
  3) 実行結果が画面に表示され、CSVファイルが results/ フォルダに保存されます

■サイトを追加したい場合
  下部の SITES リストに、対応する scrape_xxx 関数を作って登録してください。

■注意
  各サイトのHTML構造は将来変わる可能性があります。価格が正しく取得できない
  場合は、エラーメッセージや実行結果をそのまま共有していただければ、
  それをもとに抽出ロジックを修正します。
"""

import os
import re
import csv
import sys
import json
import time
import unicodedata
import html as html_module
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# 一部サイト(森森買取など)はTLS通信の特徴("指紋")で
# 「本物のブラウザかどうか」を判定してブロックすることがある。
# curl_cffiが入っていれば、ブラウザに近い通信でそれを回避する。
from bs4 import BeautifulSoup

# 一部サイト(森森買取など)はTLS通信の特徴("指紋")で
# 「本物のブラウザかどうか」を判定してブロックすることがある。
# curl_cffiが入っていれば、ブラウザに近い通信でそれを回避する。
try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.const import CurlHttpVersion
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


def display_width(text):
    """全角文字(2)・半角文字(1)を区別した表示上の文字幅を計算する"""
    width = 0
    for ch in str(text):
        w = unicodedata.east_asian_width(ch)
        width += 2 if w in ("W", "F") else 1
    return width


def pad_display(text, width, align="left"):
    """表示幅を揃えるためのパディング（全角文字を考慮）"""
    text = str(text)
    pad = max(0, width - display_width(text))
    if align == "right":
        return " " * pad + text
    return text + " " * pad

# ----------------------------------------------------------------------
# 共通設定
# ----------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "price_history.json")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

SLEEP_SEC = 0.8  # サイトへの負荷軽減のため、リクエスト間に空ける秒数

JST = timezone(timedelta(hours=9))


def now_jst():
    """実行環境のタイムゾーンによらず、常に日本時間を返す
    （GitHub ActionsなどクラウドのサーバーはUTC(世界標準時)で動いているため）"""
    return datetime.now(JST)

# True にすると、各サイトから取得した生のHTMLを debug_html/ フォルダに保存します。
# 「価格が正しく取れない」「0件ヒットする」等の調査時にオンにしてください。
# 保存されたHTMLファイルをそのままアップロードしてもらえれば、正確に修正できます。
SAVE_DEBUG_HTML = False
DEBUG_DIR = os.path.join(BASE_DIR, "debug_html")


def save_debug_html(site_name, label, html_text):
    if not SAVE_DEBUG_HTML:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    ts = now_jst().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^\w\-]+", "_", label)[:50]
    path = os.path.join(DEBUG_DIR, f"{site_name}_{safe_label}_{ts}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"    [debug] HTML保存: {path}")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# 「Connection aborted」等の一時的な接続断に備えて、自動リトライを設定する
_retry = Retry(
    total=3,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)


# ----------------------------------------------------------------------
# 設定・履歴の読み書き
# ----------------------------------------------------------------------

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {}
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# サイトごとのスクレイピング処理
# ----------------------------------------------------------------------

def scrape_base():
    """買取BASE：トレカ買取価格表ページの中の「ポケモンカード買取価格」表を取得する"""
    url = "https://kaitori-base.com/?p=9534"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [買取BASE] 通信エラー: {e}")
        return results

    save_debug_html("base", "toreca_hyou", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # 「ポケモンカード買取価格」という見出しの次にあるテーブルを探す
    heading = None
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        if h.get_text(strip=True) == "ポケモンカード買取価格":
            heading = h
            break

    if heading is None:
        print("  [買取BASE] 「ポケモンカード買取価格」の見出しが見つかりませんでした")
        return results

    table = heading.find_next(["table", "figure"])
    if table and table.name == "figure":
        table = table.find("table")
    if table is None:
        return results

    rows = table.find_all("tr")
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) < 2:
            continue
        product_name = cells[0]
        price_text = cells[-1]  # 一番右の列が買取価格
        price_match = re.search(r"[\d,]+", price_text)
        if not price_match:
            continue
        price = int(price_match.group(0).replace(",", ""))

        results.append({
            "site": "買取BASE",
            "product_name_on_site": product_name,
            "match_text": " ".join(cells),
            "variant": "",
            "price": price,
            "url": url,
        })

    time.sleep(SLEEP_SEC)
    return results


def scrape_homura():
    """買取ホムラ：ポケモンBOXサブカテゴリ(128)を全ページ取得する"""
    results = []
    seen_ids = set()
    url = "https://kaitori-homura.com/products"

    for page in range(1, 6):
        params = {
            "q[product_sub_category_id_eq]": "128",  # ポケモンBOXサブカテゴリ
            "q[product_sub_category_product_category_id_eq]": "14",
            "page": str(page),
        }

        try:
            resp = SESSION.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [買取ホムラ] 通信エラー: {e}")
            break

        save_debug_html("homura", f"pokemon_box_page{page}", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")

        anchors = soup.find_all("a", href=re.compile(r"/products/\d+"))
        by_pid, order = {}, []
        for a in anchors:
            m = re.search(r"/products/(\d+)", a["href"])
            if not m:
                continue
            pid = m.group(1)
            if pid not in by_pid:
                order.append(pid)
            if a.get_text(strip=True):
                by_pid[pid] = a

        # 商品ごとに詳細ページを取得
        for pid in order:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            detail_url = f"https://kaitori-homura.com/products/{pid}"
            try:
                detail_resp = SESSION.get(detail_url, timeout=15)
                detail_resp.raise_for_status()
            except requests.RequestException as e:
                print(f"    [買取ホムラ] 商品詳細ページ取得エラー (PID={pid}): {e}")
                continue

            save_debug_html("homura", f"product_{pid}", detail_resp.text)
            detail_soup = BeautifulSoup(detail_resp.text, "lxml")

            # 商品名を取得
            h1 = detail_soup.find("h1")
            if not h1:
                continue
            product_name = h1.get_text(strip=True)

            # 価格を取得（「買取価格」という見出しの後の数字を探す）
            price_text = None
            for tag in detail_soup.find_all(["span", "p", "td", "div"]):
                t = tag.get_text(strip=True)
                if "買取価格" in t:
                    # このタグまたは次のタグに価格がある場合が多い
                    next_tag = tag.find_next()
                    if next_tag:
                        price_text = next_tag.get_text(strip=True)
                    break

            if price_text is None:
                # 別の方法で探す
                for tag in detail_soup.find_all(["p", "span", "td"]):
                    t = tag.get_text(strip=True)
                    m = re.search(r"([\d,]+)円", t)
                    if m and "買取" in detail_soup.get_text()[:500]:
                        price_text = m.group(1)
                        break

            if price_text:
                price_match = re.search(r"[\d,]+", price_text)
                if price_match:
                    price = int(price_match.group(0).replace(",", ""))
                    results.append({
                        "site": "買取ホムラ",
                        "product_name_on_site": product_name,
                        "match_text": product_name,
                        "variant": "",
                        "price": price,
                        "url": detail_url,
                    })

            time.sleep(SLEEP_SEC)

        # ページネーション: 次のページがなければ終了
        next_button = soup.find("a", text=re.compile(r"次"))
        if not next_button:
            break

        time.sleep(SLEEP_SEC)

    return results


def scrape_runto():
    """Runto買取：ポケモンBOX一覧ページから価格を取得"""
    url = "https://runto-kaitori.com/pokemon-buy-price/?search_types=1"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Runto買取] 通信エラー: {e}")
        return results

    save_debug_html("runto", "pokemon_list", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # 商品ごとの行を探す（tableの場合、liの場合、divの場合等がある）
    rows = soup.find_all(["tr", "li", "div"], class_=re.compile(r"product|item|box"))
    if not rows:
        rows = soup.find_all(["div", "article"])

    for row in rows:
        # 商品名を探す
        name_tag = row.find(["h3", "h2", "a", "span"], class_=re.compile(r"name|title"))
        if not name_tag:
            continue
        product_name = name_tag.get_text(strip=True)
        if not product_name:
            continue

        # 価格を探す
        price_tag = row.find(["span", "p", "td"], class_=re.compile(r"price|kaitori"))
        if not price_tag:
            price_tag = row.find(re.compile(r"span|td|p"), string=re.compile(r"[\d,]+円"))

        price_text = None
        if price_tag:
            price_text = price_tag.get_text(strip=True)

        if price_text:
            price_match = re.search(r"[\d,]+", price_text)
            if price_match:
                price = int(price_match.group(0).replace(",", ""))
                results.append({
                    "site": "Runto買取",
                    "product_name_on_site": product_name,
                    "match_text": product_name,
                    "variant": "",
                    "price": price,
                    "url": url,
                })

    time.sleep(SLEEP_SEC)
    return results


def scrape_rudeya():
    """買取ルデヤ：ポケモン買取ページを検索取得"""
    base_url = "https://kaitori-rudeya.com/search"
    results = []

    try:
        params = {"word": "ポケモンBOX"}
        resp = SESSION.get(base_url, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [買取ルデヤ] 通信エラー: {e}")
        return results

    save_debug_html("rudeya", "pokemon_search", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # 検索結果の商品行を探す
    items = soup.find_all(["div", "li"], class_=re.compile(r"product|item|result"))

    for item in items:
        # 商品名
        name_tag = item.find(["a", "h3", "h2", "span"])
        if not name_tag:
            continue
        product_name = name_tag.get_text(strip=True)
        if not product_name:
            continue

        # 価格
        price_tag = item.find(re.compile(r"span|td|p"), string=re.compile(r"[\d,]+円"))
        if not price_tag:
            price_tag = item.find(["span", "p"], class_=re.compile(r"price|kaitori"))

        price_text = None
        if price_tag:
            price_text = price_tag.get_text(strip=True)

        if price_text:
            price_match = re.search(r"[\d,]+", price_text)
            if price_match:
                price = int(price_match.group(0).replace(",", ""))
                results.append({
                    "site": "買取ルデヤ",
                    "product_name_on_site": product_name,
                    "match_text": product_name,
                    "variant": "",
                    "price": price,
                    "url": base_url,
                })

    time.sleep(SLEEP_SEC)
    return results


def scrape_enoking():
    """買取エノキング：ポケモンカテゴリを取得"""
    url = "https://kaitori-enoking.com/category/pokemon"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [買取エノキング] 通信エラー: {e}")
        return results

    save_debug_html("enoking", "pokemon_category", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # 商品一覧を取得
    products = soup.find_all(["div", "li"], class_=re.compile(r"product|item|box"))

    for product in products:
        # 商品名
        name_tag = product.find(["a", "h3", "h2"])
        if not name_tag:
            continue
        product_name = name_tag.get_text(strip=True)
        if not product_name:
            continue

        # 価格
        price_tag = product.find(re.compile(r"span|p|td"), string=re.compile(r"[\d,]+円"))
        if not price_tag:
            price_tag = product.find(["span", "p"], class_=re.compile(r"price|kaitori"))

        price_text = None
        if price_tag:
            price_text = price_tag.get_text(strip=True)

        if price_text:
            price_match = re.search(r"[\d,]+", price_text)
            if price_match:
                price = int(price_match.group(0).replace(",", ""))
                results.append({
                    "site": "買取エノキング",
                    "product_name_on_site": product_name,
                    "match_text": product_name,
                    "variant": "",
                    "price": price,
                    "url": url,
                })

    time.sleep(SLEEP_SEC)
    return results


def scrape_mobile_ichiban():
    """モバイル一番：ポケモンカード買取ページ"""
    url = "https://kaitori-mobile-ichiban.com/pokemon-card-list"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [モバイル一番] 通信エラー: {e}")
        return results

    save_debug_html("mobile_ichiban", "pokemon_list", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # ポケモン商品を検索
    items = soup.find_all(["div", "tr", "li"], class_=re.compile(r"product|item|pokemon"))

    for item in items:
        name_tag = item.find(["a", "h3", "td", "span"])
        if not name_tag:
            continue
        product_name = name_tag.get_text(strip=True)
        if not product_name or len(product_name) < 2:
            continue

        price_tag = item.find(re.compile(r"span|td|p"), string=re.compile(r"[\d,]+円"))
        if not price_tag:
            continue

        price_text = price_tag.get_text(strip=True)
        price_match = re.search(r"[\d,]+", price_text)
        if price_match:
            price = int(price_match.group(0).replace(",", ""))
            results.append({
                "site": "モバイル一番",
                "product_name_on_site": product_name,
                "match_text": product_name,
                "variant": "",
                "price": price,
                "url": url,
            })

    time.sleep(SLEEP_SEC)
    return results


def scrape_kaitori_shouten():
    """買取商店：ポケモンカード買取ページ"""
    url = "https://kaitori-shouten.com/pokemon"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [買取商店] 通信エラー: {e}")
        return results

    save_debug_html("kaitori_shouten", "pokemon", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    products = soup.find_all(["div", "tr", "li"])

    for product in products:
        # 商品名と価格を探す
        text = product.get_text(strip=True)
        if "ポケモン" not in text and "BOX" not in text:
            continue

        # 価格を抽出
        price_match = re.search(r"([\d,]+)円", text)
        if not price_match:
            continue

        # 商品名を取得
        name_tag = product.find(["a", "h3", "h2", "span"])
        if not name_tag:
            continue

        product_name = name_tag.get_text(strip=True)
        if not product_name:
            continue

        price = int(price_match.group(1).replace(",", ""))
        results.append({
            "site": "買取商店",
            "product_name_on_site": product_name,
            "match_text": product_name,
            "variant": "",
            "price": price,
            "url": url,
        })

    time.sleep(SLEEP_SEC)
    return results


def scrape_kaitori_itchome():
    """買取1丁目：ポケモン買取ページ"""
    url = "https://kaitori-itchome.com/pokemon-buy"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [買取1丁目] 通信エラー: {e}")
        return results

    save_debug_html("kaitori_itchome", "pokemon_buy", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # 買取対象の商品行を抽出
    items = soup.find_all(["tr", "div", "li"], class_=re.compile(r"product|item"))

    for item in items:
        cells = item.find_all(["td", "div", "span"])
        if len(cells) < 2:
            continue

        product_name = cells[0].get_text(strip=True)
        if not product_name:
            continue

        # 最後のセルが価格の場合が多い
        for cell in reversed(cells):
            price_text = cell.get_text(strip=True)
            price_match = re.search(r"([\d,]+)円", price_text)
            if price_match:
                price = int(price_match.group(1).replace(",", ""))
                results.append({
                    "site": "買取1丁目",
                    "product_name_on_site": product_name,
                    "match_text": product_name,
                    "variant": "",
                    "price": price,
                    "url": url,
                })
                break

    time.sleep(SLEEP_SEC)
    return results


def scrape_toreca_lounge():
    """トレカラウンジ：ポケモン買取ページ"""
    url = "https://toreca-lounge.com/pokemon-buy-price"
    results = []

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [トレカラウンジ] 通信エラー: {e}")
        return results

    save_debug_html("toreca_lounge", "pokemon_buy_price", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    # 買取リスト
    items = soup.find_all(["tr", "div", "li"])

    for item in items:
        text = item.get_text(strip=True)

        # 商品名（通常は最初の部分）
        name_match = re.match(r"^([^0-9\d]*)", text)
        if not name_match:
            continue

        product_name = name_match.group(1).strip()
        if not product_name or len(product_name) < 2:
            continue

        # 価格を抽出
        price_match = re.search(r"([\d,]+)円", text)
        if not price_match:
            continue

        price = int(price_match.group(1).replace(",", ""))
        results.append({
            "site": "トレカラウンジ",
            "product_name_on_site": product_name,
            "match_text": product_name,
            "variant": "",
            "price": price,
            "url": url,
        })

    time.sleep(SLEEP_SEC)
    return results


# 全サイト
SITES = [
    ("買取BASE", scrape_base),
    ("買取ホムラ", scrape_homura),
    ("Runto買取", scrape_runto),
    ("買取ルデヤ", scrape_rudeya),
    ("買取エノキング", scrape_enoking),
    ("モバイル一番", scrape_mobile_ichiban),
    ("買取商店", scrape_kaitori_shouten),
    ("買取1丁目", scrape_kaitori_itchome),
    ("トレカラウンジ", scrape_toreca_lounge),
]


def run_all(config):
    """全サイトから並列に情報を取得して、マッチング結果を返す"""
    products = config.get("products", [])
    all_results = []

    print(f"\n[実行開始] {now_jst().strftime('%Y-%m-%d %H:%M:%S')} (日本時間)")
    print(f"対象商品数: {len(products)}")
    print(f"対象サイト数: {len(SITES)}")
    print()

    # 全サイトから並列でスクレイピング
    print("複数サイトから価格を取得中...")
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for site_name, scrape_func in SITES:
            print(f"  {site_name}...")
            future = executor.submit(scrape_func)
            futures[future] = site_name

        site_results = {}
        for future in futures:
            site_name = futures[future]
            try:
                results = future.result(timeout=30)
                site_results[site_name] = results
                print(f"  ✓ {site_name}: {len(results)}件")
            except Exception as e:
                print(f"  ✗ {site_name}: {e}")
                site_results[site_name] = []

    # 商品ごとにマッチング
    print()
    print("商品とのマッチング中...")

    for product in products:
        display_name = product["display_name"]
        keywords = product.get("keywords", [])
        jan_codes = product.get("jan_codes", [])
        exclude_keywords = product.get("exclude_keywords", [])

        for site_name, site_result_list in site_results.items():
            for site_result in site_result_list:
                match = False

                # キーワードマッチング
                product_name_lower = site_result["product_name_on_site"].lower()
                for keyword in keywords:
                    if keyword.lower() in product_name_lower:
                        match = True
                        break

                # JANコードマッチング
                if not match and jan_codes:
                    match_text = site_result.get("match_text", "").lower()
                    for jan in jan_codes:
                        if jan in match_text:
                            match = True
                            break

                if not match:
                    continue

                # 除外キーワードチェック
                excluded = False
                for ex_keyword in exclude_keywords:
                    if ex_keyword.lower() in product_name_lower:
                        excluded = True
                        break

                if excluded:
                    continue

                # マッチした結果を追加
                all_results.append({
                    "product_display_name": display_name,
                    "site": site_result["site"],
                    "product_name_on_site": site_result["product_name_on_site"],
                    "variant": site_result.get("variant", ""),
                    "price": site_result["price"],
                    "url": site_result.get("url", ""),
                    "match_text": site_result.get("match_text", ""),
                    "cost_price": product.get("cost_price"),
                    "diff_from_prev": None,  # 後で設定される
                })

    return all_results


def attach_comparisons(results, history):
    """前回実行時の履歴と比較して、diff_from_prev を設定する"""
    new_history = {}

    for r in results:
        key = (r["product_display_name"], r["site"], r["product_name_on_site"])
        prev_price = history.get(str(key))

        if prev_price is not None:
            r["diff_from_prev"] = r["price"] - prev_price
        else:
            r["diff_from_prev"] = None

        new_history[str(key)] = r["price"]

    return results, new_history


def filter_results(results, exclude_keywords):
    """除外キーワードを含む結果をフィルタリングする"""
    filtered = []
    for r in results:
        excluded = False
        for keyword in exclude_keywords:
            if keyword.lower() in r["product_name_on_site"].lower():
                excluded = True
                break
        if not excluded:
            filtered.append(r)
    return filtered


def build_discord_messages(results, report_url=None):
    """Discord通知用のメッセージを生成する（複数メッセージに分割対応）"""
    if not results:
        return ["該当商品がありません。"]

    # 変更内容をカウント
    new_count = sum(1 for r in results if r.get("diff_from_prev") is None)
    up_count = sum(1 for r in results if (r.get("diff_from_prev") or 0) > 0)
    down_count = sum(1 for r in results if r.get("diff_from_prev", 0) < 0)

    # ヘッダー
    header = (
        f"✅ 買取価格チェック完了！\n"
        f"🔄 変更点が {len(results)}件 見つかりました\n\n"
        f"📈 値上がり: {up_count}件\n"
        f"📉 値下がり: {down_count}件\n"
        f"✨ 新規: {new_count}件\n"
    )

    if report_url:
        header += f"\n👉 詳細はこちら: {report_url}"

    # 商品ごとに詳細を作成
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)

    details = []
    for product_name in sorted(grouped.keys()):
        rows = grouped[product_name]
        rows_sorted = sorted(rows, key=lambda x: x["price"], reverse=True)

        block = f"📦 {product_name}\n"
        block += "─" * 30 + "\n"
        for r in rows_sorted:
            prev = r.get("diff_from_prev")
            if prev is None:
                prev_str = "初回"
                symbol = "✨"
            elif prev > 0:
                prev_str = f"+{prev:,}円"
                symbol = "📈"
            else:
                prev_str = f"{prev:,}円"
                symbol = "📉"

            variant = r.get("variant") or "―"
            line = f"[{r['site']}] {r['price']:,}円 ({prev_str}) {symbol}\n"
            block += line

        details.append(block)

    # 2000字ずつに分割してメッセージを作成
    messages = [header]
    current_parts = []
    current_len = len(header) + 10  # ヘッダーの長さ + 余裕

    for detail in details:
        detail_len = len(detail.encode("utf-8"))

        if current_len + detail_len > 2000:
            # 現在のメッセージを完成
            if current_parts:
                messages.append("\n\n".join(current_parts))
            # 新しいメッセージを開始
            current_parts = [detail]
            current_len = detail_len
        else:
            current_parts.append(detail)
            current_len += detail_len

    if current_parts:
        messages.append("\n\n".join(current_parts))

    return messages if messages else [header]


def send_discord_notification(webhook_url, messages):
    if not webhook_url:
        print("[Discord] webhook_url が config.json に未設定のため、通知はスキップしました。")
        return

    if isinstance(messages, str):
        messages = [messages]

    for i, msg in enumerate(messages, 1):
        try:
            resp = SESSION.post(webhook_url, json={"content": msg}, timeout=15)
            if resp.status_code in (200, 204):
                print(f"[Discord] 通知を送信しました。（{i}/{len(messages)}通目）")
            else:
                print(f"[Discord] 送信失敗: status={resp.status_code} body={resp.text[:200]}")
        except requests.RequestException as e:
            print(f"[Discord] 通信エラー: {e}")
        if i < len(messages):
            time.sleep(1)  # Discordのレート制限対策


def print_results(results):
    if not results:
        print("\n該当する商品が見つかりませんでした。")
        return

    # (見出し, 幅, 揃え方向) 幅は「表示上の文字数」基準（全角=2としてカウント）
    columns = [
        ("商品", 18, "left"),
        ("業者", 10, "left"),
        ("状態", 14, "left"),
        ("価格", 12, "right"),
        ("前回比", 10, "right"),
    ]
    total_width = sum(w for _, w, _ in columns) + (len(columns) - 1)

    def format_row(cells):
        parts = [pad_display(c, w, a) for c, (_, w, a) in zip(cells, columns)]
        return " ".join(parts)  # 列間に必ず1マス空けて詰まりを防ぐ

    print("\n" + "=" * total_width)
    print(format_row([c[0] for c in columns]))
    print("-" * total_width)

    # 商品ごとにグループ化し、価格が高い順に表示
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)

    for product_name, rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda x: x["price"], reverse=True)
        for r in rows_sorted:
            prev = r["diff_from_prev"]
            prev_str = "初回" if prev is None else f"{prev:+,}"
            variant = r["variant"] or "―"
            cells = [
                product_name, r["site"], variant,
                f'{r["price"]:,}円', prev_str,
            ]
            print(format_row(cells))
        print("-" * total_width)

    print("※ 前回比は「+」が値上がり、「-」が値下がりです")
    print("※ 「初回」は前回データがまだないため比較なし（次回実行時から表示されます）")


REPORT_DIR = os.path.join(BASE_DIR, "docs")


def generate_html_report(results):
    """全商品・全サイトの詳細を、クリックで見られる1枚のHTMLページとして生成する。
    GitHub Pagesで公開すると、DiscordにはこのURLだけ送ればよくなる。"""
    os.makedirs(REPORT_DIR, exist_ok=True)

    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)

    def diff_badge(diff):
        if diff is None:
            return '<span class="badge new">NEW</span>'
        if diff > 0:
            return f'<span class="badge up">+{diff:,}円 ▲</span>'
        if diff < 0:
            return f'<span class="badge down">{diff:,}円 ▼</span>'
        return '<span class="badge flat">±0</span>'

    rows_html = []
    for product_name, rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda x: x["price"], reverse=True)
        best = rows_sorted[0]
        rows_html.append(
            f'<tr class="product-row"><td colspan="4"><strong>{product_name}</strong>'
            f' <span class="best">最高値 {best["price"]:,}円（{best["site"]}）</span></td></tr>'
        )
        for r in rows_sorted:
            variant = r["variant"] or "―"
            rows_html.append(
                "<tr>"
                f"<td>{r['site']}</td>"
                f"<td>{variant}</td>"
                f"<td class='price'>{r['price']:,}円</td>"
                f"<td>{diff_badge(r['diff_from_prev'])}</td>"
                "</tr>"
            )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>買取価格一覧</title>
<style>
  body {{ font-family: -apple-system, "Hiragino Sans", sans-serif; background:#f5f5f7; margin:0; padding:16px; }}
  h1 {{ font-size: 20px; }}
  .updated {{ color:#666; font-size: 13px; margin-bottom: 16px; }}
  table {{ width:100%; border-collapse: collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  td {{ padding:8px 10px; border-bottom:1px solid #eee; font-size:14px; }}
  .product-row td {{ background:#eef2ff; padding-top:12px; }}
  .best {{ color:#3355dd; font-size:12px; margin-left:8px; }}
  .price {{ text-align:right; font-variant-numeric: tabular-nums; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; }}
  .badge.up {{ background:#ffe1e1; color:#c62828; }}
  .badge.down {{ background:#e3f2fd; color:#1565c0; }}
  .badge.new {{ background:#fff3cd; color:#8a6d00; }}
  .badge.flat {{ background:#eee; color:#888; }}
</style>
</head>
<body>
  <h1>📦 買取価格一覧（ポケモンカード）</h1>
  <div class="updated">最終更新: {now_jst().strftime('%Y-%m-%d %H:%M')}（日本時間）</div>
  <table>
    {''.join(rows_html)}
  </table>
</body>
</html>
"""

    path = os.path.join(REPORT_DIR, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nHTMLレポートを保存しました: {path}")
    return path


def save_csv(results):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = now_jst().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"kaitori_{timestamp}.csv")

    fieldnames = [
        "product_display_name", "site", "product_name_on_site", "variant",
        "price", "diff_from_prev", "url",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k) for k in fieldnames})

    print(f"\nCSVを保存しました: {path}")


# ----------------------------------------------------------------------
# エントリーポイント
# ----------------------------------------------------------------------

def get_discord_webhook_url(config):
    """Discord Webhook URLを取得する。
    環境変数 DISCORD_WEBHOOK_URL が設定されていればそちらを優先する
    （GitHub ActionsのSecrets等、URLをファイルに直接書きたくない場合向け）。
    設定されていなければ config.json の discord_webhook_url を使う
    （ローカルでの通常運用向け）。"""
    return os.environ.get("DISCORD_WEBHOOK_URL") or config.get("discord_webhook_url", "")


def has_price_changes(results):
    """前回実行時から価格の変化（新規含む）があるかを判定する"""
    for r in results:
        diff = r.get("diff_from_prev")
        if diff is None or diff != 0:
            return True
    return False


def run_once(config, save_csv_file=False):
    history = load_history()

    results = run_all(config)
    results, new_history = attach_comparisons(results, history)
    save_history(new_history)  # 履歴の比較には除外前の全件を使う

    exclude_keywords = config.get("exclude_variant_keywords", [])
    filtered = filter_results(results, exclude_keywords)

    print_results(filtered)

    if save_csv_file:
        save_csv(filtered)

    # HTMLレポートは毎回生成する（Discord通知の有無にかかわらず、
    # 常に最新の状態をクリックで見られるようにするため）
    generate_html_report(filtered)

    if not has_price_changes(filtered):
        print("\n前回実行時から価格の変化がなかったため、Discord通知はスキップしました。")
        return

    report_url = config.get("report_url") or None
    messages = build_discord_messages(filtered, report_url=report_url)
    send_discord_notification(get_discord_webhook_url(config), messages)


def main():
    global SAVE_DEBUG_HTML
    if "--debug" in sys.argv:
        SAVE_DEBUG_HTML = True
        print(f"[debug] デバッグモード: 取得したHTMLを {DEBUG_DIR} に保存します")

    save_csv_file = "--csv" in sys.argv  # 明示的に指定した時だけCSVを保存する

    config = load_config()

    if "--loop" in sys.argv:
        # 起動しっぱなしで1時間ごとに実行し続けるモード
        # （PC・ターミナルを閉じると止まります。安定運用にはタスクスケジューラ推奨）
        interval_sec = 60 * 60
        print(f"[loop] ループモードで起動しました。{interval_sec}秒（1時間）ごとに実行します。")
        print("[loop] 停止するには Ctrl + C を押してください。")
        while True:
            try:
                run_once(config, save_csv_file=save_csv_file)
            except Exception as e:
                # 1回の失敗でループ自体は止めない
                print(f"[loop] 実行中にエラーが発生しましたが、ループは継続します: {e}")
            print(f"[loop] 次回実行まで{interval_sec}秒待機します...")
            time.sleep(interval_sec)
    else:
        # 1回だけ実行するモード（タスクスケジューラでの定期実行向け）
        run_once(config, save_csv_file=save_csv_file)


if __name__ == "__main__":
    main()

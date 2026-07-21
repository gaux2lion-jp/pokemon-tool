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

        if not order:
            break

        new_found = False
        for pid in order:
            a = by_pid.get(pid)
            if a is None or pid in seen_ids:
                continue
            name = a.get_text(strip=True)
            if not name:
                continue

            price = None
            for nxt in a.find_all_next(string=re.compile(r"¥")):
                m = re.search(r"([\d,]{3,})", nxt)
                if m:
                    price = int(m.group(1).replace(",", ""))
                    break
            if price is None:
                continue

            seen_ids.add(pid)
            new_found = True
            variant_match = re.search(r"【(.+?)】", name)
            variant = variant_match.group(1) if variant_match else ""

            results.append({
                "site": "買取ホムラ",
                "product_name_on_site": name,
                "match_text": name,
                "variant": variant,
                "price": price,
                "url": "https://kaitori-homura.com" + a["href"].split("?")[0],
            })

        if not new_found:
            break

        time.sleep(SLEEP_SEC)

    return results


def scrape_rudeya():
    """買取ルデヤ：ポケモンカードカテゴリページ(114)を取得する"""
    results = []
    seen_ids = set()
    url = "https://kaitori-rudeya.com/category/detail/114"

    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [買取ルデヤ] 通信エラー: {e}")
        return results

    save_debug_html("rudeya", "category114", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")

    anchors = soup.find_all("a", href=re.compile(r"/product/item/\d+"))
    by_pid, order = {}, []
    for a in anchors:
        m = re.search(r"/product/item/(\d+)", a["href"])
        pid = m.group(1)
        if pid not in by_pid:
            order.append(pid)
        if a.get_text(strip=True):
            by_pid[pid] = a

    for pid in order:
        a = by_pid.get(pid)
        if a is None or pid in seen_ids:
            continue
        name = a.get_text(strip=True)
        if not name:
            continue

        # 価格ラベルと金額が別々のタグに分かれているため、
        # 商品カード全体（article.pgrid-card）のテキストをまとめて正規表現で探す
        card = a.find_parent("article", class_="pgrid-card") or a.find_parent(["article", "li", "div"])
        card_text = card.get_text(" ", strip=True) if card else a.find_parent().get_text(" ", strip=True)

        price = None
        m = re.search(r"買取価格\s*([\d,]+)\s*円", card_text)
        if m:
            price = int(m.group(1).replace(",", ""))
        if price is None:
            continue

        seen_ids.add(pid)
        variant_match = re.search(r"[\[【](.+?)[\]】]", name)
        variant = variant_match.group(1) if variant_match else ""
        href = a["href"]
        full_url = href if href.startswith("http") else "https://kaitori-rudeya.com" + href

        results.append({
            "site": "買取ルデヤ",
            "product_name_on_site": name,
            "match_text": name,
            "variant": variant,
            "price": price,
            "url": full_url,
        })

    time.sleep(SLEEP_SEC)
    return results


def scrape_enoking():
    """買取エノキング：ポケモンカードカテゴリを取得する"""
    results = []
    seen_keys = set()
    base_url = "https://newenoking-kaitori.com/products?cat=9a1e60fa-496c-4c17-b94a-2eb418b7270f"

    for page in range(1, 5):
        page_url = f"{base_url}&page={page}"
        try:
            resp = SESSION.get(page_url, timeout=15)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [買取エノキング] 通信エラー（{page_url}）: {e}")
            break

        save_debug_html("enoking", f"pokemon_page{page}", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")

        price_nodes = soup.find_all(string=re.compile(r"参考買取金額"))
        if not price_nodes:
            break

        for node in price_nodes:
            price = None
            label_tag = node.parent
            price_tag = label_tag.find_next_sibling(["p", "span", "div"]) if label_tag else None
            if price_tag:
                m = re.search(r"([\d,]{3,})", price_tag.get_text(strip=True))
                if m:
                    price = int(m.group(1).replace(",", ""))
            if price is None:
                container = label_tag.parent if label_tag else None
                if container:
                    m = re.search(r"¥\s*([\d,]{3,})", container.get_text(" ", strip=True))
                    if m:
                        price = int(m.group(1).replace(",", ""))

            name = None
            for prev in node.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"]):
                text = prev.get_text(strip=True)
                if text:
                    name = text
                    break

            if not name or price is None:
                continue

            key = f"{name}-{price}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            results.append({
                "site": "買取エノキング",
                "product_name_on_site": name,
                "match_text": name,
                "variant": "",
                "price": price,
                "url": page_url,
            })

    time.sleep(SLEEP_SEC)
    return results


def scrape_somurie():
    """買取ソムリエ：商品一覧ページ（トレカ以外も混在）からポケモン関連のみ拾う。
    ※このサイトは構造を実機で確認できなかったため、他サイトで有効だった
    一般的なパターンで実装している。うまく取れない場合は --debug で
    保存されるHTMLを確認して調整する。"""
    results = []
    base_url = "https://somurie-kaitori.com/products"

    for page in range(1, 6):
        page_url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = SESSION.get(page_url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [買取ソムリエ] 通信エラー（{page_url}）: {e}")
            break

        save_debug_html("somurie", f"page{page}", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")

        # 「円」という価格表示を手がかりに、直前の見出しやテキストを商品名とみなす
        price_nodes = soup.find_all(string=re.compile(r"^\s*[\d,]+\s*$"))
        found_any = False
        seen = set()

        for node in price_nodes:
            parent = node.parent
            # 直後に「円」がある要素だけを価格とみなす
            next_text = ""
            nxt = node.find_next(string=True)
            if nxt:
                next_text = nxt.strip()
            if next_text != "円":
                continue

            price = int(re.sub(r"[,\s]", "", node))

            # 商品名は、価格要素より手前にある最も近い見出し/リンクのテキストから探す
            name = None
            for prev in parent.find_all_previous(["h1", "h2", "h3", "h4", "h5", "a", "p"]):
                text = prev.get_text(strip=True)
                if text and len(text) >= 4 and "円" not in text and "ログイン" not in text:
                    name = text
                    break

            if not name or "ポケモン" not in name and "ポケカ" not in name:
                continue

            key = f"{name}-{price}"
            if key in seen:
                continue
            seen.add(key)
            found_any = True

            variant_match = re.search(r"[\[【](.+?)[\]】]", name)
            variant = variant_match.group(1) if variant_match else ""

            results.append({
                "site": "買取ソムリエ",
                "product_name_on_site": name,
                "match_text": name,
                "variant": variant,
                "price": price,
                "url": page_url,
            })

        if not found_any:
            break

        time.sleep(SLEEP_SEC)

    return results


def scrape_torecalounge():
    """トレカラウンジ：ポケモンカードBOX一覧（未開封/シュリンクなし）を取得する。
    商品名と価格がカテゴリ一覧ページ自体に直接書かれているため、
    個別の商品ページを開く必要がない（静的HTML、JS実行不要）。"""
    results = []
    base_url = "https://kaitori.toreca-lounge.com/products/pokemon/box"

    for page in range(1, 5):
        page_url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = SESSION.get(page_url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [トレカラウンジ] 通信エラー（{page_url}）: {e}")
            break

        save_debug_html("torecalounge", f"page{page}", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")

        anchors = soup.find_all("a", href=re.compile(r"/product/[A-Za-z0-9]+$"))
        if not anchors:
            break

        found_any = False
        seen_hrefs = set()
        for a in anchors:
            href = a["href"]
            if href in seen_hrefs:
                continue  # 同じ商品が同一ページ内で重複掲載されている場合を除外

            text = a.get_text(" ", strip=True)
            # 例: "バイオレットex バイオレットex 型番:- レアリティ/種別:- / 未開封 買取価格:¥11,600"
            price_m = re.search(r"買取価格[:：]\s*¥?([\d,]+)", text)
            if not price_m:
                continue
            price = int(price_m.group(1).replace(",", ""))

            # 「型番:」より前の部分を商品名として使う（重複しがちなタイトルの前半だけ使う）
            name_part = text.split("型番")[0].strip()
            # タイトルが2回繰り返される作り（例:"バイオレットexバイオレットex ..."）なので、
            # 前半と後半が同じ場合は半分に切る
            half = len(name_part) // 2
            if half > 0 and name_part[:half] == name_part[half:]:
                name_part = name_part[:half]

            variant = "シュリンクなし" if "シュリンクなし" in name_part else ""

            found_any = True
            seen_hrefs.add(href)
            results.append({
                "site": "トレカラウンジ",
                "product_name_on_site": name_part,
                "match_text": name_part,
                "variant": variant,
                "price": price,
                "url": "https://kaitori.toreca-lounge.com" + a["href"],
            })

        if not found_any:
            break

        time.sleep(SLEEP_SEC)

    return results


def scrape_1chome():
    """買取1丁目：ポケモンBOXカテゴリを、裏側のJSON APIから直接取得する。
    ログイン不要で呼び出せる、構造化されたAPIエンドポイント。"""
    results = []
    base_url = "https://www.1-chome.com/api/goods/listPage"
    cate_code = "IIzyMdayU5wp7T4G"  # ポケモンカードBOXカテゴリ

    for page in range(1, 5):
        params = {
            "accCode": "", "page": str(page), "size": "24",
            "isImpo": "false", "isCampaign": "false",
            "cateCode": cate_code, "kbNames": "", "cateName": "", "keyword": "",
        }
        try:
            resp = SESSION.get(base_url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [買取1丁目] 通信エラー（page={page}）: {e}")
            break

        save_debug_html("1chome", f"page{page}", resp.text)

        content = data.get("data", {}).get("content", [])
        if not content:
            break

        for item in content:
            name = item.get("title", "")
            jan = item.get("jan", "") or ""
            if not name:
                continue

            details = item.get("goodsKbDetails") or []
            if details:
                for d in details:
                    price = d.get("kbDetailPrice")
                    if price is None:
                        continue
                    variant = d.get("kbDetailName", "") or ""
                    results.append({
                        "site": "買取1丁目",
                        "product_name_on_site": name,
                        "match_text": f"{name} {jan}",
                        "variant": variant,
                        "price": int(price),
                        "url": "https://www.1-chome.com/tradeCards",
                    })
            else:
                price = item.get("price")
                if price is not None:
                    results.append({
                        "site": "買取1丁目",
                        "product_name_on_site": name,
                        "match_text": f"{name} {jan}",
                        "variant": "",
                        "price": int(price),
                        "url": "https://www.1-chome.com/tradeCards",
                    })

        total_pages = data.get("data", {}).get("totalPages", 1)
        if page >= total_pages:
            break

        time.sleep(SLEEP_SEC)

    return results


def scrape_runto(max_pages=9):
    """Runto買取：ポケモンカードカテゴリ("card"という名前だが実質ポケモン専用)を取得する"""
    results = []
    category_url = "https://runto666.com/product-category/card/"
    product_links = {}

    for page in range(1, max_pages + 1):
        page_url = category_url if page == 1 else f"{category_url}page/{page}/"
        try:
            resp = SESSION.get(page_url, timeout=15)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [Runto買取] 通信エラー（{page_url}）: {e}")
            break

        save_debug_html("runto_category", f"page{page}", resp.text)
        soup = BeautifulSoup(resp.text, "lxml")

        found_any = False
        for a in soup.find_all("a", href=re.compile(r"/product/[^/]+/?$")):
            name = a.get_text(strip=True)
            if not name:
                continue
            found_any = True
            product_links[name] = a["href"]

        if not found_any:
            break

        time.sleep(SLEEP_SEC)

    def fetch_one(item):
        name, purl = item
        try:
            resp = SESSION.get(purl, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [Runto買取] 商品ページ取得エラー（{purl}）: {e}")
            return None

        page_html = resp.text
        save_debug_html("runto_product", name, page_html)
        rows = _parse_runto_variations(page_html)

        rows_out = []
        if rows:
            for r in rows:
                rows_out.append({
                    "site": "Runto買取",
                    "product_name_on_site": name,
                    "match_text": name,
                    "variant": r["variant"],
                    "price": r["price"],
                    "url": purl,
                })
        else:
            m = re.search(r"¥([\d,]+)\s*[–\-]\s*¥([\d,]+)", page_html)
            if m:
                rows_out.append({
                    "site": "Runto買取",
                    "product_name_on_site": name,
                    "match_text": name,
                    "variant": "(価格帯：状態により変動)",
                    "price": int(m.group(2).replace(",", "")),
                    "url": purl,
                })
        return rows_out

    with ThreadPoolExecutor(max_workers=5) as executor:
        for rows_out in executor.map(fetch_one, product_links.items()):
            if rows_out:
                results.extend(rows_out)

    return results


def _parse_runto_variations(page_html):
    """RuntoのWooCommerce商品ページから、状態(シュリンク等)別の価格を抽出する"""
    rows = []

    m = re.search(r'data-product_variations="([^"]+)"', page_html)
    if not m:
        return rows

    try:
        raw_json = html_module.unescape(m.group(1))
        variations = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        return rows

    label_map = {}
    soup = BeautifulSoup(page_html, "lxml")
    for select in soup.select("select[name^='attribute_']"):
        for opt in select.find_all("option"):
            val = opt.get("value", "")
            if val:
                label_map[val] = opt.get_text(strip=True)

    for v in variations:
        attrs = v.get("attributes", {}) or {}
        labels = [label_map.get(slug, slug) for slug in attrs.values() if slug]
        variant_label = "/".join(labels) if labels else "(状態指定なし)"
        price = v.get("display_price")
        if price is None:
            continue
        rows.append({"variant": variant_label, "price": int(price)})

    return rows


# ----------------------------------------------------------------------


def _scrape_jan_style_listing(site_label, urls):
    """「商品名 → JAN → 価格」が同じ商品カード内に並んでいるタイプの共通処理。
    「JAN:」ラベルと数値が別々のタグに分かれているサイトにも対応するため、
    商品カード全体のテキストをまとめてから正規表現で解析する。"""
    results = []
    seen = set()

    for url in urls:
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [{site_label}] 通信エラー（{url}）: {e}")
            break

        save_debug_html(site_label, re.sub(r"\W+", "_", url)[-40:], resp.text)
        soup = BeautifulSoup(resp.text, "lxml")

        jan_nodes = soup.find_all(string=re.compile(r"JAN"))
        if not jan_nodes:
            break

        for node in jan_nodes:
            # JANラベルを含むノードから、「JAN番号」と「価格(円)」の
            # 両方を含む祖先要素まで さかのぼり、そこを商品カードとみなす。
            # 商品名は見出し(h1〜h6)タグとは限らない(labelタグ等のサイトもある)ため、
            # 見出しタグを優先しつつ、無ければカード内の意味のある最初のテキストを使う。
            card = None
            ancestor = node.parent
            for _ in range(10):
                if ancestor is None:
                    break
                text = ancestor.get_text(" ", strip=True)
                if "JAN" in text and re.search(r"[\d,]{3,}\s*円", text):
                    card = ancestor
                    break
                ancestor = ancestor.parent

            if card is None:
                continue

            card_text = card.get_text(" ", strip=True)

            jan_m = re.search(r"JAN[:：]?\s*(\d{6,})", card_text)
            jan = jan_m.group(1) if jan_m else ""

            name_tag = card.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if name_tag:
                name = name_tag.get_text(strip=True)
            else:
                name = None
                for leaf in card.find_all(string=True):
                    t = leaf.strip()
                    if len(t) >= 6 and "JAN" not in t and not re.match(r"^[\d,]+\s*円?$", t):
                        name = t
                        break

            price_m = re.search(r"([\d,]{3,})\s*円", card_text)
            price = int(price_m.group(1).replace(",", "")) if price_m else None

            if not name or price is None:
                continue

            key = f"{name}-{price}"
            if key in seen:
                continue
            seen.add(key)

            variant_match = re.search(r"[\[【](.+?)[\]】]", name)
            variant = variant_match.group(1) if variant_match else ""

            results.append({
                "site": site_label,
                "product_name_on_site": name,
                "match_text": name + " " + jan,
                "variant": variant,
                "price": price,
                "url": url,
            })

    time.sleep(SLEEP_SEC)
    return results


def scrape_mobileichiban():
    """モバイル一番：ポケモンカードカテゴリ（kid=3, bid=04）を取得する"""
    base = "https://www.mobile-ichiban.com"
    urls = [f"{base}/Prod/3/04"] + [f"{base}/G01_ProdutShow/Index/{p}?kid=3&bid=04" for p in range(2, 4)]
    return _scrape_jan_style_listing("モバイル一番", urls)


def scrape_kaitorishouten():
    """買取商店：トレカカテゴリ（ワンピース等混在）を一度だけ取得する"""
    base_url = "https://www.kaitorishouten-co.jp/toreka"
    urls = [base_url] + [f"{base_url}?page={p}" for p in range(2, 6)]
    return _scrape_jan_style_listing("買取商店", urls)


# サイトの登録（追加したい場合はここにタプルを増やす）
# ポケモン版は現在この2サイトのみ対応。他サイトはポケモン用のURLを
# 順次調査して追加していく予定。
SITES = [
    ("買取ホムラ", scrape_homura),
    ("買取BASE", scrape_base),
    ("Runto買取", scrape_runto),
    ("買取ルデヤ", scrape_rudeya),
    ("買取エノキング", scrape_enoking),
    ("モバイル一番", scrape_mobileichiban),
    ("買取商店", scrape_kaitorishouten),
    ("買取1丁目", scrape_1chome),
    ("トレカラウンジ", scrape_torecalounge),
    ("買取ソムリエ", scrape_somurie),
]


def run_all(config):
    """各サイトを一度だけ取得し、そのデータに対して全商品をローカルでマッチングする
    （以前は商品×サイトの数だけ通信していたため、大幅に高速化される）"""
    all_results = []

    # 1. 各サイトから一度だけ全件取得
    site_items = {}
    for site_name, scrape_func in SITES:
        print(f"\n{site_name} を取得中...")
        try:
            items = scrape_func()
        except Exception as e:
            print(f"  [{site_name}] 予期しないエラー: {e}")
            items = []
        site_items[site_name] = items
        print(f"  {site_name}: {len(items)} 件取得")

    # 2. 取得済みデータに対して、商品ごとにローカルでキーワード一致を確認
    print("\n=== 商品ごとに一致確認中 ===")
    for product in config["products"]:
        display_name = product["display_name"]
        keywords = list(product["keywords"]) + list(product.get("jan_codes", []))
        exclude_keywords = product.get("exclude_keywords", [])
        hit_count = 0

        for site_name, items in site_items.items():
            for item in items:
                text = item.get("match_text", "").lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
                if exclude_keywords and any(kw.lower() in text for kw in exclude_keywords):
                    continue  # 似た名前の別商品を誤って拾わないよう除外
                r = dict(item)
                r["product_display_name"] = display_name
                r["cost_price"] = product.get("cost_price")
                all_results.append(r)
                hit_count += 1

        print(f"  {display_name}: {hit_count} 件一致")

    return all_results

def attach_comparisons(results, history):
    """前回価格・仕入れ値との差額を各結果に追加する"""
    new_history = dict(history)  # 今回分で上書きしていく

    for r in results:
        key = f"{r['site']}|{r['product_display_name']}|{r['variant']}"
        prev_price = history.get(key)

        if prev_price is None:
            r["diff_from_prev"] = None
        else:
            r["diff_from_prev"] = r["price"] - prev_price

        cost_price = r.get("cost_price")
        if cost_price:
            r["diff_from_cost"] = r["price"] - cost_price
        else:
            r["diff_from_cost"] = None

        new_history[key] = r["price"]

    return results, new_history


def filter_results(results, exclude_keywords):
    """状態(variant)や商品名にexclude_keywordsを含む結果を除外する（例：カートンを除外）"""
    if not exclude_keywords:
        return results
    filtered = []
    for r in results:
        combined = (r.get("variant") or "") + (r.get("product_name_on_site") or "")
        if any(kw in combined for kw in exclude_keywords):
            continue
        filtered.append(r)
    return filtered


# ----------------------------------------------------------------------
# Discord通知
# ----------------------------------------------------------------------

DISCORD_MAX_LEN = 1900  # Discordの2000文字制限に少し余裕を持たせる


def build_discord_messages(results, report_url=None):
    """Discordに投稿するメッセージを組み立てる。
    商品数が多いため、詳細な全商品一覧はDiscordには載せず、
    「価格が変わった商品」と「新規掲載」を分けて表示し、詳細はHTMLレポートへの
    リンク（クリックで見られる一覧ページ）に誘導する。
    「新規掲載」が大量にある場合（初回実行時など）は、1件ずつ列挙すると
    それだけで長文になってしまうため、件数だけの要約に切り替える。
    文字数が多い場合は2000文字制限を超えないよう複数メッセージに分割する。
    戻り値は文字列のリスト（1件でも必ずリストで返す）。"""
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)

    header = f"📦 **買取価格チェック**（{now_jst().strftime('%Y-%m-%d %H:%M')}）"

    # 新規掲載(diffがNone)と、実際の値上がり/値下がり(diffが0以外)を分けて集計する
    new_lines = []
    change_lines = []
    for product_name, rows in grouped.items():
        for r in rows:
            diff = r["diff_from_prev"]
            variant_note = f"[{r['variant']}]" if r["variant"] else ""
            if diff is None:
                new_lines.append(f"🆕 {product_name}：{r['price']:,}円 （{r['site']}{variant_note}） 新規掲載")
            elif diff != 0:
                emoji = "📈" if diff > 0 else "📉"
                change_lines.append(
                    f"{emoji} {product_name}：{r['price']:,}円 （{r['site']}{variant_note}） {diff:+,}円"
                )

    MAX_LISTED_NEW_ITEMS = 15  # これを超えたら1件ずつ列挙せず件数だけ表示する

    blocks = []
    if change_lines:
        blocks.append("**🔔 価格が変わった商品**\n" + "\n".join(change_lines))

    if new_lines:
        if len(new_lines) > MAX_LISTED_NEW_ITEMS:
            blocks.append(
                f"🆕 **新規掲載: {len(new_lines)}件**\n"
                "（初回実行、またはサイト追加などでまとめて増えました。詳細は下記リンクから）"
            )
        else:
            blocks.append("**🆕 新規掲載**\n" + "\n".join(new_lines))

    if not change_lines and not new_lines:
        blocks.append("今回、価格の変化はありませんでした。")

    if report_url:
        blocks.append(f"📋 **全商品・全サイトの詳細一覧はこちら**\n{report_url}")

    # ブロックを、上限文字数を超えない範囲でメッセージにまとめる
    messages = []
    current_parts = [header]
    current_len = len(header)

    for block in blocks:
        block_len = len(block) + 2  # 区切りの空行分
        if current_len + block_len > DISCORD_MAX_LEN and len(current_parts) > 1:
            messages.append("\n\n".join(current_parts))
            current_parts = [block]
            current_len = len(block)
        else:
            current_parts.append(block)
            current_len += block_len

    if current_parts:
        messages.append("\n\n".join(current_parts))

    return messages if messages else [header]


def send_discord_notification(webhook_url, messages):
    if not webhook_url:
        print("[Discord] webhook_url \u304c config.json \u306b\u672a\u8a2d\u5b9a\u306e\u305f\u3081\u3001\u901a\u77e5\u306f\u30b9\u30ad\u30c3\u30d7\u3057\u307e\u3057\u305f\u3002")
        return

    if isinstance(messages, str):
        messages = [messages]

    for i, msg in enumerate(messages, 1):
        try:
            resp = SESSION.post(webhook_url, json={"content": msg}, timeout=15)
            if resp.status_code in (200, 204):
                print(f"[Discord] \u901a\u77e5\u3092\u9001\u4fe1\u3057\u307e\u3057\u305f\u3002\uff08{i}/{len(messages)}\u901a\u76ee\uff09")
            else:
                print(f"[Discord] \u9001\u4fe1\u5931\u6557: status={resp.status_code} body={resp.text[:200]}")
        except requests.RequestException as e:
            print(f"[Discord] \u901a\u4fe1\u30a8\u30e9\u30fc: {e}")
        if i < len(messages):
            time.sleep(1)  # Discord\u306e\u30ec\u30fc\u30c8\u5236\u9650\u5bfe\u7b56


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

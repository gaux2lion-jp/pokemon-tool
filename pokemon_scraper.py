# -*- coding: utf-8 -*-
"""
ポケモンカード買取価格チェッカー
8つの買取サイトから価格を自動取得・比較
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

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# =====================================================================
# ユーティリティ
# =====================================================================

def display_width(text):
    width = 0
    for ch in str(text):
        w = unicodedata.east_asian_width(ch)
        width += 2 if w in ("W", "F") else 1
    return width

def pad_display(text, width, align="left"):
    text = str(text)
    pad = max(0, width - display_width(text))
    if align == "right":
        return " " * pad + text
    return text + " " * pad

# =====================================================================
# グローバル設定
# =====================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "price_history.json")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
REPORT_DIR = os.path.join(BASE_DIR, "docs")

SLEEP_SEC = 1.0
JST = timezone(timedelta(hours=9))
SAVE_DEBUG_HTML = False
DEBUG_DIR = os.path.join(BASE_DIR, "debug_html")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
_retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)

def now_jst():
    return datetime.now(JST)

def save_debug_html(site_name, label, html_text):
    if not SAVE_DEBUG_HTML:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    ts = now_jst().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^\w\-]+", "_", label)[:50]
    path = os.path.join(DEBUG_DIR, f"{site_name}_{safe_label}_{ts}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)

# =====================================================================
# 設定・履歴の読み書き
# =====================================================================

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

# =====================================================================
# スクレイピング関数（8サイト）
# =====================================================================

def scrape_base():
    """買取BASE"""
    url = "https://kaitori-base.com/?p=9534"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [買取BASE] エラー: {e}")
        return results
    
    save_debug_html("base", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        table = soup.find("table", class_="wp-block-table")
        if table:
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    name = cells[0].get_text(strip=True)
                    price_text = cells[1].get_text(strip=True)
                    try:
                        price = int(re.sub(r"[^\d]", "", price_text))
                        results.append({"product_name": name, "site": "買取BASE", "price": price, "variant": None})
                    except:
                        pass
    except Exception as e:
        print(f" [買取BASE] 解析エラー: {e}")
    
    return results

def scrape_runto():
    """Runto買取"""
    url = "https://runto666.com/kaitori/pokemon/"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [Runto買取] エラー: {e}")
        return results
    
    save_debug_html("runto", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 3:
                name = cells[0].get_text(strip=True)
                price_text = cells[2].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "Runto買取", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [Runto買取] 解析エラー: {e}")
    
    return results

def scrape_newenoking():
    """買取エノキング"""
    url = "https://newenoking-kaitori.com/"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [買取エノキング] エラー: {e}")
        return results
    
    save_debug_html("newenoking", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                price_text = cells[1].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "買取エノキング", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [買取エノキング] 解析エラー: {e}")
    
    return results

def scrape_mobile_ichiban():
    """モバイル一番"""
    url = "https://www.mobile-ichiban.com/Prod/3/04"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [モバイル一番] エラー: {e}")
        return results
    
    save_debug_html("mobile_ichiban", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 3:
                name = cells[0].get_text(strip=True)
                price_text = cells[2].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "モバイル一番", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [モバイル一番] 解析エラー: {e}")
    
    return results

def scrape_1chome():
    """買取１丁目"""
    url = "https://www.1-chome.com/index"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [買取１丁目] エラー: {e}")
        return results
    
    save_debug_html("1chome", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                price_text = cells[1].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "買取１丁目", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [買取１丁目] 解析エラー: {e}")
    
    return results

def scrape_rudeya():
    """買取るであ"""
    url = "https://kaitori-rudeya.com/"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [買取るであ] エラー: {e}")
        return results
    
    save_debug_html("rudeya", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                price_text = cells[1].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "買取るであ", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [買取るであ] 解析エラー: {e}")
    
    return results

def scrape_somurie():
    """買取ソムリエ"""
    url = "https://somurie-kaitori.com/"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [買取ソムリエ] エラー: {e}")
        return results
    
    save_debug_html("somurie", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                price_text = cells[1].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "買取ソムリエ", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [買取ソムリエ] 解析エラー: {e}")
    
    return results

def scrape_toreca_lounge():
    """トレカラウンジ"""
    url = "https://kaitori.toreca-lounge.com/pokemon"
    results = []
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" [トレカラウンジ] エラー: {e}")
        return results
    
    save_debug_html("toreca_lounge", "main", resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    try:
        rows = soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                price_text = cells[1].get_text(strip=True)
                try:
                    price = int(re.sub(r"[^\d]", "", price_text))
                    results.append({"product_name": name, "site": "トレカラウンジ", "price": price, "variant": None})
                except:
                    pass
    except Exception as e:
        print(f" [トレカラウンジ] 解析エラー: {e}")
    
    return results

# =====================================================================
# メイン処理
# =====================================================================

def run_all(config, save_csv_file=False):
    config_products = {p.get("display_name", p.get("name")): p for p in config.get("products", [])}
    
    print(f"\n{'='*60}")
    print(f"ポケモンカード買取価格チェック（8サイト対応）")
    print(f"実行時刻: {now_jst().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    all_results = []
    
    print("スクレイピング中...\n")
    all_results.extend(scrape_base())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_runto())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_newenoking())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_mobile_ichiban())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_1chome())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_rudeya())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_somurie())
    time.sleep(SLEEP_SEC)
    all_results.extend(scrape_toreca_lounge())
    time.sleep(SLEEP_SEC)
    
    history = load_history()
    for result in all_results:
        product_key = result["product_name"]
        if product_key in config_products:
            result["product_display_name"] = config_products[product_key].get("display_name", product_key)
        else:
            result["product_display_name"] = product_key
        
        hist_key = f"{result['product_display_name']}_{result['site']}"
        prev_price = history.get(hist_key)
        if prev_price is not None:
            result["diff_from_prev"] = result["price"] - prev_price
        else:
            result["diff_from_prev"] = None
        
        history[hist_key] = result["price"]
    
    save_history(history)
    generate_html_report(all_results)
    print_results(all_results)
    
    if save_csv_file:
        save_csv(all_results)
    
    send_discord_notification(all_results)

def print_results(results):
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)
    
    for product_name in sorted(grouped.keys()):
        rows = grouped[product_name]
        print(f"{product_name}")
        print("─" * 60)
        
        for r in sorted(rows, key=lambda x: x["price"], reverse=True):
            diff_str = "初回"
            if r["diff_from_prev"] is not None:
                diff_str = f"{r['diff_from_prev']:+,}" if r["diff_from_prev"] != 0 else "0"
            
            print(f"  [{r['site']}] {r['price']:,}円 ({diff_str})")
        
        print()

def save_csv(results):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = now_jst().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(RESULTS_DIR, f"pokemon_prices_{ts}.csv")
    
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["商品名", "サイト", "価格", "前回との差"])
        for r in results:
            diff = r["diff_from_prev"] if r["diff_from_prev"] is not None else "初回"
            writer.writerow([r["product_display_name"], r["site"], r["price"], diff])

def generate_html_report(results):
    os.makedirs(REPORT_DIR, exist_ok=True)
    
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)
    
    rows_html = []
    
    for product_name in sorted(grouped.keys()):
        rows = grouped[product_name]
        rows_sorted = sorted(rows, key=lambda x: x["price"], reverse=True)
        best = rows_sorted[0]
        
        rows_html.append(
            f'<tr class="product-row"><td colspan="4"><strong>{product_name}</strong> '
            f'<span class="best">最高値 {best["price"]:,}円 ({best["site"]})</span></td></tr>'
        )
        
        for r in rows_sorted:
            diff_html = ""
            if r["diff_from_prev"] is None:
                diff_html = '<span class="badge new">初回</span>'
            elif r["diff_from_prev"] > 0:
                diff_html = f'<span class="badge up">+{r["diff_from_prev"]:,}円 ▲</span>'
            elif r["diff_from_prev"] < 0:
                diff_html = f'<span class="badge down">{r["diff_from_prev"]:,}円 ▼</span>'
            else:
                diff_html = '<span class="badge flat">±0</span>'
            
            rows_html.append(
                f'<tr><td>{r["site"]}</td><td>―</td><td class="price">{r["price"]:,}円</td><td>{diff_html}</td></tr>'
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
.product-row td {{ background:#eef2ff; padding-top:12px; padding-bottom:12px; font-weight:500; }}
.best {{ color:#3355dd; font-size:12px; margin-left:8px; }}
.price {{ text-align:right; font-weight:600; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; font-weight:500; }}
.badge.new {{ background:#e8f4fd; color:#0066cc; }}
.badge.up {{ background:#ffe8e8; color:#cc0000; }}
.badge.down {{ background:#e8f4e8; color:#00aa00; }}
.badge.flat {{ background:#f0f0f0; color:#666; }}
</style>
</head>
<body>
<h1>📊 買取価格一覧（ポケモンカード）</h1>
<div class="updated">最終更新: {now_jst().strftime('%Y-%m-%d %H:%M (日本時間)')}</div>
<table>
{"".join(rows_html)}
</table>
</body>
</html>"""
    
    filepath = os.path.join(REPORT_DIR, "index.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

def send_discord_notification(results):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    
    grouped = {}
    for r in results:
        grouped.setdefault(r["product_display_name"], []).append(r)
    
    messages = []
    new_count = 0
    up_count = 0
    down_count = 0
    
    for product_name in sorted(grouped.keys()):
        rows = grouped[product_name]
        best = max(rows, key=lambda x: x["price"])
        
        diff_str = "初回"
        if best["diff_from_prev"] is not None:
            diff_str = f"{best['diff_from_prev']:+,}円"
            if best["diff_from_prev"] > 0:
                up_count += 1
            elif best["diff_from_prev"] < 0:
                down_count += 1
        else:
            new_count += 1
        
        messages.append(f"{product_name} ────────────────────────────── [{best['site']}] {best['price']:,}円 ({diff_str})")
    
    content = (
        f"買取価格チェック完了！\n"
        f"変更点が {len(results)}件 見つかりました\n"
        f"値上がり: {up_count}件\n"
        f"値下がり: {down_count}件\n"
        f"新規: {new_count}件\n"
        f"詳細はこちら: https://gaux2lion-jp.github.io/pokemon-tool/\n\n"
        + "\n".join(messages)
    )
    
    try:
        requests.post(webhook_url, json={"content": content}, timeout=10)
    except Exception as e:
        print(f"Discord通知エラー: {e}")

if __name__ == "__main__":
    os.system("git stash")
    os.system("git pull origin main --rebase")
    
    config = load_config()
    run_all(config, save_csv_file=False)
    
    os.system("git add -A")
    os.system(f'git commit -m "Update prices: {now_jst().strftime(\"%Y-%m-%d %H:%M\")}"')
    os.system("git push origin main")
